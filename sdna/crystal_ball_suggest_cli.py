"""CLI bridge for Crystal Ball llm_suggest calls.

Usage:
  echo '{"space_name":"X", ...}' | python -m sdna.crystal_ball_suggest_cli
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict

from .crystal_ball import cb_llm_suggest


def _read_input() -> Dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON input: {exc}")
    if not isinstance(data, dict):
        raise SystemExit("Input JSON must be an object")
    return data


def main() -> None:
    payload = _read_input()
    result = cb_llm_suggest(
        space_name=str(payload.get("space_name", "")),
        coordinate=str(payload.get("coordinate", "")),
        include_node_ids=[str(x) for x in payload.get("include_node_ids", [])],
        prompt=str(payload.get("prompt", "")),
        resolved_labels=[str(x) for x in payload.get("resolved_labels", [])],
        neighborhood=payload.get("neighborhood", []),
        model=str(payload.get("model", "MiniMax-M2.5-highspeed")),
        max_turns=int(payload.get("max_turns", 1)),
        mode=str(payload.get("mode", "single")),
        max_actions=int(payload.get("max_actions", 8)),
        per_parent_cap=int(payload.get("per_parent_cap", 0)),
        existing_by_parent=payload.get("existing_by_parent") or {},
        retry_attempts=int(payload.get("retry_attempts", 2)),
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
