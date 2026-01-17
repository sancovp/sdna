"""
Custom tools for Hermes agents.

The key tool is report_blocked - allows agents to signal
they cannot proceed and need intervention.

Block reports use XML tags for reliable parsing:
<genuinely-blocked>
goal: ...
open_tasks: ...
obstacle: ...
reason: ...
</genuinely-blocked>
"""

import os
import re
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from enum import Enum


# Cache directory for block reports
BLOCK_REPORTS_DIR = Path.home() / ".hermes" / "block_reports"


class BlockReason(str, Enum):
    """Standard reasons an agent might be blocked."""
    MISSING_INPUT = "missing_input"  # Required data not available
    PERMISSION_DENIED = "permission_denied"  # Can't access resource
    AMBIGUOUS_GOAL = "ambiguous_goal"  # Goal unclear, need clarification
    TOOL_FAILURE = "tool_failure"  # A tool errored
    DEPENDENCY_MISSING = "dependency_missing"  # Need something from another step
    HUMAN_REQUIRED = "human_required"  # Need human decision
    OTHER = "other"


@dataclass
class BlockedReport:
    """
    Report from an agent that it cannot proceed.

    Parsed from <genuinely-blocked> XML tag in agent response.
    """
    goal: str = ""
    open_tasks: str = ""
    obstacle: str = ""
    reason: str = ""
    raw_text: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    cached_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "blocked": True,
            "goal": self.goal,
            "open_tasks": self.open_tasks,
            "obstacle": self.obstacle,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "cached_path": self.cached_path,
        }

    def save(self, config_name: str = "unknown") -> str:
        """Save report to cache file, return path."""
        BLOCK_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # Filename: timestamp_configname.json
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', config_name)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{ts}_{safe_name}.json"
        filepath = BLOCK_REPORTS_DIR / filename

        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

        self.cached_path = str(filepath)
        return self.cached_path


def get_blocked_instruction() -> str:
    """
    Return the instruction text to append to prompts for block reporting.

    This tells the agent HOW to report being blocked using XML tags.
    """
    return """

## If You Cannot Proceed

If you encounter a genuine obstacle that prevents completing this task, report it using this EXACT format:

<genuinely-blocked>
goal: [the goal you were trying to accomplish]
open_tasks: [what remains to be done]
obstacle: [what specifically is blocking you]
reason: [why this is blocking - missing_input, permission_denied, ambiguous_goal, tool_failure, dependency_missing, human_required, or other]
</genuinely-blocked>

Only use this when truly blocked. Try to complete the task first. If blocked, report immediately without further attempts.
"""


def parse_blocked_from_text(text: str) -> Optional[BlockedReport]:
    """
    Parse a <genuinely-blocked> XML tag from agent response text.

    Returns BlockedReport if found, None otherwise.
    """
    pattern = r'<genuinely-blocked>\s*(.*?)\s*</genuinely-blocked>'
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

    if not match:
        return None

    content = match.group(1)

    # Parse the key: value pairs
    report = BlockedReport(raw_text=content)

    for line in content.split('\n'):
        line = line.strip()
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip().lower().replace(' ', '_')
            value = value.strip()

            if key == 'goal':
                report.goal = value
            elif key == 'open_tasks':
                report.open_tasks = value
            elif key == 'obstacle':
                report.obstacle = value
            elif key == 'reason':
                report.reason = value

    return report


def get_cached_reports(limit: int = 10) -> List[BlockedReport]:
    """Get recent cached block reports."""
    if not BLOCK_REPORTS_DIR.exists():
        return []

    reports = []
    files = sorted(BLOCK_REPORTS_DIR.glob("*.json"), reverse=True)[:limit]

    for f in files:
        try:
            with open(f) as fp:
                data = json.load(fp)
                report = BlockedReport(
                    goal=data.get("goal", ""),
                    open_tasks=data.get("open_tasks", ""),
                    obstacle=data.get("obstacle", ""),
                    reason=data.get("reason", ""),
                    timestamp=data.get("timestamp", ""),
                    cached_path=str(f),
                )
                reports.append(report)
        except Exception:
            continue

    return reports


def clear_cached_reports() -> int:
    """Clear all cached block reports. Returns count deleted."""
    if not BLOCK_REPORTS_DIR.exists():
        return 0

    count = 0
    for f in BLOCK_REPORTS_DIR.glob("*.json"):
        f.unlink()
        count += 1

    return count
