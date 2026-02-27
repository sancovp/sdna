"""Tests for OrchestratedDUOChain — external OVP pattern."""

import pytest
from sdna.orchestrated_duo_chain import (
    OrchestratedDUOChain, OrchestratedDUOChainResult, OrchestratedDUOChainStatus,
    orchestrated_duo_chain,
)
from sdna.duo_chain import (
    DUOChain, PositionResult, PositionStatus,
    PassthroughPosition,
)
from sdna.sdna import SDNAFlowchain


# =============================================================================
# Mock Positions
# =============================================================================

class MockPosition:
    def __init__(self, key: str):
        self.key = key
        self.call_count = 0

    async def execute(self, context):
        self.call_count += 1
        ctx = dict(context)
        ctx[self.key] = ctx.get(self.key, 0) + 1
        return PositionResult(status=PositionStatus.SUCCESS, context=ctx)


class MockBlockedPosition:
    async def execute(self, context):
        return PositionResult(status=PositionStatus.BLOCKED, context=dict(context))


class MockErrorPosition:
    async def execute(self, context):
        return PositionResult(status=PositionStatus.ERROR, context=dict(context), error="test error")


# =============================================================================
# Basic Execute/Resume
# =============================================================================

class TestOrchestratedBasic:
    @pytest.mark.asyncio
    async def test_execute_returns_awaiting_ovp(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            max_n=2, max_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == OrchestratedDUOChainStatus.AWAITING_OVP
        assert result.outer_cycles == 1
        assert result.inner_iterations == 2
        assert result.context["a"] == 2
        assert result.context["p"] == 2

    @pytest.mark.asyncio
    async def test_resume_approved(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            max_n=1, max_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == OrchestratedDUOChainStatus.AWAITING_OVP

        result = await chain.resume("Looks good!", approved=True)
        assert result.status == OrchestratedDUOChainStatus.SUCCESS
        assert result.ovp_feedback == "Looks good!"
        assert result.outer_cycles == 1

    @pytest.mark.asyncio
    async def test_resume_rejected_runs_next_cycle(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            max_n=1, max_cycles=5,
        )
        result = await chain.execute({})
        assert result.status == OrchestratedDUOChainStatus.AWAITING_OVP
        assert result.outer_cycles == 1

        result = await chain.resume("Needs work", approved=False)
        assert result.status == OrchestratedDUOChainStatus.AWAITING_OVP
        assert result.outer_cycles == 2
        assert result.context["a"] == 2
        assert result.context["p"] == 2

    @pytest.mark.asyncio
    async def test_multi_cycle_then_approve(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            max_n=1, max_cycles=5,
        )
        await chain.execute({})
        await chain.resume("try again", approved=False)
        await chain.resume("try again", approved=False)
        result = await chain.resume("ok now", approved=True)
        assert result.status == OrchestratedDUOChainStatus.SUCCESS
        assert result.outer_cycles == 3

    @pytest.mark.asyncio
    async def test_max_cycles_exhaustion(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            max_n=1, max_cycles=2,
        )
        await chain.execute({})
        await chain.resume("nope", approved=False)
        result = await chain.resume("still nope", approved=False)
        assert result.status == OrchestratedDUOChainStatus.MAX_CYCLES
        assert result.outer_cycles == 2

    @pytest.mark.asyncio
    async def test_context_preserved(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            max_n=1, max_cycles=3,
        )
        result = await chain.execute({"existing": "data"})
        assert result.context["existing"] == "data"

    @pytest.mark.asyncio
    async def test_feedback_in_context(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            max_n=1, max_cycles=3,
        )
        await chain.execute({})
        result = await chain.resume("fix the meter", approved=False)
        assert result.context["ovp_feedback"] == "fix the meter"


# =============================================================================
# Resume Target
# =============================================================================

class TestResumeTarget:
    @pytest.mark.asyncio
    async def test_resume_target_ariadne_calls_both(self):
        a = MockPosition("a")
        p = MockPosition("p")
        chain = OrchestratedDUOChain(
            name="test", ariadne=a, poimandres=p,
            max_n=1, max_cycles=3, resume_target="ariadne",
        )
        await chain.execute({})
        assert a.call_count == 1
        assert p.call_count == 1

        await chain.resume("try again", approved=False)
        assert a.call_count == 2  # A called again
        assert p.call_count == 2  # P called again

    @pytest.mark.asyncio
    async def test_resume_target_poimandres_skips_a(self):
        a = MockPosition("a")
        p = MockPosition("p")
        chain = OrchestratedDUOChain(
            name="test", ariadne=a, poimandres=p,
            max_n=1, max_cycles=3, resume_target="poimandres",
        )
        await chain.execute({})
        assert a.call_count == 1
        assert p.call_count == 1

        await chain.resume("try again", approved=False)
        assert a.call_count == 1  # A NOT called
        assert p.call_count == 2  # P called directly

    @pytest.mark.asyncio
    async def test_resume_target_override_per_call(self):
        a = MockPosition("a")
        p = MockPosition("p")
        chain = OrchestratedDUOChain(
            name="test", ariadne=a, poimandres=p,
            max_n=1, max_cycles=5, resume_target="ariadne",
        )
        await chain.execute({})
        # Override to poimandres for this one call
        await chain.resume("try again", approved=False, resume_target="poimandres")
        assert a.call_count == 1  # A skipped due to override
        assert p.call_count == 2

    @pytest.mark.asyncio
    async def test_resume_target_poimandres_max_n_gt_1(self):
        a = MockPosition("a")
        p = MockPosition("p")
        chain = OrchestratedDUOChain(
            name="test", ariadne=a, poimandres=p,
            max_n=3, max_cycles=3, resume_target="poimandres",
        )
        await chain.execute({})
        assert a.call_count == 3
        assert p.call_count == 3

        await chain.resume("try again", approved=False)
        # Step 1: P only. Steps 2-3: A→P each.
        assert a.call_count == 3 + 2  # 2 more A calls (steps 2,3)
        assert p.call_count == 3 + 3  # 3 more P calls (steps 1,2,3)


# =============================================================================
# Error Handling
# =============================================================================

class TestOrchestratedErrors:
    @pytest.mark.asyncio
    async def test_ariadne_blocked(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockBlockedPosition(), poimandres=MockPosition("p"),
            max_n=1, max_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == OrchestratedDUOChainStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_poimandres_error(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockErrorPosition(),
            max_n=1, max_cycles=3,
        )
        result = await chain.execute({})
        assert result.status == OrchestratedDUOChainStatus.ERROR
        assert result.error == "test error"

    @pytest.mark.asyncio
    async def test_resume_before_execute_raises(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
        )
        with pytest.raises(RuntimeError, match="execute"):
            await chain.resume("feedback", approved=True)

    @pytest.mark.asyncio
    async def test_resume_after_complete_raises(self):
        chain = OrchestratedDUOChain(
            name="test", ariadne=MockPosition("a"), poimandres=MockPosition("p"),
            max_n=1, max_cycles=3,
        )
        await chain.execute({})
        await chain.resume("ok", approved=True)
        with pytest.raises(RuntimeError, match="completed"):
            await chain.resume("again", approved=True)


# =============================================================================
# Type Hierarchy
# =============================================================================

class TestOrchestratedHierarchy:
    def test_is_duochain(self):
        assert issubclass(OrchestratedDUOChain, DUOChain)

    def test_is_sdnaflowchain(self):
        assert issubclass(OrchestratedDUOChain, SDNAFlowchain)

    def test_constructor(self):
        chain = orchestrated_duo_chain(
            "test", MockPosition("a"), MockPosition("p"),
            max_n=2, max_cycles=5, resume_target="poimandres",
        )
        assert isinstance(chain, OrchestratedDUOChain)
        assert isinstance(chain, DUOChain)

    def test_imports_from_sdna(self):
        from sdna import (
            OrchestratedDUOChain,
            OrchestratedDUOChainResult,
            OrchestratedDUOChainStatus,
            orchestrated_duo_chain,
        )
        assert OrchestratedDUOChain is not None
