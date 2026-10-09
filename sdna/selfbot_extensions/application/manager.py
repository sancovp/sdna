"""
SelfbotManager - CRUD and scheduling for selfbots.

Application layer: orchestrates domain objects with injected infrastructure.
"""

import logging
from typing import Optional, List
from datetime import datetime

from ..domain.models import (
    Selfbot, Schedule, Execution,
    SelfbotRepository, ExecutionRepository
)

logger = logging.getLogger(__name__)


class SelfbotManager:
    """
    Manages selfbot lifecycle - create, update, delete, list, schedule.

    Dependencies injected - doesn't know about filesystem, cron, etc.
    """

    def __init__(
        self,
        selfbot_repo: SelfbotRepository,
        execution_repo: Optional[ExecutionRepository] = None
    ):
        self.selfbot_repo = selfbot_repo
        self.execution_repo = execution_repo

    # === CRUD ===

    def create(
        self,
        name: str,
        script_path: str,
        schedule: Optional[Schedule] = None,
        **kwargs
    ) -> Selfbot:
        """Create and save a new selfbot."""
        if self.selfbot_repo.get_by_name(name):
            raise ValueError(f"Selfbot '{name}' already exists")

        selfbot = Selfbot(
            name=name,
            script_path=script_path,
            schedule=schedule or Schedule(),
            **kwargs
        )

        self.selfbot_repo.save(selfbot)
        logger.info(f"Created selfbot: {selfbot}")
        return selfbot

    def get(self, selfbot_id: str) -> Optional[Selfbot]:
        """Get selfbot by ID."""
        return self.selfbot_repo.get(selfbot_id)

    def get_by_name(self, name: str) -> Optional[Selfbot]:
        """Get selfbot by name."""
        return self.selfbot_repo.get_by_name(name)

    def list_all(self) -> List[Selfbot]:
        """List all selfbots."""
        return self.selfbot_repo.list_all()

    def list_enabled(self) -> List[Selfbot]:
        """List only enabled selfbots."""
        return self.selfbot_repo.list_enabled()

    def update(self, selfbot: Selfbot) -> Selfbot:
        """Update an existing selfbot."""
        self.selfbot_repo.save(selfbot)
        logger.info(f"Updated selfbot: {selfbot}")
        return selfbot

    def delete(self, selfbot_id: str) -> bool:
        """Delete a selfbot."""
        result = self.selfbot_repo.delete(selfbot_id)
        if result:
            logger.info(f"Deleted selfbot: {selfbot_id}")
        return result

    def enable(self, selfbot_id: str) -> Optional[Selfbot]:
        """Enable a selfbot."""
        selfbot = self.selfbot_repo.get(selfbot_id)
        if selfbot:
            selfbot.enabled = True
            self.selfbot_repo.save(selfbot)
        return selfbot

    def disable(self, selfbot_id: str) -> Optional[Selfbot]:
        """Disable a selfbot."""
        selfbot = self.selfbot_repo.get(selfbot_id)
        if selfbot:
            selfbot.enabled = False
            self.selfbot_repo.save(selfbot)
        return selfbot

    # === History ===

    def get_history(self, selfbot_id: str, limit: int = 10) -> List[Execution]:
        """Get recent executions for a selfbot."""
        if not self.execution_repo:
            return []
        return self.execution_repo.get_recent(selfbot_id, limit)

    def get_all_history(self, limit: int = 50) -> List[Execution]:
        """Get recent executions across all selfbots."""
        if not self.execution_repo:
            return []
        return self.execution_repo.get_all_recent(limit)

    # === Batch operations ===

    def create_from_dict(self, config: dict) -> Selfbot:
        """Create selfbot from dictionary config."""
        schedule_config = config.pop("schedule", {})
        schedule = Schedule(**schedule_config) if schedule_config else Schedule()
        return self.create(schedule=schedule, **config)

    def export_all(self) -> List[dict]:
        """Export all selfbots as dictionaries."""
        selfbots = self.list_all()
        return [
            {
                "id": s.id,
                "name": s.name,
                "script_path": s.script_path,
                "schedule": {
                    "cron_expr": s.schedule.cron_expr,
                    "interval_seconds": s.schedule.interval_seconds,
                    "run_once": s.schedule.run_once,
                },
                "screen_size": s.screen_size,
                "timeout_seconds": s.timeout_seconds,
                "input_file": s.input_file,
                "output_file": s.output_file,
                "enabled": s.enabled,
                "tags": s.tags,
                "config": s.config,
            }
            for s in selfbots
        ]
