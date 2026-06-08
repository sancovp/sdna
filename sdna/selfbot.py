"""
SDNA SelfBot — Agent self-prompting via tmux session control.

Primitives for an agent to prompt itself or other agents via tmux.
This is direct agent-to-agent communication through session injection.

This is the BASE LIBRARY. CAVE's automation.py uses these primitives
alongside sdna.cron for scheduled self-prompting.

Usage:
    from sdna.selfbot import SelfBot

    bot = SelfBot()

    # Immediate self-prompt
    bot.prompt("Check inbox and summarize")

    # Delayed self-prompt
    bot.prompt_in("Daily summary time", seconds=3600)

    # Prompt another agent's session
    bot.prompt("Do this task", session="worker-1")
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_tmux_session(preferred: Optional[str] = None) -> str:
    """Detect or use a tmux session.

    Priority:
        1. Explicit preferred name
        2. CLAUDE_TMUX_SESSION env var
        3. Auto-detect from known names
    """
    if preferred:
        return preferred

    session = os.environ.get("CLAUDE_TMUX_SESSION")
    if session:
        return session

    for name in ["cave", "claude", "gnosys"]:
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True,
        )
        if result.returncode == 0:
            return name

    raise RuntimeError("No tmux session found (tried 'cave', 'claude', 'gnosys')")


class SelfBot:
    """Agent self-prompting via tmux.

    Sends text to a tmux session as if a human typed it.
    Used for:
        - Self-referential cron (agent prompts itself on schedule)
        - Agent-to-agent communication (prompt another session)
        - Delayed one-shot prompts
    """

    def __init__(self, default_session: Optional[str] = None):
        self._default_session = default_session

    @property
    def session(self) -> str:
        return get_tmux_session(self._default_session)

    def prompt(self, text: str, session: Optional[str] = None) -> bool:
        """Send a prompt to a tmux session immediately.

        Args:
            text: The prompt text to inject
            session: Target session (default: self.session)

        Returns:
            True if sent successfully
        """
        target = session or self.session

        try:
            # Send the text
            subprocess.run(
                ["tmux", "send-keys", "-t", target, text],
                check=True,
            )
            # Press Enter
            subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                check=True,
            )
            logger.info(f"SelfBot → {target}: {text[:60]}...")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"SelfBot failed to send to {target}: {e}")
            return False

    def prompt_from_file(self, filepath: str, session: Optional[str] = None) -> bool:
        """Send prompt loaded from a file."""
        text = Path(filepath).read_text().strip()
        return self.prompt(text, session=session)

    def prompt_in(self, text: str, seconds: int, session: Optional[str] = None) -> int:
        """Schedule a one-shot prompt N seconds from now.

        Returns PID of background process.
        """
        target = session or self.session
        text_escaped = text.replace("'", "'\"'\"'")
        cmd = f"(sleep {seconds} && tmux send-keys -t {target} '{text_escaped}' Enter) &"

        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f"SelfBot scheduled in {seconds}s → {target} (PID: {proc.pid})")
        return proc.pid

    def list_sessions(self) -> list:
        """List available tmux sessions."""
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
        return []


# CLI interface
def main():
    import sys
    logging.basicConfig(level=logging.INFO)
    bot = SelfBot()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  selfbot prompt 'Your prompt here'")
        print("  selfbot prompt-file /path/to/prompt.txt")
        print("  selfbot in SECONDS 'Your prompt here'")
        print("  selfbot sessions")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "prompt" and len(sys.argv) >= 3:
        bot.prompt(" ".join(sys.argv[2:]))

    elif cmd == "prompt-file" and len(sys.argv) >= 3:
        bot.prompt_from_file(sys.argv[2])

    elif cmd == "in" and len(sys.argv) >= 4:
        seconds = int(sys.argv[2])
        text = " ".join(sys.argv[3:])
        pid = bot.prompt_in(text, seconds)
        print(f"Scheduled in {seconds}s (PID: {pid})")

    elif cmd == "sessions":
        for s in bot.list_sessions():
            print(s)

    else:
        print(f"Unknown: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
