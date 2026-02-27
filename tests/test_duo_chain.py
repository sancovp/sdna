"""Tests for DUOChain abstract state machine."""

import pytest
from sdna.duo_chain import (
    DUOChain, DUOChainResult, DUOChainStatus,
    PositionResult, PositionStatus,
    PassthroughPosition, CallablePosition,
    AutoDUOAgent,
    duo_chain, auto_duo_agent,
)


# =============================================================================
# Mock Positions
# =============================================================================

class MockPosition:
    """Position that increments a counter and succeeds."""
    def __init__(self, key: str):
        self.key = key

    async def execute(self, context):
        ctx = dict(context)
        ctx[self.key] = ctx.get(self.key, 0) + 1
        return PositionResult(status=PositionStatus.SUCCESS, context=ctx)


class MockOVPApproveAfterN:
    """OVP that approves after N cycles."""
    def __init__(self, approve_after: int = 1):
        self.approve_after = approve_after
        self.calls = 0

    async def execute(self, context):
        self.calls += 1
        ctx = dict(context)
        approved = self.calls >= self.approve_after
        return PositionResult(
            status=PositionStatus.SUCCESS,
            context=ctx,
            approved=approved,
            feedback=f"Cycle {self.calls}: {'approved' if approved else 'needs work'}",
        )


class MockBlockedPosition:
    async def execute(self, context):
        return PositionResult(status=PositionStatus.BLOCKED, context=dict(context))


class MockErrorPosition:
    async def execute(self, context):
        return PositionResult(status=PositionStatus.ERROR, context=dict(context), error="test error")


class MockAwaitingPosition:
    async def execute(self, context):
        return PositionResult(status=PositionStatus.AWAITING_INPUT, context=dict(context))


# =============================================================================
# Basic State Machine Tests
# =============================================================================

class TestDUOChainBasic:
    @pytest.mark.asyncio
    async def test_single_cycle_approved(self):
        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            ovp=MockOVPApproveAfterN(1), max_n=2, max_duo_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.SUCCESS
        assert result.outer_cycles == 1
        assert result.inner_iterations == 2
        assert result.context["a"] == 2
        assert result.context["p"] == 2

    @pytest.mark.asyncio
    async def test_multi_cycle_approved(self):
        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            ovp=MockOVPApproveAfterN(3), max_n=1, max_duo_cycles=5,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.SUCCESS
        assert result.outer_cycles == 3
        assert result.inner_iterations == 3
        assert result.context["a"] == 3
        assert result.context["p"] == 3

    @pytest.mark.asyncio
    async def test_max_cycles_hit(self):
        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            ovp=MockOVPApproveAfterN(99), max_n=1, max_duo_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.MAX_CYCLES
        assert result.outer_cycles == 3
        assert result.inner_iterations == 3

    @pytest.mark.asyncio
    async def test_do_while_at_least_once(self):
        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            ovp=MockOVPApproveAfterN(99), max_n=1, max_duo_cycles=1,
        )
        result = await chain.execute({})
        assert result.outer_cycles == 1
        assert result.inner_iterations == 1
        assert result.context["a"] == 1
        assert result.context["p"] == 1

    @pytest.mark.asyncio
    async def test_inner_loop_alternation(self):
        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            ovp=MockOVPApproveAfterN(1), max_n=5, max_duo_cycles=1,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.SUCCESS
        assert result.context["a"] == 5
        assert result.context["p"] == 5
        assert result.inner_iterations == 5

    @pytest.mark.asyncio
    async def test_context_passes_through(self):
        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            ovp=MockOVPApproveAfterN(1), max_n=1, max_duo_cycles=1,
        )
        result = await chain.execute({"existing": "data"})
        assert result.context["existing"] == "data"
        assert result.context["a"] == 1


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestDUOChainErrors:
    @pytest.mark.asyncio
    async def test_ariadne_blocked(self):
        chain = DUOChain(
            name="test", ariadne=MockBlockedPosition(), poimandres=MockPosition("p"),
            ovp=MockOVPApproveAfterN(1), max_n=1, max_duo_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_poimandres_error(self):
        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockErrorPosition(),
            ovp=MockOVPApproveAfterN(1), max_n=1, max_duo_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.ERROR
        assert result.error == "test error"

    @pytest.mark.asyncio
    async def test_ovp_error(self):
        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            ovp=MockErrorPosition(), max_n=1, max_duo_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.ERROR

    @pytest.mark.asyncio
    async def test_ariadne_awaiting_input(self):
        chain = DUOChain(
            name="test", ariadne=MockAwaitingPosition(), poimandres=MockPosition("p"),
            ovp=MockOVPApproveAfterN(1), max_n=1, max_duo_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.AWAITING_INPUT


# =============================================================================
# Position Type Tests
# =============================================================================

class TestPositionTypes:
    @pytest.mark.asyncio
    async def test_passthrough(self):
        pos = PassthroughPosition()
        result = await pos.execute({"key": "value"})
        assert result.status == PositionStatus.SUCCESS
        assert result.context["key"] == "value"

    @pytest.mark.asyncio
    async def test_callable_position(self):
        async def double_x(ctx):
            ctx = dict(ctx)
            ctx["x"] = ctx.get("x", 0) * 2
            return ctx

        pos = CallablePosition(double_x)
        result = await pos.execute({"x": 5})
        assert result.status == PositionStatus.SUCCESS
        assert result.context["x"] == 10

    @pytest.mark.asyncio
    async def test_callable_position_error(self):
        async def fail(ctx):
            raise ValueError("boom")

        pos = CallablePosition(fail)
        result = await pos.execute({})
        assert result.status == PositionStatus.ERROR
        assert "boom" in result.error


# =============================================================================
# OVP Feedback Tests
# =============================================================================

class TestOVPFeedback:
    @pytest.mark.asyncio
    async def test_feedback_propagates(self):
        class FeedbackOVP:
            def __init__(self):
                self.calls = 0
            async def execute(self, context):
                self.calls += 1
                ctx = dict(context)
                if self.calls >= 2:
                    return PositionResult(
                        status=PositionStatus.SUCCESS, context=ctx,
                        approved=True, feedback="looks good",
                    )
                return PositionResult(
                    status=PositionStatus.SUCCESS, context=ctx,
                    approved=False, feedback="needs more work",
                )

        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            ovp=FeedbackOVP(), max_n=1, max_duo_cycles=5,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.SUCCESS
        assert result.outer_cycles == 2
        assert result.ovp_feedback == "looks good"

    @pytest.mark.asyncio
    async def test_feedback_in_context_for_next_cycle(self):
        class CheckFeedbackOVP:
            def __init__(self):
                self.calls = 0
                self.saw_feedback = False
            async def execute(self, context):
                self.calls += 1
                ctx = dict(context)
                if self.calls > 1 and ctx.get("ovp_feedback") == "try harder":
                    self.saw_feedback = True
                    return PositionResult(
                        status=PositionStatus.SUCCESS, context=ctx,
                        approved=True, feedback="ok now",
                    )
                return PositionResult(
                    status=PositionStatus.SUCCESS, context=ctx,
                    approved=False, feedback="try harder",
                )

        ovp = CheckFeedbackOVP()
        chain = DUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            ovp=ovp, max_n=1, max_duo_cycles=5,
        )
        result = await chain.execute({})
        assert result.status == DUOChainStatus.SUCCESS
        assert ovp.saw_feedback is True


# =============================================================================
# Constructor Tests
# =============================================================================

class TestConstructors:
    def test_duo_chain_constructor(self):
        chain = duo_chain(
            "test", MockPosition("a"), MockPosition("p"),
            MockOVPApproveAfterN(1), max_n=2, max_duo_cycles=3,
        )
        assert isinstance(chain, DUOChain)
        assert chain.max_n == 2
        assert chain.max_duo_cycles == 3

    def test_auto_duo_agent_is_duo_chain(self):
        assert issubclass(AutoDUOAgent, DUOChain)
