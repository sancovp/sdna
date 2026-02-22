"""Slinky Context Manager - Background rollup module for CaveAgent memory.

Replaces Claude Code's compaction entirely. Runs as continuous background process
watching context and triggering compression at task boundaries in GIINT projects.

📦=Unpackable CartON Ref

Architecture:
- SlinkyWatcher: Monitors session file for changes
- SlinkyRollup: Applies hierarchical compression (L1/L2/L3)
- GiintIntegration: Triggers on task completion events
- CartonBridge: Refs point to existing Carton content

Flow:
1. GIINT project task/goal completes
2. SlinkyWatcher detects boundary
3. SlinkyRollup compresses completed work
4. Session shrinks, Carton refs remain
5. Agent continues with freed context
"""
import json
import os
import time
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from threading import Thread, Event
import logging

logger = logging.getLogger(__name__)


@dataclass
class CompressionEvent:
    """Record of a compression action."""
    timestamp: str
    trigger: str  # "task_complete", "token_threshold", "manual"
    iterations_compressed: int
    chars_before: int
    chars_after: int
    level: str  # "L1", "L2", "L3"
    giint_project: Optional[str] = None
    task_id: Optional[str] = None


@dataclass 
class SlinkyState:
    """Current state of the Slinky system."""
    session_path: Path
    last_modified: float = 0
    total_compressions: int = 0
    chars_saved_total: int = 0
    current_context_chars: int = 0
    compression_history: List[CompressionEvent] = field(default_factory=list)


class SlinkyRollup:
    """Apply hierarchical compression to session."""
    
    def __init__(
        self, 
        summarizer: Optional[Callable[[str], str]] = None,
        l1_summary_tokens: int = 100,
        l2_summary_tokens: int = 200,
        l3_summary_tokens: int = 100
    ):
        self.summarizer = summarizer or self._mock_summarizer
        self.l1_tokens = l1_summary_tokens
        self.l2_tokens = l2_summary_tokens
        self.l3_tokens = l3_summary_tokens
    
    def _mock_summarizer(self, content: str, max_chars: int = 400) -> str:
        """Mock summarizer - replace with LLM call."""
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "..."
    
    def compress_iteration(
        self,
        lines: List[str],
        iteration_lines: List[int],
        iter_num: int,
        timestamp: str,
        level: str = "L1",
        summary: Optional[str] = None
    ) -> Dict[int, str]:
        """Compress a single iteration to refs + summary.
        
        Args:
            lines: All session lines
            iteration_lines: Line numbers in this iteration
            iter_num: Iteration number
            timestamp: Timestamp for ref
            level: Compression level (L1, L2, L3)
            summary: Optional summary from GIINT task. If None, uses mock.
        
        Returns: dict mapping line_num -> new_line_content
        """
        modifications = {}
        
        for idx, line_num in enumerate(iteration_lines):
            try:
                line = lines[line_num].strip()
                data = json.loads(line)
                msg_type = data.get("type")
                
                if msg_type not in ("user", "assistant"):
                    continue
                
                # First message gets summary, rest get refs
                if idx == 0:
                    ref = f"[📦 {level}_{iter_num}_{timestamp}]"
                    iter_summary = summary or f"Iteration {iter_num}: work completed"
                    replacement = f"{ref} {iter_summary}"
                else:
                    prefix = "A" if msg_type == "assistant" else "M"
                    replacement = f"[📦 {prefix}_{iter_num}_{idx}]"
                
                # Replace content
                new_data = self._replace_content(data, replacement)
                modifications[line_num] = json.dumps(new_data)
                
            except json.JSONDecodeError:
                continue
        
        return modifications
    
    def _replace_content(self, data: Dict, replacement: str) -> Dict:
        """Replace all text content in message."""
        data = json.loads(json.dumps(data))  # Deep copy
        message = data.get("message", {})
        content = message.get("content")
        
        if data.get("type") == "user":
            if isinstance(content, str):
                message["content"] = replacement
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            item["text"] = replacement
                        elif item.get("type") == "tool_result":
                            item["content"] = replacement
        
        elif data.get("type") == "assistant":
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            item["text"] = replacement
                        elif item.get("type") == "thinking":
                            item["thinking"] = replacement
                        elif item.get("type") == "tool_use":
                            item["input"] = {"ref": replacement}
        
        return data


class GiintIntegration:
    """Integration with GIINT project system for compression boundaries.
    
    GIINT Structure:
        Project → Features → Components → Deliverables → Tasks
        
    Compression triggers on:
    1. Manual signal (touch ~/.slinky_compress) - shortest cadence
    2. Deliverable complete (all tasks in a deliverable DONE) - natural checkpoint
    3. Token threshold exceeded - fallback safety net
    
    Deliverable metadata aggregates all task insights.
    """
    
    def __init__(
        self, 
        registry_path: Optional[Path] = None,
        poll_interval: float = 2.0,
        signal_file: Optional[Path] = None
    ):
        # Default to LLM_INTELLIGENCE_DIR/projects.json
        if registry_path:
            self.registry_path = Path(registry_path)
        else:
            base_dir = Path(os.environ.get(
                "LLM_INTELLIGENCE_DIR", 
                "/tmp/llm_intelligence_responses"
            ))
            self.registry_path = base_dir / "projects.json"
        
        # Manual signal file
        self.signal_file = signal_file or Path.home() / ".slinky_compress"
        
        self.poll_interval = poll_interval
        self.completed_units: List[Dict[str, Any]] = []
        # Track completed deliverables (not tasks or components)
        self._completed_deliverables: Dict[str, set] = {}  # project_id -> set of deliverable paths
        self._load_initial_state()
    
    def _load_initial_state(self) -> None:
        """Load initial state of completed deliverables."""
        if not self.registry_path.exists():
            return
        
        try:
            with open(self.registry_path, 'r') as f:
                projects = json.load(f)
            
            for project_id, project in projects.items():
                completed_dels = set()
                
                for feat_name, feature in project.get("features", {}).items():
                    for comp_name, component in feature.get("components", {}).items():
                        for del_name, deliverable in component.get("deliverables", {}).items():
                            del_path = f"{feat_name}/{comp_name}/{del_name}"
                            
                            if self._is_deliverable_complete(deliverable):
                                completed_dels.add(del_path)
                
                self._completed_deliverables[project_id] = completed_dels
                
        except Exception as e:
            logger.warning(f"Failed to load GIINT initial state: {e}")
    
    def _is_deliverable_complete(self, deliverable: Dict) -> bool:
        """Check if all tasks in a deliverable are done."""
        tasks = deliverable.get("tasks", {})
        if not tasks:
            return False  # Must have at least one task
        return all(
            task.get("status") == "done" 
            for task in tasks.values()
        )
    
    def check_compression_trigger(self) -> Optional[Dict[str, Any]]:
        """Check if compression should trigger.
        
        Returns trigger info if:
        1. Manual signal file exists
        2. A deliverable newly completed
        
        Returns None otherwise.
        """
        # Check manual signal first (highest priority, shortest cadence)
        if self.signal_file.exists():
            try:
                self.signal_file.unlink()  # Remove signal
                return {
                    "trigger_type": "manual",
                    "timestamp": datetime.now().isoformat(),
                    "key_insight": "Manual compression signal"
                }
            except:
                pass
        
        if not self.registry_path.exists():
            return None
        
        try:
            with open(self.registry_path, 'r') as f:
                projects = json.load(f)
            
            for project_id, project in projects.items():
                prev_dels = self._completed_deliverables.get(project_id, set())
                current_dels = set()
                
                for feat_name, feature in project.get("features", {}).items():
                    for comp_name, component in feature.get("components", {}).items():
                        for del_name, deliverable in component.get("deliverables", {}).items():
                            del_path = f"{feat_name}/{comp_name}/{del_name}"
                            
                            if self._is_deliverable_complete(deliverable):
                                current_dels.add(del_path)
                                
                                # NEW deliverable completion!
                                if del_path not in prev_dels:
                                    # Aggregate task metadata
                                    insights, files = self._aggregate_deliverable_metadata(deliverable)
                                    
                                    self._completed_deliverables[project_id] = current_dels
                                    
                                    return {
                                        "trigger_type": "deliverable_complete",
                                        "project_id": project_id,
                                        "feature": feat_name,
                                        "component": comp_name,
                                        "deliverable": del_name,
                                        "deliverable_path": del_path,
                                        "key_insight": " | ".join(insights) if insights else f"Deliverable '{del_name}' complete",
                                        "files_touched": files,
                                        "timestamp": datetime.now().isoformat()
                                    }
                
                self._completed_deliverables[project_id] = current_dels
            
            return None
            
        except Exception as e:
            logger.warning(f"Failed to check GIINT completions: {e}")
            return None
    
    def _aggregate_deliverable_metadata(self, deliverable: Dict) -> tuple:
        """Aggregate metadata from all tasks in a deliverable."""
        insights = []
        files = []
        
        for task in deliverable.get("tasks", {}).values():
            if task.get("key_insight"):
                insights.append(task["key_insight"])
            if task.get("files_touched"):
                files.extend(task["files_touched"])
        
        return insights, list(set(files))  # Dedupe files
    
    def register_completion(self, trigger_info: Dict[str, Any]) -> None:
        """Register that a compression triggered (for history)."""
        self.completed_units.append(trigger_info)
    
    def build_summary_from_trigger(self, trigger_info: Dict[str, Any]) -> str:
        """Build compression summary from trigger metadata."""
        parts = []
        
        trigger_type = trigger_info.get("trigger_type", "unknown")
        
        if trigger_type == "manual":
            parts.append("Manual compression")
        elif trigger_type == "deliverable_complete":
            del_name = trigger_info.get("deliverable", "unknown")
            comp_name = trigger_info.get("component", "")
            if comp_name:
                parts.append(f"'{comp_name}/{del_name}' complete")
            else:
                parts.append(f"Deliverable '{del_name}' complete")
        
        # Add key insight
        if trigger_info.get("key_insight") and trigger_type != "manual":
            parts.append(trigger_info["key_insight"])
        
        # Add files touched (limited)
        files = trigger_info.get("files_touched", [])
        if files:
            if len(files) <= 3:
                parts.append(f"Files: {', '.join(files)}")
            else:
                parts.append(f"Files: {', '.join(files[:3])} +{len(files)-3} more")
        
        return " | ".join(parts)


class SlinkyWatcher:
    """Watch session file and trigger compression at boundaries."""
    
    def __init__(
        self,
        session_path: Path,
        giint: Optional[GiintIntegration] = None,
        token_threshold: int = 150000,
        check_interval: float = 5.0
    ):
        self.session_path = Path(session_path)
        self.giint = giint or GiintIntegration()
        self.rollup = SlinkyRollup()
        self.state = SlinkyState(session_path=session_path)
        self.token_threshold = token_threshold
        self.check_interval = check_interval
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
    
    def start(self) -> None:
        """Start background watcher thread."""
        self._stop_event.clear()
        self._thread = Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info(f"Slinky watcher started for {self.session_path}")
    
    def stop(self) -> None:
        """Stop background watcher."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Slinky watcher stopped")
    
    def _watch_loop(self) -> None:
        """Main watch loop."""
        while not self._stop_event.is_set():
            try:
                self._check_and_compress()
            except Exception as e:
                logger.error(f"Slinky watch error: {e}")
            
            self._stop_event.wait(self.check_interval)
    
    def _check_and_compress(self) -> None:
        """Check if compression needed and apply."""
        if not self.session_path.exists():
            return
        
        # Check for file changes
        mtime = self.session_path.stat().st_mtime
        if mtime == self.state.last_modified:
            return
        
        self.state.last_modified = mtime
        
        # Read current session
        with open(self.session_path, 'r') as f:
            lines = f.readlines()
        
        # Calculate current context size
        context_chars = self._count_context_chars(lines)
        self.state.current_context_chars = context_chars
        context_tokens = context_chars // 4
        
        # Check triggers
        should_compress = False
        trigger = ""
        trigger_info = None
        
        # Trigger 1: GIINT component/feature completed or manual signal
        trigger_info = self.giint.check_compression_trigger()
        if trigger_info:
            should_compress = True
            trigger = trigger_info.get("trigger_type", "giint")
        
        # Trigger 2: Token threshold exceeded
        elif context_tokens > self.token_threshold:
            should_compress = True
            trigger = "token_threshold"
        
        if should_compress:
            self._apply_compression(lines, trigger, trigger_info)
    
    def _count_context_chars(self, lines: List[str]) -> int:
        """Count chars that go to Claude context."""
        total = 0
        for line in lines:
            try:
                data = json.loads(line)
                if data.get("type") not in ("user", "assistant"):
                    continue
                
                message = data.get("message", {})
                content = message.get("content")
                
                if isinstance(content, str):
                    total += len(content)
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            if "text" in item:
                                total += len(item["text"])
                            if "thinking" in item:
                                total += len(item["thinking"])
                            if "content" in item:
                                c = item["content"]
                                total += len(c) if isinstance(c, str) else 0
                            if "input" in item:
                                total += len(json.dumps(item["input"]))
            except:
                pass
        return total
    
    def _apply_compression(
        self,
        lines: List[str],
        trigger: str,
        task_info: Optional[Dict] = None
    ) -> None:
        """Apply compression to session."""
        before_chars = self._count_context_chars(lines)
        
        # Identify iterations
        iterations = self._identify_iterations(lines)
        if not iterations:
            return
        
        # Compress all but last 2 iterations
        to_compress = iterations[:-2] if len(iterations) > 2 else []
        if not to_compress:
            return
        
        # Apply modifications
        all_mods = {}
        ts = datetime.now().strftime("%Y%m%d_%H")
        
        # Build summary from GIINT trigger if available
        giint_summary = None
        if task_info:
            giint_summary = self.giint.build_summary_from_trigger(task_info)
            self.giint.register_completion(task_info)
        
        for iteration in to_compress:
            mods = self.rollup.compress_iteration(
                lines,
                iteration["lines"],
                iteration["number"],
                ts,
                summary=giint_summary  # Use GIINT insight as summary
            )
            all_mods.update(mods)
        
        # Write modified session
        with open(self.session_path, 'w') as f:
            for i, line in enumerate(lines):
                if i in all_mods:
                    f.write(all_mods[i] + "\n")
                else:
                    f.write(line if line.endswith("\n") else line + "\n")
        
        # Update state
        after_chars = before_chars - sum(
            len(lines[i]) - len(all_mods[i]) for i in all_mods
        )
        
        event = CompressionEvent(
            timestamp=datetime.now().isoformat(),
            trigger=trigger,
            iterations_compressed=len(to_compress),
            chars_before=before_chars,
            chars_after=after_chars,
            level="L1",
            giint_project=task_info.get("project") if task_info else None,
            task_id=task_info.get("task_id") if task_info else None
        )
        
        self.state.compression_history.append(event)
        self.state.total_compressions += 1
        self.state.chars_saved_total += (before_chars - after_chars)
        
        logger.info(
            f"Slinky compressed {len(to_compress)} iterations, "
            f"saved {before_chars - after_chars:,} chars ({trigger})"
        )
    
    def _identify_iterations(self, lines: List[str]) -> List[Dict]:
        """Identify iterations in session."""
        iterations = []
        current = None
        iter_num = 0
        
        for i, line in enumerate(lines):
            try:
                data = json.loads(line)
                msg_type = data.get("type")
                
                if msg_type == "user":
                    message = data.get("message", {})
                    content = message.get("content")
                    is_meta = data.get("isMeta", False)
                    
                    is_new = False
                    if not is_meta:
                        if isinstance(content, str) and not content.startswith("<command"):
                            is_new = True
                        elif isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    is_new = True
                                    break
                    
                    if is_new:
                        if current:
                            iterations.append(current)
                        iter_num += 1
                        current = {"number": iter_num, "lines": [i]}
                    elif current:
                        current["lines"].append(i)
                
                elif msg_type == "assistant" and current:
                    current["lines"].append(i)
                    
            except:
                pass
        
        if current:
            iterations.append(current)
        
        return iterations
    
    def get_status(self) -> Dict[str, Any]:
        """Get current Slinky status."""
        return {
            "session": str(self.session_path),
            "current_tokens": self.state.current_context_chars // 4,
            "threshold_tokens": self.token_threshold,
            "total_compressions": self.state.total_compressions,
            "chars_saved_total": self.state.chars_saved_total,
            "tokens_saved_total": self.state.chars_saved_total // 4,
            "history": [
                {
                    "time": e.timestamp,
                    "trigger": e.trigger,
                    "iterations": e.iterations_compressed,
                    "saved": e.chars_before - e.chars_after
                }
                for e in self.state.compression_history[-10:]
            ]
        }


# Singleton for easy access
_slinky_instance: Optional[SlinkyWatcher] = None


def start_slinky(session_path: str, token_threshold: int = 150000) -> SlinkyWatcher:
    """Start Slinky context manager for a session."""
    global _slinky_instance
    
    if _slinky_instance:
        _slinky_instance.stop()
    
    _slinky_instance = SlinkyWatcher(
        session_path=Path(session_path),
        token_threshold=token_threshold
    )
    _slinky_instance.start()
    return _slinky_instance


def stop_slinky() -> None:
    """Stop Slinky context manager."""
    global _slinky_instance
    if _slinky_instance:
        _slinky_instance.stop()
        _slinky_instance = None


def get_slinky_status() -> Dict[str, Any]:
    """Get current Slinky status."""
    if _slinky_instance:
        return _slinky_instance.get_status()
    return {"status": "not running"}


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python slinky_manager.py <session.jsonl> [--threshold N]")
        sys.exit(1)
    
    session = sys.argv[1]
    threshold = 150000
    
    for i, arg in enumerate(sys.argv):
        if arg == "--threshold" and i + 1 < len(sys.argv):
            threshold = int(sys.argv[i + 1])
    
    print(f"🗜️ SLINKY CONTEXT MANAGER")
    print(f"📦=Unpackable CartON Ref")
    print(f"Session: {session}")
    print(f"Threshold: {threshold:,} tokens")
    print()
    
    watcher = start_slinky(session, threshold)
    
    print("Running... Press Ctrl+C to stop")
    try:
        while True:
            time.sleep(10)
            status = get_slinky_status()
            print(f"Context: {status['current_tokens']:,} tokens, "
                  f"Compressions: {status['total_compressions']}, "
                  f"Saved: {status['tokens_saved_total']:,} tokens")
    except KeyboardInterrupt:
        stop_slinky()
        print("\nStopped.")
