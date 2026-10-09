"""
Factory - Assembles the selfbot system with proper dependency injection.

This is where all the layers get wired together.
"""

from pathlib import Path
from typing import Optional

from .domain.models import Selfbot, Schedule
from .application.runner import SelfbotRunner
from .application.manager import SelfbotManager
from .application.sdk_builder import SdkBuilder
from .application.immune import ImmuneSystem
from .infrastructure.screen_adapter import VirtualScreenProvider
from .infrastructure.file_storage import JsonSelfbotRepository, JsonExecutionRepository
from .infrastructure.procedure_storage import JsonProcedureRepository
from .infrastructure.scheduler import SimpleScheduler


class SelfbotSystem:
    """
    Fully assembled selfbot system.

    Usage:
        system = SelfbotSystem()

        # Create a selfbot
        bot = system.manager.create(
            name="etsy-checker",
            script_path="/path/to/etsy_check.py",
            schedule=Schedule(interval_seconds=3600),  # hourly
        )

        # Run it once
        execution = system.runner.run(bot)

        # Or schedule it
        system.scheduler.add(bot)
        system.scheduler.start()

    And the procedure/SDK pipeline on the same system:

        system.sdk.begin("etsy", "list_item", inner_driver=PlaywrightDriver(page))
        ... drive the site through system.sdk.driver ...
        system.sdk.finish(postcondition=Condition(selector=".listing-live"))
        system.sdk.verify("etsy", "list_item", driver)
        system.sdk.promote("etsy", "list_item", verified_by="isaac")
        system.sdk.compile()

        system.immune.sweep()   # keeps the compiled SDK honest
    """

    def __init__(
        self,
        storage_dir: str = "/tmp/selfbots",
        procedure_dir: Optional[str] = None,
        sdk_dir: Optional[str] = None,
    ):
        # Infrastructure
        self.screen_provider = VirtualScreenProvider()
        self.selfbot_repo = JsonSelfbotRepository(storage_dir)
        self.execution_repo = JsonExecutionRepository(f"{storage_dir}/executions")
        self.procedure_repo = JsonProcedureRepository(
            procedure_dir or f"{storage_dir}/procedures"
        )

        # Application
        self.runner = SelfbotRunner(
            screen_provider=self.screen_provider,
            execution_repo=self.execution_repo
        )
        self.manager = SelfbotManager(
            selfbot_repo=self.selfbot_repo,
            execution_repo=self.execution_repo
        )
        self.sdk = SdkBuilder(
            procedure_repo=self.procedure_repo,
            sdk_dir=Path(sdk_dir or f"{storage_dir}/sdk"),
        )
        self.immune = ImmuneSystem(
            procedure_repo=self.procedure_repo,
            sdk_dir=Path(sdk_dir or f"{storage_dir}/sdk"),
        )

        # Scheduler (uses runner.run as callback)
        self.scheduler = SimpleScheduler(run_callback=self.runner.run)

    def quick_run(self, name: str, script_path: str, **kwargs):
        """Create and immediately run a one-shot selfbot."""
        bot = Selfbot(
            name=name,
            script_path=script_path,
            schedule=Schedule(run_once=True),
            **kwargs
        )
        return self.runner.run(bot)

    def load_and_schedule_all(self):
        """Load all enabled selfbots and add to scheduler."""
        for bot in self.manager.list_enabled():
            if not bot.schedule.run_once:
                self.scheduler.add(bot)


# Convenience function
def create_system(storage_dir: str = "/tmp/selfbots") -> SelfbotSystem:
    """Create a fully configured selfbot system."""
    return SelfbotSystem(storage_dir)
