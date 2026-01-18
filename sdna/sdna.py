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
# SDNA^F (optimizer + target pairs)
# =============================================================================

class SDNAFlowchain:
    """SDNA^F - optimizer + target pairs."""

    def __init__(self, name: str, pairs: List[Tuple[OptimizerSDNACConfig, SDNACConfig]]):
        self.name = name
        self.pairs = pairs

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> SDNAResult:
        ctx = dict(context) if context else {}
        # Implementation: run target, then optimizer reviews
        # (Full implementation requires hydration from configs)
        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)

    def to_graph(self) -> CompiledGraph:
        """
        Build LangGraph: optimizer + target pairs (meta-optimization).

        Each pair runs: target → optimizer reviews → iterate or done.
        """
        graph = StateGraph(SDNAState)

        # For now, simple sequential execution of pairs
        # Full implementation would have optimizer-driven iteration
        node_names = []
        for i, (optimizer_cfg, target_cfg) in enumerate(self.pairs):
            target_name = f"pair_{i}_target"
            optimizer_name = f"pair_{i}_optimizer"
            node_names.extend([target_name, optimizer_name])

            # Placeholder nodes - full impl would hydrate configs
            async def target_node(state: SDNAState) -> Dict[str, Any]:
                return {"status": "success"}

            async def optimizer_node(state: SDNAState) -> Dict[str, Any]:
                return {"status": "success"}

            graph.add_node(target_name, target_node)
            graph.add_node(optimizer_name, optimizer_node)

        # Wire sequentially
        if node_names:
            graph.add_edge(START, node_names[0])
            for i in range(len(node_names) - 1):
                graph.add_edge(node_names[i], node_names[i + 1])
            graph.add_edge(node_names[-1], END)
        else:
            async def passthrough(state: SDNAState) -> Dict[str, Any]:
                return {"status": "success"}
            graph.add_node("passthrough", passthrough)
            graph.add_edge(START, "passthrough")
            graph.add_edge("passthrough", END)

        return graph.compile()


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
