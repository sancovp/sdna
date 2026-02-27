"""Tests for SDNAFlowchain, type hierarchy, and deprecation."""

import warnings
import pytest
from sdna.sdna import (
    SDNAFlowchain, SDNAFlowchainResult, SDNAFlowchainStatus,
    SDNAResult, SDNAStatus, SDNAFlow, SDNAC,
    sdna_flowchain,
)
from sdna.duo_chain import (
    DUOChain, DUOChainResult, DUOChainStatus,
    AutoDUOAgent,
    PositionResult, PositionStatus,
)
from sdna.duo_v2 import DuoAgentV2, DUOv2Result, DUOv2Status
from sdna.duo import DUOAgent


# =============================================================================
# Mock Flow & OVP (implement the execute(ctx) -> SDNAResult protocol)
# =============================================================================

class MockFlow:
    """Flow that increments a counter and succeeds."""
    def __init__(self, key: str = "flow_runs"):
        self.key = key

    async def execute(self, context=None):
        ctx = dict(context) if context else {}
        ctx[self.key] = ctx.get(self.key, 0) + 1
        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)


class MockOVPApproveAfterN:
    """OVP that sets ovp_approved=True after N calls."""
    def __init__(self, approve_after: int = 1):
        self.approve_after = approve_after
        self.calls = 0

    async def execute(self, context=None):
        self.calls += 1
        ctx = dict(context) if context else {}
        approved = self.calls >= self.approve_after
        ctx["ovp_approved"] = approved
        ctx["ovp_feedback"] = f"Cycle {self.calls}: {'approved' if approved else 'needs work'}"
        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)


class MockOVPNeverApprove:
    """OVP that never approves."""
    async def execute(self, context=None):
        ctx = dict(context) if context else {}
        ctx["ovp_approved"] = False
        ctx["ovp_feedback"] = "never approving"
        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)


class MockBlockedFlow:
    async def execute(self, context=None):
        ctx = dict(context) if context else {}
        return SDNAResult(status=SDNAStatus.BLOCKED, context=ctx)


class MockErrorFlow:
    async def execute(self, context=None):
        ctx = dict(context) if context else {}
        return SDNAResult(status=SDNAStatus.ERROR, context=ctx, error="flow error")


class MockErrorOVP:
    async def execute(self, context=None):
        ctx = dict(context) if context else {}
        return SDNAResult(status=SDNAStatus.ERROR, context=ctx, error="ovp error")


class MockAwaitingFlow:
    async def execute(self, context=None):
        ctx = dict(context) if context else {}
        return SDNAResult(status=SDNAStatus.AWAITING_INPUT, context=ctx)


# =============================================================================
# SDNAFlowchain Basic Tests
# =============================================================================

class TestSDNAFlowchainBasic:
    @pytest.mark.asyncio
    async def test_single_cycle_approved(self):
        fc = SDNAFlowchain(
            name="test", flow=MockFlow(), ovp=MockOVPApproveAfterN(1),
            max_cycles=3,
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.SUCCESS
        assert result.cycles == 1
        assert result.context["flow_runs"] == 1
        assert result.context["ovp_approved"] is True

    @pytest.mark.asyncio
    async def test_multi_cycle_approved(self):
        fc = SDNAFlowchain(
            name="test", flow=MockFlow(), ovp=MockOVPApproveAfterN(3),
            max_cycles=5,
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.SUCCESS
        assert result.cycles == 3
        assert result.context["flow_runs"] == 3

    @pytest.mark.asyncio
    async def test_max_cycles_hit(self):
        fc = SDNAFlowchain(
            name="test", flow=MockFlow(), ovp=MockOVPNeverApprove(),
            max_cycles=3,
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.MAX_CYCLES
        assert result.cycles == 3
        assert result.context["flow_runs"] == 3

    @pytest.mark.asyncio
    async def test_target_goal_injected(self):
        fc = SDNAFlowchain(
            name="test", flow=MockFlow(), ovp=MockOVPApproveAfterN(1),
            target="Write a haiku about testing",
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.SUCCESS
        assert result.context["target"] == "Write a haiku about testing"

    @pytest.mark.asyncio
    async def test_context_preserved(self):
        fc = SDNAFlowchain(
            name="test", flow=MockFlow(), ovp=MockOVPApproveAfterN(1),
        )
        result = await fc.execute({"existing": "data", "number": 42})
        assert result.context["existing"] == "data"
        assert result.context["number"] == 42
        assert result.context["flow_runs"] == 1

    @pytest.mark.asyncio
    async def test_flowchain_cycle_counter_in_context(self):
        fc = SDNAFlowchain(
            name="test", flow=MockFlow(), ovp=MockOVPApproveAfterN(2),
            max_cycles=5,
        )
        result = await fc.execute({})
        assert result.context["flowchain_cycle"] == 2

    @pytest.mark.asyncio
    async def test_ovp_feedback_in_result(self):
        fc = SDNAFlowchain(
            name="test", flow=MockFlow(), ovp=MockOVPApproveAfterN(1),
        )
        result = await fc.execute({})
        assert result.ovp_feedback is not None
        assert "approved" in result.ovp_feedback


# =============================================================================
# SDNAFlowchain Error Handling
# =============================================================================

class TestSDNAFlowchainErrors:
    @pytest.mark.asyncio
    async def test_flow_blocked(self):
        fc = SDNAFlowchain(
            name="test", flow=MockBlockedFlow(), ovp=MockOVPApproveAfterN(1),
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_flow_error(self):
        fc = SDNAFlowchain(
            name="test", flow=MockErrorFlow(), ovp=MockOVPApproveAfterN(1),
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.ERROR
        assert result.error == "flow error"

    @pytest.mark.asyncio
    async def test_ovp_error(self):
        fc = SDNAFlowchain(
            name="test", flow=MockFlow(), ovp=MockErrorOVP(),
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.ERROR
        assert result.error == "ovp error"

    @pytest.mark.asyncio
    async def test_flow_awaiting_input(self):
        fc = SDNAFlowchain(
            name="test", flow=MockAwaitingFlow(), ovp=MockOVPApproveAfterN(1),
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.AWAITING_INPUT


# =============================================================================
# SDNAFlowchain Constructor
# =============================================================================

class TestSDNAFlowchainConstructor:
    def test_sdna_flowchain_constructor(self):
        fc = sdna_flowchain(
            "test", flow=MockFlow(), ovp=MockOVPApproveAfterN(1),
            target="goal", max_cycles=5,
        )
        assert isinstance(fc, SDNAFlowchain)
        assert fc.name == "test"
        assert fc.target == "goal"
        assert fc.max_cycles == 5

    @pytest.mark.asyncio
    async def test_sdna_flowchain_constructor_runs(self):
        fc = sdna_flowchain(
            "test", flow=MockFlow(), ovp=MockOVPApproveAfterN(1),
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.SUCCESS


# =============================================================================
# SDNAFlowchain Overridable Hooks
# =============================================================================

class TestSDNAFlowchainHooks:
    @pytest.mark.asyncio
    async def test_run_flow_overridable(self):
        """Subclass can override _run_flow for custom inner loop."""
        class CustomFlowchain(SDNAFlowchain):
            async def _run_flow(self, ctx):
                ctx["custom_flow"] = True
                return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)

        fc = CustomFlowchain(
            name="test", flow=None, ovp=MockOVPApproveAfterN(1),
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.SUCCESS
        assert result.context["custom_flow"] is True

    @pytest.mark.asyncio
    async def test_evaluate_overridable(self):
        """Subclass can override _evaluate for custom OVP logic."""
        class CustomEvalFlowchain(SDNAFlowchain):
            async def _evaluate(self, ctx):
                ctx["ovp_approved"] = True
                ctx["ovp_feedback"] = "custom eval approved"
                return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)

        fc = CustomEvalFlowchain(
            name="test", flow=MockFlow(), ovp=None,
        )
        result = await fc.execute({})
        assert result.status == SDNAFlowchainStatus.SUCCESS
        assert result.ovp_feedback == "custom eval approved"


# =============================================================================
# Type Hierarchy Tests
# =============================================================================

class TestTypeHierarchy:
    def test_duochain_is_sdnaflowchain(self):
        assert issubclass(DUOChain, SDNAFlowchain)

    def test_autoduoagent_is_duochain(self):
        assert issubclass(AutoDUOAgent, DUOChain)

    def test_autoduoagent_is_sdnaflowchain(self):
        assert issubclass(AutoDUOAgent, SDNAFlowchain)

    def test_duoagentv2_is_duochain(self):
        assert issubclass(DuoAgentV2, DUOChain)

    def test_duoagentv2_is_sdnaflowchain(self):
        assert issubclass(DuoAgentV2, SDNAFlowchain)

    def test_duoagent_v1_not_sdnaflowchain(self):
        """DUOAgent v1 is NOT in the new hierarchy."""
        assert not issubclass(DUOAgent, SDNAFlowchain)


# =============================================================================
# DUOChain as SDNAFlowchain Specialization
# =============================================================================

class TestDUOChainAsFlowchain:
    @pytest.mark.asyncio
    async def test_duochain_result_has_flowchain_fields(self):
        """DUOChainResult wraps SDNAFlowchainResult fields."""

        class SimplePos:
            async def execute(self, ctx):
                return PositionResult(status=PositionStatus.SUCCESS, context=dict(ctx))

        class ApproveOVP:
            async def execute(self, ctx):
                return PositionResult(
                    status=PositionStatus.SUCCESS, context=dict(ctx),
                    approved=True, feedback="ok",
                )

        chain = DUOChain(
            name="test", ariadne=SimplePos(), poimandres=SimplePos(),
            ovp=ApproveOVP(), max_n=2, max_duo_cycles=3,
        )
        result = await chain.execute({"target": "test goal"})
        assert result.status == DUOChainStatus.SUCCESS
        assert result.outer_cycles == 1
        assert result.inner_iterations == 2
        # Target preserved from SDNAFlowchain
        assert result.context.get("target") == "test goal"


# =============================================================================
# DUOAgent v1 Deprecation
# =============================================================================

class TestDeprecation:
    def test_duoagent_v1_warns(self):
        """DUOAgent v1 constructor emits DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # DUOAgent requires (name, target_sdnac, ovp_sdnac) — need mock SDNACs
            agent = DUOAgent.__new__(DUOAgent)  # bypass __init__ to avoid needing real args
            # Call __init__ manually with None args — will fail, but deprecation fires first
            try:
                DUOAgent.__init__(agent, "test", None, None)
            except Exception:
                pass  # We only care about the warning
            deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecation_warnings) >= 1
            assert "deprecated" in str(deprecation_warnings[0].message).lower()


# =============================================================================
# Import Tests
# =============================================================================

class TestNewImports:
    def test_sdnaflowchain_exports(self):
        from sdna import (
            SDNAFlowchain, SDNAFlowchainResult, SDNAFlowchainStatus,
            sdna_flowchain,
        )
        assert SDNAFlowchain is not None
        assert SDNAFlowchainResult is not None
        assert SDNAFlowchainStatus is not None
        assert callable(sdna_flowchain)

    def test_duochain_exports(self):
        from sdna import (
            DUOChain, DUOChainResult, DUOChainStatus,
            AutoDUOAgent, duo_chain, auto_duo_agent,
        )
        assert issubclass(DUOChain, SDNAFlowchain)
        assert issubclass(AutoDUOAgent, DUOChain)
