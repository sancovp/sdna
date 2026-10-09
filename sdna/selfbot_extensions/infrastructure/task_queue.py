"""
Task Queue - Persistent queue for Claude prompts.

Manages a queue of tasks to be sent to Claude via tmux.
Handles conversation routing (new/resume/continue) and scheduling.
"""

import json
import uuid
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Literal
from enum import Enum

logger = logging.getLogger(__name__)

QUEUE_DIR = Path("/tmp/agent_queue")


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ConversationMode(str, Enum):
    NEW = "new"          # Start fresh conversation
    RESUME = "resume"    # Resume specific conversation by ID
    CONTINUE = "continue"  # Keep current conversation
    AUTO = "auto"        # System decides based on tags/context


@dataclass
class Conversation:
    """Tracked Claude conversation."""
    id: str                           # Claude's conversation ID
    name: str                         # Human-readable name
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_active: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "idle"              # "active" | "idle" | "compacted"
    context_tokens: int = 0           # Estimated tokens used
    tags: list = field(default_factory=list)  # For routing


@dataclass
class QueuedTask:
    """Task waiting to be processed."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    prompt: str = ""
    status: TaskStatus = TaskStatus.PENDING

    # Routing
    conversation_mode: ConversationMode = ConversationMode.CONTINUE
    conversation_id: Optional[str] = None  # If resume, which one
    conversation_tags: list = field(default_factory=list)  # If auto, match by tags

    # Scheduling
    scheduled_at: Optional[str] = None  # ISO timestamp, None = ASAP
    priority: int = 5                    # Higher = sooner (1-10)
    cron_expression: Optional[str] = None  # e.g., "0 9 * * *" for recurring

    # Context Engineering
    context_config: Optional[dict] = None  # Context dict for injection
    weave_source: Optional[str] = None     # Session ID to weave from
    weave_range: Optional[tuple] = None    # (start, end) message indices

    # Results
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None        # Output or error message

    def to_dict(self) -> dict:
        d = asdict(self)
        d['status'] = self.status.value
        d['conversation_mode'] = self.conversation_mode.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'QueuedTask':
        d['status'] = TaskStatus(d.get('status', 'pending'))
        d['conversation_mode'] = ConversationMode(d.get('conversation_mode', 'continue'))
        return cls(**d)


class TaskQueue:
    """Persistent task queue with JSON storage."""

    def __init__(self, storage_dir: Path = QUEUE_DIR):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        (self.storage_dir / "history").mkdir(exist_ok=True)

        self.queue_file = self.storage_dir / "queue.json"
        self.conversations_file = self.storage_dir / "conversations.json"

        self._load()

    def _load(self):
        """Load queue and conversations from disk."""
        if self.queue_file.exists():
            data = json.loads(self.queue_file.read_text())
            self.tasks = [QueuedTask.from_dict(t) for t in data]
        else:
            self.tasks = []

        if self.conversations_file.exists():
            data = json.loads(self.conversations_file.read_text())
            self.conversations = {k: Conversation(**v) for k, v in data.items()}
        else:
            self.conversations = {}

    def _save(self):
        """Persist queue and conversations to disk."""
        self.queue_file.write_text(json.dumps(
            [t.to_dict() for t in self.tasks],
            indent=2
        ))
        self.conversations_file.write_text(json.dumps(
            {k: asdict(v) for k, v in self.conversations.items()},
            indent=2
        ))

    def add(
        self,
        prompt: str,
        mode: ConversationMode = ConversationMode.CONTINUE,
        conversation_id: Optional[str] = None,
        tags: Optional[list] = None,
        priority: int = 5,
        scheduled_at: Optional[datetime] = None,
        cron_expression: Optional[str] = None
    ) -> QueuedTask:
        """Add a task to the queue."""
        task = QueuedTask(
            prompt=prompt,
            conversation_mode=mode,
            conversation_id=conversation_id,
            conversation_tags=tags or [],
            priority=priority,
            scheduled_at=scheduled_at.isoformat() if scheduled_at else None,
            cron_expression=cron_expression
        )
        self.tasks.append(task)
        self._save()
        logger.info(f"Added task {task.id}: {prompt[:50]}...")
        return task

    def requeue_recurring(self, task: QueuedTask) -> Optional[QueuedTask]:
        """Requeue a recurring task with next scheduled time."""
        if not task.cron_expression:
            return None

        try:
            from croniter import croniter
            cron = croniter(task.cron_expression, datetime.now())
            next_run = cron.get_next(datetime)

            return self.add(
                prompt=task.prompt,
                mode=task.conversation_mode,
                conversation_id=task.conversation_id,
                tags=task.conversation_tags,
                priority=task.priority,
                scheduled_at=next_run,
                cron_expression=task.cron_expression
            )
        except Exception as e:
            logger.exception(f"Failed to requeue recurring task: {e}")
            return None

    def get_next(self) -> Optional[QueuedTask]:
        """Get next task to process (highest priority pending task that's ready)."""
        now = datetime.now()
        pending = [
            t for t in self.tasks
            if t.status == TaskStatus.PENDING
            and (t.scheduled_at is None or datetime.fromisoformat(t.scheduled_at) <= now)
        ]
        if not pending:
            return None

        # Sort by priority (desc) then by position (first added)
        pending.sort(key=lambda t: -t.priority)
        return pending[0]

    def start_task(self, task_id: str) -> Optional[QueuedTask]:
        """Mark task as running."""
        for task in self.tasks:
            if task.id == task_id:
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now().isoformat()
                self._save()
                return task
        return None

    def complete_task(self, task_id: str, result: str = "success") -> Optional[QueuedTask]:
        """Mark task as done and archive it."""
        for task in self.tasks:
            if task.id == task_id:
                task.status = TaskStatus.DONE
                task.completed_at = datetime.now().isoformat()
                task.result = result

                # Archive to history
                history_file = self.storage_dir / "history" / f"{task_id}.json"
                history_file.write_text(json.dumps(task.to_dict(), indent=2))

                # Remove from active queue
                self.tasks.remove(task)
                self._save()
                return task
        return None

    def fail_task(self, task_id: str, error: str) -> Optional[QueuedTask]:
        """Mark task as failed."""
        for task in self.tasks:
            if task.id == task_id:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now().isoformat()
                task.result = f"ERROR: {error}"
                self._save()
                return task
        return None

    def list_pending(self) -> list[QueuedTask]:
        """List all pending tasks."""
        return [t for t in self.tasks if t.status == TaskStatus.PENDING]

    def list_running(self) -> list[QueuedTask]:
        """List all running tasks."""
        return [t for t in self.tasks if t.status == TaskStatus.RUNNING]

    def get_task(self, task_id: str) -> Optional[QueuedTask]:
        """Get a specific task by ID."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def remove_task(self, task_id: str) -> bool:
        """Remove a task from the queue."""
        for task in self.tasks:
            if task.id == task_id:
                self.tasks.remove(task)
                self._save()
                return True
        return False

    # Conversation management
    def register_conversation(self, conv_id: str, name: str, tags: list = None) -> Conversation:
        """Register a new conversation."""
        conv = Conversation(id=conv_id, name=name, tags=tags or [])
        self.conversations[conv_id] = conv
        self._save()
        return conv

    def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        """Get a conversation by ID."""
        return self.conversations.get(conv_id)

    def find_conversation_by_tags(self, tags: list) -> Optional[Conversation]:
        """Find a conversation matching any of the given tags."""
        for conv in self.conversations.values():
            if any(tag in conv.tags for tag in tags):
                return conv
        return None

    def update_conversation_activity(self, conv_id: str):
        """Update last_active timestamp for a conversation."""
        if conv_id in self.conversations:
            self.conversations[conv_id].last_active = datetime.now().isoformat()
            self._save()


# CLI for testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    queue = TaskQueue()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  task_queue.py add 'prompt' [--priority N] [--mode new|resume|continue]")
        print("  task_queue.py list")
        print("  task_queue.py next")
        print("  task_queue.py complete TASK_ID")
        print("  task_queue.py remove TASK_ID")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 3:
        prompt = sys.argv[2]
        priority = 5
        mode = ConversationMode.CONTINUE

        # Parse optional args
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--priority" and i + 1 < len(sys.argv):
                priority = int(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--mode" and i + 1 < len(sys.argv):
                mode = ConversationMode(sys.argv[i + 1])
                i += 2
            else:
                i += 1

        task = queue.add(prompt, mode=mode, priority=priority)
        print(f"Added task {task.id}")

    elif cmd == "list":
        pending = queue.list_pending()
        running = queue.list_running()

        if running:
            print("RUNNING:")
            for t in running:
                print(f"  [{t.id}] (started {t.started_at})")
                print(f"    {t.prompt[:60]}...")

        if pending:
            print("PENDING:")
            for t in sorted(pending, key=lambda x: -x.priority):
                sched = f" (scheduled: {t.scheduled_at})" if t.scheduled_at else ""
                print(f"  [{t.id}] priority={t.priority}{sched}")
                print(f"    {t.prompt[:60]}...")

        if not pending and not running:
            print("Queue is empty")

    elif cmd == "next":
        task = queue.get_next()
        if task:
            print(f"Next task: {task.id}")
            print(f"  Priority: {task.priority}")
            print(f"  Mode: {task.conversation_mode.value}")
            print(f"  Prompt: {task.prompt}")
        else:
            print("No tasks ready")

    elif cmd == "complete" and len(sys.argv) >= 3:
        task_id = sys.argv[2]
        task = queue.complete_task(task_id)
        if task:
            print(f"Completed task {task_id}")
        else:
            print(f"Task not found: {task_id}")

    elif cmd == "remove" and len(sys.argv) >= 3:
        task_id = sys.argv[2]
        if queue.remove_task(task_id):
            print(f"Removed task {task_id}")
        else:
            print(f"Task not found: {task_id}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
