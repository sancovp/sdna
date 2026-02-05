"""
CodeAgentSDNAC - SDNA Chain type for live Claude Code agents.

This is the SDNAC pattern applied to a running Claude Code agent:
- AriadneChain → Hook handlers (context injection via additionalContext)
- HermesConfig → Agent's system prompt + context
- Poimandres → The actual Claude Code agent execution

Used by CAVE's AgentInferenceLoop to type the main agent's execution pattern.
"""

from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

from .ariadne import AriadneChain, AriadneElement, ariadne, inject_literal
from .sdna import SDNAStatus


class CodeAgentStatus(str, Enum):
    """Status of the live code agent."""
    WORKING = "working"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    AWAITING_INPUT = "awaiting_input"
    IDLE = "idle"

    def to_sdna_status(self) -> SDNAStatus:
        """Map to SDNA status."""
        mapping = {
            CodeAgentStatus.WORKING: SDNAStatus.SUCCESS,
            CodeAgentStatus.BLOCKED: SDNAStatus.BLOCKED,
            CodeAgentStatus.COMPLETE: SDNAStatus.SUCCESS,
            CodeAgentStatus.AWAITING_INPUT: SDNAStatus.AWAITING_INPUT,
            CodeAgentStatus.IDLE: SDNAStatus.SUCCESS,
        }
        return mapping.get(self, SDNAStatus.SUCCESS)


@dataclass
class HookAriadne:
    """Ariadne chain for a specific hook type.

    When the hook fires, this chain executes to prepare context
    that gets injected into the agent via additionalContext.
    """
    hook_type: str  # pretool, posttool, stop, etc.
    chain: AriadneChain

    # Optional conditions for when this chain should run
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None

    async def execute(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the Ariadne chain for this hook."""
        # Check condition if present
        if self.condition and not self.condition(state):
            return {"result": "continue"}

        # Build context from payload + state
        context = {**state, "hook_payload": payload}

        # Run Ariadne chain
        result = await self.chain.execute(context)

        # Extract additionalContext from result
        additional_context_parts = []
        for key, value in result.context.items():
            if key.startswith("inject_") or key.endswith("_context"):
                additional_context_parts.append(str(value))

        return {
            "result": "continue",
            "additionalContext": "\n".join(additional_context_parts) if additional_context_parts else None,
            "ariadne_context": result.context,
        }


@dataclass
class CodeAgentSDNAC:
    """
    SDNAC pattern for a live Claude Code agent.

    Components:
    - hook_ariadnes: Ariadne chains for each hook type (context injection)
    - conditions: When to transition states (like SDNA status checks)
    - on_start/on_stop: Lifecycle callbacks

    This is what powers AgentInferenceLoop under the hood.
    """
    name: str
    description: str = ""

    # Ariadne chains for each hook type
    hook_ariadnes: Dict[str, HookAriadne] = field(default_factory=dict)

    # Conditions that check state and return bool
    # These map to SDNA's SDNAResult.status logic
    conditions: Dict[str, Callable[[Dict[str, Any]], bool]] = field(default_factory=dict)

    # Lifecycle
    on_start: Optional[Callable[[Dict[str, Any]], None]] = None
    on_stop: Optional[Callable[[Dict[str, Any]], None]] = None

    # Current status
    status: CodeAgentStatus = CodeAgentStatus.IDLE

    def add_hook_ariadne(
        self,
        hook_type: str,
        chain: AriadneChain,
        condition: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> "CodeAgentSDNAC":
        """Add an Ariadne chain for a hook type. Fluent API."""
        self.hook_ariadnes[hook_type] = HookAriadne(
            hook_type=hook_type,
            chain=chain,
            condition=condition,
        )
        return self

    def add_condition(
        self,
        name: str,
        condition: Callable[[Dict[str, Any]], bool],
    ) -> "CodeAgentSDNAC":
        """Add a condition check. Fluent API."""
        self.conditions[name] = condition
        return self

    async def handle_hook(
        self,
        hook_type: str,
        payload: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle a hook signal by running the appropriate Ariadne chain."""
        hook_ariadne = self.hook_ariadnes.get(hook_type)
        if not hook_ariadne:
            return {"result": "continue"}

        return await hook_ariadne.execute(payload, state)

    def check_conditions(self, state: Dict[str, Any]) -> Optional[str]:
        """Check all conditions, return first that matches."""
        for name, condition in self.conditions.items():
            try:
                if condition(state):
                    return name
            except Exception:
                pass
        return None

    def to_sdna_status(self) -> SDNAStatus:
        """Get current status as SDNA status."""
        return self.status.to_sdna_status()


# =============================================================================
# CONVENIENCE CONSTRUCTORS
# =============================================================================

def code_agent_sdnac(
    name: str,
    description: str = "",
) -> CodeAgentSDNAC:
    """
    Create a CodeAgentSDNAC for a live Claude Code agent.

    Use fluent API to add hook_ariadnes and conditions:

        agent = code_agent_sdnac("autopoiesis", "Self-maintaining agent")
            .add_hook_ariadne("pretool", ariadne("prep", inject_literal("...", "ctx")))
            .add_hook_ariadne("stop", ariadne("stop", inject_literal("...", "ctx")))
            .add_condition("blocked", lambda s: s.get("mode") == "blocked")
    """
    return CodeAgentSDNAC(name=name, description=description)


def hook_ariadne(
    hook_type: str,
    *elements: AriadneElement,
    condition: Optional[Callable[[Dict[str, Any]], bool]] = None,
) -> HookAriadne:
    """
    Create a HookAriadne for a specific hook type.

    Args:
        hook_type: pretool, posttool, stop, notification, subagentspawn
        *elements: Ariadne elements (inject_literal, inject_file, inject_brain, etc.)
        condition: Optional condition for when to run

    Example:
        hook_ariadne("pretool",
            inject_literal("[autopoiesis] Persist meaningful work", "reminder"),
            condition=lambda s: s.get("tool_name") == "Write"
        )
    """
    chain = ariadne(f"{hook_type}_ariadne", *elements)
    return HookAriadne(hook_type=hook_type, chain=chain, condition=condition)
