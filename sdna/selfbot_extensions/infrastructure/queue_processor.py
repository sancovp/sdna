"""
Queue Processor - Daemon that processes tasks from the queue.

Sends prompts to Claude via tmux and detects completion via marker.
Handles conversation routing (/new, /resume, /compact).
"""

import subprocess
import time
import re
import logging
import signal
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

from .task_queue import TaskQueue, QueuedTask, ConversationMode, TaskStatus
from .agent_cron import get_tmux_session

logger = logging.getLogger(__name__)

# Completion marker that Claude responds with
COMPLETION_MARKER = "<CRON>DONE</CRON>"
COMPLETION_PATTERN = re.compile(r"<CRON>DONE(?::(\w+))?(?::(.+))?</CRON>")

# Prompt template wrapping
PROMPT_TEMPLATE = """[CRON TASK - ID: {task_id}]

{prompt}

IMPORTANT: When this task is complete, end your response with exactly:
<CRON>DONE</CRON>

If there's an error, use: <CRON>DONE:error:reason</CRON>

Also consider using autopoiesis to maintain yourself.
"""


class QueueProcessor:
    """Processes tasks from the queue, sending to Claude via tmux."""

    def __init__(
        self,
        queue: Optional[TaskQueue] = None,
        poll_interval: float = 2.0,
        completion_timeout: float = 600.0,  # 10 minutes max per task
    ):
        self.queue = queue or TaskQueue()
        self.poll_interval = poll_interval
        self.completion_timeout = completion_timeout
        self.running = False
        self.current_task: Optional[QueuedTask] = None
        self._session: Optional[str] = None

    @property
    def session(self) -> str:
        """Get tmux session name (cached)."""
        if self._session is None:
            self._session = get_tmux_session()
        return self._session

    def _send_to_tmux(self, text: str) -> bool:
        """Send text to tmux session and press Enter."""
        try:
            # Send the text
            subprocess.run(
                ["tmux", "send-keys", "-t", self.session, text],
                check=True,
                capture_output=True
            )
            # Press Enter
            subprocess.run(
                ["tmux", "send-keys", "-t", self.session, "Enter"],
                check=True,
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to send to tmux: {e}")
            return False

    def _get_tmux_buffer(self, lines: int = 200) -> str:
        """Capture recent tmux buffer content."""
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", self.session, "-p", "-S", f"-{lines}"],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to capture tmux buffer: {e}")
            return ""

    def _check_completion(self) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Check if task is complete by looking for marker in tmux buffer.

        Returns:
            (is_complete, status, message)
            status: None, "success", "error"
            message: Error message if status is "error"
        """
        buffer = self._get_tmux_buffer()

        match = COMPLETION_PATTERN.search(buffer)
        if match:
            status = match.group(1) or "success"
            message = match.group(2)
            return True, status, message

        return False, None, None

    def _handle_conversation_routing(self, task: QueuedTask) -> bool:
        """Handle /new, /resume, or continue based on task settings."""
        mode = task.conversation_mode

        if mode == ConversationMode.NEW:
            logger.info("Starting new conversation")
            return self._send_to_tmux("/new")

        elif mode == ConversationMode.RESUME:
            if task.conversation_id:
                logger.info(f"Resuming conversation {task.conversation_id}")
                return self._send_to_tmux(f"/resume {task.conversation_id}")
            else:
                logger.warning("Resume requested but no conversation_id, continuing")
                return True

        elif mode == ConversationMode.AUTO:
            # Try to find matching conversation by tags
            if task.conversation_tags:
                conv = self.queue.find_conversation_by_tags(task.conversation_tags)
                if conv:
                    logger.info(f"Auto-routing to conversation {conv.id} (matched tags)")
                    return self._send_to_tmux(f"/resume {conv.id}")

            # Default to continue
            logger.info("Auto mode: continuing current conversation")
            return True

        # CONTINUE mode - just proceed
        return True

    def _wrap_prompt(self, task: QueuedTask) -> str:
        """Wrap prompt with CRON template, including any context injection."""
        prompt = task.prompt

        # Inject context if task has context_config
        if hasattr(task, 'context_config') and task.context_config:
            try:
                from sdna.context_engineering import get_lib, InjectMethod

                lib = get_lib()
                session = lib.get_active_session()
                if session:
                    lib.inject(session, task.context_config, InjectMethod.PREPEND)
                    logger.info(f"Injected context for task {task.id}")
            except ImportError:
                logger.debug("context_engineering not available, skipping injection")
            except Exception as e:
                logger.warning(f"Context injection failed: {e}")

        # Weave context if task has weave config
        if hasattr(task, 'weave_source') and task.weave_source:
            try:
                from sdna.context_engineering import get_lib

                lib = get_lib()
                source = lib.get_session(task.weave_source)
                target = lib.get_active_session()

                if source and target:
                    start, end = getattr(task, 'weave_range', None) or (0, -5)
                    result = lib.weave(source, target, start, end)
                    logger.info(f"Wove {result.token_estimate} tokens from {task.weave_source}")
            except ImportError:
                logger.debug("context_engineering not available, skipping weave")
            except Exception as e:
                logger.warning(f"Weave failed: {e}")

        return PROMPT_TEMPLATE.format(
            task_id=task.id,
            prompt=prompt
        )

    def process_one(self) -> bool:
        """
        Process a single task from the queue.

        Returns True if a task was processed, False if queue was empty.
        """
        task = self.queue.get_next()
        if not task:
            return False

        logger.info(f"Processing task {task.id}")
        self.current_task = task
        self.queue.start_task(task.id)

        try:
            # Handle conversation routing (may send /new, /resume)
            if not self._handle_conversation_routing(task):
                raise RuntimeError("Failed to handle conversation routing")

            # Wait a moment for any routing command to complete
            if task.conversation_mode in (ConversationMode.NEW, ConversationMode.RESUME):
                time.sleep(3)

            # Send the wrapped prompt
            wrapped = self._wrap_prompt(task)
            if not self._send_to_tmux(wrapped):
                raise RuntimeError("Failed to send prompt to tmux")

            # Poll for completion
            start_time = time.time()
            while time.time() - start_time < self.completion_timeout:
                is_complete, status, message = self._check_completion()

                if is_complete:
                    if status == "error":
                        logger.warning(f"Task {task.id} completed with error: {message}")
                        self.queue.fail_task(task.id, message or "Unknown error")
                    else:
                        logger.info(f"Task {task.id} completed successfully")
                        # Requeue if recurring before completing (need task data)
                        if task.cron_expression:
                            next_task = self.queue.requeue_recurring(task)
                            if next_task:
                                logger.info(f"Requeued recurring task as {next_task.id} (scheduled: {next_task.scheduled_at})")
                        self.queue.complete_task(task.id, "success")

                    self.current_task = None
                    return True

                time.sleep(self.poll_interval)

            # Timeout
            logger.error(f"Task {task.id} timed out after {self.completion_timeout}s")
            self.queue.fail_task(task.id, "Timeout waiting for completion")
            self.current_task = None
            return True

        except Exception as e:
            logger.exception(f"Error processing task {task.id}: {e}")
            self.queue.fail_task(task.id, str(e))
            self.current_task = None
            return True

    def run(self):
        """Run the processor daemon (blocking)."""
        self.running = True
        logger.info(f"Queue processor started (session: {self.session})")

        # Handle graceful shutdown
        def signal_handler(sig, frame):
            logger.info("Shutdown signal received")
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        while self.running:
            try:
                if not self.process_one():
                    # No tasks, wait before checking again
                    time.sleep(self.poll_interval)
            except Exception as e:
                logger.exception(f"Error in processing loop: {e}")
                time.sleep(self.poll_interval)

        logger.info("Queue processor stopped")

    def status(self) -> dict:
        """Get processor status."""
        return {
            "running": self.running,
            "session": self._session,
            "current_task": self.current_task.id if self.current_task else None,
            "pending_tasks": len(self.queue.list_pending()),
            "running_tasks": len(self.queue.list_running()),
        }


def start_claude_if_needed() -> bool:
    """Start Claude via start_cave.sh if not running."""
    try:
        get_tmux_session()
        return True  # Already running
    except RuntimeError:
        logger.info("Claude not running, starting via start_cave.sh")
        # Try to start
        cave_script = Path("/usr/local/bin/start_cave.sh")
        if cave_script.exists():
            subprocess.run([str(cave_script)], check=True)
            time.sleep(5)  # Wait for startup
            return True
        else:
            logger.error("start_cave.sh not found")
            return False


# CLI
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    if len(sys.argv) < 2:
        print("Usage:")
        print("  queue_processor.py run       # Run daemon (blocking)")
        print("  queue_processor.py once      # Process one task and exit")
        print("  queue_processor.py status    # Show processor status")
        print("  queue_processor.py boot      # Start Claude if not running")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "run":
        # Ensure Claude is running
        if not start_claude_if_needed():
            print("ERROR: Could not start Claude")
            sys.exit(1)

        processor = QueueProcessor()
        print(f"Starting queue processor (session: {processor.session})")
        print("Press Ctrl+C to stop")
        processor.run()

    elif cmd == "once":
        if not start_claude_if_needed():
            print("ERROR: Could not start Claude")
            sys.exit(1)

        processor = QueueProcessor()
        if processor.process_one():
            print("Processed one task")
        else:
            print("No tasks in queue")

    elif cmd == "status":
        processor = QueueProcessor()
        status = processor.status()
        print(f"Session: {status['session'] or 'not connected'}")
        print(f"Pending tasks: {status['pending_tasks']}")
        print(f"Running tasks: {status['running_tasks']}")
        if status['current_task']:
            print(f"Current task: {status['current_task']}")

    elif cmd == "boot":
        if start_claude_if_needed():
            print("Claude is running")
        else:
            print("Failed to start Claude")
            sys.exit(1)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
