"""
Ariadne - The Threader

Context manipulation: inject, weave, dovetail, human input.
Ariadne prepares the thread that guides Poimandres.

LangGraph is the native execution substrate. Each element has to_langgraph_node(),
and AriadneChain has to_graph() which compiles to a LangGraph.
"""

from typing import Dict, Any, List, Union, Optional, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from pydantic import BaseModel, Field, ConfigDict
import importlib
import os

from langgraph.graph import StateGraph, START, END
from langgraph.graph.graph import CompiledGraph

from .config import DovetailModel
from .state import SDNAState

if TYPE_CHECKING:
    from .state import SDNAState


# =============================================================================
# ARIADNE ELEMENTS
# =============================================================================

class HumanInput(BaseModel):
    """Stop step - pause, return to human, resume with answer."""
    prompt: str
    input_key: str
    choices: Optional[List[str]] = None

    def to_langgraph_node(self) -> Callable[[SDNAState], Dict[str, Any]]:
        """Convert to LangGraph node that sets awaiting_input state."""
        async def node(state: SDNAState) -> Dict[str, Any]:
            return {
                "status": "awaiting_input",
                "awaiting_input": True,
                "pending_prompt": self.prompt,
                "pending_input_key": self.input_key,
                "pending_choices": self.choices,
            }
        return node


class InjectConfig(BaseModel):
    """Inject external data into context."""
    source: str  # "file", "function", "literal", "env"
    inject_as: str
    path: Optional[str] = None
    module: Optional[str] = None
    func: Optional[str] = None
    args: Dict[str, Any] = Field(default_factory=dict)
    value: Optional[Any] = None
    env_var: Optional[str] = None
    default: Optional[str] = None

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if self.source == "file":
            with open(self.path, 'r') as f:
                context[self.inject_as] = f.read()
        elif self.source == "function":
            mod = importlib.import_module(self.module)
            fn = getattr(mod, self.func)
            resolved = {
                k: context.get(v[1:], v) if isinstance(v, str) and v.startswith("$") else v
                for k, v in self.args.items()
            }
            context[self.inject_as] = fn(**resolved)
        elif self.source == "literal":
            context[self.inject_as] = self.value
        elif self.source == "env":
            context[self.inject_as] = os.environ.get(self.env_var, self.default)
        return context

    def to_langgraph_node(self) -> Callable[[SDNAState], Dict[str, Any]]:
        """Convert to LangGraph node that injects into context."""
        async def node(state: SDNAState) -> Dict[str, Any]:
            ctx = dict(state.get("context", {}))
            ctx = await self.execute(ctx)
            return {"context": ctx}
        return node


class WeaveConfig(BaseModel):
    """Context surgery - move message ranges between sessions."""
    source_session: Optional[str] = None
    target_session: Optional[str] = None
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    inject_as: str = "woven_context"

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: Implement with SDK session access
        context[self.inject_as] = {
            "source": self.source_session,
            "range": (self.start_index, self.end_index),
            "_pending": True,
        }
        return context

    def to_langgraph_node(self) -> Callable[[SDNAState], Dict[str, Any]]:
        """Convert to LangGraph node that weaves context."""
        async def node(state: SDNAState) -> Dict[str, Any]:
            ctx = dict(state.get("context", {}))
            ctx = await self.execute(ctx)
            return {"context": ctx}
        return node


AriadneElement = Union[HumanInput, InjectConfig, WeaveConfig, DovetailModel, "BrainInjectConfig"]


# =============================================================================
# RESULT
# =============================================================================

class AriadneStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    AWAITING_INPUT = "awaiting_input"


@dataclass
class AriadneResult:
    """Result of Ariadne chain execution."""
    status: AriadneStatus
    context: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    # For AWAITING_INPUT
    pending_prompt: Optional[str] = None
    pending_input_key: Optional[str] = None
    pending_choices: Optional[List[str]] = None
    resume_at: Optional[int] = None


# =============================================================================
# ARIADNE CHAIN
# =============================================================================

class AriadneChain:
    """
    Chain of context operations.
    Prepares the thread that guides Poimandres.
    """

    def __init__(self, name: str, elements: List[AriadneElement]):
        self.name = name
        self.elements = elements

    async def execute(
        self,
        context: Optional[Dict[str, Any]] = None,
        start_at: int = 0,
    ) -> AriadneResult:
        ctx = dict(context) if context else {}

        for i in range(start_at, len(self.elements)):
            elem = self.elements[i]

            try:
                if isinstance(elem, HumanInput):
                    return AriadneResult(
                        status=AriadneStatus.AWAITING_INPUT,
                        context=ctx,
                        pending_prompt=elem.prompt,
                        pending_input_key=elem.input_key,
                        pending_choices=elem.choices,
                        resume_at=i + 1,
                    )

                elif isinstance(elem, InjectConfig):
                    ctx = await elem.execute(ctx)

                elif isinstance(elem, WeaveConfig):
                    ctx = await elem.execute(ctx)

                elif isinstance(elem, BrainInjectConfig):
                    ctx = await elem.execute(ctx)

                elif isinstance(elem, DovetailModel):
                    next_inputs = elem.prepare_next_inputs(ctx)
                    ctx.update(next_inputs)

            except Exception as e:
                return AriadneResult(status=AriadneStatus.ERROR, context=ctx, error=str(e))

        return AriadneResult(status=AriadneStatus.SUCCESS, context=ctx)

    def __repr__(self):
        return f"AriadneChain('{self.name}', {len(self.elements)} elements)"

    def to_graph(self) -> CompiledGraph:
        """
        Build LangGraph from this chain's elements.

        Each element becomes a node. HumanInput nodes trigger interrupt.
        Returns a compiled graph that can be invoked or composed.
        """
        graph = StateGraph(SDNAState)

        # Add nodes for each element
        node_names = []
        for i, elem in enumerate(self.elements):
            node_name = f"{self.name}_step_{i}"
            node_names.append(node_name)

            if hasattr(elem, 'to_langgraph_node'):
                graph.add_node(node_name, elem.to_langgraph_node())
            elif isinstance(elem, DovetailModel):
                # Dovetail transforms outputs to inputs
                async def dovetail_node(state: SDNAState, dv=elem) -> Dict[str, Any]:
                    ctx = dict(state.get("context", {}))
                    next_inputs = dv.prepare_next_inputs(ctx)
                    ctx.update(next_inputs)
                    return {"context": ctx}
                graph.add_node(node_name, dovetail_node)

        # Wire edges: START → step_0 → step_1 → ... → END
        if node_names:
            graph.add_edge(START, node_names[0])
            for i in range(len(node_names) - 1):
                # Check if current node is HumanInput - need conditional edge
                if isinstance(self.elements[i], HumanInput):
                    # After human input node, check if awaiting
                    def check_human(state: SDNAState) -> str:
                        return "wait" if state.get("awaiting_input") else "continue"
                    graph.add_conditional_edges(
                        node_names[i],
                        check_human,
                        {"wait": END, "continue": node_names[i + 1]}
                    )
                else:
                    graph.add_edge(node_names[i], node_names[i + 1])

            # Last node to END (unless it's HumanInput, handled above)
            if not isinstance(self.elements[-1], HumanInput):
                graph.add_edge(node_names[-1], END)
            else:
                def check_human_final(state: SDNAState) -> str:
                    return "wait" if state.get("awaiting_input") else "done"
                graph.add_conditional_edges(
                    node_names[-1],
                    check_human_final,
                    {"wait": END, "done": END}
                )
        else:
            # Empty chain - just pass through
            async def passthrough(state: SDNAState) -> Dict[str, Any]:
                return {"status": "success"}
            graph.add_node("passthrough", passthrough)
            graph.add_edge(START, "passthrough")
            graph.add_edge("passthrough", END)

        return graph.compile()


# =============================================================================
# CONVENIENCE CONSTRUCTORS
# =============================================================================

def ariadne(name: str, *elements: AriadneElement) -> AriadneChain:
    """
    Create an Ariadne chain for context threading.

    Args:
        name: Chain identifier
        *elements: HumanInput, InjectConfig, WeaveConfig, or DovetailModel

    Example:
        thread = ariadne('prep',
            inject_file('spec.md', 'spec'),
            human('Approve?', 'approval'),
        )
    """
    return AriadneChain(name, list(elements))


def human(prompt: str, as_key: str, choices: List[str] = None) -> HumanInput:
    """
    Create a human input stop step. Pauses chain, awaits input, resumes.

    Args:
        prompt: Question to show the human
        as_key: Context key where answer is stored
        choices: Optional list of choices to present

    Example:
        human('Which approach?', 'choice', ['A', 'B', 'C'])
    """
    return HumanInput(prompt=prompt, input_key=as_key, choices=choices)


def inject_file(path: str, as_key: str) -> InjectConfig:
    """
    Inject file contents into context.

    Args:
        path: Path to file to read
        as_key: Context key where contents are stored

    Example:
        inject_file('README.md', 'readme')
    """
    return InjectConfig(source="file", path=path, inject_as=as_key)


def inject_func(module: str, func: str, as_key: str, **args) -> InjectConfig:
    """
    Inject function result into context.

    Args:
        module: Python module path (e.g., 'mypackage.utils')
        func: Function name to call
        as_key: Context key where result is stored
        **args: Arguments to pass (use $key to reference context values)

    Example:
        inject_func('utils', 'get_data', 'data', id='$user_id')
    """
    return InjectConfig(source="function", module=module, func=func, args=args, inject_as=as_key)


def inject_literal(value: Any, as_key: str) -> InjectConfig:
    """
    Inject a literal value into context.

    Args:
        value: Any value to inject
        as_key: Context key where value is stored

    Example:
        inject_literal({'mode': 'fast'}, 'config')
    """
    return InjectConfig(source="literal", value=value, inject_as=as_key)


def inject_env(env_var: str, as_key: str, default: str = None) -> InjectConfig:
    """
    Inject environment variable into context.

    Args:
        env_var: Environment variable name
        as_key: Context key where value is stored
        default: Default if env var not set

    Example:
        inject_env('API_KEY', 'api_key', default='none')
    """
    return InjectConfig(source="env", env_var=env_var, default=default, inject_as=as_key)


def weave(source: str = None, start: int = None, end: int = None, as_key: str = "woven") -> WeaveConfig:
    """
    Weave message ranges between sessions (context surgery).

    Args:
        source: Source session ID
        start: Start message index
        end: End message index
        as_key: Context key where woven content is stored

    Example:
        weave(source='session_123', start=5, end=10, as_key='prior_context')
    """
    return WeaveConfig(source_session=source, start_index=start, end_index=end, inject_as=as_key)


class BrainInjectConfig(BaseModel):
    """Inject knowledge from Brain neurons into context."""
    brain_directory: str
    query_key: str  # Context key containing query (or literal if starts with !)
    inject_as: str
    max_neurons: int = 5
    extensions: list = Field(default_factory=lambda: [".md", ".txt", ".py"])

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        from .brain import Brain, BrainConfig

        # Resolve query from context or use literal
        if self.query_key.startswith("$"):
            query = context.get(self.query_key[1:], "")
        else:
            query = self.query_key

        # Create and run brain
        brain_config = BrainConfig(
            name="ariadne_brain",
            directory=self.brain_directory,
            extensions=self.extensions,
        )
        brain = Brain(brain_config)
        brain.load_neurons()

        # Cognize and synthesize
        result = await brain.think(query)
        context[self.inject_as] = result.instructions
        context[f"{self.inject_as}_neurons"] = [
            {"name": n.name, "relevance": n.relevance}
            for n in result.relevant_neurons
        ]
        return context

    def to_langgraph_node(self) -> Callable[[SDNAState], Dict[str, Any]]:
        """Convert to LangGraph node that injects brain knowledge."""
        async def node(state: SDNAState) -> Dict[str, Any]:
            ctx = dict(state.get("context", {}))
            ctx = await self.execute(ctx)
            return {"context": ctx}
        return node


def inject_brain(directory: str, query_key: str, as_key: str, max_neurons: int = 5) -> BrainInjectConfig:
    """
    Inject knowledge from Brain neurons into context.

    Uses Haiku to find relevant documents and synthesize instructions.

    Args:
        directory: Path to directory containing neuron files (.md, .txt, .py)
        query_key: Context key with query (use $key) or literal query
        as_key: Context key where synthesized instructions are stored
        max_neurons: Max relevant neurons to use (default 5)

    Example:
        inject_brain('/docs/mcp-guides', '$user_question', 'knowledge')
    """
    return BrainInjectConfig(
        brain_directory=directory,
        query_key=query_key,
        inject_as=as_key,
        max_neurons=max_neurons,
    )
