"""Selfbot - Scheduled GUI automation via virtual screens."""

from .domain.models import Selfbot, Schedule, Execution, ExecutionStatus
from .application.runner import SelfbotRunner
from .application.manager import SelfbotManager

__all__ = [
    "Selfbot",
    "Schedule",
    "Execution",
    "ExecutionStatus",
    "SelfbotRunner",
    "SelfbotManager",
]
