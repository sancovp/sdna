"""
OrchestratedDUOChain - DUOChain with External OVP

Like DUOChain but pauses after each A→P cycle for external feedback
instead of running an internal OVP. Enables human-in-the-loop and
remote agent evaluation patterns.

Hierarchy:
    SDNAFlowchain (base)
      └── DUOChain — A→P alternating flow + internal OVP loop
           └── OrchestratedDUOChain — A→P flow + external OVP (pause/resume)

Usage:
    chain = orchestrated_duo_chain("my_chain", a_pos, p_pos, max_cycles=3)
    result = await chain.execute({"target": "Write a poem"})
    # result.status == AWAITING_OVP — inspect result.deliverable
    result = await chain.resume("Looks good!", approved=True)
    # result.status == SUCCESS
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from .sdna import SDNAResult, SDNAStatus
from .duo_chain import (
    DUOChain,
    PositionResult, PositionStatus, DUOPosition,
    PassthroughPosition,
    _pos_to_sdna,
)


# =============================================================================
# STATUS & RESULT
# =============================================================================

class OrchestratedDUOChainStatus(str, Enum):
    SUCCESS = "success"
    AWAITING_OVP = "awaiting_ovp"
    MAX_CYCLES = "max_cycles"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass
class OrchestratedDUOChainResult:
    status: OrchestratedDUOChainStatus
    context: Dict[str, Any] = field(default_factory=dict)
    inner_iterations: int = 0
    outer_cycles: int = 0
    error: Optional[str] = None
    ovp_feedback: Optional[str] = None
    deliverable: Optional[str] = None


# =============================================================================
# ORCHESTRATED DUO CHAIN
# =============================================================================

class OrchestratedDUOChain(DUOChain):
    """
    DUOChain with external OVP — pauses after A→P for caller-provided feedback.

    The A→P inner loop runs normally (max_n steps). Instead of automatically
    running an OVP position, the chain returns AWAITING_OVP. The caller
    inspects the deliverable and calls resume() with feedback.

    resume_target controls where feedback goes on the next cycle:
    - "ariadne": feedback → A re-challenges → P generates (thorough, 2+ LLM calls)
    - "poimandres": feedback → P regenerates directly (cheaper, 1+ LLM calls)
    """

    def __init__(
        self,
        name: str,
        ariadne: 'DUOPosition',
        poimandres: 'DUOPosition',
        max_n: int = 3,
        max_cycles: int = 3,
        resume_target: str = "ariadne",
        approval_key: str = "ovp_approved",
        feedback_key: str = "ovp_feedback",
    ):
        # DUOChain base — OVP is PassthroughPosition (never called)
        super().__init__(
            name=name,
            ariadne=ariadne,
            poimandres=poimandres,
            ovp=PassthroughPosition(),
            max_n=max_n,
            max_duo_cycles=max_cycles,
        )
        self.resume_target = resume_target
        self.approval_key = approval_key
        self.feedback_key = feedback_key

        # Internal state (reset on each execute())
        self._cycle = 0
        self._total_inner = 0
        self._context: Dict[str, Any] = {}
        self._phase = "idle"  # "idle" | "awaiting_ovp" | "complete"

    async def execute(self, context=None) -> OrchestratedDUOChainResult:
        """
        Run the first A→P cycle, then pause for external OVP.

        Returns AWAITING_OVP with deliverable in context.
        Returns ERROR/BLOCKED if the inner flow fails.
        """
        # Reset state
        self._cycle = 0
        self._total_inner = 0
        self._context = dict(context) if context else {}
        self._phase = "idle"

        if hasattr(self, 'target') and self.target:
            self._context["target"] = self.target

        return await self._run_one_cycle()

    async def resume(
        self,
        feedback: str,
        approved: bool = False,
        resume_target: Optional[str] = None,
    ) -> OrchestratedDUOChainResult:
        """
        Provide external OVP feedback and continue the chain.

        Args:
            feedback: The OVP feedback text
            approved: Whether the OVP approves the deliverable
            resume_target: Override where feedback goes ("ariadne" or "poimandres").
                           If None, uses self.resume_target.

        Returns AWAITING_OVP if another cycle needs feedback.
        Returns SUCCESS if approved.
        Returns MAX_CYCLES if limit reached.
        """
        if self._phase != "awaiting_ovp":
            raise RuntimeError(
                f"Chain not in AWAITING_OVP state (phase={self._phase}). "
                f"Call execute() first." if self._phase == "idle"
                else f"Chain already completed."
            )

        # Inject feedback
        self._context[self.feedback_key] = feedback
        self._context[self.approval_key] = approved

        if approved:
            self._phase = "complete"
            return OrchestratedDUOChainResult(
                status=OrchestratedDUOChainStatus.SUCCESS,
                context=self._context,
                inner_iterations=self._total_inner,
                outer_cycles=self._cycle,
                ovp_feedback=feedback,
                deliverable=self._context.get("deliverable") or self._context.get("text"),
            )

        if self._cycle >= self.max_duo_cycles:
            self._phase = "complete"
            return OrchestratedDUOChainResult(
                status=OrchestratedDUOChainStatus.MAX_CYCLES,
                context=self._context,
                inner_iterations=self._total_inner,
                outer_cycles=self._cycle,
                ovp_feedback=feedback,
            )

        # Run next cycle
        effective_target = resume_target or self.resume_target
        if effective_target == "poimandres":
            return await self._run_one_cycle(skip_ariadne_first=True)
        else:
            return await self._run_one_cycle()

    async def _run_one_cycle(self, skip_ariadne_first=False) -> OrchestratedDUOChainResult:
        """Run one A→P inner cycle, then pause."""
        self._cycle += 1
        ctx = self._context
        ctx["flowchain_cycle"] = self._cycle

        if skip_ariadne_first:
            flow_result = await self._run_flow_poimandres_first(ctx)
        else:
            flow_result = await self._run_flow(ctx)

        ctx = flow_result.context
        self._context = ctx

        if flow_result.status != SDNAStatus.SUCCESS:
            self._phase = "complete"
            return OrchestratedDUOChainResult(
                status=_sdna_to_orchestrated(flow_result.status),
                context=ctx,
                inner_iterations=self._total_inner,
                outer_cycles=self._cycle,
                error=flow_result.error,
            )

        self._phase = "awaiting_ovp"
        return OrchestratedDUOChainResult(
            status=OrchestratedDUOChainStatus.AWAITING_OVP,
            context=ctx,
            inner_iterations=self._total_inner,
            outer_cycles=self._cycle,
            deliverable=ctx.get("deliverable") or ctx.get("text"),
        )

    async def _run_flow_poimandres_first(self, ctx: Dict[str, Any]) -> SDNAResult:
        """A→P loop but P goes first on step 1 (skip A for cost saving)."""
        for step in range(self.max_n):
            ctx["duo_inner_step"] = step + 1
            self._total_inner += 1

            if step == 0:
                # Skip A, go straight to P
                p_result = await self.poimandres.execute(ctx)
                ctx = p_result.context
                if p_result.status != PositionStatus.SUCCESS:
                    return SDNAResult(
                        status=_pos_to_sdna(p_result.status),
                        context=ctx, error=p_result.error,
                    )
            else:
                # Normal A→P
                a_result = await self.ariadne.execute(ctx)
                ctx = a_result.context
                if a_result.status != PositionStatus.SUCCESS:
                    return SDNAResult(
                        status=_pos_to_sdna(a_result.status),
                        context=ctx, error=a_result.error,
                    )

                p_result = await self.poimandres.execute(ctx)
                ctx = p_result.context
                if p_result.status != PositionStatus.SUCCESS:
                    return SDNAResult(
                        status=_pos_to_sdna(p_result.status),
                        context=ctx, error=p_result.error,
                    )

        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)


def _sdna_to_orchestrated(status: SDNAStatus) -> OrchestratedDUOChainStatus:
    return {
        SDNAStatus.ERROR: OrchestratedDUOChainStatus.ERROR,
        SDNAStatus.BLOCKED: OrchestratedDUOChainStatus.BLOCKED,
        SDNAStatus.AWAITING_INPUT: OrchestratedDUOChainStatus.ERROR,
    }.get(status, OrchestratedDUOChainStatus.ERROR)


# =============================================================================
# CONSTRUCTOR
# =============================================================================

def orchestrated_duo_chain(
    name: str,
    ariadne: 'DUOPosition',
    poimandres: 'DUOPosition',
    max_n: int = 3,
    max_cycles: int = 3,
    resume_target: str = "ariadne",
) -> OrchestratedDUOChain:
    """Create an OrchestratedDUOChain: A→P flow with external OVP."""
    return OrchestratedDUOChain(name, ariadne, poimandres, max_n, max_cycles, resume_target)
