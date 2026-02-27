"""
DUOChain - DUO Pattern as SDNAFlowchain Specialization

DUOChain IS an SDNAFlowchain where the inner flow is A→P alternation.

Hierarchy:
    SDNAFlowchain (base) — any SDNAF + OVP evaluator loop
      └── DUOChain — A→P alternating flow + OVP loop
           └── AutoDUOAgent — all positions are SDNACs

DUO archetype positions:
- Ariadne (A-type): Context threading constraints
- Poimandres (P-type): Generation constraints
- OVP (Observer View-Point): Evaluation constraints
"""

from typing import Dict, Any, Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field
from enum import Enum

from .sdna import (
    SDNAFlowchain, SDNAFlowchainResult, SDNAFlowchainStatus,
    SDNAResult, SDNAStatus, SDNAFlow, SDNAC,
)


# =============================================================================
# POSITION RESULT
# =============================================================================

class PositionStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    AWAITING_INPUT = "awaiting_input"


@dataclass
class PositionResult:
    """Result from any position (A, P, or OVP) execution."""
    status: PositionStatus
    context: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    approved: Optional[bool] = None
    feedback: Optional[str] = None


# =============================================================================
# POSITION PROTOCOL
# =============================================================================

@runtime_checkable
class DUOPosition(Protocol):
    """Abstract position in a DUOChain. Any async execute(context)->PositionResult."""
    async def execute(self, context: Dict[str, Any]) -> PositionResult: ...


# =============================================================================
# DUO CHAIN RESULT (extends SDNAFlowchainResult with inner iteration tracking)
# =============================================================================

class DUOChainStatus(str, Enum):
    SUCCESS = "success"
    MAX_CYCLES = "max_cycles"
    BLOCKED = "blocked"
    ERROR = "error"
    AWAITING_INPUT = "awaiting_input"


@dataclass
class DUOChainResult:
    status: DUOChainStatus
    context: Dict[str, Any] = field(default_factory=dict)
    inner_iterations: int = 0
    outer_cycles: int = 0
    error: Optional[str] = None
    ovp_feedback: Optional[str] = None


# =============================================================================
# DUO CHAIN (SDNAFlowchain with A→P alternating flow)
# =============================================================================

class DUOChain(SDNAFlowchain):
    """
    DUO pattern: A→P alternating flow evaluated by OVP.

    Extends SDNAFlowchain — the inner flow is A→P alternation for max_n steps.

    Structure:
        loop (max_duo_cycles):          # outer loop (from SDNAFlowchain)
            loop (max_n):               # inner loop (A→P alternation)
                A → P → A → P → ...
            end inner
            OVP evaluates               # from SDNAFlowchain
            if OVP approves: break
        end outer
    """

    def __init__(
        self,
        name: str,
        ariadne: 'DUOPosition',
        poimandres: 'DUOPosition',
        ovp: 'DUOPosition',
        max_n: int = 3,
        max_duo_cycles: int = 3,
    ):
        # SDNAFlowchain base — flow=None (we override _run_flow), ovp handled by us
        super().__init__(
            name=name,
            flow=None,  # type: ignore — we override _run_flow
            ovp=None,   # type: ignore — we override _evaluate
            max_cycles=max_duo_cycles,
        )
        self.ariadne = ariadne
        self.poimandres = poimandres
        self._ovp = ovp
        self.max_n = max_n
        self.max_duo_cycles = max_duo_cycles
        self._total_inner = 0

    async def _run_flow(self, ctx: Dict[str, Any]) -> SDNAResult:
        """A→P alternating for max_n steps."""
        for step in range(self.max_n):
            ctx["duo_inner_step"] = step + 1
            self._total_inner += 1

            # A position
            a_result = await self.ariadne.execute(ctx)
            ctx = a_result.context
            if a_result.status != PositionStatus.SUCCESS:
                return SDNAResult(
                    status=_pos_to_sdna(a_result.status),
                    context=ctx,
                    error=a_result.error,
                )

            # P position
            p_result = await self.poimandres.execute(ctx)
            ctx = p_result.context
            if p_result.status != PositionStatus.SUCCESS:
                return SDNAResult(
                    status=_pos_to_sdna(p_result.status),
                    context=ctx,
                    error=p_result.error,
                )

        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)

    async def _evaluate(self, ctx: Dict[str, Any]) -> SDNAResult:
        """Run OVP position evaluation."""
        ovp_result = await self._ovp.execute(ctx)
        ctx = ovp_result.context

        # Set approval in context for SDNAFlowchain._check_approval
        if ovp_result.approved is not None:
            ctx[self.approval_key] = ovp_result.approved
        if ovp_result.feedback is not None:
            ctx[self.feedback_key] = ovp_result.feedback

        return SDNAResult(
            status=_pos_to_sdna(ovp_result.status),
            context=ctx,
            error=ovp_result.error,
        )

    async def execute(self, context=None) -> DUOChainResult:
        """Run DUO state machine. Returns DUOChainResult with inner iteration tracking."""
        self._total_inner = 0
        fc_result = await super().execute(context)

        return DUOChainResult(
            status=_fc_to_duo(fc_result.status),
            context=fc_result.context,
            inner_iterations=self._total_inner,
            outer_cycles=fc_result.cycles,
            error=fc_result.error,
            ovp_feedback=fc_result.ovp_feedback,
        )


def _pos_to_sdna(ps: PositionStatus) -> SDNAStatus:
    return {
        PositionStatus.SUCCESS: SDNAStatus.SUCCESS,
        PositionStatus.ERROR: SDNAStatus.ERROR,
        PositionStatus.BLOCKED: SDNAStatus.BLOCKED,
        PositionStatus.AWAITING_INPUT: SDNAStatus.AWAITING_INPUT,
    }.get(ps, SDNAStatus.ERROR)


def _fc_to_duo(fs: SDNAFlowchainStatus) -> DUOChainStatus:
    return {
        SDNAFlowchainStatus.SUCCESS: DUOChainStatus.SUCCESS,
        SDNAFlowchainStatus.MAX_CYCLES: DUOChainStatus.MAX_CYCLES,
        SDNAFlowchainStatus.BLOCKED: DUOChainStatus.BLOCKED,
        SDNAFlowchainStatus.ERROR: DUOChainStatus.ERROR,
        SDNAFlowchainStatus.AWAITING_INPUT: DUOChainStatus.AWAITING_INPUT,
    }.get(fs, DUOChainStatus.ERROR)


# =============================================================================
# CONCRETE POSITIONS
# =============================================================================

class SDNACPosition:
    """Wraps an SDNAC as a DUOPosition (for A or P slots)."""
    def __init__(self, sdnac):
        self.sdnac = sdnac

    async def execute(self, context: Dict[str, Any]) -> PositionResult:
        result = await self.sdnac.execute(context)
        return PositionResult(
            status=_sdna_to_pos(result.status),
            context=result.context,
            error=result.error,
        )


class SDNACOVPPosition:
    """Wraps an SDNAC as OVP with approval extraction."""
    def __init__(self, sdnac, approval_key="ovp_approved", feedback_key="ovp_feedback"):
        self.sdnac = sdnac
        self.approval_key = approval_key
        self.feedback_key = feedback_key

    async def execute(self, context: Dict[str, Any]) -> PositionResult:
        result = await self.sdnac.execute(context)
        ctx = result.context

        approved = ctx.get(self.approval_key)
        if approved is None:
            ovp_text = ctx.get("text", "").upper()
            approved = "APPROVED" in ovp_text or "OVP_APPROVED: TRUE" in ovp_text
            ctx[self.approval_key] = approved

        feedback = ctx.get(self.feedback_key)
        if feedback is None:
            feedback = ctx.get("text", "")
            ctx[self.feedback_key] = feedback

        return PositionResult(
            status=_sdna_to_pos(result.status),
            context=ctx,
            error=result.error,
            approved=bool(approved),
            feedback=feedback,
        )


class PassthroughPosition:
    """Position that passes context through unchanged."""
    async def execute(self, context: Dict[str, Any]) -> PositionResult:
        return PositionResult(status=PositionStatus.SUCCESS, context=dict(context))


class CallablePosition:
    """Position that wraps any async callable."""
    def __init__(self, fn):
        self.fn = fn

    async def execute(self, context: Dict[str, Any]) -> PositionResult:
        try:
            result_ctx = await self.fn(context)
            return PositionResult(
                status=PositionStatus.SUCCESS,
                context=result_ctx if isinstance(result_ctx, dict) else dict(context),
            )
        except Exception as e:
            return PositionResult(
                status=PositionStatus.ERROR,
                context=dict(context),
                error=str(e),
            )


def _sdna_to_pos(sdna_status) -> PositionStatus:
    return {
        SDNAStatus.SUCCESS: PositionStatus.SUCCESS,
        SDNAStatus.BLOCKED: PositionStatus.BLOCKED,
        SDNAStatus.ERROR: PositionStatus.ERROR,
        SDNAStatus.AWAITING_INPUT: PositionStatus.AWAITING_INPUT,
    }.get(sdna_status, PositionStatus.ERROR)


# =============================================================================
# AUTODUOAGENT
# =============================================================================

class AutoDUOAgent(DUOChain):
    """DUOChain where all positions are SDNACs (LLM-equipped)."""

    def __init__(
        self, name, ariadne, poimandres, ovp,
        max_n=1, max_duo_cycles=3,
        approval_key="ovp_approved", feedback_key="ovp_feedback",
    ):
        super().__init__(
            name=name,
            ariadne=SDNACPosition(ariadne),
            poimandres=SDNACPosition(poimandres),
            ovp=SDNACOVPPosition(ovp, approval_key, feedback_key),
            max_n=max_n,
            max_duo_cycles=max_duo_cycles,
        )
        self._ariadne_sdnac = ariadne
        self._poimandres_sdnac = poimandres
        self._ovp_sdnac = ovp


# =============================================================================
# CONSTRUCTORS
# =============================================================================

def duo_chain(name, ariadne, poimandres, ovp, max_n=3, max_duo_cycles=3):
    """Create a DUOChain: A→P alternating flow + OVP evaluation loop."""
    return DUOChain(name, ariadne, poimandres, ovp, max_n, max_duo_cycles)


def auto_duo_agent(name, ariadne, poimandres, ovp, max_n=1, max_duo_cycles=3):
    """Create an AutoDUOAgent: all positions are SDNACs."""
    return AutoDUOAgent(name, ariadne, poimandres, ovp, max_n, max_duo_cycles)
