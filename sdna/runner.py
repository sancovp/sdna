"""
Agent execution for Hermes - thin wrapper over claude-agent-sdk.

Uses the SDK's query() function with HermesConfig.to_sdk_options().
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Union
from enum import Enum

# SDK imports
try:
    from claude_agent_sdk import query
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False

from .config import HermesConfig
from .tools import BlockedReport, parse_blocked_from_text, get_blocked_instruction


class StepStatus(str, Enum):
    """Outcome of an agent step."""
    SUCCESS = "success"
    BLOCKED = "blocked"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class StepResult:
    """Result from agent_step."""
    status: StepStatus
    output: Dict[str, Any] = field(default_factory=dict)
    blocked: Optional[BlockedReport] = None
    error: Optional[str] = None
    session_id: Optional[str] = None
    messages: List[Any] = field(default_factory=list)

    def is_success(self) -> bool:
        return self.status == StepStatus.SUCCESS

    def is_blocked(self) -> bool:
        return self.status == StepStatus.BLOCKED


async def agent_step(
    config: Union[HermesConfig, Dict[str, Any]],
    variable_inputs: Optional[Dict[str, Any]] = None,
) -> StepResult:
    """
    Execute a single agent step using claude-agent-sdk.

    Args:
        config: HermesConfig or dict
        variable_inputs: Values for goal template interpolation

    Returns:
        StepResult with status and output
    """
    if not SDK_AVAILABLE:
        return StepResult(
            status=StepStatus.ERROR,
            error="claude-agent-sdk not installed"
        )

    # Handle dict config
    if isinstance(config, dict):
        config = HermesConfig(**config)

    # Resolve goal with variables
    merged_inputs = dict(variable_inputs) if variable_inputs else {}

    # Brain integration - inject context if configured
    if config.brain_query and config.brain_project_root:
        try:
            from .brain import get_project_context
            context = await get_project_context(
                config.brain_project_root,
                config.brain_query
            )
            merged_inputs[config.inject_context_as] = context
        except Exception as e:
            merged_inputs[config.inject_context_as] = f"[Brain query failed: {e}]"

    # Build prompt
    prompt = config.resolve_goal(merged_inputs)
    prompt = prompt + get_blocked_instruction()

    # Get SDK options
    options = config.to_sdk_options()

    # Execute via SDK
    result = StepResult(status=StepStatus.SUCCESS)
    final_text = ""

    try:
        async for message in query(prompt=prompt, options=options):
            result.messages.append(message)

            # Extract session ID
            if hasattr(message, 'session_id'):
                result.session_id = message.session_id
            elif isinstance(message, dict) and 'session_id' in message:
                result.session_id = message['session_id']

            # Extract text content
            if hasattr(message, 'content'):
                for block in message.content:
                    if hasattr(block, 'text'):
                        final_text = block.text
            elif isinstance(message, dict) and 'content' in message:
                final_text = str(message['content'])

    except Exception as e:
        result.status = StepStatus.ERROR
        result.error = str(e)
        return result

    # Check for blocked signal
    if final_text:
        blocked_report = parse_blocked_from_text(final_text)
        if blocked_report:
            result.status = StepStatus.BLOCKED
            result.blocked = blocked_report
            blocked_report.save(config.name)
            return result

    # Success
    result.output = {"text": final_text}
    return result
