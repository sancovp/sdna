"""
DUO - Dual Space Unifying Operators (DEPRECATED)

DEPRECATED: Use DUOChain from duo_chain.py instead.

DUOAgent is the original 2-SDNAC pattern (poimandres + OVP) without a separate
Ariadne position. It works but is structurally incomplete — missing the A-type
archetype for explicit context threading between cycles.

Migration:
    # Old (DUOAgent):
    duo = duo_agent('name', target_sdnac, ovp_sdnac, max_iterations=3)

    # New (DUOChain with Passthrough A):
    from sdna.duo_chain import duo_chain, PassthroughPosition, SDNACPosition, SDNACOVPPosition
    chain = duo_chain('name',
        ariadne=PassthroughPosition(),
        poimandres=SDNACPosition(target_sdnac),
        ovp=SDNACOVPPosition(ovp_sdnac),
        max_n=1, max_duo_cycles=3,
    )

    # Or use AutoDUOAgent with explicit A:
    chain = auto_duo_agent('name', ariadne_sdnac, poimandres_sdnac, ovp_sdnac)

DUO archetype positions:
- Ariadne (A-type): Context threading constraints
- Poimandres (P-type): Generation constraints
- OVP (Observer View-Point): Evaluation constraints
"""

import warnings

from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from langgraph.graph import StateGraph, START, END
from langgraph.graph.graph import CompiledGraph

from .sdna import SDNAC, SDNAResult, SDNAStatus
from .state import SDNAState


# =============================================================================
# DUO STATUS & RESULT
# =============================================================================

class DUOStatus(str, Enum):
    SUCCESS = "success"          # OVP approved
    MAX_ITERATIONS = "max_iterations"  # Hit limit without approval
    BLOCKED = "blocked"          # SDNAC was blocked
    ERROR = "error"
    AWAITING_INPUT = "awaiting_input"


@dataclass
class DUOResult:
    status: DUOStatus
    context: Dict[str, Any] = field(default_factory=dict)
    iterations: int = 0
    error: Optional[str] = None
    ovp_feedback: Optional[str] = None  # Last feedback from OVP


# =============================================================================
# DUOAgent
# =============================================================================

class DUOAgent:
    """
    DEPRECATED: Use DUOChain or AutoDUOAgent from duo_chain.py instead.

    Original 2-SDNAC DUO pattern (poimandres + OVP).
    Missing separate Ariadne archetype position.

    The 'target' parameter is the Poimandres-typed SDNAC (does the work).
    The 'ovp' parameter is the OVP-typed SDNAC (evaluates).
    """

    def __init__(
        self,
        name: str,
        target: SDNAC,
        ovp: SDNAC,
        max_iterations: int = 3,
        approval_key: str = "ovp_approved",
        feedback_key: str = "ovp_feedback",
    ):
        warnings.warn(
            "DUOAgent is deprecated. Use DUOChain or AutoDUOAgent from duo_chain.py instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.name = name
        self.target = target
        self.ovp = ovp
        self.max_iterations = max_iterations
        self.approval_key = approval_key
        self.feedback_key = feedback_key

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> DUOResult:
        """
        Run the DUO loop: Target SDNAC → OVP SDNAC evaluates → loop or done.

        Args:
            context: Initial context dict

        Returns:
            DUOResult with final context and iteration count
        """
        ctx = dict(context) if context else {}
        ctx["duo_iteration"] = 0

        for iteration in range(self.max_iterations):
            ctx["duo_iteration"] = iteration + 1

            # Run Target SDNAC (Poimandres does the work)
            target_result = await self.target.execute(ctx)
            ctx = target_result.context

            # Preserve target output before OVP potentially overwrites "text"
            ctx["target_output"] = ctx.get("text", "")

            # Check for non-success from Target
            if target_result.status == SDNAStatus.AWAITING_INPUT:
                return DUOResult(
                    status=DUOStatus.AWAITING_INPUT,
                    context=ctx,
                    iterations=iteration + 1,
                )
            elif target_result.status == SDNAStatus.BLOCKED:
                return DUOResult(
                    status=DUOStatus.BLOCKED,
                    context=ctx,
                    iterations=iteration + 1,
                )
            elif target_result.status == SDNAStatus.ERROR:
                return DUOResult(
                    status=DUOStatus.ERROR,
                    context=ctx,
                    iterations=iteration + 1,
                    error=target_result.error,
                )

            # Run OVP SDNAC (Observer evaluates with its own LLM call)
            ovp_result = await self.ovp.execute(ctx)
            ctx = ovp_result.context

            # Check for non-success from OVP
            if ovp_result.status == SDNAStatus.ERROR:
                return DUOResult(
                    status=DUOStatus.ERROR,
                    context=ctx,
                    iterations=iteration + 1,
                    error=ovp_result.error,
                )
            elif ovp_result.status == SDNAStatus.BLOCKED:
                return DUOResult(
                    status=DUOStatus.BLOCKED,
                    context=ctx,
                    iterations=iteration + 1,
                )

            # Check if OVP approved
            # If approval_key not explicitly set (e.g. Heaven backend only returns text),
            # parse OVP text output for approval keywords
            approved = ctx.get(self.approval_key)
            if approved is None:
                ovp_text = ctx.get("text", "").upper()
                approved = "APPROVED" in ovp_text or "OVP_APPROVED: TRUE" in ovp_text
                ctx[self.approval_key] = approved
            feedback = ctx.get(self.feedback_key)
            if feedback is None:
                feedback = ctx.get("text", "")
                ctx[self.feedback_key] = feedback

            if approved:
                return DUOResult(
                    status=DUOStatus.SUCCESS,
                    context=ctx,
                    iterations=iteration + 1,
                    ovp_feedback=feedback,
                )

            # Not approved - will retry (feedback available for next iteration)

        # Hit max iterations without approval
        return DUOResult(
            status=DUOStatus.MAX_ITERATIONS,
            context=ctx,
            iterations=self.max_iterations,
            ovp_feedback=ctx.get(self.feedback_key),
        )

    def to_graph(self) -> CompiledGraph:
        """
        Build LangGraph with iteration loop.

        Graph structure:
            START → target → check_target → ovp → check_ovp → (loop back or END)
        """
        graph = StateGraph(SDNAState)

        # Add Target SDNAC as subgraph
        graph.add_node("target", self.target.to_graph())

        # Add OVP SDNAC as subgraph
        graph.add_node("ovp", self.ovp.to_graph())

        # Initialize iteration counter
        async def init_iteration(state: SDNAState) -> Dict[str, Any]:
            ctx = dict(state.get("context", {}))
            ctx["duo_iteration"] = ctx.get("duo_iteration", 0) + 1
            return {"context": ctx, "iteration": ctx["duo_iteration"]}

        graph.add_node("init", init_iteration)

        # Check Target result
        def check_target(state: SDNAState) -> str:
            status = state.get("status", "success")
            if status == "success":
                return "continue"
            return "stop"  # blocked, error, awaiting_input

        # Check OVP result - approved or retry?
        def check_ovp(state: SDNAState) -> str:
            ctx = state.get("context", {})
            approved = ctx.get(self.approval_key, False)
            iteration = state.get("iteration", 1)

            if approved:
                return "done"
            elif iteration >= self.max_iterations:
                return "max_iterations"
            else:
                return "retry"

        # Wire the graph
        graph.add_edge(START, "init")
        graph.add_edge("init", "target")
        graph.add_conditional_edges(
            "target",
            check_target,
            {"continue": "ovp", "stop": END}
        )
        graph.add_conditional_edges(
            "ovp",
            check_ovp,
            {"done": END, "max_iterations": END, "retry": "init"}
        )

        return graph.compile()


# =============================================================================
# CONSTRUCTOR
# =============================================================================

def duo_agent(
    name: str,
    target: SDNAC,
    ovp: SDNAC,
    max_iterations: int = 3,
) -> DUOAgent:
    """
    DEPRECATED: Use duo_chain() or auto_duo_agent() from duo_chain.py instead.

    Create a DUOAgent: Two SDNACs in refinement loop.
    """
    return DUOAgent(name, target, ovp, max_iterations)
