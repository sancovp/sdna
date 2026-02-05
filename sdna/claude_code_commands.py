"""
Claude Code Commands - Semantic wrappers for Claude Code slash commands.

Send Claude Code commands to tmux sessions without caring about the raw keystrokes.
Works with context_engineering.py's TmuxTransport.

Usage:
    from sdna.claude_code_commands import ClaudeCodeSession
    
    cc = ClaudeCodeSession("cave")  # tmux session name
    cc.new_chat()
    cc.send_prompt("Build a REST API")
    cc.compact()
    cc.resume("abc123")
"""

import re
import subprocess
import time
from typing import Optional, List, TYPE_CHECKING, Union
from dataclasses import dataclass

from .context_engineering import parse_tmux_messages, ParsedMessage


@dataclass
class ConversationInfo:
    """Info about a Claude Code conversation."""
    id: str
    title: str
    timestamp: Optional[str] = None


class ClaudeCodeSession:
    """
    Control a Claude Code instance running in a tmux session.
    
    Provides semantic commands instead of raw send_keys.
    """
    
    def __init__(self, session_name: str = "cave"):
        """
        Args:
            session_name: Name of the tmux session running Claude Code
        """
        self.session_name = session_name
    
    # =========================================================================
    # RAW TMUX OPERATIONS
    # =========================================================================
    
    def _send_keys(self, text: str, enter: bool = True):
        """Send keystrokes to the tmux session."""
        subprocess.run(["tmux", "send-keys", "-t", self.session_name, text])
        if enter:
            subprocess.run(["tmux", "send-keys", "-t", self.session_name, "Enter"])
    
    def _capture_pane(self, lines: int = 100) -> str:
        """Capture tmux pane content."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self.session_name, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True
        )
        return result.stdout if result.returncode == 0 else ""
    
    def session_exists(self) -> bool:
        """Check if the tmux session exists."""
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.session_name],
            capture_output=True
        )
        return result.returncode == 0
    
    # =========================================================================
    # SESSION COMMANDS
    # =========================================================================
    
    def new_chat(self):
        """Start a new conversation. Equivalent to /new."""
        self._send_keys("/new")
    
    def compact(self):
        """Compact the context. Equivalent to /compact."""
        self._send_keys("/compact")
    
    def clear(self):
        """Clear the conversation. Equivalent to /clear."""
        self._send_keys("/clear")
    
    def resume(self, conversation_id: Optional[str] = None):
        """
        Resume a conversation.
        
        Args:
            conversation_id: Specific conversation to resume. 
                           If None, opens interactive picker.
        """
        if conversation_id:
            self._send_keys(f"/resume {conversation_id}")
        else:
            self._send_keys("/resume")
    
    def cost(self):
        """Show cost information. Equivalent to /cost."""
        self._send_keys("/cost")
    
    def config(self):
        """Open config. Equivalent to /config."""
        self._send_keys("/config")
    
    def help(self):
        """Show help. Equivalent to /help."""
        self._send_keys("/help")
    
    def status(self):
        """Show status. Equivalent to /status."""
        self._send_keys("/status")
    
    # =========================================================================
    # CONTEXT COMMANDS
    # =========================================================================
    
    def add_file(self, path: str):
        """Add a file to context. Equivalent to /add <path>."""
        self._send_keys(f"/add {path}")
    
    def add_url(self, url: str):
        """Add a URL to context. Equivalent to /add <url>."""
        self._send_keys(f"/add {url}")
    
    # =========================================================================
    # PROMPT COMMANDS
    # =========================================================================
    
    def send_prompt(self, prompt: str, wait_ms: int = 0):
        """
        Send a prompt to Claude Code.
        
        Args:
            prompt: The prompt text
            wait_ms: Optional wait time after sending (for multi-line prompts)
        """
        # Handle multi-line prompts by escaping newlines
        if "\n" in prompt:
            # For multi-line, we need to be careful with tmux
            lines = prompt.split("\n")
            for i, line in enumerate(lines):
                if i == len(lines) - 1:
                    self._send_keys(line, enter=True)
                else:
                    # Send line without enter, then send Shift+Enter for newline
                    self._send_keys(line, enter=False)
                    subprocess.run(["tmux", "send-keys", "-t", self.session_name, "S-Enter"])
        else:
            self._send_keys(prompt)
        
        if wait_ms > 0:
            time.sleep(wait_ms / 1000)
    
    def send_yes(self):
        """Send 'y' to confirm a prompt."""
        self._send_keys("y")
    
    def send_no(self):
        """Send 'n' to decline a prompt."""
        self._send_keys("n")
    
    def cancel(self):
        """Send Ctrl+C to cancel current operation."""
        subprocess.run(["tmux", "send-keys", "-t", self.session_name, "C-c"])
    
    def escape(self):
        """Send Escape key."""
        subprocess.run(["tmux", "send-keys", "-t", self.session_name, "Escape"])
    
    # =========================================================================
    # ACCEPT/REJECT EDITS
    # =========================================================================
    
    def accept_all(self):
        """Accept all pending edits. Sends 'a' key."""
        self._send_keys("a", enter=False)
    
    def reject_all(self):
        """Reject all pending edits. Sends 'r' key."""
        self._send_keys("r", enter=False)
    
    # =========================================================================
    # STATE QUERIES
    # =========================================================================
    
    def get_visible_content(self, lines: int = 100) -> str:
        """Get the visible content from the tmux pane."""
        return self._capture_pane(lines)
    
    def is_idle(self) -> bool:
        """
        Check if Claude Code appears to be idle (waiting for input).
        
        Looks for the prompt character (❯) at the end of the visible content.
        """
        content = self._capture_pane(10)
        lines = [l.strip() for l in content.strip().split("\n") if l.strip()]
        if not lines:
            return False
        # Look for prompt indicator in last few lines
        for line in lines[-3:]:
            if line.startswith("❯") or line == "❯":
                return True
        return False
    
    def wait_for_idle(self, timeout_seconds: int = 300, poll_interval: float = 2.0) -> bool:
        """
        Wait for Claude Code to become idle.
        
        Args:
            timeout_seconds: Maximum time to wait
            poll_interval: How often to check (seconds)
        
        Returns:
            True if became idle, False if timed out
        """
        elapsed = 0.0
        while elapsed < timeout_seconds:
            if self.is_idle():
                return True
            time.sleep(poll_interval)
            elapsed += poll_interval
        return False
    
    # =========================================================================
    # PARSED MESSAGES (using context_engineering parser)
    # =========================================================================
    
    def get_messages(self, last_n: Optional[int] = None, capture_lines: int = 500) -> List[ParsedMessage]:
        """
        Get parsed messages from the session.
        
        Uses context_engineering's parse_tmux_messages to extract structured
        messages (user/assistant/tool) from the raw tmux capture.
        
        Args:
            last_n: Only return the last N messages (None = all)
            capture_lines: How many lines of tmux history to capture
        
        Returns:
            List of ParsedMessage objects with role, content, line info
        """
        raw = self._capture_pane(capture_lines)
        messages = parse_tmux_messages(raw)
        if last_n is not None:
            return messages[-last_n:]
        return messages
    
    def get_last_assistant_message(self) -> Optional[ParsedMessage]:
        """Get the most recent assistant message."""
        messages = self.get_messages()
        for msg in reversed(messages):
            if msg.role == "assistant":
                return msg
        return None
    
    def get_last_user_message(self) -> Optional[ParsedMessage]:
        """Get the most recent user message."""
        messages = self.get_messages()
        for msg in reversed(messages):
            if msg.role == "user":
                return msg
        return None
    
    # =========================================================================
    # HIGH-LEVEL COMPOSITES
    # =========================================================================
    
    def run_prompt(
        self, 
        prompt: str, 
        wait: bool = True, 
        timeout_seconds: int = 300,
        capture: bool = True
    ) -> Optional[ParsedMessage]:
        """
        Send a prompt and optionally wait for response.
        
        This is the main composite: send → wait → capture.
        
        Args:
            prompt: The prompt to send
            wait: Whether to wait for Claude to finish
            timeout_seconds: Max wait time
            capture: Whether to capture and return the response
        
        Returns:
            The assistant's response as ParsedMessage, or None if not capturing
        """
        self.send_prompt(prompt)
        
        if wait:
            self.wait_for_idle(timeout_seconds=timeout_seconds)
        
        if capture:
            return self.get_last_assistant_message()
        
        return None
    
    # =========================================================================
    # PATTERN MATCHING
    # =========================================================================
    
    def matches_pattern(self, pattern: Union[str, re.Pattern]) -> bool:
        """
        Check if the last assistant message matches a regex pattern.
        
        Args:
            pattern: Regex pattern (string or compiled)
        
        Returns:
            True if pattern found in last assistant message
        """
        msg = self.get_last_assistant_message()
        if not msg:
            return False
        if isinstance(pattern, str):
            return bool(re.search(pattern, msg.content))
        return bool(pattern.search(msg.content))
    
    def wait_for_pattern(
        self, 
        pattern: Union[str, re.Pattern],
        timeout_seconds: int = 300,
        poll_interval: float = 2.0
    ) -> bool:
        """
        Wait until the last assistant message matches a pattern.
        
        Useful for detecting completion signals like <promise>DONE</promise>
        or blocking conditions.
        
        Args:
            pattern: Regex pattern to match
            timeout_seconds: Max time to wait
            poll_interval: How often to check
        
        Returns:
            True if pattern matched, False if timed out
        """
        elapsed = 0.0
        while elapsed < timeout_seconds:
            # First wait for idle (so we have a complete message)
            if self.is_idle() and self.matches_pattern(pattern):
                return True
            time.sleep(poll_interval)
            elapsed += poll_interval
        return False
    
    def extract_pattern(self, pattern: Union[str, re.Pattern]) -> Optional[str]:
        """
        Extract matched content from last assistant message.
        
        Args:
            pattern: Regex with capture group(s)
        
        Returns:
            First captured group, or full match if no groups, or None
        """
        msg = self.get_last_assistant_message()
        if not msg:
            return None
        if isinstance(pattern, str):
            match = re.search(pattern, msg.content)
        else:
            match = pattern.search(msg.content)
        if match:
            groups = match.groups()
            return groups[0] if groups else match.group(0)
        return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_session(name: str = "cave") -> ClaudeCodeSession:
    """Get a ClaudeCodeSession instance."""
    return ClaudeCodeSession(name)


def list_tmux_sessions() -> List[str]:
    """List all available tmux sessions."""
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip().split("\n")
    return []


def find_claude_session() -> Optional[str]:
    """Find a tmux session that likely has Claude Code running."""
    sessions = list_tmux_sessions()
    # Prefer common names
    for preferred in ["cave", "claude", "cc"]:
        if preferred in sessions:
            return preferred
    # Return first if any exist
    return sessions[0] if sessions else None
