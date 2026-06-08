"""Universal Chain Ontology — Link and Chain homoiconic primitives.

The entire SDNA hierarchy reduces to two concepts:

    Link: atomic unit of execution (wraps a config)
    Chain(Link): sequence of Links — which IS ALSO a Link

This gives homoiconic composition: a Chain can be a Link in another Chain,
so SDNAC, SDNAFlow, SDNAFlowchain, DUOChain all become specializations of
the same two primitives.

    SDNAC            = Link (ariadne + hermes config)
    SDNAFlow         = Chain (sequential links)
    SDNAFlowchain    = EvalChain (chain + OVP link in a loop)
    DUOChain         = DUOChain (A→P alternation chain)
    CompiledAgent    = Link | Chain (pipeline output)

Source: Heaven core/chains/base/link.py + base_chain.py
Extracted from llegos actor model — we keep only the composition,
not the message-passing substrate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


# =============================================================================
# Result protocol
# =============================================================================

class LinkStatus(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    ERROR = "error"
    AWAITING_INPUT = "awaiting_input"


@dataclass
class LinkResult:
    """Result of executing a Link."""
    status: LinkStatus
    context: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    resume_path: Optional[List[int]] = None


# =============================================================================
# Link — atomic unit
# =============================================================================

class Link(ABC):
    """Atomic unit of execution in the universal chain ontology.

    A Link wraps a configuration and knows how to execute itself.
    Everything in SDNA is a Link — single units, flows, flowchains.

    The homoiconic property: Chain extends Link, so a Chain
    can appear as a Link inside another Chain. This is the
    entire composition model.

    Contract:
        - name: str (attribute or property — both work)
        - execute(context) → LinkResult (or compatible result type)

    SDNA compatibility: SDNAC sets self.name in __init__ (attribute),
    which satisfies this contract. Subclasses may also use @property.
    """

    # name can be set as attribute in __init__ or as @property
    # We don't make it @abstractmethod to allow plain attributes
    name: str

    @abstractmethod
    async def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Execute this link with the given context.

        Args:
            context: Shared mutable context dictionary.
            **kwargs: Subclass-specific params (e.g. on_message for SDNAC).

        Returns:
            Result with status and updated context.
            Type varies by subclass (SDNAResult, SDNAFlowchainResult, etc.)
        """
        ...

    def describe(self, depth: int = 0) -> str:
        """Return an LLM-readable description of this link.

        This is the metaprogramming surface. LLMs call this to inspect
        the chain structure they just built. Without this, homoiconic
        composition has no consumer.

        EVENTUAL BEHAVIOR (not yet implemented):
            1. Send this object's AST to ontologization (Carton/YOUKNOW)
               if not already represented in the ontology
            2. Query the ontology for what it knows about this Link
            3. Return the ontology CLI info — effectively starting a
               non-interactive persistent session about this object

        Goes as deep as the callgraph but doesn't show everything
        all at once — progressive pagination. The LLM can drill
        deeper by following references, not by receiving a wall.

        So: str(link) becomes a live ontology query, not a static string.
        The object describes itself through the knowledge graph.

        Current: static format string, overridden per subclass.
        Future: ontology-backed self-description with pagination.
        """
        indent = "  " * depth
        return f"{indent}Link \"{self.name}\""

    def __str__(self) -> str:
        """String representation = ontology CLI session about this object.

        Eventually: calling str() on any Link starts an ontology CLI
        non-interactive persistent session about that thing. The AST
        gets sent to ontologization if not in ontology, the ontology
        gets queried, and the CLI info comes back.

        Progressive pagination: shows the top level, with references
        the LLM can follow to go deeper. Never dumps the full tree.

        For now: delegates to describe().
        """
        return self.describe()


# =============================================================================
# Chain(Link) — homoiconic sequence
# =============================================================================

class Chain(Link):
    """Sequence of Links — which IS ALSO a Link.

    This is the homoiconic composition primitive.
    A Chain can be a Link in another Chain, giving recursive nesting:

        Chain([Link, Chain([Link, Link]), Link])

    Execution is sequential: each link gets the context from the previous.
    Stops on first non-SUCCESS.
    """

    def __init__(self, chain_name: str, links: Optional[List[Link]] = None):
        self._name = chain_name
        self.links: List[Link] = links or []

    @property
    def name(self) -> str:
        return self._name

    def add(self, link: Link) -> "Chain":
        """Add a link to the chain. Returns self for fluent API."""
        self.links.append(link)
        return self

    async def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Execute links sequentially. Stop on first failure."""
        ctx = dict(context) if context else {}

        for i, link in enumerate(self.links):
            result = await link.execute(ctx)
            ctx = result.context

            if result.status != LinkStatus.SUCCESS:
                result.resume_path = [i] + (result.resume_path or [])
                return result

        return LinkResult(status=LinkStatus.SUCCESS, context=ctx)

    def __len__(self) -> int:
        return len(self.links)

    def __getitem__(self, index: int) -> Link:
        return self.links[index]

    def describe(self, depth: int = 0) -> str:
        """Recursive tree description of the chain."""
        indent = "  " * depth
        lines = [f"{indent}Chain \"{self.name}\" ({len(self.links)} links):"]
        for i, link in enumerate(self.links):
            connector = "└──" if i == len(self.links) - 1 else "├──"
            child_desc = link.describe(depth + 1).lstrip()
            lines.append(f"{indent}  {connector} {child_desc}")
        return "\n".join(lines)


# =============================================================================
# EvalChain(Chain) — chain + evaluator in a loop
# =============================================================================

class EvalChain(Chain):
    """Chain with an evaluator Link in a loop.

    Runs the inner chain, then runs the evaluator.
    If evaluator approves → done. Otherwise loop (max_cycles).

    This is SDNAFlowchain / OVP pattern.
    """

    def __init__(
        self,
        chain_name: str,
        links: Optional[List[Link]] = None,
        evaluator: Optional[Link] = None,
        max_cycles: int = 3,
        approval_key: str = "approved",
    ):
        super().__init__(chain_name, links)
        self.evaluator = evaluator
        self.max_cycles = max_cycles
        self.approval_key = approval_key

    async def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Run chain → evaluate → loop."""
        ctx = dict(context) if context else {}

        for cycle in range(self.max_cycles):
            ctx["cycle"] = cycle + 1

            # Run inner chain
            result = await super().execute(ctx)
            ctx = result.context

            if result.status != LinkStatus.SUCCESS:
                return result

            # If no evaluator, single pass
            if not self.evaluator:
                return result

            # Evaluate
            eval_result = await self.evaluator.execute(ctx)
            ctx = eval_result.context

            if eval_result.status != LinkStatus.SUCCESS:
                return eval_result

            if ctx.get(self.approval_key):
                return LinkResult(status=LinkStatus.SUCCESS, context=ctx)

        return LinkResult(
            status=LinkStatus.BLOCKED,
            context=ctx,
            error=f"Max cycles ({self.max_cycles}) reached",
        )

    def describe(self, depth: int = 0) -> str:
        indent = "  " * depth
        lines = [f"{indent}EvalChain \"{self.name}\" ({len(self.links)} links, max_cycles={self.max_cycles}):"]
        for i, link in enumerate(self.links):
            connector = "├──" if i < len(self.links) - 1 or self.evaluator else "└──"
            child_desc = link.describe(depth + 1).lstrip()
            lines.append(f"{indent}  {connector} {child_desc}")
        if self.evaluator:
            eval_desc = self.evaluator.describe(depth + 1).lstrip()
            lines.append(f"{indent}  └── [evaluator] {eval_desc}")
        return "\n".join(lines)


# =============================================================================
# Compiler(Chain) — chain that produces new Links/Chains
# =============================================================================

class Compiler(Chain):
    """A Chain whose output is a Link or Chain.

    This is the D:D→D type in the hierarchy:

        Link           — executes
        Chain(Link)    — executes Links in sequence
        Compiler(Chain) — executes Links that PRODUCE new Links

    A Compiler takes a specification (as context) and produces
    executable structure (a Link/Chain) as output. The produced
    structure is stored in context under the 'compiled' key.

    This is what makes the system self-compiling: a Compiler
    can compile another Compiler, and the output is always
    something that can be composed and executed.
    """

    def __init__(
        self,
        chain_name: str,
        links: Optional[List[Link]] = None,
        output_key: str = "compiled",
    ):
        super().__init__(chain_name, links)
        self.output_key = output_key

    def get_compiled(self, context: Dict[str, Any]) -> Optional[Link]:
        """Extract the compiled Link/Chain from context."""
        return context.get(self.output_key)

    def describe(self, depth: int = 0) -> str:
        indent = "  " * depth
        lines = [f"{indent}Compiler \"{self.name}\" ({len(self.links)} links):"]
        for i, link in enumerate(self.links):
            connector = "└──" if i == len(self.links) - 1 else "├──"
            child_desc = link.describe(depth + 1).lstrip()
            lines.append(f"{indent}  {connector} {child_desc}")
        lines.append(f"{indent}  → produces Link via '{self.output_key}'")
        return "\n".join(lines)


# =============================================================================
# ConfigLink — concrete Link wrapping a config dict
# =============================================================================

@dataclass
class LinkConfig:
    """Configuration for a Link — the serializable part.

    This is what the compiler produces. At runtime, a LinkConfig
    becomes a Link via a factory/bridge.

    Maps to HermesConfig fields:
    - name            → identity
    - goal            → input prompt (what to do)
    - system_prompt   → behavioral frame
    - model           → which LLM
    - provider        → which API
    - temperature     → creativity
    - max_turns       → execution limit
    - permission_mode → trust boundary
    - allowed_tools   → tool surface
    - mcp_servers     → MCP configs
    - skills          → injected skill context
    """
    name: str = ""
    goal: str = ""
    system_prompt: str = ""
    model: str = ""
    provider: str = ""
    temperature: float = 0.7
    max_turns: int = 10
    permission_mode: str = "default"
    allowed_tools: List[str] = field(default_factory=list)
    mcp_servers: Dict[str, Any] = field(default_factory=dict)
    skills: str = ""  # injected context
    passthrough: Dict[str, Any] = field(default_factory=dict)


class ConfigLink(Link):
    """Concrete Link that wraps a LinkConfig.

    This is the leaf node — the thing that actually holds the config
    the compiler produced. At runtime, this gets converted to an
    SDNAC with the appropriate AriadneChain and HermesConfig.
    """

    def __init__(self, config: LinkConfig):
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    async def execute(self, context: Optional[Dict[str, Any]] = None, **kwargs):
        """Placeholder execute — real execution creates an SDNAC and runs it.

        In test/dry-run mode, this just passes through.
        In production, the config gets instantiated as an SDNAC.
        """
        ctx = dict(context) if context else {}
        ctx["_link_config"] = self.config
        ctx["_link_name"] = self.config.name
        return LinkResult(status=LinkStatus.SUCCESS, context=ctx)

    def describe(self, depth: int = 0) -> str:
        indent = "  " * depth
        parts = [f'Link "{self.config.name}"']
        if self.config.model:
            parts.append(f"model={self.config.model}")
        if self.config.temperature != 0.7:
            parts.append(f"temp={self.config.temperature}")
        if self.config.goal:
            goal_preview = self.config.goal[:60]
            if len(self.config.goal) > 60:
                goal_preview += "..."
            parts.append(f'goal="{goal_preview}"')
        if self.config.allowed_tools:
            parts.append(f"tools=[{', '.join(self.config.allowed_tools[:5])}]")
        return f"{indent}{' | '.join(parts)}"
