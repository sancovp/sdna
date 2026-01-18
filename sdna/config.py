"""
Configuration models for Hermes workflow system.

HermesConfig is a thin wrapper over claude-agent-sdk's ClaudeAgentOptions,
adding goal templating, brain integration, and chain/dovetail support.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union, Callable, TYPE_CHECKING
from pathlib import Path
from pydantic import Field, BaseModel, ConfigDict

if TYPE_CHECKING:
    from .state import SDNAState

# Import SDK types
try:
    from claude_agent_sdk import ClaudeAgentOptions
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False
    ClaudeAgentOptions = None


class HermesConfig(BaseModel):
    """
    Configuration for a single agent execution.

    Wraps claude-agent-sdk's ClaudeAgentOptions with additions:
    - goal: Templated prompt with {variable} interpolation
    - variable_inputs: Values for goal template
    - brain_query: Auto-inject context from brain
    - auto_brace: Read session from /tmp/current_claude_session_id
    """

    # === HERMES ADDITIONS ===
    name: str = ""  # Config identifier
    goal: str = ""  # Templated prompt (use {var} for interpolation)
    variable_inputs: Dict[str, Any] = Field(default_factory=dict)

    # Brain integration
    brain_query: Optional[str] = None
    brain_project_root: Optional[str] = None
    inject_context_as: str = "project_context"

    # Auto-brace (read session from hook-written file)
    auto_brace: bool = False

    # === SDK PASS-THROUGH OPTIONS ===
    # Tools
    tools: Optional[List[str]] = None
    allowed_tools: List[str] = Field(default_factory=lambda: ["Read", "Write", "Edit", "Bash", "Glob", "Grep"])
    disallowed_tools: List[str] = Field(default_factory=list)

    # System prompt
    system_prompt: Optional[str] = None

    # MCP servers
    mcp_servers: Dict[str, Any] = Field(default_factory=dict)

    # Permissions
    permission_mode: Optional[str] = None  # default, acceptEdits, plan, bypassPermissions

    # Session management
    resume: Optional[str] = None  # Session ID to resume
    fork_session: bool = False  # Fork instead of continue
    continue_conversation: bool = False

    # Limits
    max_turns: Optional[int] = None  # Maps to iterations
    max_budget_usd: Optional[float] = None
    max_thinking_tokens: Optional[int] = None

    # Model
    model: Optional[str] = None
    fallback_model: Optional[str] = None

    # Environment
    cwd: Optional[str] = None
    env: Dict[str, str] = Field(default_factory=dict)
    add_dirs: List[str] = Field(default_factory=list)

    # Hooks (dynamic)
    hooks: Optional[Dict[str, List[Any]]] = None

    # Agents (for multi-agent)
    agents: Optional[Dict[str, Any]] = None

    # Plugins
    plugins: List[Any] = Field(default_factory=list)

    # Sandbox
    sandbox: Optional[Any] = None

    # Other SDK options
    cli_path: Optional[str] = None
    settings: Optional[str] = None
    extra_args: Dict[str, Any] = Field(default_factory=dict)
    betas: List[str] = Field(default_factory=list)
    output_format: Optional[Dict[str, Any]] = None
    enable_file_checkpointing: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # === HERMES METHODS ===

    def resolve_goal(self, inputs: Optional[Dict[str, Any]] = None) -> str:
        """Resolve goal template with provided inputs."""
        if not inputs and not self.variable_inputs:
            return self.goal
        merged = {**self.variable_inputs, **(inputs or {})}
        try:
            return self.goal.format(**merged)
        except KeyError as e:
            raise ValueError(f"Missing required variable in goal template: {e}")

    def resolve_session_id(self) -> Optional[str]:
        """
        Resolve session ID, with auto_brace support.

        If auto_brace=True, reads from /tmp/current_claude_session_id.
        Raises if fork_session requires resume but none available.
        """
        sid = self.resume

        if self.auto_brace:
            brace_file = Path("/tmp/current_claude_session_id")
            if brace_file.exists():
                sid = brace_file.read_text().strip()

        # Validate: forking requires a session to fork from
        if self.fork_session and not sid:
            raise ValueError(
                "fork_session=True requires resume or auto_brace=True with valid session file"
            )

        return sid

    def to_sdk_options(self) -> "ClaudeAgentOptions":
        """Convert to claude-agent-sdk ClaudeAgentOptions."""
        if not SDK_AVAILABLE:
            raise RuntimeError("claude-agent-sdk not installed")

        return ClaudeAgentOptions(
            tools=self.tools,
            allowed_tools=self.allowed_tools,
            disallowed_tools=self.disallowed_tools,
            system_prompt=self.system_prompt,
            mcp_servers=self.mcp_servers,
            permission_mode=self.permission_mode,
            resume=self.resolve_session_id(),
            fork_session=self.fork_session,
            continue_conversation=self.continue_conversation,
            max_turns=self.max_turns,
            max_budget_usd=self.max_budget_usd,
            max_thinking_tokens=self.max_thinking_tokens,
            model=self.model,
            fallback_model=self.fallback_model,
            cwd=self.cwd,
            env=self.env,
            add_dirs=self.add_dirs,
            hooks=self.hooks,
            agents=self.agents,
            plugins=self.plugins,
            sandbox=self.sandbox,
            cli_path=self.cli_path,
            settings=self.settings,
            extra_args=self.extra_args,
            betas=self.betas,
            output_format=self.output_format,
            enable_file_checkpointing=self.enable_file_checkpointing,
        )

    # Legacy compatibility
    def to_runner_kwargs(self, variable_inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Legacy method - prefer to_sdk_options()."""
        return {
            "goal": self.resolve_goal(variable_inputs),
            "options": self.to_sdk_options(),
        }

    def to_langgraph_node(self) -> Callable[["SDNAState"], Dict[str, Any]]:
        """
        Convert to LangGraph node that executes Poimandres generation.

        The node reads context from state, executes via poimandres.execute(),
        and returns updated state with output.
        """
        async def node(state: "SDNAState") -> Dict[str, Any]:
            from . import poimandres
            from .state import SDNAState

            ctx = dict(state.get("context", {}))
            result = await poimandres.execute(self, ctx)

            if result.blocked:
                return {"status": "blocked", "error": "Poimandres blocked"}
            elif not result.success:
                return {"status": "error", "error": result.error}

            # Update context with output
            ctx.update(result.output or {})
            return {
                "context": ctx,
                "status": "success",
                "output": result.output,
                "results": state.get("results", []) + [{"poimandres": result.output}],
            }
        return node


class HermesConfigInput(BaseModel):
    """
    Defines how to extract and transform a single input
    from a previous step's output.
    """
    source_key: str  # Dot-notation path (e.g., "result.files.0")
    transform: Optional[Callable[[Any], Any]] = None
    required: bool = True
    default: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def extract(self, data: Dict[str, Any]) -> Any:
        """Extract value from data using source_key path."""
        value = data
        for part in self.source_key.split('.'):
            if value is None:
                break
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, (list, tuple)) and part.isdigit():
                idx = int(part)
                value = value[idx] if idx < len(value) else None
            else:
                value = None

        if value is None:
            if self.required:
                raise ValueError(f"Required input '{self.source_key}' not found")
            return self.default

        if self.transform:
            value = self.transform(value)

        return value


class DovetailModel(BaseModel):
    """
    The joint between two configs in a chain.

    Declares expected outputs from previous step and
    how to map them to inputs for the next step.
    """
    name: str = ""
    expected_outputs: List[str] = Field(default_factory=list)
    input_map: Dict[str, HermesConfigInput] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def validate_outputs(self, result: Dict[str, Any]) -> List[str]:
        """Check expected outputs are present. Returns missing keys."""
        missing = []
        for key in self.expected_outputs:
            value = result
            for part in key.split('.'):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            if value is None:
                missing.append(key)
        return missing

    def prepare_next_inputs(self, previous_result: Dict[str, Any]) -> Dict[str, Any]:
        """Transform previous outputs into next step inputs."""
        missing = self.validate_outputs(previous_result)
        if missing:
            raise ValueError(f"Dovetail '{self.name}' missing outputs: {missing}")

        next_inputs = {}
        for input_name, input_spec in self.input_map.items():
            next_inputs[input_name] = input_spec.extract(previous_result)

        return next_inputs
