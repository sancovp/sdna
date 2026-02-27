"""
SDNA - Sanctuary DNA

The spiral of Ariadne and Poimandres.
LangGraph is the native execution substrate.

SDNAC = AriadneChain → HermesConfig → Poimandres executes → repeat
SDNAF = flow of SDNACs
SDNA^F = optimizer + target pairs
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel, Field

from langgraph.graph import StateGraph, START, END
from langgraph.graph.graph import CompiledGraph

from .config import HermesConfig
from .ariadne import AriadneChain, AriadneResult, AriadneStatus
from .state import SDNAState, initial_state
from . import poimandres


# =============================================================================
# STATUS & RESULT
# =============================================================================

class SDNAStatus(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    ERROR = "error"
    AWAITING_INPUT = "awaiting_input"


@dataclass
class SDNAResult:
    status: SDNAStatus
    context: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    resume_path: Optional[List[int]] = None
    pending_prompt: Optional[str] = None
    pending_input_key: Optional[str] = None


# =============================================================================
# SDNAC (Ariadne → HermesConfig → Poimandres)
# =============================================================================

class SDNAC:
    """
    Single SDNAC unit: AriadneChain preps context, then Poimandres executes config.
    """

    def __init__(self, name: str, ariadne: AriadneChain, config: HermesConfig):
        self.name = name
        self.ariadne = ariadne
        self.config = config

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> SDNAResult:
        ctx = dict(context) if context else {}

        # Ariadne preps the thread
        ariadne_result = await self.ariadne.execute(ctx)
        ctx = ariadne_result.context

        if ariadne_result.status == AriadneStatus.AWAITING_INPUT:
            return SDNAResult(
                status=SDNAStatus.AWAITING_INPUT,
                context=ctx,
                pending_prompt=ariadne_result.pending_prompt,
                pending_input_key=ariadne_result.pending_input_key,
            )
        elif ariadne_result.status == AriadneStatus.ERROR:
            return SDNAResult(status=SDNAStatus.ERROR, context=ctx, error=ariadne_result.error)

        # Poimandres generates
        poimandres_result = await poimandres.execute(self.config, ctx)

        if poimandres_result.blocked:
            return SDNAResult(status=SDNAStatus.BLOCKED, context=ctx)
        elif not poimandres_result.success:
            return SDNAResult(status=SDNAStatus.ERROR, context=ctx, error=poimandres_result.error)

        ctx.update(poimandres_result.output)
        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)

    def to_graph(self) -> CompiledGraph:
        """
        Build LangGraph: Ariadne subgraph → Poimandres node.

        Returns a compiled graph that can be invoked or composed.
        """
        graph = StateGraph(SDNAState)

        # Ariadne as subgraph (has internal visibility)
        graph.add_node("ariadne", self.ariadne.to_graph())

        # Poimandres as node
        graph.add_node("poimandres", self.config.to_langgraph_node())

        # Check Ariadne result - if awaiting input, stop
        def check_ariadne(state: SDNAState) -> str:
            if state.get("awaiting_input"):
                return "wait"
            if state.get("status") == "error":
                return "error"
            return "continue"

        graph.add_edge(START, "ariadne")
        graph.add_conditional_edges(
            "ariadne",
            check_ariadne,
            {"wait": END, "error": END, "continue": "poimandres"}
        )
        graph.add_edge("poimandres", END)

        return graph.compile()


# =============================================================================
# SDNAF (flow of SDNACs)
# =============================================================================

class SDNAFlow:
    """SDNAF - Flow of SDNACs."""

    def __init__(self, name: str, sdnacs: List[SDNAC]):
        self.name = name
        self.sdnacs = sdnacs

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> SDNAResult:
        ctx = dict(context) if context else {}

        for i, sdnac in enumerate(self.sdnacs):
            result = await sdnac.execute(ctx)
            ctx = result.context

            if result.status != SDNAStatus.SUCCESS:
                result.resume_path = [i]
                return result

        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)

    def to_graph(self) -> CompiledGraph:
        """
        Build LangGraph: sequence of SDNAC subgraphs.

        Each SDNAC is a subgraph with internal visibility.
        """
        graph = StateGraph(SDNAState)

        # Add each SDNAC as a subgraph node
        node_names = []
        for i, unit in enumerate(self.sdnacs):
            node_name = f"{self.name}_unit_{i}"
            node_names.append(node_name)
            graph.add_node(node_name, unit.to_graph())

        # Check status after each unit
        def check_status(state: SDNAState) -> str:
            status = state.get("status", "success")
            if status == "success":
                return "continue"
            return "stop"  # blocked, error, awaiting_input

        # Wire: START → unit_0 → unit_1 → ... → END
        if node_names:
            graph.add_edge(START, node_names[0])
            for i in range(len(node_names) - 1):
                graph.add_conditional_edges(
                    node_names[i],
                    check_status,
                    {"continue": node_names[i + 1], "stop": END}
                )
            graph.add_edge(node_names[-1], END)
        else:
            async def passthrough(state: SDNAState) -> Dict[str, Any]:
                return {"status": "success"}
            graph.add_node("passthrough", passthrough)
            graph.add_edge(START, "passthrough")
            graph.add_edge("passthrough", END)

        return graph.compile()


# =============================================================================
# CONFIGS (serializable)
# =============================================================================

class SDNACConfig(BaseModel):
    """Serializable config for SDNAC."""
    name: str
    ariadne_elements: List[dict]
    hermes_config: dict


class OptimizerSDNACConfig(SDNACConfig):
    """Config for optimizer SDNAC."""
    optimization_target: str
    optimization_strategy: str
    feedback_key: str = "optimizer_feedback"


class SDNAFlowConfig(BaseModel):
    """Config for SDNAF."""
    name: str
    sdnacs: List[SDNACConfig]


# =============================================================================
# SDNA^F (SDNAFlowchain = SDNAF + OVP evaluator loop)
# =============================================================================

class SDNAFlowchainStatus(str, Enum):
    SUCCESS = "success"
    MAX_CYCLES = "max_cycles"
    BLOCKED = "blocked"
    ERROR = "error"
    AWAITING_INPUT = "awaiting_input"


@dataclass
class SDNAFlowchainResult:
    status: SDNAFlowchainStatus
    context: Dict[str, Any] = field(default_factory=dict)
    cycles: int = 0
    error: Optional[str] = None
    ovp_feedback: Optional[str] = None


class SDNAFlowchain:
    """
    SDNA^F — any SDNAF evaluated by an OVP SDNAC in a loop.

    Structure:
        loop (max_cycles):
            run flow (SDNAF — N SDNACs in sequence)
            OVP evaluates
            if OVP approves: done
        end loop

    The flow is any SDNAFlow (or object with async execute(ctx) -> SDNAResult).
    The OVP is an SDNAC that evaluates and sets approval in context.
    The target is an optional goal string injected into context.

    DUOChain extends this with A→P alternation as the flow.
    """

    def __init__(
        self,
        name: str,
        flow: SDNAFlow,
        ovp: SDNAC,
        target: Optional[str] = None,
        max_cycles: int = 3,
        approval_key: str = "ovp_approved",
        feedback_key: str = "ovp_feedback",
    ):
        self.name = name
        self.flow = flow
        self.ovp = ovp
        self.target = target
        self.max_cycles = max_cycles
        self.approval_key = approval_key
        self.feedback_key = feedback_key

    async def _run_flow(self, ctx: Dict[str, Any]) -> SDNAResult:
        """Run the inner flow. Override for custom flow patterns (e.g. DUOChain A→P)."""
        return await self.flow.execute(ctx)

    async def _evaluate(self, ctx: Dict[str, Any]) -> SDNAResult:
        """Run OVP evaluation. Override for custom evaluation logic."""
        return await self.ovp.execute(ctx)

    def _check_approval(self, ctx: Dict[str, Any]) -> tuple:
        """Extract approval and feedback from context. Returns (approved, feedback)."""
        approved = ctx.get(self.approval_key)
        if approved is None:
            ovp_text = ctx.get("text", "").upper()
            approved = "APPROVED" in ovp_text or "OVP_APPROVED: TRUE" in ovp_text
            ctx[self.approval_key] = approved
        feedback = ctx.get(self.feedback_key)
        if feedback is None:
            feedback = ctx.get("text", "")
            ctx[self.feedback_key] = feedback
        return bool(approved), feedback

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> SDNAFlowchainResult:
        """
        Run the SDNA^F loop: flow executes → OVP evaluates → loop or done.

        Do-while semantics: runs at least one complete cycle.
        """
        ctx = dict(context) if context else {}
        if self.target:
            ctx["target"] = self.target

        for cycle in range(self.max_cycles):
            ctx["flowchain_cycle"] = cycle + 1

            # Run inner flow
            flow_result = await self._run_flow(ctx)
            ctx = flow_result.context

            if flow_result.status != SDNAStatus.SUCCESS:
                return SDNAFlowchainResult(
                    status=_map_sdna_to_flowchain(flow_result.status),
                    context=ctx,
                    cycles=cycle + 1,
                    error=flow_result.error,
                )

            # OVP evaluates
            ctx["duo_evaluating"] = True
            ovp_result = await self._evaluate(ctx)
            ctx = ovp_result.context
            ctx.pop("duo_evaluating", None)

            if ovp_result.status != SDNAStatus.SUCCESS:
                return SDNAFlowchainResult(
                    status=_map_sdna_to_flowchain(ovp_result.status),
                    context=ctx,
                    cycles=cycle + 1,
                    error=ovp_result.error,
                )

            # Check approval
            approved, feedback = self._check_approval(ctx)

            if approved:
                return SDNAFlowchainResult(
                    status=SDNAFlowchainStatus.SUCCESS,
                    context=ctx,
                    cycles=cycle + 1,
                    ovp_feedback=feedback,
                )

            # Not approved — feedback for next cycle
            if feedback:
                ctx["ovp_feedback"] = feedback

        return SDNAFlowchainResult(
            status=SDNAFlowchainStatus.MAX_CYCLES,
            context=ctx,
            cycles=self.max_cycles,
            ovp_feedback=ctx.get("ovp_feedback"),
        )


def _map_sdna_to_flowchain(status: SDNAStatus) -> SDNAFlowchainStatus:
    """Map SDNAStatus to SDNAFlowchainStatus."""
    return {
        SDNAStatus.ERROR: SDNAFlowchainStatus.ERROR,
        SDNAStatus.BLOCKED: SDNAFlowchainStatus.BLOCKED,
        SDNAStatus.AWAITING_INPUT: SDNAFlowchainStatus.AWAITING_INPUT,
    }.get(status, SDNAFlowchainStatus.ERROR)


# =============================================================================
# CONSTRUCTORS
# =============================================================================

def sdnac(name: str, ariadne: AriadneChain, config: HermesConfig) -> SDNAC:
    """
    Create an SDNAC unit: AriadneChain preps context, then Poimandres executes.

    Args:
        name: Unit identifier
        ariadne: AriadneChain for context preparation
        config: HermesConfig (the message Ariadne sends)

    Example:
        unit = sdnac('generate',
            ariadne('prep', inject_file('spec.md', 'spec')),
            HermesConfig(name='gen', system_prompt='...')
        )
        result = await unit.execute({'initial': 'context'})
    """
    return SDNAC(name, ariadne, config)


def sdna_flowchain(
    name: str,
    flow: SDNAFlow,
    ovp: SDNAC,
    target: Optional[str] = None,
    max_cycles: int = 3,
) -> SDNAFlowchain:
    """
    Create an SDNA^F: SDNAF + OVP evaluator in a loop.

    Args:
        name: Flowchain identifier
        flow: SDNAFlow (N SDNACs in sequence) — the inner flow
        ovp: OVP-type SDNAC that evaluates and approves/rejects
        target: Optional goal string injected into context
        max_cycles: Maximum OVP evaluation cycles (default: 3)
    """
    return SDNAFlowchain(name, flow, ovp, target=target, max_cycles=max_cycles)


def sdna_flow(name: str, *sdnacs: SDNAC) -> SDNAFlow:
    """
    Create an SDNAF: sequential flow of SDNACs.

    Args:
        name: Flow identifier
        *sdnacs: SDNAC units to execute in sequence

    Example:
        flow = sdna_flow('pipeline', unit1, unit2, unit3)
        result = await flow.execute()
        # Stops on first non-SUCCESS, returns resume_path
    """
    return SDNAFlow(name, list(sdnacs))
