"""Slinky Context - Full hierarchical compression algorithm.

Levels:
- L0: Raw content (preserve recent)
- L1: Iteration → summary + ref (400 tokens)
- L2: Group of L1s → meta-summary + refs (800 tokens per 50 L1s)
- L3: Group of L2s → meta-meta-summary (400 tokens per 25 L2s)

Date decay:
- Today/yesterday: preserve more detail
- Older: more aggressive compression

📦=Unpackable CartON Ref
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple


def parse_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse ISO timestamp to datetime."""
    try:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except:
        return None


def ts_to_ref(dt: Optional[datetime]) -> str:
    """Convert datetime to ref string."""
    if dt:
        return dt.strftime("%Y_%m_%d_%H")
    return "unknown"


def identify_iterations(lines: List[str]) -> List[Dict[str, Any]]:
    """Identify iterations in session."""
    iterations = []
    current_iter = None
    iter_count = 0
    
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            msg_type = data.get("type")
            timestamp = parse_timestamp(data.get("timestamp", ""))
            
            if msg_type == "user":
                message = data.get("message", {})
                content = message.get("content")
                is_meta = data.get("isMeta", False)
                
                is_new_iter = False
                if not is_meta:
                    if isinstance(content, str) and content.strip() and not content.startswith("<command"):
                        is_new_iter = True
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                is_new_iter = True
                                break
                
                if is_new_iter:
                    if current_iter and current_iter["messages"]:
                        iterations.append(current_iter)
                    iter_count += 1
                    current_iter = {
                        "number": iter_count,
                        "start_line": i,
                        "timestamp": timestamp,
                        "messages": [],
                        "level": 0  # L0 = raw
                    }
            
            if current_iter is not None and msg_type in ("user", "assistant"):
                current_iter["messages"].append({
                    "line": i,
                    "type": msg_type,
                    "timestamp": timestamp,
                    "data": data
                })
        except json.JSONDecodeError:
            continue
    
    if current_iter and current_iter["messages"]:
        iterations.append(current_iter)
    
    return iterations


def get_age_category(timestamp: Optional[datetime], now: datetime) -> str:
    """Categorize iteration by age."""
    if not timestamp:
        return "old"
    
    age = now - timestamp.replace(tzinfo=None) if timestamp.tzinfo else now - timestamp
    
    if age < timedelta(days=1):
        return "today"
    elif age < timedelta(days=2):
        return "yesterday"
    elif age < timedelta(weeks=1):
        return "this_week"
    else:
        return "old"


def mock_l1_summary(iter_num: int, msg_count: int, age: str) -> str:
    """Mock L1 summary (replace with LLM call)."""
    actions = ["analyzed", "implemented", "fixed", "refactored", "reviewed", 
               "debugged", "connected", "read", "updated", "wired"]
    return f"User requested work, assistant {actions[iter_num % len(actions)]} ({msg_count} msgs)"


def mock_l2_summary(iter_range: Tuple[int, int], total_msgs: int) -> str:
    """Mock L2 meta-summary (replace with LLM call)."""
    return f"Work block: iterations {iter_range[0]}-{iter_range[1]}, {total_msgs} total messages. Multiple features implemented and bugs fixed."


def mock_l3_summary(l2_count: int, iter_range: Tuple[int, int]) -> str:
    """Mock L3 meta-meta-summary (replace with LLM call)."""
    return f"Major work phase: {l2_count} work blocks covering iterations {iter_range[0]}-{iter_range[1]}. Significant progress on core functionality."


def replace_content(data: Dict[str, Any], replacement: str) -> Dict[str, Any]:
    """Replace all text content in message."""
    data = json.loads(json.dumps(data))
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
    
    return data


def compress_l1(iteration: Dict[str, Any], lines: List[str]) -> List[Tuple[int, str]]:
    """Compress iteration to L1 (summary + refs)."""
    mods = []
    iter_num = iteration["number"]
    ts = ts_to_ref(iteration["timestamp"])
    messages = iteration["messages"]
    age = iteration.get("age", "old")
    
    for idx, msg in enumerate(messages):
        line_num = msg["line"]
        msg_type = msg["type"]
        data = msg["data"]
        msg_ts = ts_to_ref(msg["timestamp"])
        
        if idx == 0 and msg_type == "user":
            # First user message gets summary
            ref = f"[📦 Iter_{iter_num}_{ts}]"
            summary = mock_l1_summary(iter_num, len(messages), age)
            replacement = f"{ref} {summary}"
        else:
            # Other messages just get refs
            prefix = "Asst" if msg_type == "assistant" else "Msg"
            ref = f"[📦 {prefix}_{iter_num}_{idx}_{msg_ts}]"
            replacement = ref
        
        new_data = replace_content(data, replacement)
        mods.append((line_num, json.dumps(new_data)))
    
    return mods


def compress_l2(l1_iterations: List[Dict[str, Any]], lines: List[str]) -> Tuple[List[Tuple[int, str]], str]:
    """Compress group of L1 iterations to L2.
    
    First iteration's user message gets L2 summary.
    Other iterations' summaries become just refs.
    """
    if not l1_iterations:
        return [], ""
    
    mods = []
    first_iter = l1_iterations[0]
    last_iter = l1_iterations[-1]
    iter_range = (first_iter["number"], last_iter["number"])
    total_msgs = sum(len(it["messages"]) for it in l1_iterations)
    
    for it_idx, iteration in enumerate(l1_iterations):
        iter_num = iteration["number"]
        ts = ts_to_ref(iteration["timestamp"])
        
        for msg_idx, msg in enumerate(iteration["messages"]):
            line_num = msg["line"]
            data = msg["data"]
            msg_ts = ts_to_ref(msg["timestamp"])
            
            if it_idx == 0 and msg_idx == 0:
                # First message of first iteration gets L2 summary
                l2_ref = f"[📦 L2_{iter_range[0]}_{iter_range[1]}_{ts}]"
                l2_summary = mock_l2_summary(iter_range, total_msgs)
                replacement = f"{l2_ref} {l2_summary}"
            else:
                # Everything else becomes minimal ref
                prefix = "L1" if msg_idx == 0 else "M"
                replacement = f"[📦 {prefix}_{iter_num}_{msg_ts}]"
            
            new_data = replace_content(data, replacement)
            mods.append((line_num, json.dumps(new_data)))
    
    l2_ref = f"L2_{iter_range[0]}_{iter_range[1]}"
    return mods, l2_ref


def slinky_compress(
    session_path: str,
    output_path: Optional[str] = None,
    preserve_recent: int = 2,
    l1_threshold: int = 50,  # Compress to L2 after this many L1s
    l2_threshold: int = 25,  # Compress to L3 after this many L2s
) -> Dict[str, Any]:
    """Full hierarchical compression.
    
    Args:
        session_path: Input session .jsonl
        output_path: Output path
        preserve_recent: Keep last N iterations uncompressed
        l1_threshold: Number of L1s before compressing to L2
        l2_threshold: Number of L2s before compressing to L3
    """
    session = Path(session_path)
    with open(session, 'r') as f:
        lines = f.readlines()
    
    now = datetime.now()
    iterations = identify_iterations(lines)
    
    if not iterations:
        return {"error": "No iterations found"}
    
    # Assign age categories
    for it in iterations:
        it["age"] = get_age_category(it["timestamp"], now)
    
    # Determine compression levels based on age and count
    # Recent: preserve raw
    # Today/yesterday: L1
    # Older: L2 or L3
    
    if len(iterations) <= preserve_recent:
        to_l1 = []
        to_preserve = iterations
    else:
        to_process = iterations[:-preserve_recent]
        to_preserve = iterations[-preserve_recent:]
        
        # Split by age for different compression
        to_l1 = [it for it in to_process if it["age"] in ("today", "yesterday")]
        to_l2_candidates = [it for it in to_process if it["age"] not in ("today", "yesterday")]
        
        # Group L2 candidates into chunks
        l2_groups = []
        for i in range(0, len(to_l2_candidates), l1_threshold):
            group = to_l2_candidates[i:i + l1_threshold]
            if len(group) >= l1_threshold // 2:  # Only group if significant
                l2_groups.append(group)
            else:
                to_l1.extend(group)  # Small remainder stays L1
    
    # Collect all modifications
    all_mods = {}
    l1_count = 0
    l2_count = 0
    
    # Apply L1 compression
    for iteration in to_l1:
        mods = compress_l1(iteration, lines)
        for line_num, new_line in mods:
            all_mods[line_num] = new_line
        l1_count += 1
    
    # Apply L2 compression (groups of iterations)
    for group in l2_groups if 'l2_groups' in dir() else []:
        mods, _ = compress_l2(group, lines)
        for line_num, new_line in mods:
            all_mods[line_num] = new_line
        l2_count += 1
    
    # Build output
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
    
    # Stats
    original_chars = sum(len(line) for line in lines)
    compressed_chars = sum(len(line) for line in output_lines)
    
    return {
        "total_iterations": len(iterations),
        "preserved": len(to_preserve),
        "l1_compressed": l1_count,
        "l2_compressed": l2_count,
        "original_chars": original_chars,
        "compressed_chars": compressed_chars,
        "chars_saved": original_chars - compressed_chars,
        "ratio": original_chars / compressed_chars if compressed_chars else 0,
        "output": output_path
    }


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python slinky_full.py <session.jsonl> [output.jsonl] [--preserve N]")
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
    
    print("🗜️ SLINKY CONTEXT - FULL HIERARCHICAL COMPRESSION")
    print("=" * 50)
    print("📦=Unpackable CartON Ref")
    print()
    
    stats = slinky_compress(session, output, preserve_recent=preserve)
    
    print(f"📊 RESULTS:")
    print(f"  Iterations: {stats['total_iterations']}")
    print(f"    Preserved (raw): {stats['preserved']}")
    print(f"    L1 (summary+ref): {stats['l1_compressed']}")
    print(f"    L2 (meta-summary): {stats['l2_compressed']}")
    print()
    print(f"  Original: {stats['original_chars']:,} chars")
    print(f"  Compressed: {stats['compressed_chars']:,} chars")
    print(f"  Saved: {stats['chars_saved']:,} chars ({stats['ratio']:.1f}x)")
    print()
    print(f"  Output: {stats['output']}")
