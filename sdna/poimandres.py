"""
Poimandres - The Divine Mind

The generation moment. Takes HermesConfig (the message Ariadne sends)
and context, runs the agent, produces output.

Routes to either claude_agent_sdk (runner.py) or Heaven/MiniMax (heaven_runner.py)
based on config.backend.
"""

import os
import warnings
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from .config import HermesConfig
from .runner import StepResult, StepStatus


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

    Routes to the appropriate backend based on config.backend:
    - "claude" (default): claude_agent_sdk via runner.agent_step()
    - "heaven": Heaven framework via heaven_runner.heaven_agent_step()

    Args:
        config: HermesConfig with agent settings
        context: Dict of context values (from Ariadne thread)

    Returns:
        PoimandresResult with success/blocked/error status and output
    """
    ctx = dict(context) if context else {}

    try:
        if config.backend == "heaven":
            from .heaven_runner import heaven_agent_step
            step_result = await heaven_agent_step(config, ctx)
        else:
            if not os.environ.get("SDNA_ALLOW_CLAUDE_SDK"):
                warnings.warn(
                    "Poimandres using Claude SDK backend. Set backend='heaven' on HermesConfig "
                    "to use Heaven, or set SDNA_ALLOW_CLAUDE_SDK=1 to suppress this warning.",
                    UserWarning,
                    stacklevel=2,
                )
            from .runner import agent_step
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
