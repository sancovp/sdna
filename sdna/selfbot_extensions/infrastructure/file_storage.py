"""
File Storage - JSON-based persistence for selfbots and executions.

Infrastructure layer: implements repository protocols.
"""

import json
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from ..domain.models import (
    Selfbot, Schedule, Execution, ExecutionStatus,
    SelfbotRepository, ExecutionRepository
)

logger = logging.getLogger(__name__)


class JsonSelfbotRepository(SelfbotRepository):
    """Persists selfbots to JSON files."""

    def __init__(self, storage_dir: str = "/tmp/selfbots"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self.storage_dir / "index.json"
        self._load_index()

    def _load_index(self):
        """Load the name->id index."""
        if self._index_file.exists():
            self._index = json.loads(self._index_file.read_text())
        else:
            self._index = {}

    def _save_index(self):
        """Save the name->id index."""
        self._index_file.write_text(json.dumps(self._index, indent=2))

    def _selfbot_path(self, selfbot_id: str) -> Path:
        return self.storage_dir / f"{selfbot_id}.json"

    def _to_dict(self, selfbot: Selfbot) -> dict:
        return {
            "id": selfbot.id,
            "name": selfbot.name,
            "script_path": selfbot.script_path,
            "schedule": {
                "cron_expr": selfbot.schedule.cron_expr,
                "interval_seconds": selfbot.schedule.interval_seconds,
                "run_once": selfbot.schedule.run_once,
            },
            "screen_size": list(selfbot.screen_size),
            "timeout_seconds": selfbot.timeout_seconds,
            "input_file": selfbot.input_file,
            "output_file": selfbot.output_file,
            "enabled": selfbot.enabled,
            "tags": selfbot.tags,
            "config": selfbot.config,
        }

    def _from_dict(self, data: dict) -> Selfbot:
        schedule_data = data.pop("schedule", {})
        schedule = Schedule(**schedule_data)
        data["screen_size"] = tuple(data.get("screen_size", [1920, 1080]))
        return Selfbot(schedule=schedule, **data)

    def save(self, selfbot: Selfbot) -> None:
        path = self._selfbot_path(selfbot.id)
        path.write_text(json.dumps(self._to_dict(selfbot), indent=2))
        self._index[selfbot.name] = selfbot.id
        self._save_index()

    def get(self, selfbot_id: str) -> Optional[Selfbot]:
        path = self._selfbot_path(selfbot_id)
        if not path.exists():
            return None
        return self._from_dict(json.loads(path.read_text()))

    def get_by_name(self, name: str) -> Optional[Selfbot]:
        selfbot_id = self._index.get(name)
        if not selfbot_id:
            return None
        return self.get(selfbot_id)

    def list_all(self) -> List[Selfbot]:
        selfbots = []
        for selfbot_id in self._index.values():
            selfbot = self.get(selfbot_id)
            if selfbot:
                selfbots.append(selfbot)
        return selfbots

    def list_enabled(self) -> List[Selfbot]:
        return [s for s in self.list_all() if s.enabled]

    def delete(self, selfbot_id: str) -> bool:
        path = self._selfbot_path(selfbot_id)
        if not path.exists():
            return False

        selfbot = self.get(selfbot_id)
        if selfbot and selfbot.name in self._index:
            del self._index[selfbot.name]
            self._save_index()

        path.unlink()
        return True


class JsonExecutionRepository(ExecutionRepository):
    """Persists execution history to JSON."""

    def __init__(self, storage_dir: str = "/tmp/selfbots/executions"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _execution_path(self, execution_id: str) -> Path:
        return self.storage_dir / f"{execution_id}.json"

    def _to_dict(self, execution: Execution) -> dict:
        return {
            "id": execution.id,
            "selfbot_id": execution.selfbot_id,
            "selfbot_name": execution.selfbot_name,
            "status": execution.status.value,
            "started_at": execution.started_at.isoformat(),
            "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
            "output": execution.output,
            "error": execution.error,
            "screenshot_path": execution.screenshot_path,
            "display_num": execution.display_num,
        }

    def _from_dict(self, data: dict) -> Execution:
        return Execution(
            id=data["id"],
            selfbot_id=data["selfbot_id"],
            selfbot_name=data["selfbot_name"],
            status=ExecutionStatus(data["status"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            finished_at=datetime.fromisoformat(data["finished_at"]) if data.get("finished_at") else None,
            output=data.get("output"),
            error=data.get("error"),
            screenshot_path=data.get("screenshot_path"),
            display_num=data.get("display_num"),
        )

    def save(self, execution: Execution) -> None:
        path = self._execution_path(execution.id)
        path.write_text(json.dumps(self._to_dict(execution), indent=2))

    def get_recent(self, selfbot_id: str, limit: int = 10) -> List[Execution]:
        executions = []
        for path in sorted(self.storage_dir.glob("*.json"), reverse=True):
            data = json.loads(path.read_text())
            if data["selfbot_id"] == selfbot_id:
                executions.append(self._from_dict(data))
                if len(executions) >= limit:
                    break
        return executions

    def get_all_recent(self, limit: int = 50) -> List[Execution]:
        executions = []
        for path in sorted(self.storage_dir.glob("*.json"), reverse=True)[:limit]:
            data = json.loads(path.read_text())
            executions.append(self._from_dict(data))
        return executions
