"""
Context Engineering Library - Bridge SDK and tmux paradigms.

Unified interface for context surgery (inject, weave, dovetail)
that works across both Claude Agent SDK and tmux/Claude Code.
"""

import os
import json
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from enum import Enum


# =============================================================================
# MODELS
# =============================================================================

class TransportType(str, Enum):
    TMUX = "tmux"
    SDK = "sdk"
    AUTO = "auto"


class InjectMethod(str, Enum):
    PREPEND = "prepend"      # Prepend to prompt
    FILE = "file"            # Write to file, reference in prompt
    RULES = "rules"          # Write to .claude/rules/
    ENV = "env"              # Environment variables


@dataclass
class Session:
    """Unified session model - abstracts tmux vs SDK."""
    id: str
    transport: TransportType
    tmux_session: Optional[str] = None
    conversation_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WeaveResult:
    """Result of a weave operation."""
    source_session: str
    target_session: str
    start_index: int
    end_index: int
    content: str
    summarized: bool = False
    token_estimate: int = 0


@dataclass
class ParsedMessage:
    """A parsed message from tmux or SDK transcript."""
    index: int
    role: Literal["user", "assistant", "tool", "system"]
    content: str
    line_start: int
    line_end: int


# =============================================================================
# TMUX MESSAGE PARSING
# =============================================================================

import re
import hashlib

# Weave cache: hash(raw_output) -> List[ParsedMessage]
_WEAVE_CACHE: Dict[str, List[ParsedMessage]] = {}


def parse_tmux_messages(raw_output: str) -> List[ParsedMessage]:
    """
    Parse raw tmux capture into indexed messages.

    Identifies:
    - User prompts (lines starting with '>' or after prompt markers)
    - Claude responses (text blocks between user inputs)
    - Tool outputs (between <tool> markers or similar patterns)
    """
    # Check cache first
    cache_key = hashlib.md5(raw_output.encode()).hexdigest()
    if cache_key in _WEAVE_CACHE:
        return _WEAVE_CACHE[cache_key]

    messages = []
    lines = raw_output.split("\n")

    # Patterns for identifying message boundaries
    user_prompt_pattern = re.compile(r"^>\s*(.+)$")  # Lines starting with >
    tool_start_pattern = re.compile(r"^<tool|^\[Tool:|^⚙️")
    tool_end_pattern = re.compile(r"^</tool|^\]$|^✓|^✗")
    claude_marker = re.compile(r"^(Claude|Assistant|🤖):")

    current_role = "assistant"
    current_content = []
    current_start = 0
    msg_index = 0

    def flush_message():
        nonlocal msg_index, current_content, current_start
        if current_content:
            content = "\n".join(current_content).strip()
            if content:
                messages.append(ParsedMessage(
                    index=msg_index,
                    role=current_role,
                    content=content,
                    line_start=current_start,
                    line_end=len(messages)
                ))
                msg_index += 1
        current_content = []

    for i, line in enumerate(lines):
        # Skip empty lines at message boundaries
        stripped = line.strip()

        # Check for user input
        user_match = user_prompt_pattern.match(line)
        if user_match:
            flush_message()
            current_role = "user"
            current_start = i
            current_content = [user_match.group(1)]
            continue

        # Check for tool output markers
        if tool_start_pattern.match(stripped):
            flush_message()
            current_role = "tool"
            current_start = i
            current_content = [line]
            continue

        if current_role == "tool" and tool_end_pattern.match(stripped):
            current_content.append(line)
            flush_message()
            current_role = "assistant"
            current_start = i + 1
            continue

        # Check for Claude response marker
        if claude_marker.match(stripped):
            flush_message()
            current_role = "assistant"
            current_start = i
            current_content = [stripped]
            continue

        # Default: append to current message
        current_content.append(line)

    # Flush final message
    flush_message()

    # Cache result
    _WEAVE_CACHE[cache_key] = messages

    return messages


def clear_weave_cache():
    """Clear the weave parsing cache."""
    global _WEAVE_CACHE
    _WEAVE_CACHE = {}


# =============================================================================
# TRANSPORTS
# =============================================================================

class TmuxTransport:
    """Transport layer for tmux-based Claude Code interaction."""
    
    def __init__(self, default_session: str = "cave"):
        self.default_session = default_session
    
    def session_exists(self, name: str) -> bool:
        """Check if tmux session exists."""
        result = subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True
        )
        return result.returncode == 0
    
    def list_sessions(self) -> List[str]:
        """List all tmux sessions."""
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")
        return []
    
    def send_keys(self, session: str, text: str, enter: bool = True):
        """Send keystrokes to tmux session."""
        subprocess.run(["tmux", "send-keys", "-t", session, text])
        if enter:
            subprocess.run(["tmux", "send-keys", "-t", session, "Enter"])
    
    def capture_pane(self, session: str, lines: int = 1000) -> str:
        """Capture tmux pane content."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", session, "-p", "-S", f"-{lines}"],
            capture_output=True, text=True
        )
        return result.stdout if result.returncode == 0 else ""
    
    def get_active_session(self) -> Optional[str]:
        """Get currently active tmux session."""
        for name in ["cave", "claude"]:
            if self.session_exists(name):
                return name
        sessions = self.list_sessions()
        return sessions[0] if sessions else None


class SDKTransport:
    """Transport layer for Claude Agent SDK interaction."""
    
    def __init__(self):
        self._sdk_available = None
    
    @property
    def sdk_available(self) -> bool:
        if self._sdk_available is None:
            try:
                from claude_agent_sdk import query
                self._sdk_available = True
            except ImportError:
                self._sdk_available = False
        return self._sdk_available
    
    def send(self, prompt: str, config: Dict[str, Any] = None) -> Dict:
        """Send prompt via SDK."""
        if not self.sdk_available:
            raise RuntimeError("Claude Agent SDK not available")
        
        from claude_agent_sdk import query, ClaudeAgentOptions
        
        options = ClaudeAgentOptions(**(config or {}))
        result = query(prompt, options)
        return {"response": result}
    
    def get_conversation_id(self) -> Optional[str]:
        """Get current conversation ID from session file."""
        session_file = Path("/tmp/current_claude_session_id")
        if session_file.exists():
            return session_file.read_text().strip()
        return None


# =============================================================================
# MAIN LIBRARY
# =============================================================================

class ContextEngineeringLib:
    """
    Bridge SDK and tmux - callers don't care which transport.
    
    Usage:
        lib = ContextEngineeringLib()  # auto-detect
        session = lib.get_active_session()
        lib.inject(session, {"key": "value"})
        lib.send(session, "Do the thing")
    """
    
    STATE_DIR = Path("/tmp/context_engineering")
    
    def __init__(self, transport: TransportType = TransportType.AUTO):
        self.requested_transport = transport
        self._transport_type = None
        self._tmux = TmuxTransport()
        self._sdk = SDKTransport()
        
        # Ensure state directory exists
        self.STATE_DIR.mkdir(parents=True, exist_ok=True)
    
    @property
    def transport_type(self) -> TransportType:
        """Get resolved transport type."""
        if self._transport_type is None:
            self._transport_type = self._detect_transport()
        return self._transport_type
    
    def _detect_transport(self) -> TransportType:
        """Auto-detect best available transport."""
        if self.requested_transport != TransportType.AUTO:
            return self.requested_transport
        
        # Prefer tmux if available (most common for Claude Code)
        if self._tmux.get_active_session():
            return TransportType.TMUX
        
        # Fall back to SDK
        if self._sdk.sdk_available:
            return TransportType.SDK
        
        # Default to tmux
        return TransportType.TMUX
    
    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================
    
    def list_sessions(self) -> List[Session]:
        """List all available sessions."""
        sessions = []
        
        # Tmux sessions
        for name in self._tmux.list_sessions():
            sessions.append(Session(
                id=f"tmux:{name}",
                transport=TransportType.TMUX,
                tmux_session=name
            ))
        
        # SDK session (if available)
        conv_id = self._sdk.get_conversation_id()
        if conv_id:
            sessions.append(Session(
                id=f"sdk:{conv_id}",
                transport=TransportType.SDK,
                conversation_id=conv_id
            ))
        
        return sessions
    
    def get_active_session(self) -> Optional[Session]:
        """Get the currently active session."""
        if self.transport_type == TransportType.TMUX:
            name = self._tmux.get_active_session()
            if name:
                return Session(
                    id=f"tmux:{name}",
                    transport=TransportType.TMUX,
                    tmux_session=name
                )
        else:
            conv_id = self._sdk.get_conversation_id()
            if conv_id:
                return Session(
                    id=f"sdk:{conv_id}",
                    transport=TransportType.SDK,
                    conversation_id=conv_id
                )
        return None
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID."""
        for session in self.list_sessions():
            if session.id == session_id:
                return session
        return None
    
    # =========================================================================
    # CONTEXT SURGERY
    # =========================================================================
    
    def inject(
        self,
        session: Session,
        context: Dict[str, Any],
        method: InjectMethod = InjectMethod.PREPEND,
        inject_as: Optional[str] = None
    ) -> bool:
        """
        Inject context into a session.

        Args:
            session: Target session
            context: Context dict to inject
            method: How to inject (prepend, file, rules, env)
            inject_as: Name for the injection (used for file/rules naming)

        Returns:
            True if successful
        """
        try:
            if method == InjectMethod.PREPEND:
                return self._inject_prepend(session, context)
            elif method == InjectMethod.FILE:
                return self._inject_file(session, context, inject_as)
            elif method == InjectMethod.RULES:
                return self._inject_rules(session, context, inject_as)
            elif method == InjectMethod.ENV:
                return self._inject_env(session, context)
            else:
                raise ValueError(f"Unknown inject method: {method}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Injection failed: {e}")
            return False

    def _format_context(self, context: Dict[str, Any]) -> str:
        """Format context dict as readable text for injection."""
        lines = ["<injected-context>"]
        for key, value in context.items():
            if isinstance(value, dict):
                lines.append(f"## {key}")
                for k, v in value.items():
                    lines.append(f"- {k}: {v}")
            elif isinstance(value, list):
                lines.append(f"## {key}")
                for item in value:
                    lines.append(f"- {item}")
            else:
                lines.append(f"## {key}")
                lines.append(str(value))
        lines.append("</injected-context>")
        return "\n".join(lines)

    def _inject_prepend(self, session: Session, context: Dict[str, Any]) -> bool:
        """
        PREPEND method: Store context in session state for next send().

        The context will be prepended to the next prompt automatically.
        """
        state = self.get_session_state(session)

        # Store pending injection
        pending = state.get("pending_injections", [])
        pending.append({
            "context": context,
            "formatted": self._format_context(context),
            "timestamp": datetime.now().isoformat()
        })
        state["pending_injections"] = pending

        self.save_session_state(session, state)
        return True

    def _inject_file(
        self,
        session: Session,
        context: Dict[str, Any],
        inject_as: Optional[str] = None
    ) -> bool:
        """
        FILE method: Write context to temp file, store path for reference.

        Returns the file path that can be referenced in prompts.
        """
        injected_dir = self.STATE_DIR / "injected"
        injected_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        name = inject_as or f"context_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        file_path = injected_dir / f"{name}.md"

        # Write formatted context
        content = self._format_context(context)
        file_path.write_text(content)

        # Store reference in session state
        state = self.get_session_state(session)
        injected_files = state.get("injected_files", {})
        injected_files[name] = {
            "path": str(file_path),
            "timestamp": datetime.now().isoformat()
        }
        state["injected_files"] = injected_files
        self.save_session_state(session, state)

        return True

    def get_injected_file_path(self, session: Session, name: str) -> Optional[str]:
        """Get path to an injected file by name."""
        state = self.get_session_state(session)
        injected_files = state.get("injected_files", {})
        if name in injected_files:
            return injected_files[name]["path"]
        return None

    def _inject_rules(
        self,
        session: Session,
        context: Dict[str, Any],
        inject_as: Optional[str] = None
    ) -> bool:
        """
        RULES method: Write context to .claude/rules/ for auto-injection.

        Claude Code automatically injects rules based on file operations.
        """
        rules_dir = Path.home() / ".claude" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)

        name = inject_as or f"injected_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        rule_file = rules_dir / f"{name}.md"

        # Format as rule with optional path scoping
        lines = []

        # Check if context specifies path patterns
        paths = context.pop("_paths", None)
        if paths:
            lines.append("---")
            lines.append("paths:")
            for p in paths:
                lines.append(f'  - "{p}"')
            lines.append("---")
            lines.append("")

        lines.append(f"# {name}")
        lines.append("")
        lines.append(self._format_context(context))

        rule_file.write_text("\n".join(lines))

        # Track in session state
        state = self.get_session_state(session)
        injected_rules = state.get("injected_rules", {})
        injected_rules[name] = {
            "path": str(rule_file),
            "timestamp": datetime.now().isoformat()
        }
        state["injected_rules"] = injected_rules
        self.save_session_state(session, state)

        return True

    def _inject_env(self, session: Session, context: Dict[str, Any]) -> bool:
        """
        ENV method: Set environment variables.

        For SDK: Sets os.environ directly.
        For tmux: Stores commands to prepend 'export VAR=val &&' to next send.
        """
        if session.transport == TransportType.SDK:
            # Direct env var setting for SDK
            for key, value in context.items():
                os.environ[key] = str(value)
        else:
            # For tmux, store export commands for next send
            state = self.get_session_state(session)
            env_exports = state.get("pending_env_exports", {})
            env_exports.update(context)
            state["pending_env_exports"] = env_exports
            self.save_session_state(session, state)

        return True

    def get_pending_injections(self, session: Session) -> List[Dict[str, Any]]:
        """Get and clear pending injections for a session."""
        state = self.get_session_state(session)
        pending = state.pop("pending_injections", [])
        self.save_session_state(session, state)
        return pending

    def get_pending_env_exports(self, session: Session) -> Dict[str, Any]:
        """Get and clear pending env exports for a session."""
        state = self.get_session_state(session)
        exports = state.pop("pending_env_exports", {})
        self.save_session_state(session, state)
        return exports
    
    def weave(
        self,
        source: Session,
        target: Session,
        start: int,
        end: int,
        summarize: bool = False
    ) -> WeaveResult:
        """
        Weave message range from source to target session.

        Args:
            source: Source session to pull from
            target: Target session to inject into
            start: Start message index (0-based, negative = from end)
            end: End message index (0-based, negative = from end)
            summarize: Whether to summarize content first

        Returns:
            WeaveResult with extracted content
        """
        # Get messages from source
        if source.transport == TransportType.TMUX:
            raw = self._tmux.capture_pane(source.tmux_session)
            messages = parse_tmux_messages(raw)
        else:
            # SDK: read from conversation transcript
            messages = self._get_sdk_messages(source)

        # Handle negative indices
        if start < 0:
            start = max(0, len(messages) + start)
        if end < 0:
            end = len(messages) + end

        # Extract message range
        selected = messages[start:end]
        content = "\n\n---\n\n".join(m.content for m in selected)

        # Optionally summarize
        if summarize:
            content = self._summarize_content(content)

        # Estimate tokens (rough: ~4 chars per token)
        token_estimate = len(content) // 4

        result = WeaveResult(
            source_session=source.id,
            target_session=target.id,
            start_index=start,
            end_index=end,
            content=content,
            summarized=summarize,
            token_estimate=token_estimate
        )

        # Auto-inject into target as prepend
        self.inject(target, {"woven_context": content}, InjectMethod.PREPEND)

        return result

    def _get_sdk_messages(self, session: Session) -> List['ParsedMessage']:
        """Get messages from SDK session transcript."""
        # Try to read from SDNA transcript files
        transcript_dir = Path("/tmp/sdna_transcripts")
        if session.conversation_id and transcript_dir.exists():
            transcript_file = transcript_dir / f"{session.conversation_id}.json"
            if transcript_file.exists():
                data = json.loads(transcript_file.read_text())
                messages = []
                for i, msg in enumerate(data.get("messages", [])):
                    messages.append(ParsedMessage(
                        index=i,
                        role=msg.get("role", "unknown"),
                        content=msg.get("content", ""),
                        line_start=0,
                        line_end=0
                    ))
                return messages

        # Fallback: empty list
        return []

    def _summarize_content(self, content: str) -> str:
        """Summarize content using a lightweight approach."""
        # For now, just truncate intelligently
        # In production, could use Haiku for actual summarization
        max_chars = 4000
        if len(content) <= max_chars:
            return content

        # Take first and last portions
        first_part = content[:max_chars // 2]
        last_part = content[-(max_chars // 2):]
        return f"{first_part}\n\n[... content truncated ...]\n\n{last_part}"
    
    def dovetail(
        self,
        sessions: List[Session],
        strategy: str = "merge"
    ) -> Dict[str, Any]:
        """
        Dovetail multiple sessions together.

        Args:
            sessions: Sessions to dovetail
            strategy: How to combine:
                - "merge": Combine all state into one dict (later overwrites earlier)
                - "chain": Sequential context from each session
                - "parallel": Separate namespaced contexts per session

        Returns:
            Combined context dict
        """
        if strategy == "merge":
            combined = {}
            for session in sessions:
                state = self.get_session_state(session)
                combined.update(state)
            return combined

        elif strategy == "chain":
            # Sequential: each session's context in order
            chain = []
            for session in sessions:
                state = self.get_session_state(session)
                if state:
                    chain.append({
                        "session_id": session.id,
                        "state": state
                    })
            return {"chained_contexts": chain}

        elif strategy == "parallel":
            # Namespaced: each session gets its own namespace
            parallel = {}
            for session in sessions:
                # Create safe namespace key from session ID
                namespace = session.id.replace(":", "_").replace("/", "_")
                parallel[namespace] = self.get_session_state(session)
            return {"namespaced_contexts": parallel}

        else:
            raise ValueError(f"Unknown dovetail strategy: {strategy}")
    
    # =========================================================================
    # PROMPT EXECUTION
    # =========================================================================
    
    def send(
        self,
        session: Session,
        prompt: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send prompt to session with optional context injection.

        Args:
            session: Target session
            prompt: Prompt text
            context: Optional context to inject first

        Returns:
            Result dict (transport-specific)
        """
        # Inject context if provided (adds to pending)
        if context:
            self.inject(session, context, method=InjectMethod.PREPEND)

        # Build final prompt with pending injections
        final_prompt = self._build_prompt_with_injections(session, prompt)

        # Send via appropriate transport
        if session.transport == TransportType.TMUX:
            # Handle pending env exports for tmux
            env_exports = self.get_pending_env_exports(session)
            if env_exports:
                export_cmd = " && ".join(f"export {k}={v}" for k, v in env_exports.items())
                final_prompt = f"{export_cmd} && {final_prompt}"

            self._tmux.send_keys(session.tmux_session, final_prompt)
            return {"sent": True, "transport": "tmux", "prompt_length": len(final_prompt)}
        else:
            return self._sdk.send(final_prompt)

    def _build_prompt_with_injections(self, session: Session, prompt: str) -> str:
        """Build prompt with any pending prepend injections."""
        pending = self.get_pending_injections(session)
        if not pending:
            return prompt

        # Prepend all pending context
        parts = []
        for injection in pending:
            parts.append(injection["formatted"])
        parts.append("")
        parts.append(prompt)

        return "\n".join(parts)
    
    def send_chain(self, session: Session, chain: Any) -> Dict[str, Any]:
        """
        Execute an Ariadne chain in a session.
        
        Args:
            session: Target session
            chain: Ariadne chain to execute
        
        Returns:
            Chain execution result
        """
        # TODO: Integrate with Ariadne
        raise NotImplementedError("send_chain() not yet implemented")
    
    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================
    
    def get_session_state(self, session: Session) -> Dict[str, Any]:
        """Get persisted state for a session."""
        state_file = self.STATE_DIR / "state" / f"{session.id.replace(':', '_')}.json"
        if state_file.exists():
            return json.loads(state_file.read_text())
        return {}
    
    def save_session_state(self, session: Session, state: Dict[str, Any]):
        """Save state for a session."""
        state_dir = self.STATE_DIR / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / f"{session.id.replace(':', '_')}.json"
        state_file.write_text(json.dumps(state, indent=2))


# =============================================================================
# CONVENIENCE FUNCTIONS (for Ariadne integration)
# =============================================================================

_lib: Optional[ContextEngineeringLib] = None

def get_lib() -> ContextEngineeringLib:
    """Get singleton lib instance."""
    global _lib
    if _lib is None:
        _lib = ContextEngineeringLib()
    return _lib


def inject_context(context: Dict[str, Any], method: str = "prepend") -> bool:
    """Inject context into active session."""
    lib = get_lib()
    session = lib.get_active_session()
    if session:
        return lib.inject(session, context, InjectMethod(method))
    return False


def weave_context(source_id: str, start: int, end: int) -> Optional[str]:
    """Weave content from another session."""
    lib = get_lib()
    source = lib.get_session(source_id)
    target = lib.get_active_session()
    if source and target:
        result = lib.weave(source, target, start, end)
        return result.content
    return None
