"""
SDNA Cron — Schedule-based agent task execution with delivery targets.

Primitives for scheduling agent prompts/code on cron expressions
or intervals, with delivery routing for results.

This is the BASE LIBRARY. CAVE's automation.py uses these primitives
to build its reflective Automation(Link) system.

Usage:
    from sdna.cron import CronJob, CronScheduler, DeliveryTarget

    job = CronJob(
        name="daily-tweet",
        schedule="0 9 * * *",
        prompt="Write today's tweet based on recent work",
        delivery=DeliveryTarget(type="discord", channel_id="12345"),
    )

    scheduler = CronScheduler()
    scheduler.add(job)
    scheduler.start()
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# DELIVERY TARGET — Where cron output goes
# =============================================================================

class DeliveryType(str, Enum):
    """Where a cron job's result gets delivered."""
    AGENT = "agent"          # Send to a registered agent (by agent_id)
    DISCORD = "discord"      # Post to a Discord channel (by channel_id)
    FILE = "file"            # Write to a file (by path)
    WEBHOOK = "webhook"      # POST to a URL
    TMUX = "tmux"            # Send to tmux session (legacy, default)
    CALLBACK = "callback"    # Python callable


@dataclass
class DeliveryTarget:
    """Delivery routing for cron job results.

    Examples:
        DeliveryTarget(type="discord", channel_id="12345")
        DeliveryTarget(type="agent", agent_id="openclaw-worker")
        DeliveryTarget(type="file", path="/workspace/output/result.md")
        DeliveryTarget(type="tmux", session="cave")
        DeliveryTarget(type="webhook", url="https://example.com/hook")
        DeliveryTarget(type="callback", callback=my_func)
    """
    type: DeliveryType = DeliveryType.TMUX
    # Type-specific fields
    session: Optional[str] = None       # tmux session name
    channel_id: Optional[str] = None    # Discord channel ID
    agent_id: Optional[str] = None      # Agent registry ID
    path: Optional[str] = None          # File path
    url: Optional[str] = None           # Webhook URL
    callback: Optional[Callable] = None # Python callable

    def to_dict(self) -> dict:
        """Serialize (excludes callback)."""
        d = {"type": self.type.value}
        for k in ["session", "channel_id", "agent_id", "path", "url"]:
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'DeliveryTarget':
        """Deserialize from dict."""
        dtype = DeliveryType(data.get("type", "tmux"))
        return cls(
            type=dtype,
            session=data.get("session"),
            channel_id=data.get("channel_id"),
            agent_id=data.get("agent_id"),
            path=data.get("path"),
            url=data.get("url"),
        )


# =============================================================================
# CRON JOB — A scheduled task with delivery
# =============================================================================

class SessionTarget(str, Enum):
    """Whether to run on main agent session or isolated."""
    MAIN = "main"          # Run on the main agent (heartbeat-style)
    ISOLATED = "isolated"  # Run a fresh sub-agent


@dataclass
class CronJob:
    """A scheduled agent task.

    schedule: Cron expression ("0 9 * * *") or interval ("every:300" = 300s)
    prompt: What to tell the agent
    code_pointer: Optional "module.func" to import and call
    delivery: Where the result goes
    session_target: Run on main agent or spawn isolated
    """
    name: str
    schedule: str                                    # Cron expr or "every:N"
    prompt: Optional[str] = None                     # Agent prompt
    code_pointer: Optional[str] = None               # "module.func" to call
    code_args: Dict[str, Any] = field(default_factory=dict)
    delivery: Optional[DeliveryTarget] = None        # Where output goes
    session_target: SessionTarget = SessionTarget.MAIN
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    priority: int = 5

    # Runtime state
    last_run: Optional[datetime] = field(default=None, repr=False)
    run_count: int = field(default=0, repr=False)

    def __post_init__(self):
        """Anchor cron-EXPRESSION jobs at creation so they actually fire.

        BUGFIX: a cron-expr job left with last_run=None never fired — is_due()'s
        `base = self.last_run or now` made `base=now`, so `croniter.get_next()` was
        ALWAYS strictly future and `now >= next_run` was always False; last_run then
        never advanced, so the job never fired, forever. Stamping last_run=now at
        creation makes the FIRST fire land on the next REAL scheduled boundary
        (correct cron semantics: no surprise immediate fire, no catch-up of boundaries
        missed while down). INTERVAL jobs are intentionally LEFT with last_run=None so
        their is_due() (`last_run is None -> return True`) still fires once immediately —
        that behavior is unchanged.
        """
        if self.last_run is None and not self.is_interval:
            self.last_run = datetime.now()

    @property
    def is_interval(self) -> bool:
        """Check if this is an interval schedule vs cron expression."""
        return self.schedule.startswith("every:")

    @property
    def interval_seconds(self) -> Optional[int]:
        """Get interval in seconds if interval-based."""
        if self.is_interval:
            return int(self.schedule.split(":")[1])
        return None

    def is_due(self) -> bool:
        """Check if this job is due to run."""
        if not self.enabled:
            return False

        now = datetime.now()

        if self.is_interval:
            seconds = self.interval_seconds
            if self.last_run is None:
                return True
            elapsed = (now - self.last_run).total_seconds()
            return elapsed >= seconds

        # Cron expression
        try:
            from croniter import croniter
            base = self.last_run or now
            cron_iter = croniter(self.schedule, base)
            next_run = cron_iter.get_next(datetime)
            return now >= next_run
        except ImportError:
            logger.warning("croniter not installed, cron expressions disabled")
            return False

    def mark_run(self):
        """Mark this job as having run."""
        self.last_run = datetime.now()
        self.run_count += 1

    def to_dict(self) -> dict:
        """Serialize to dict."""
        d = {
            "name": self.name,
            "schedule": self.schedule,
            "session_target": self.session_target.value,
            "enabled": self.enabled,
            "tags": self.tags,
            "priority": self.priority,
        }
        if self.prompt:
            d["prompt"] = self.prompt
        if self.code_pointer:
            d["code_pointer"] = self.code_pointer
            d["code_args"] = self.code_args
        if self.delivery:
            d["delivery"] = self.delivery.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'CronJob':
        """Deserialize from dict."""
        delivery = None
        if "delivery" in data:
            delivery = DeliveryTarget.from_dict(data["delivery"])
        session_target = SessionTarget(data.get("session_target", "main"))
        return cls(
            name=data["name"],
            schedule=data["schedule"],
            prompt=data.get("prompt"),
            code_pointer=data.get("code_pointer"),
            code_args=data.get("code_args", {}),
            delivery=delivery,
            session_target=session_target,
            enabled=data.get("enabled", True),
            tags=data.get("tags", []),
            priority=data.get("priority", 5),
        )


# =============================================================================
# CRON SCHEDULER — Runs CronJobs on schedule
# =============================================================================

class CronScheduler:
    """Scheduler for CronJobs. Checks due jobs and fires them.

    The scheduler only manages TIMING. Actual execution and delivery
    are handled by the executor (passed to start() or tick()).
    CAVE's AutomationMixin provides the executor.
    """

    def __init__(self, storage_dir: Optional[str] = None):
        self.jobs: Dict[str, CronJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._storage_dir = Path(storage_dir) if storage_dir else None
        if self._storage_dir:
            self._storage_dir.mkdir(parents=True, exist_ok=True)

    def add(self, job: CronJob) -> None:
        """Register a cron job."""
        self.jobs[job.name] = job
        if self._storage_dir:
            self._save_job(job)

    def remove(self, name: str) -> bool:
        """Remove a cron job."""
        if name in self.jobs:
            del self.jobs[name]
            if self._storage_dir:
                path = self._storage_dir / f"{name}.json"
                if path.exists():
                    path.unlink()
            return True
        return False

    def enable(self, name: str) -> bool:
        if name in self.jobs:
            self.jobs[name].enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        if name in self.jobs:
            self.jobs[name].enabled = False
            return True
        return False

    def get_due(self) -> List[CronJob]:
        """Get all jobs that are due to run."""
        return [job for job in self.jobs.values() if job.is_due()]

    def load_all(self) -> int:
        """Load all job definitions from storage dir."""
        if not self._storage_dir:
            return 0
        count = 0
        for json_file in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text())
                job = CronJob.from_dict(data)
                self.jobs[job.name] = job
                count += 1
            except Exception as e:
                logger.error(f"Failed to load cron job {json_file}: {e}")
        return count

    def _save_job(self, job: CronJob):
        """Persist job definition."""
        if self._storage_dir:
            path = self._storage_dir / f"{job.name}.json"
            path.write_text(json.dumps(job.to_dict(), indent=2))

    def tick(self, executor: Optional[Callable] = None) -> List[Dict[str, Any]]:
        """Check all jobs, fire due ones. Returns results.

        If executor is provided, it's called as executor(job) for each due job.
        Otherwise returns the list of due jobs for external handling.
        """
        results = []
        for job in self.get_due():
            if executor:
                try:
                    result = executor(job)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Cron job {job.name} failed: {e}")
                    results.append({"name": job.name, "error": str(e)})
            else:
                results.append({"name": job.name, "due": True})
            job.mark_run()
        return results

    def start(self, executor: Callable, check_interval: float = 1.0) -> None:
        """Start scheduler in background thread."""
        if self._running:
            return
        self._running = True

        def run_loop():
            while self._running:
                self.tick(executor)
                time.sleep(check_interval)

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def status(self) -> Dict[str, Any]:
        """Get status of all jobs."""
        return {
            "running": self._running,
            "jobs": {
                name: {
                    "schedule": job.schedule,
                    "enabled": job.enabled,
                    "session_target": job.session_target.value,
                    "last_run": job.last_run.isoformat() if job.last_run else None,
                    "run_count": job.run_count,
                    "has_delivery": job.delivery is not None,
                    "delivery_type": job.delivery.type.value if job.delivery else None,
                }
                for name, job in self.jobs.items()
            },
        }
