"""WAVE 1 tests for cb_llm_suggest (2026-07-05 rulings). NO live LLM.

Covers:
- observer persona is the DEFAULT system prompt (Isaac's construction)
- injectable system_prompt parameter overrides the default
- goal prompt enumerates (no "high-quality" curation language)
- success path parses actions from a canned heaven response
- total failure returns ok=False, stub=True, actions=[] (NO fabricated
  candidate_/expand_ stub actions), error message intact
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

import sdna.crystal_ball as cb
from sdna.runner import StepStatus


class _FakeStep:
    def __init__(self, status: StepStatus, output: Dict[str, Any], error: str | None = None):
        self.status = status
        self.output = output
        self.error = error


def _capture_calls(monkeypatch, steps: List[_FakeStep]):
    """Monkeypatch heaven_agent_step to pop canned steps; capture configs."""
    configs: List[Any] = []
    queue = list(steps)

    async def fake_heaven_agent_step(config):
        configs.append(config)
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]

    monkeypatch.setattr(cb, "heaven_agent_step", fake_heaven_agent_step)
    return configs


def _success_step() -> _FakeStep:
    return _FakeStep(
        status=StepStatus.SUCCESS,
        output={
            "text": "ok",
            "extracted_content": {
                "keywords": "alpha, beta",
                "suggested_action_json": '{"label":"alpha_item","parentId":"1"}',
                "batch_actions_json": '[{"label":"beta_item","parentId":"2"}]',
                "rationale": "observed pattern",
                "confidence": "0.8",
            },
            "extracted_content_keys": ["keywords"],
            "history_id": "h1",
        },
    )


def _failure_step() -> _FakeStep:
    return _FakeStep(
        status=StepStatus.ERROR,
        output={"text": "", "extracted_content": {}},
        error="auth exploded loudly",
    )


def test_observer_system_prompt_is_default(monkeypatch):
    configs = _capture_calls(monkeypatch, [_success_step()])
    cb.cb_llm_suggest("S", "root", mode="single", max_actions=3)
    assert len(configs) == 1
    assert configs[0].system_prompt == cb.OBSERVER_SYSTEM_PROMPT
    # Isaac's observer construction, near-verbatim
    assert "speak only from a third-person perspective with no opinion" in configs[0].system_prompt
    assert "web out the obvious information not said" in configs[0].system_prompt
    assert "scientific hypothesis" in configs[0].system_prompt
    # structural-output contract retained
    assert "Always emit the required XML tags" in configs[0].system_prompt
    assert "Never file a block report" in configs[0].system_prompt
    # old operator framing is gone
    assert "suggestion operator" not in configs[0].system_prompt


def test_system_prompt_is_injectable(monkeypatch):
    configs = _capture_calls(monkeypatch, [_success_step()])
    cb.cb_llm_suggest("S", "root", system_prompt="CUSTOM OBSERVER", max_actions=3)
    assert configs[0].system_prompt == "CUSTOM OBSERVER"


def test_goal_enumerates_no_curation_language(monkeypatch):
    configs = _capture_calls(monkeypatch, [_success_step()])
    cb.cb_llm_suggest("S", "root", mode="batch", max_actions=3)
    goal = configs[0].goal
    assert "ENUMERATE all things that match the invariant" in goal
    assert "do not rank" in goal
    assert "high-quality" not in goal
    assert "suggestion operator" not in goal


def test_success_parses_actions(monkeypatch):
    _capture_calls(monkeypatch, [_success_step()])
    result = cb.cb_llm_suggest("S", "root", mode="batch", max_actions=5)
    assert result["ok"] is True
    assert result["stub"] is False
    labels = [a["label"] for a in result["actions"]]
    assert "alpha_item" in labels and "beta_item" in labels
    assert result["confidence"] == pytest.approx(0.8)


def test_total_failure_returns_empty_actions_stub_true(monkeypatch):
    _capture_calls(monkeypatch, [_failure_step()])
    result = cb.cb_llm_suggest("S", "root", mode="batch", max_actions=5, retry_attempts=1)
    assert result["ok"] is False
    assert result["stub"] is True
    assert result["actions"] == []          # NO fabricated fallback actions
    assert result["suggestedAction"] is None
    assert "auth exploded loudly" in result["error"]


def test_fallback_fabricators_are_deleted():
    # The deterministic fabrication helpers must not exist at all
    assert not hasattr(cb, "_fallback_actions")
    assert not hasattr(cb, "_default_suggest_action")
