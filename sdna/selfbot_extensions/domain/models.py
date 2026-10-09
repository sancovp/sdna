"""
Domain Models - Pure business objects, no external dependencies.

These represent WHAT a selfbot system deals with, not HOW it works.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
import uuid


class ExecutionStatus(Enum):
    """Status of a selfbot execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class Schedule:
    """
    When a selfbot should run.

    Supports cron expressions or simple intervals.
    """
    cron_expr: Optional[str] = None  # "0 9 * * *" = 9am daily
    interval_seconds: Optional[int] = None  # Run every N seconds
    run_once: bool = False  # Single execution, no repeat

    def __post_init__(self):
        if not self.cron_expr and not self.interval_seconds and not self.run_once:
            self.run_once = True  # Default to single run


@dataclass
class Selfbot:
    """
    A selfbot definition - what to run and when.

    The selfbot doesn't know HOW it runs (Screen, Xvfb, etc).
    It just knows WHAT it is.
    """
    name: str
    script_path: str  # Path to Python script to execute
    schedule: Schedule = field(default_factory=Schedule)

    # Execution context
    screen_size: tuple[int, int] = (1920, 1080)
    timeout_seconds: int = 300  # 5 min default

    # Data interchange
    input_file: Optional[str] = None   # Read input from here
    output_file: Optional[str] = None  # Write output here

    # Metadata
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self):
        return f"Selfbot({self.name}, schedule={self.schedule})"


@dataclass
class Execution:
    """
    Record of a selfbot execution.

    Immutable after creation - represents what happened.
    """
    selfbot_id: str
    selfbot_name: str
    status: ExecutionStatus
    started_at: datetime
    finished_at: Optional[datetime] = None

    # Results
    output: Optional[str] = None
    error: Optional[str] = None
    screenshot_path: Optional[str] = None

    # Metadata
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    display_num: Optional[int] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.finished_at and self.started_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None

    def __repr__(self):
        dur = f", {self.duration_seconds:.1f}s" if self.duration_seconds else ""
        return f"Execution({self.selfbot_name}, {self.status.value}{dur})"


# Protocols for dependency inversion (domain defines what it needs)

class SelfbotRepository:
    """Protocol for selfbot storage - domain says WHAT, infra says HOW."""

    def save(self, selfbot: Selfbot) -> None:
        raise NotImplementedError

    def get(self, selfbot_id: str) -> Optional[Selfbot]:
        raise NotImplementedError

    def get_by_name(self, name: str) -> Optional[Selfbot]:
        raise NotImplementedError

    def list_all(self) -> list[Selfbot]:
        raise NotImplementedError

    def list_enabled(self) -> list[Selfbot]:
        raise NotImplementedError

    def delete(self, selfbot_id: str) -> bool:
        raise NotImplementedError


class ExecutionRepository:
    """Protocol for execution history storage."""

    def save(self, execution: Execution) -> None:
        raise NotImplementedError

    def get_recent(self, selfbot_id: str, limit: int = 10) -> list[Execution]:
        raise NotImplementedError

    def get_all_recent(self, limit: int = 50) -> list[Execution]:
        raise NotImplementedError


class ScreenProvider:
    """Protocol for virtual screen creation - domain says WHAT, infra says HOW."""

    def create_screen(self, size: tuple[int, int]) -> Any:
        """Returns something that can launch(), screenshot(), close()."""
        raise NotImplementedError
