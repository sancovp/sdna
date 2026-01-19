"""
DUO - Dual Space Unifying Operators

DUOAgent IS an SDNA^F where:
- Target = SDNAC (Poimandres does the work)
- OVP = SDNAC (Observer evaluates with its own LLM call)
- Loop: Target runs → OVP evaluates → rerun or accept (up to max_iterations)

This is a GAN pattern: generator (Target SDNAC) + discriminator (OVP SDNAC) in refinement loop.
Two SDNACs in a loop = SDNA^F.

Three roles in DUO theory:
- Ariadne (Challenger): Context threading - comes from upstream
- Poimandres (Provider): Generation - the Target SDNAC
- OVP (Observer View-Point): Evaluation - the OVP SDNAC that decides continue/done
"""

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
    DUO = Dual Space Unifying Operators

    DUOAgent IS an SDNA^F where:
    - Target = SDNAC (Poimandres does the work)
    - OVP = SDNAC (Observer evaluates with its own LLM call)
    - Loop until OVP approves or max_iterations reached

    Two SDNACs in a loop = SDNA^F (meta-optimization).

    The OVP SDNAC must set in context:
    - ovp_approved: bool - True to accept, False to retry
    - ovp_feedback: str - Optional feedback for next iteration

    Example:
        # Target: generates code
        target = sdnac('generate',
            ariadne('prep', inject_file('spec.md', 'spec')),
            HermesConfig(name='gen', goal='Generate code for {spec}')
        )

        # OVP: evaluates the output (has its own LLM call)
        ovp = sdnac('evaluate',
            ariadne('eval_prep', inject_literal('Evaluate the output', 'task')),
            HermesConfig(name='evaluator', goal='Set ovp_approved=True if good, False if needs work')
        )

        # DUOAgent: loops until approved
        duo = DUOAgent('code_gen', target, ovp, max_iterations=3)
        result = await duo.execute({'project': 'myapp'})
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
            approved = ctx.get(self.approval_key, False)
            feedback = ctx.get(self.feedback_key)

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
    Create a DUOAgent: Two SDNACs in refinement loop (SDNA^F).

    Args:
        name: Agent identifier
        target: The target SDNAC (Poimandres does the work)
        ovp: The OVP SDNAC (Observer evaluates with its own LLM call)
        max_iterations: Maximum refinement iterations (default: 3)

    Example:
        agent = duo_agent('refiner',
            sdnac('generate', ariadne('prep', ...), HermesConfig(...)),
            sdnac('evaluate', ariadne('eval', ...), HermesConfig(goal='Set ovp_approved=True/False')),
            max_iterations=5
        )
        result = await agent.execute(context)
    """
    return DUOAgent(name, target, ovp, max_iterations)
