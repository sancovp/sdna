"""
Agent Cron - Schedule prompts to Claude via tmux.

This is for automating the AGENT (cognition), not browser automation.
Much simpler and more powerful for most use cases.

Usage:
    from sdna.selfbot_extensions.infrastructure.agent_cron import AgentScheduler

    scheduler = AgentScheduler()

    # One-shot prompt
    scheduler.prompt("Write today's tweet based on yesterday's work")

    # Scheduled prompt
    scheduler.schedule(
        name="daily-tweet",
        prompt="Write today's tweet based on recent conversations",
        cron="0 9 * * *"  # 9am daily
    )

    # Or from CLI:
    # python -m selfbot.infrastructure.agent_cron prompt "Do something"
    # python -m selfbot.infrastructure.agent_cron schedule daily-tweet "0 9 * * *" "Write tweet"
"""

import subprocess
import json
import os
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Session detection - same logic as self_compact
def get_tmux_session() -> str:
    """Detect the Claude tmux session name."""
    import os

    # Env var override
    session = os.environ.get("CLAUDE_TMUX_SESSION")
    if session:
        return session

    # Try common names
    for name in ["cave", "claude"]:
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True
        )
        if result.returncode == 0:
            return name

    raise RuntimeError("No tmux session found (tried 'cave', 'claude')")


class AgentScheduler:
    """Schedule prompts to Claude via tmux."""

    def __init__(self, storage_dir: str = "/tmp/agent_cron"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.schedules_file = self.storage_dir / "schedules.json"
        self._load_schedules()

    def _load_schedules(self):
        if self.schedules_file.exists():
            self.schedules = json.loads(self.schedules_file.read_text())
        else:
            self.schedules = {}

    def _save_schedules(self):
        self.schedules_file.write_text(json.dumps(self.schedules, indent=2))

    def prompt(self, text: str, wait: bool = False) -> bool:
        """
        Send a prompt to Claude immediately.

        Args:
            text: The prompt to send
            wait: If True, wait for response (blocking)

        Returns:
            True if sent successfully
        """
        try:
            session = get_tmux_session()

            # Send the prompt text
            subprocess.run(
                ["tmux", "send-keys", "-t", session, text],
                check=True
            )

            # Press Enter to submit
            subprocess.run(
                ["tmux", "send-keys", "-t", session, "Enter"],
                check=True
            )

            logger.info(f"Sent prompt to {session}: {text[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to send prompt: {e}")
            return False

    def prompt_from_file(self, filepath: str) -> bool:
        """Send prompt from a file."""
        text = Path(filepath).read_text().strip()
        return self.prompt(text)

    def prompt_in(self, text: str, seconds: int) -> int:
        """
        Schedule a one-shot prompt N seconds from now.

        Args:
            text: The prompt to send
            seconds: Delay in seconds

        Returns:
            PID of the background process
        """
        script_path = Path(__file__).resolve()
        # Escape for shell
        text_escaped = text.replace("'", "'\"'\"'")
        cmd = f"(sleep {seconds} && python3 {script_path} prompt '{text_escaped}') &"

        result = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        logger.info(f"Scheduled prompt in {seconds}s (PID: {result.pid})")
        return result.pid

    def schedule(
        self,
        name: str,
        prompt: str,
        cron: str,
        enabled: bool = True
    ) -> dict:
        """
        Add a scheduled prompt.

        This writes to schedules.json - use install_cron() to
        actually install to system crontab.

        Args:
            name: Unique name for this schedule
            prompt: The prompt text (or path to file with @/path/to/file)
            cron: Cron expression (e.g., "0 9 * * *" for 9am daily)
            enabled: Whether this schedule is active
        """
        self.schedules[name] = {
            "prompt": prompt,
            "cron": cron,
            "enabled": enabled,
            "created": datetime.now().isoformat(),
        }
        self._save_schedules()
        logger.info(f"Scheduled '{name}': {cron}")
        return self.schedules[name]

    def unschedule(self, name: str) -> bool:
        """Remove a scheduled prompt."""
        if name in self.schedules:
            del self.schedules[name]
            self._save_schedules()
            return True
        return False

    def list_schedules(self) -> dict:
        """List all scheduled prompts."""
        return self.schedules.copy()

    def install_cron(self) -> str:
        """
        Generate crontab entries for all enabled schedules.

        Returns the crontab lines to add. User should review and install.
        """
        lines = ["# Agent Cron - Claude prompt scheduler"]
        script = str(Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "skills/use-computer/resources/selfbot/infrastructure/agent_cron.py")

        for name, config in self.schedules.items():
            if not config.get("enabled", True):
                continue

            cron_expr = config["cron"]
            prompt = config["prompt"]

            # Escape quotes in prompt
            prompt_escaped = prompt.replace('"', '\\"')

            line = f'{cron_expr} python3 {script} prompt "{prompt_escaped}"'
            lines.append(f"# {name}")
            lines.append(line)

        return "\n".join(lines)


# CLI interface
def main():
    import sys

    logging.basicConfig(level=logging.INFO)
    scheduler = AgentScheduler()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  agent_cron.py prompt 'Your prompt here'")
        print("  agent_cron.py in SECONDS 'Your prompt here'")
        print("  agent_cron.py prompt-file /path/to/prompt.txt")
        print("  agent_cron.py schedule NAME 'CRON' 'PROMPT'")
        print("  agent_cron.py list")
        print("  agent_cron.py install")
        print("  agent_cron.py remove NAME")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "prompt" and len(sys.argv) >= 3:
        text = " ".join(sys.argv[2:])
        scheduler.prompt(text)

    elif cmd == "in" and len(sys.argv) >= 4:
        seconds = int(sys.argv[2])
        text = " ".join(sys.argv[3:])
        pid = scheduler.prompt_in(text, seconds)
        print(f"Scheduled in {seconds}s (PID: {pid})")

    elif cmd == "prompt-file" and len(sys.argv) >= 3:
        scheduler.prompt_from_file(sys.argv[2])

    elif cmd == "schedule" and len(sys.argv) >= 5:
        name, cron, prompt = sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])
        scheduler.schedule(name, prompt, cron)
        print(f"Scheduled '{name}'")

    elif cmd == "list":
        for name, config in scheduler.list_schedules().items():
            status = "enabled" if config.get("enabled", True) else "disabled"
            print(f"[{name}] ({status})")
            print(f"  Cron: {config['cron']}")
            print(f"  Prompt: {config['prompt'][:60]}...")
            print()

    elif cmd == "install":
        print(scheduler.install_cron())
        print("\n# Add these lines to crontab with: crontab -e")

    elif cmd == "remove" and len(sys.argv) >= 3:
        if scheduler.unschedule(sys.argv[2]):
            print(f"Removed '{sys.argv[2]}'")
        else:
            print(f"Not found: '{sys.argv[2]}'")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
