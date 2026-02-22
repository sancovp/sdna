"""Slinky Context - Full algorithm with mocked LLM calls.

Replaces session content with refs + summaries:
- User messages (iteration start): "[📦 Iter_N_YYYY_MM_DD_HH] Summary: user did X, assistant did Y"
- Assistant messages: "[📦 Asst_N_YYYY_MM_DD_HH]"  
- Tool use/results: "[📦 Tool_N_YYYY_MM_DD_HH]"
"""
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


def parse_timestamp(ts_str: str) -> str:
    """Extract YYYY_MM_DD_HH from ISO timestamp."""
    try:
        # Handle ISO format: 2026-01-17T12:37:24.802Z
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime("%Y_%m_%d_%H")
    except:
        return "unknown_time"


def identify_iterations(lines: List[str]) -> List[Dict[str, Any]]:
    """Identify iterations in session.
    
    An iteration starts with a user message that has text content (not just tool_result).
    It includes all following messages until the next such user message.
    """
    iterations = []
    current_iter = None
    iter_count = 0
    
    for i, line in enumerate(lines):
        if not line.strip():
            continue
            
        try:
            data = json.loads(line)
            msg_type = data.get("type")
            timestamp = data.get("timestamp", "")
            
            if msg_type == "user":
                message = data.get("message", {})
                content = message.get("content")
                is_meta = data.get("isMeta", False)
                
                # Check if this starts a new iteration
                is_new_iter = False
                if not is_meta:
                    if isinstance(content, str) and content.strip():
                        # Check it's not just a command
                        if not content.startswith("<command"):
                            is_new_iter = True
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                is_new_iter = True
                                break
                
                if is_new_iter:
                    # Save previous iteration
                    if current_iter and current_iter["messages"]:
                        iterations.append(current_iter)
                    
                    iter_count += 1
                    current_iter = {
                        "number": iter_count,
                        "start_line": i,
                        "timestamp": parse_timestamp(timestamp),
                        "messages": []
                    }
            
            # Add message to current iteration
            if current_iter is not None and msg_type in ("user", "assistant"):
                current_iter["messages"].append({
                    "line": i,
                    "type": msg_type,
                    "timestamp": parse_timestamp(timestamp),
                    "data": data
                })
                    
        except json.JSONDecodeError:
            continue
    
    # Don't forget last iteration
    if current_iter and current_iter["messages"]:
        iterations.append(current_iter)
    
    return iterations


def mock_summary(iter_num: int, msg_count: int) -> str:
    """Generate mock summary for an iteration."""
    actions = [
        "analyzed the code structure",
        "implemented the feature",
        "fixed the bug",
        "refactored the module", 
        "reviewed the changes",
        "debugged the issue",
        "connected the MCP",
        "read the files",
        "updated the config",
        "wired the endpoints"
    ]
    action = actions[iter_num % len(actions)]
    return f"User requested work, assistant {action} across {msg_count} messages"


def compress_iteration(
    iteration: Dict[str, Any],
    lines: List[str],
    preserve: bool = False
) -> List[Tuple[int, str]]:
    """Compress an iteration, returning list of (line_number, new_line).
    
    If preserve=True, don't compress (keep recent iterations intact).
    """
    if preserve:
        return []
    
    modifications = []
    iter_num = iteration["number"]
    iter_ts = iteration["timestamp"]
    messages = iteration["messages"]
    
    for idx, msg in enumerate(messages):
        line_num = msg["line"]
        msg_type = msg["type"]
        msg_ts = msg["timestamp"]
        data = msg["data"]
        
        # First user message in iteration gets the summary
        is_iteration_start = (idx == 0 and msg_type == "user")
        
        if is_iteration_start:
            # Generate summary ref
            ref = f"[📦 Iter_{iter_num}_{iter_ts}]"
            summary = mock_summary(iter_num, len(messages))
            replacement = f"{ref} {summary}"
        else:
            # Non-start messages just get refs
            if msg_type == "assistant":
                ref = f"[📦 Asst_{iter_num}_{idx}_{msg_ts}]"
            else:
                ref = f"[📦 Msg_{iter_num}_{idx}_{msg_ts}]"
            replacement = ref
        
        # Replace content in data
        new_data = replace_content(data, replacement)
        new_line = json.dumps(new_data)
        modifications.append((line_num, new_line))
    
    return modifications


def replace_content(data: Dict[str, Any], replacement: str) -> Dict[str, Any]:
    """Replace all text content in a message with the replacement string."""
    data = json.loads(json.dumps(data))  # Deep copy
    
    msg_type = data.get("type")
    message = data.get("message", {})
    content = message.get("content")
    
    if msg_type == "user":
        if isinstance(content, str):
            message["content"] = replacement
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        item["text"] = replacement
                    elif item.get("type") == "tool_result":
                        # Replace tool result content
                        result_content = item.get("content")
                        if isinstance(result_content, str):
                            item["content"] = replacement
                        elif isinstance(result_content, list):
                            item["content"] = replacement
    
    elif msg_type == "assistant":
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        item["text"] = replacement
                    elif item.get("type") == "thinking":
                        item["thinking"] = replacement
                    elif item.get("type") == "tool_use":
                        # Keep tool_use structure but could add ref to input
                        pass
    
    return data


def slinky_compress(
    session_path: str,
    output_path: Optional[str] = None,
    preserve_recent: int = 2
) -> Dict[str, Any]:
    """Main compression function.
    
    Args:
        session_path: Path to session .jsonl
        output_path: Where to write output (default: adds .slinky.jsonl)
        preserve_recent: Number of recent iterations to keep uncompressed
        
    Returns:
        Stats dict
    """
    session = Path(session_path)
    
    # Load session
    with open(session, 'r') as f:
        lines = f.readlines()
    
    # Identify iterations
    iterations = identify_iterations(lines)
    
    if not iterations:
        return {"error": "No iterations found"}
    
    # Determine which to compress
    if len(iterations) <= preserve_recent:
        to_compress = []
        to_preserve = iterations
    else:
        to_compress = iterations[:-preserve_recent]
        to_preserve = iterations[-preserve_recent:]
    
    # Collect all modifications
    all_mods = {}
    for iteration in to_compress:
        mods = compress_iteration(iteration, lines, preserve=False)
        for line_num, new_line in mods:
            all_mods[line_num] = new_line
    
    # Apply modifications
    output_lines = []
    for i, line in enumerate(lines):
        if i in all_mods:
            output_lines.append(all_mods[i] + "\n")
        else:
            output_lines.append(line if line.endswith("\n") else line + "\n")
    
    # Write output
    if output_path is None:
        output_path = str(session.with_suffix('.slinky.jsonl'))
    
    with open(output_path, 'w') as f:
        f.writelines(output_lines)
    
    # Calculate stats
    original_chars = sum(len(line) for line in lines)
    compressed_chars = sum(len(line) for line in output_lines)
    
    return {
        "total_iterations": len(iterations),
        "compressed_iterations": len(to_compress),
        "preserved_iterations": len(to_preserve),
        "original_chars": original_chars,
        "compressed_chars": compressed_chars,
        "chars_saved": original_chars - compressed_chars,
        "compression_ratio": original_chars / compressed_chars if compressed_chars > 0 else 0,
        "output_path": output_path
    }


def show_compressed_sample(output_path: str, num_lines: int = 10):
    """Show sample of compressed output."""
    with open(output_path, 'r') as f:
        lines = f.readlines()
    
    print("\n" + "=" * 60)
    print("COMPRESSED SESSION SAMPLE")
    print("=" * 60)
    
    shown = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            msg_type = data.get("type")
            if msg_type in ("user", "assistant"):
                message = data.get("message", {})
                content = message.get("content")
                
                print(f"\n[{msg_type.upper()}]")
                if isinstance(content, str):
                    print(f"  {content[:200]}...")
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            if "text" in item:
                                print(f"  [{item.get('type')}] {item['text'][:200]}")
                            elif "thinking" in item:
                                print(f"  [thinking] {item['thinking'][:200]}")
                            elif "type" in item:
                                print(f"  [{item['type']}]")
                
                shown += 1
                if shown >= num_lines:
                    break
        except:
            continue
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python slinky_v2.py <session.jsonl> [output.jsonl] [--preserve N]")
        sys.exit(1)
    
    session = sys.argv[1]
    output = None
    preserve = 2
    
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--preserve" and i + 1 < len(sys.argv):
            preserve = int(sys.argv[i + 1])
            i += 2
        elif not sys.argv[i].startswith("--"):
            output = sys.argv[i]
            i += 1
        else:
            i += 1
    
    print("🗜️ SLINKY CONTEXT COMPRESSION")
    print("=" * 40)
    
    stats = slinky_compress(session, output, preserve_recent=preserve)
    
    print(f"\n📊 RESULTS:")
    print(f"  Total iterations: {stats['total_iterations']}")
    print(f"  Compressed: {stats['compressed_iterations']}")
    print(f"  Preserved: {stats['preserved_iterations']}")
    print(f"\n  Original: {stats['original_chars']:,} chars")
    print(f"  Compressed: {stats['compressed_chars']:,} chars")
    print(f"  Saved: {stats['chars_saved']:,} chars")
    print(f"  Ratio: {stats['compression_ratio']:.1f}x")
    print(f"\n  Output: {stats['output_path']}")
    
    # Show sample
    show_compressed_sample(stats['output_path'])
