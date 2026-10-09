"""
SelfbotRunner - Executes selfbots in virtual screens.

Application layer: orchestrates domain objects with injected infrastructure.
"""

import subprocess
import logging
from datetime import datetime
from typing import Optional

from ..domain.models import (
    Selfbot, Execution, ExecutionStatus,
    ScreenProvider, ExecutionRepository
)

logger = logging.getLogger(__name__)


class SelfbotRunner:
    """
    Runs selfbots in isolated virtual screens.

    Dependencies injected - doesn't know about Xvfb, filesystem, etc.
    """

    def __init__(
        self,
        screen_provider: ScreenProvider,
        execution_repo: Optional[ExecutionRepository] = None
    ):
        self.screen_provider = screen_provider
        self.execution_repo = execution_repo

    def run(self, selfbot: Selfbot) -> Execution:
        """
        Execute a selfbot and return the execution record.

        1. Create isolated screen
        2. Run the selfbot script
        3. Capture output/screenshot
        4. Clean up
        5. Return execution record
        """
        execution = Execution(
            selfbot_id=selfbot.id,
            selfbot_name=selfbot.name,
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now()
        )

        screen = None
        try:
            # Create isolated virtual screen
            screen = self.screen_provider.create_screen(selfbot.screen_size)
            execution.display_num = getattr(screen, 'display_num', None)

            logger.info(f"Running selfbot '{selfbot.name}' on {screen}")

            # Build command with input/output file injection
            env_vars = []
            if selfbot.input_file:
                env_vars.append(f"SELFBOT_INPUT={selfbot.input_file}")
            if selfbot.output_file:
                env_vars.append(f"SELFBOT_OUTPUT={selfbot.output_file}")

            env_prefix = " ".join(env_vars) + " " if env_vars else ""
            cmd = f"{env_prefix}python3 {selfbot.script_path}"

            # Run with timeout
            result = screen.run_command(
                f"timeout {selfbot.timeout_seconds} {cmd}"
            )

            # Capture final screenshot
            try:
                screenshot_path = f"/tmp/selfbot_{selfbot.id}_{execution.id}.png"
                img = screen.screenshot()
                img.save(screenshot_path)
                execution.screenshot_path = screenshot_path
            except Exception as e:
                logger.warning(f"Failed to capture screenshot: {e}")

            # Determine status
            if result.returncode == 0:
                execution.status = ExecutionStatus.SUCCESS
                execution.output = result.stdout
            elif result.returncode == 124:  # timeout exit code
                execution.status = ExecutionStatus.TIMEOUT
                execution.error = "Execution timed out"
            else:
                execution.status = ExecutionStatus.FAILED
                execution.error = result.stderr or f"Exit code {result.returncode}"

        except Exception as e:
            logger.exception(f"Selfbot '{selfbot.name}' failed")
            execution.status = ExecutionStatus.FAILED
            execution.error = str(e)

        finally:
            # Always clean up
            if screen:
                try:
                    screen.close()
                except Exception as e:
                    logger.warning(f"Failed to close screen: {e}")

            execution.finished_at = datetime.now()

        # Persist execution record if repo provided
        if self.execution_repo:
            self.execution_repo.save(execution)

        logger.info(f"Selfbot '{selfbot.name}' finished: {execution.status.value}")
        return execution

    def run_by_name(self, name: str, selfbot_repo) -> Optional[Execution]:
        """Convenience: look up selfbot by name and run it."""
        selfbot = selfbot_repo.get_by_name(name)
        if not selfbot:
            logger.error(f"Selfbot '{name}' not found")
            return None
        return self.run(selfbot)
