"""
Crystal Ball adapter for SDNA.

Provides a stable Python interface for invoking the TypeScript Crystal Ball tools
inside this repo (vendor/crystal_ball).
"""

from __future__ import annotations

import asyncio
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import HeavenAgentArgs, HeavenHermesArgs, HeavenInputs, HermesConfig
from .heaven_runner import heaven_agent_step
from .runner import StepStatus


class CrystalBallError(RuntimeError):
    """Raised when a Crystal Ball tool invocation fails."""


@dataclass
class CrystalBallPaths:
    """Filesystem locations used by the adapter."""

    repo_root: Path
    cb_root: Path

    @classmethod
    def from_repo_root(cls, repo_root: Optional[Path] = None) -> "CrystalBallPaths":
        if repo_root is None:
            repo_root = Path(__file__).resolve().parents[1]
        cb_root = repo_root / "vendor" / "crystal_ball"
        return cls(repo_root=repo_root, cb_root=cb_root)


@dataclass
class CrystalBallRunner:
    """Executes Crystal Ball scripts and parses outputs."""

    paths: CrystalBallPaths
    npx_cmd: str = "npx"
    tsx_package: str = "tsx"

    @classmethod
    def auto(cls) -> "CrystalBallRunner":
        return cls(paths=CrystalBallPaths.from_repo_root())

    def _run(self, args: Iterable[str], cwd: Optional[Path] = None) -> str:
        workdir = cwd or self.paths.cb_root
        if not workdir.exists():
            raise CrystalBallError(f"Crystal Ball directory not found: {workdir}")

        cmd = [self.npx_cmd, "--yes", self.tsx_package, *list(args)]
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            rendered = " ".join(shlex.quote(x) for x in cmd)
            raise CrystalBallError(
                f"Crystal Ball command failed (exit {proc.returncode}): {rendered}\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
        return proc.stdout.strip()

    def check_health(self) -> Dict[str, Any]:
        out = self._run(["scripts/map_cypher_to_cb.ts", "--help"])
        return {
            "ok": True,
            "cb_root": str(self.paths.cb_root),
            "help_preview": out.splitlines()[:3],
        }

    def map_cypher_to_cb(
        self,
        input_cypher: str | Path,
        output_cb_json: str | Path,
        space_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        input_path = Path(input_cypher).expanduser().resolve()
        output_path = Path(output_cb_json).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        args = [
            "scripts/map_cypher_to_cb.ts",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
        if space_name:
            args.extend(["--name", space_name])

        stdout = self._run(args)
        stats = self.read_cb_stats(output_path)
        return {
            "stdout": stdout,
            "output": str(output_path),
            **stats,
        }

    def enrich_story_machine_cb(
        self,
        input_cb_json: str | Path,
        output_cb_json: str | Path,
    ) -> Dict[str, Any]:
        input_path = Path(input_cb_json).expanduser().resolve()
        output_path = Path(output_cb_json).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        stdout = self._run(
            [
                "scripts/enrich_story_machine_cb.ts",
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ]
        )
        stats = self.read_cb_stats(output_path)
        return {
            "stdout": stdout,
            "output": str(output_path),
            **stats,
        }

    def run_cli_script(self, commands: Iterable[str]) -> str:
        """Run CLI non-interactively with a list of command lines."""
        payload = "\n".join(commands)
        if not payload.endswith("\n"):
            payload += "\n"
        proc = subprocess.run(
            [self.npx_cmd, "--yes", self.tsx_package, "cli.ts"],
            cwd=str(self.paths.cb_root),
            input=payload,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise CrystalBallError(
                f"Crystal Ball CLI failed (exit {proc.returncode})\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
        return proc.stdout

    def read_cb_stats(self, cb_json_path: str | Path) -> Dict[str, Any]:
        path = Path(cb_json_path).expanduser().resolve()
        data = json.loads(path.read_text())
        nodes = data.get("nodes", [])

        root = None
        by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}
        if "root" in by_id:
            root = by_id["root"]

        children = root.get("children", []) if root else []
        child_labels = []
        for cid in children:
            node = by_id.get(cid)
            if isinstance(node, dict):
                child_labels.append(node.get("label", ""))

        return {
            "space_name": data.get("name"),
            "node_count": len(nodes),
            "root_child_labels": child_labels,
        }


def get_crystal_ball_runner() -> CrystalBallRunner:
    """Factory used by SDNA callers/tools."""
    return CrystalBallRunner.auto()


def _run_async(coro):
    return asyncio.run(coro)


def _parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _parse_json_array(raw: str) -> Optional[List[Any]]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _slug(text: str) -> str:
    base = "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")
    while "__" in base:
        base = base.replace("__", "_")
    return base or "candidate"


def _default_suggest_action(include_node_ids: List[str], keywords: List[str]) -> Dict[str, Any]:
    tail = "_".join(_slug(k) for k in keywords[:2]).strip("_")
    suffix = tail if tail else "candidate"
    label = f"candidate_{suffix}"[:120]
    parent_id = include_node_ids[0] if include_node_ids else "root"
    return {
        "label": label,
        "parentId": parent_id,
        "attributes": [
            {"name": "status", "spectrum": ["draft", "validated"], "defaultValue": "draft"},
            {"name": "source", "spectrum": ["heaven-llm-suggest"], "defaultValue": "heaven-llm-suggest"},
        ],
    }


def _normalize_attributes(raw_attrs: Any, source_label: str) -> List[Dict[str, Any]]:
    attrs: List[Dict[str, Any]] = []
    if isinstance(raw_attrs, list):
        for item in raw_attrs:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            spectrum = item.get("spectrum")
            if not isinstance(spectrum, list) or len(spectrum) == 0:
                default = item.get("defaultValue")
                if default is None:
                    continue
                spectrum = [default]
            default_value = item.get("defaultValue", spectrum[0])
            attrs.append(
                {
                    "name": name,
                    "spectrum": spectrum,
                    "defaultValue": default_value,
                }
            )

    names = {a["name"] for a in attrs}
    if "status" not in names:
        attrs.append({"name": "status", "spectrum": ["draft", "validated"], "defaultValue": "draft"})
    if "source" not in names:
        attrs.append({"name": "source", "spectrum": [source_label], "defaultValue": source_label})
    return attrs


def _normalize_action(action: Any, default_parent: str, source_label: str) -> Optional[Dict[str, Any]]:
    if not isinstance(action, dict):
        return None
    label = str(action.get("label", "")).strip()
    if not label:
        return None
    parent_id = str(action.get("parentId", "")).strip() or default_parent
    attrs = _normalize_attributes(action.get("attributes"), source_label)
    return {
        "label": label[:120],
        "parentId": parent_id,
        "attributes": attrs,
    }


def _existing_keys(existing_by_parent: Optional[Dict[str, List[str]]]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    if not isinstance(existing_by_parent, dict):
        return out
    for parent_id, labels in existing_by_parent.items():
        if not isinstance(parent_id, str):
            continue
        if not isinstance(labels, list):
            continue
        for label in labels:
            if not isinstance(label, str):
                continue
            out.add((parent_id.strip().lower(), label.strip().lower()))
    return out


def _dedup_actions(
    actions: List[Dict[str, Any]],
    existing_by_parent: Optional[Dict[str, List[str]]],
    max_actions: int,
    per_parent_cap: int = 0,
) -> List[Dict[str, Any]]:
    existing = _existing_keys(existing_by_parent)
    seen: set[tuple[str, str]] = set()
    parent_counts: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    cap = max(0, int(per_parent_cap))

    for action in actions:
        if not isinstance(action, dict):
            continue
        parent = str(action.get("parentId", "")).strip()
        label = str(action.get("label", "")).strip()
        if not parent or not label:
            continue
        parent_key = parent.lower()
        if cap > 0 and parent_counts.get(parent_key, 0) >= cap:
            continue
        key = (parent_key, label.lower())
        if key in existing or key in seen:
            continue
        seen.add(key)
        parent_counts[parent_key] = parent_counts.get(parent_key, 0) + 1
        out.append(action)
        if len(out) >= max_actions:
            break
    return out


def _fallback_actions(
    include_node_ids: List[str],
    neighborhood: List[Dict[str, Any]],
    keywords: List[str],
    mode: str,
    max_actions: int,
    existing_by_parent: Optional[Dict[str, List[str]]],
    per_parent_cap: int,
) -> List[Dict[str, Any]]:
    base = _default_suggest_action(include_node_ids, keywords)
    actions: List[Dict[str, Any]] = [base]

    if mode == "batch":
        for row in neighborhood:
            if not isinstance(row, dict):
                continue
            parent = str(row.get("id", "")).strip() or (include_node_ids[0] if include_node_ids else "root")
            label_seed = str(row.get("label", "")).strip() or "node"
            label = f"expand_{_slug(label_seed)}"[:120]
            actions.append(
                {
                    "label": label,
                    "parentId": parent,
                    "attributes": [
                        {"name": "status", "spectrum": ["draft", "validated"], "defaultValue": "draft"},
                        {"name": "source", "spectrum": ["heaven-fallback"], "defaultValue": "heaven-fallback"},
                        {"name": "origin_node", "spectrum": [parent], "defaultValue": parent},
                    ],
                }
            )

    return _dedup_actions(
        actions,
        existing_by_parent=existing_by_parent,
        max_actions=max_actions,
        per_parent_cap=per_parent_cap,
    )


def _parse_confidence(value: Any) -> float:
    try:
        conf = float(str(value).strip())
    except ValueError:
        conf = 0.5
    return max(0.0, min(1.0, conf))


def cb_llm_suggest(
    space_name: str,
    coordinate: str,
    include_node_ids: Optional[List[str]] = None,
    prompt: str = "",
    resolved_labels: Optional[List[str]] = None,
    neighborhood: Optional[List[Dict[str, Any]]] = None,
    model: str = "MiniMax-M2.5-highspeed",
    max_turns: int = 1,
    mode: str = "single",
    max_actions: int = 8,
    per_parent_cap: int = 0,
    existing_by_parent: Optional[Dict[str, List[str]]] = None,
    retry_attempts: int = 2,
) -> Dict[str, Any]:
    """
    Agent-backed Crystal Ball suggestion using HEAVEN keyword extraction.

    Modes:
    - single: return one main action (+ actions array with one item)
    - batch: return multiple actions across the neighborhood
    """
    include_node_ids = list(include_node_ids or [])
    resolved_labels = list(resolved_labels or [])
    neighborhood = list(neighborhood or [])

    safe_mode = "batch" if mode == "batch" else "single"
    max_actions = max(1, min(64, int(max_actions)))
    per_parent_cap = max(0, min(16, int(per_parent_cap)))
    retry_attempts = max(0, min(4, int(retry_attempts)))

    additional_kws = [
        "keywords",
        "suggested_action_json",
        "batch_actions_json",
        "rationale",
        "confidence",
    ]

    additional_kw_instructions = """
Use these XML tags exactly once each in your response:
<keywords>comma,separated,keywords</keywords>
<suggested_action_json>{"label":"...","parentId":"...","attributes":[{"name":"...","spectrum":["..."],"defaultValue":"..."}]}</suggested_action_json>
<batch_actions_json>[{"label":"...","parentId":"...","attributes":[{"name":"...","spectrum":["..."],"defaultValue":"..."}]}]</batch_actions_json>
<rationale>2-5 short sentences</rationale>
<confidence>0.0-1.0</confidence>
""".strip()

    context_payload = {
        "spaceName": space_name,
        "coordinate": coordinate,
        "includeNodeIds": include_node_ids,
        "resolvedLabels": resolved_labels,
        "prompt": prompt,
        "neighborhood": neighborhood,
        "mode": safe_mode,
        "maxActions": max_actions,
        "perParentCap": per_parent_cap,
        "existingByParent": existing_by_parent or {},
    }
    context_json = json.dumps(context_payload, ensure_ascii=True)

    base_system_prompt = (
        "You generate structurally valid Crystal Ball actions. "
        "No tool use is required. Never file a block report for this task. "
        "Always emit the required XML tags."
    )

    last_step_status = None
    last_error = None
    last_keywords: List[str] = []
    last_output: Dict[str, Any] = {}

    for attempt in range(retry_attempts + 1):
        attempt_hint = ""
        if attempt > 0:
            attempt_hint = (
                "\nRetry constraint: output tags even if uncertain. "
                "If unsure, provide best-effort draft actions and low confidence."
            )

        goal = f"""
You are a Crystal Ball suggestion operator.

Given context_json, output actions that can be directly applied.
- If mode is single: produce one high-quality action.
- If mode is batch: produce up to maxActions actions, usually one per neighborhood position.
- If perParentCap > 0: never emit more than perParentCap actions for the same parentId.
- Do not duplicate parentId+label pairs listed in existingByParent.
- Keep labels short, concrete, and machine-usable.
{attempt_hint}

context_json:
{context_json}
""".strip()

        config = HermesConfig(
            name=f"cb_llm_suggest_agent_a{attempt}",
            goal=goal,
            system_prompt=base_system_prompt,
            backend="heaven",
            model=model,
            max_turns=max(1, int(max_turns)),
            mcp_servers={},
            heaven_inputs=HeavenInputs(
                agent=HeavenAgentArgs(
                    provider="ANTHROPIC",
                    max_tokens=5000,
                    use_uni_api=False,
                    tools=[],
                    additional_kws=additional_kws,
                    additional_kw_instructions=additional_kw_instructions,
                ),
                hermes=HeavenHermesArgs(
                    ai_messages_only=True,
                    return_summary=False,
                ),
            ),
        )

        step = _run_async(heaven_agent_step(config))
        last_step_status = step.status
        last_error = step.error or f"agent step status={step.status}"

        output = dict(step.output or {})
        last_output = output
        extracted = output.get("extracted_content") or {}

        raw_keywords = str(extracted.get("keywords") or "").strip()
        keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]
        last_keywords = keywords

        default_parent = include_node_ids[0] if include_node_ids else "root"
        primary_obj = _parse_json_object(str(extracted.get("suggested_action_json") or ""))
        primary_action = _normalize_action(primary_obj, default_parent=default_parent, source_label="heaven-llm-suggest")

        batch_raw = _parse_json_array(str(extracted.get("batch_actions_json") or "")) or []
        batch_actions: List[Dict[str, Any]] = []
        for item in batch_raw:
            normalized = _normalize_action(item, default_parent=default_parent, source_label="heaven-llm-suggest")
            if normalized:
                batch_actions.append(normalized)

        candidate_actions: List[Dict[str, Any]] = []
        if safe_mode == "batch":
            if primary_action:
                candidate_actions.append(primary_action)
            candidate_actions.extend(batch_actions)
        else:
            if primary_action:
                candidate_actions.append(primary_action)
            elif batch_actions:
                candidate_actions.append(batch_actions[0])

        actions = _dedup_actions(
            candidate_actions,
            existing_by_parent=existing_by_parent,
            max_actions=max_actions,
            per_parent_cap=per_parent_cap,
        )

        if actions:
            rationale = str(extracted.get("rationale") or "").strip()
            if not rationale:
                rationale = "Model produced actions without explicit rationale."
            confidence = _parse_confidence(extracted.get("confidence"))

            return {
                "ok": step.status == StepStatus.SUCCESS,
                "stub": False,
                "mode": safe_mode,
                "model": model,
                "per_parent_cap": per_parent_cap,
                "keywords": keywords,
                "suggestedAction": actions[0],
                "actions": actions,
                "rationale": rationale,
                "confidence": confidence,
                "status": step.status.value,
                "raw_text": output.get("text", ""),
                "extracted_content_keys": output.get("extracted_content_keys", []),
                "history_id": output.get("history_id"),
                "attempt": attempt,
                "warning": None if step.status == StepStatus.SUCCESS else "Parsed actions from non-success step status.",
            }

    fallback_actions = _fallback_actions(
        include_node_ids=include_node_ids,
        neighborhood=neighborhood,
        keywords=last_keywords,
        mode=safe_mode,
        max_actions=max_actions,
        existing_by_parent=existing_by_parent,
        per_parent_cap=per_parent_cap,
    )
    if not fallback_actions:
        fallback_actions = [_default_suggest_action(include_node_ids, last_keywords)]

    return {
        "ok": False,
        "stub": True,
        "mode": safe_mode,
        "model": model,
        "per_parent_cap": per_parent_cap,
        "error": last_error,
        "keywords": last_keywords,
        "suggestedAction": fallback_actions[0],
        "actions": fallback_actions,
        "rationale": "Agent did not return usable actions; using deterministic fallback actions.",
        "confidence": 0.0,
        "status": last_step_status.value if last_step_status else "error",
        "raw_text": last_output.get("text", ""),
        "extracted_content_keys": last_output.get("extracted_content_keys", []),
        "history_id": last_output.get("history_id"),
        "attempt": retry_attempts,
    }

def cb_map_cypher_to_cb(
    input_cypher: str,
    output_cb_json: str,
    space_name: str = "StoryMachineProjection",
) -> Dict[str, Any]:
    """Convenience wrapper for Ariadne inject_func usage."""
    runner = get_crystal_ball_runner()
    return runner.map_cypher_to_cb(
        input_cypher=input_cypher,
        output_cb_json=output_cb_json,
        space_name=space_name,
    )


def cb_enrich_story_machine_cb(
    input_cb_json: str,
    output_cb_json: str,
) -> Dict[str, Any]:
    """Convenience wrapper for Ariadne inject_func usage."""
    runner = get_crystal_ball_runner()
    return runner.enrich_story_machine_cb(
        input_cb_json=input_cb_json,
        output_cb_json=output_cb_json,
    )


def cb_read_cb_stats(cb_json_path: str) -> Dict[str, Any]:
    """Read and summarize a Crystal Ball JSON artifact."""
    runner = get_crystal_ball_runner()
    stats = runner.read_cb_stats(cb_json_path)
    stats["path"] = str(Path(cb_json_path).expanduser().resolve())
    return stats


def cb_bootstrap_story_machine(
    input_cypher: str,
    mapped_cb_json: str,
    enriched_cb_json: str,
    space_name: str = "StoryMachineProjection",
) -> Dict[str, Any]:
    """Map + enrich in one call; useful for simple orchestration."""
    runner = get_crystal_ball_runner()
    mapped = runner.map_cypher_to_cb(
        input_cypher=input_cypher,
        output_cb_json=mapped_cb_json,
        space_name=space_name,
    )
    enriched = runner.enrich_story_machine_cb(
        input_cb_json=mapped_cb_json,
        output_cb_json=enriched_cb_json,
    )
    return {
        "mapped": mapped,
        "enriched": enriched,
    }
