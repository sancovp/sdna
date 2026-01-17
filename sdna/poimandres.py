"""
Poimandres - The Divine Mind

The generation moment. Takes HermesConfig (the message Ariadne sends)
and context, runs the agent, produces output.

Poimandres is not a chain - it's the act of generation.
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from .config import HermesConfig
from .runner import agent_step, StepResult, StepStatus


@dataclass
class PoimandresResult:
    """Result of Poimandres execution."""
    success: bool
    output: Dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    error: Optional[str] = None
    step_result: Optional[StepResult] = None


async def execute(
    config: HermesConfig,
    context: Optional[Dict[str, Any]] = None,
) -> PoimandresResult:
    """
    The generation moment - Poimandres executes.

    Takes HermesConfig (the message Ariadne sends) and context,
    runs the agent via agent_step, returns PoimandresResult.

    Args:
        config: HermesConfig with agent settings
        context: Dict of context values (from Ariadne thread)

    Returns:
        PoimandresResult with success/blocked/error status and output

    Example:
        from hermes import poimandres, HermesConfig

        config = HermesConfig(name='gen', system_prompt='...')
        result = await poimandres.execute(config, {'spec': '...'})
        if result.success:
            print(result.output)
    """
    ctx = dict(context) if context else {}

    try:
        step_result = await agent_step(config, ctx)

        if step_result.status == StepStatus.BLOCKED:
            return PoimandresResult(
                success=False,
                blocked=True,
                step_result=step_result,
            )

        elif step_result.status == StepStatus.ERROR:
            return PoimandresResult(
                success=False,
                error=step_result.error,
                step_result=step_result,
            )

        else:
            return PoimandresResult(
                success=True,
                output=step_result.output or {},
                step_result=step_result,
            )

    except Exception as e:
        return PoimandresResult(
            success=False,
            error=str(e),
        )
