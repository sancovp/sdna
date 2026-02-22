"""Slinky Context - Hierarchical context compression for Claude Code sessions.

The session is a VIEW into the KG, not the source of truth.
Full content lives in Carton. Session content gets replaced with refs + summaries.

Session format:
- User messages: message.content = string OR [{"type": "tool_result", "content": [{"type": "text", "text": "..."}]}]
- Assistant messages: message.content = [{"type": "text", "text": "..."}, {"type": "thinking", "thinking": "..."}]

We replace the TEXT content, not the structure.
"""
import json
import hashlib
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Callable
from datetime import datetime


@dataclass
class ContentLocation:
    """Location of replaceable content in a message."""
    line_number: int
    path: List[str]  # JSON path to content, e.g. ["message", "content", 0, "text"]
    content: str
    content_type: str  # "text", "thinking", "tool_result"
    char_count: int
    
    @property
    def token_estimate(self) -> int:
        return self.char_count // 4


@dataclass
class CompressionResult:
    """Result of compressing a session."""
    original_chars: int
    compressed_chars: int
    locations_processed: int
    carton_refs_created: int
    
    @property
    def compression_ratio(self) -> float:
        if self.compressed_chars == 0:
            return float('inf')
        return self.original_chars / self.compressed_chars
    
    @property
    def chars_saved(self) -> int:
        return self.original_chars - self.compressed_chars


class SessionScanner:
    """Scan session for all replaceable content."""
    
    def __init__(self, session_path: Path):
        self.session_path = Path(session_path)
        self.lines: List[str] = []
        
    def load(self) -> None:
        with open(self.session_path, 'r', encoding='utf-8') as f:
            self.lines = f.readlines()
    
    def find_all_content(self, min_chars: int = 100) -> List[ContentLocation]:
        """Find all replaceable content locations above minimum size."""
        if not self.lines:
            self.load()
            
        locations = []
        
        for line_num, line in enumerate(self.lines):
            line = line.strip()
            if not line:
                continue
                
            try:
                data = json.loads(line)
                msg_type = data.get("type")
                
                if msg_type == "user":
                    locations.extend(self._scan_user_message(line_num, data, min_chars))
                elif msg_type == "assistant":
                    locations.extend(self._scan_assistant_message(line_num, data, min_chars))
                    
            except json.JSONDecodeError:
                continue
                
        return locations
    
    def _scan_user_message(self, line_num: int, data: dict, min_chars: int) -> List[ContentLocation]:
        """Scan user message for content."""
        locations = []
        message = data.get("message", {})
        content = message.get("content")
        
        # String content (simple user message)
        if isinstance(content, str) and len(content) >= min_chars:
            locations.append(ContentLocation(
                line_number=line_num,
                path=["message", "content"],
                content=content,
                content_type="text",
                char_count=len(content)
            ))
        
        # Array content (tool results, etc.)
        elif isinstance(content, list):
            for i, item in enumerate(content):
                if not isinstance(item, dict):
                    continue
                    
                item_type = item.get("type")
                
                if item_type == "tool_result":
                    # Tool result content can be string or array
                    result_content = item.get("content")
                    
                    if isinstance(result_content, str) and len(result_content) >= min_chars:
                        locations.append(ContentLocation(
                            line_number=line_num,
                            path=["message", "content", i, "content"],
                            content=result_content,
                            content_type="tool_result",
                            char_count=len(result_content)
                        ))
                    elif isinstance(result_content, list):
                        for j, sub_item in enumerate(result_content):
                            if isinstance(sub_item, dict) and sub_item.get("type") == "text":
                                text = sub_item.get("text", "")
                                if len(text) >= min_chars:
                                    locations.append(ContentLocation(
                                        line_number=line_num,
                                        path=["message", "content", i, "content", j, "text"],
                                        content=text,
                                        content_type="tool_result",
                                        char_count=len(text)
                                    ))
                
                elif item_type == "text":
                    text = item.get("text", "")
                    if len(text) >= min_chars:
                        locations.append(ContentLocation(
                            line_number=line_num,
                            path=["message", "content", i, "text"],
                            content=text,
                            content_type="text",
                            char_count=len(text)
                        ))
        
        return locations
    
    def _scan_assistant_message(self, line_num: int, data: dict, min_chars: int) -> List[ContentLocation]:
        """Scan assistant message for content."""
        locations = []
        message = data.get("message", {})
        content = message.get("content", [])
        
        if not isinstance(content, list):
            return locations
            
        for i, item in enumerate(content):
            if not isinstance(item, dict):
                continue
                
            item_type = item.get("type")
            
            if item_type == "text":
                text = item.get("text", "")
                if len(text) >= min_chars:
                    locations.append(ContentLocation(
                        line_number=line_num,
                        path=["message", "content", i, "text"],
                        content=text,
                        content_type="text",
                        char_count=len(text)
                    ))
            
            elif item_type == "thinking":
                thinking = item.get("thinking", "")
                if len(thinking) >= min_chars:
                    locations.append(ContentLocation(
                        line_number=line_num,
                        path=["message", "content", i, "thinking"],
                        content=thinking,
                        content_type="thinking",
                        char_count=len(thinking)
                    ))
        
        return locations


class CartonStore:
    """Store content to Carton KG via MCP."""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.stored: Dict[str, str] = {}  # ref_id -> concept_name
        
    def generate_ref(self, content: str, location: ContentLocation) -> str:
        """Generate unique reference ID."""
        hash_input = f"{self.session_id}:{location.line_number}:{location.content_type}:{len(content)}"
        ref_id = hashlib.sha256(hash_input.encode()).hexdigest()[:12]
        return f"Slinky_{self.session_id[:8]}_{ref_id}"
    
    def store(self, content: str, location: ContentLocation, summary: str) -> str:
        """Store content to Carton and return reference.
        
        Returns concept name that can be used as reference.
        """
        concept_name = self.generate_ref(content, location)
        
        # Build concept description with full content
        description = f"""[Slinky Context Store]
Type: {location.content_type}
Line: {location.line_number}
Chars: {location.char_count}
Summary: {summary}

---FULL CONTENT---
{content}
"""
        
        # Call Carton MCP to store
        # For now, we'll use subprocess to call the MCP tool
        # In production, this would use the MCP client directly
        try:
            # Store to Carton via add_concept with hide_youknow=True (skip validation)
            self._call_carton_add(concept_name, description)
            self.stored[concept_name] = description
        except Exception as e:
            print(f"Warning: Carton store failed for {concept_name}: {e}")
        
        return concept_name
    
    def _call_carton_add(self, concept_name: str, description: str) -> None:
        """Call Carton MCP to add concept.
        
        This is a placeholder - in production, use MCP client.
        """
        # For now, just track locally
        # TODO: Actually call mcp_carton_add_concept
        pass


class SlinkyCompressor:
    """Compress session by replacing content with refs + summaries."""
    
    def __init__(
        self, 
        session_path: Path,
        summarizer: Optional[Callable[[str], str]] = None,
        carton: Optional[CartonStore] = None
    ):
        self.session_path = Path(session_path)
        self.scanner = SessionScanner(session_path)
        self.summarizer = summarizer or self._default_summarizer
        self.carton = carton
        
    def _default_summarizer(self, content: str, max_chars: int = 400) -> str:
        """Default summarizer - just truncates."""
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "..."
    
    def compress(
        self,
        output_path: Optional[Path] = None,
        min_chars: int = 500,
        summary_max_chars: int = 400,
        preserve_recent_lines: int = 0
    ) -> CompressionResult:
        """Compress session by replacing large content with refs + summaries.
        
        Args:
            output_path: Where to write compressed session
            min_chars: Minimum content size to compress
            summary_max_chars: Maximum chars for summary
            preserve_recent_lines: Don't compress last N lines
        """
        self.scanner.load()
        locations = self.scanner.find_all_content(min_chars)
        
        if not locations:
            return CompressionResult(0, 0, 0, 0)
        
        # Filter out recent lines if requested
        if preserve_recent_lines > 0:
            max_line = len(self.scanner.lines) - preserve_recent_lines
            locations = [loc for loc in locations if loc.line_number < max_line]
        
        original_chars = sum(loc.char_count for loc in locations)
        compressed_chars = 0
        carton_refs = 0
        
        # Group locations by line for batch processing
        by_line: Dict[int, List[ContentLocation]] = {}
        for loc in locations:
            if loc.line_number not in by_line:
                by_line[loc.line_number] = []
            by_line[loc.line_number].append(loc)
        
        # Process each line
        modified_lines = list(self.scanner.lines)
        
        for line_num, line_locations in by_line.items():
            line = modified_lines[line_num].strip()
            if not line:
                continue
                
            try:
                data = json.loads(line)
                
                for loc in line_locations:
                    # Generate summary
                    summary = self.summarizer(loc.content, summary_max_chars)
                    
                    # Store to Carton if available
                    ref = ""
                    if self.carton:
                        ref = self.carton.store(loc.content, loc, summary)
                        carton_refs += 1
                    else:
                        ref = f"Line{loc.line_number}_{loc.content_type}"
                    
                    # Build replacement
                    replacement = f"[📦 {ref}] {summary}"
                    compressed_chars += len(replacement)
                    
                    # Replace content at path
                    self._set_at_path(data, loc.path, replacement)
                
                # Write modified line
                modified_lines[line_num] = json.dumps(data) + "\n"
                
            except json.JSONDecodeError:
                continue
        
        # Write output
        if output_path is None:
            output_path = self.session_path.with_suffix('.slinky.jsonl')
            
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(modified_lines)
        
        return CompressionResult(
            original_chars=original_chars,
            compressed_chars=compressed_chars,
            locations_processed=len(locations),
            carton_refs_created=carton_refs
        )
    
    def _set_at_path(self, data: dict, path: List, value: str) -> None:
        """Set value at JSON path."""
        current = data
        for key in path[:-1]:
            current = current[key]
        current[path[-1]] = value


def compress_session(
    session_path: str,
    output_path: Optional[str] = None,
    min_chars: int = 500,
    summary_max_chars: int = 400,
    preserve_recent: int = 0,
    use_carton: bool = True
) -> CompressionResult:
    """Main entry point for session compression."""
    session = Path(session_path)
    output = Path(output_path) if output_path else None
    
    session_id = session.stem
    carton = CartonStore(session_id) if use_carton else None
    
    compressor = SlinkyCompressor(session, carton=carton)
    return compressor.compress(
        output_path=output,
        min_chars=min_chars,
        summary_max_chars=summary_max_chars,
        preserve_recent_lines=preserve_recent
    )


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python slinky_context.py <session.jsonl> [output.jsonl] [--min-chars N] [--preserve N]")
        sys.exit(1)
    
    session = sys.argv[1]
    output = None
    min_chars = 500
    preserve = 0
    
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--min-chars" and i + 1 < len(sys.argv):
            min_chars = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == "--preserve" and i + 1 < len(sys.argv):
            preserve = int(sys.argv[i + 1])
            i += 2
        elif not sys.argv[i].startswith("--"):
            output = sys.argv[i]
            i += 1
        else:
            i += 1
    
    result = compress_session(
        session, 
        output, 
        min_chars=min_chars,
        preserve_recent=preserve
    )
    
    print(f"Compression complete!")
    print(f"  Original chars: {result.original_chars:,}")
    print(f"  Compressed chars: {result.compressed_chars:,}")
    print(f"  Chars saved: {result.chars_saved:,}")
    print(f"  Locations processed: {result.locations_processed}")
    print(f"  Carton refs: {result.carton_refs_created}")
    print(f"  Compression ratio: {result.compression_ratio:.1f}x")
