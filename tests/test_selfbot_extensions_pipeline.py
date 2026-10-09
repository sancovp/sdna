"""
Tests for the explore -> record -> compile -> library pipeline.

Everything here runs without a browser: FakeDriver implements PageDriver over a
dict, which is what lets the whole pipeline - including the generated SDK code
actually executing - be proven in CI.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdna.selfbot_extensions.domain.procedure import (  # noqa: E402
    Procedure, Step, StepKind, ArgSpec, ArgType, Condition, ProcedureStatus,
    PageDriver,
)
from sdna.selfbot_extensions.domain.procedure_codegen import generate_function, generate_site  # noqa: E402
from sdna.selfbot_extensions.infrastructure.procedure_runtime import (  # noqa: E402
    run_procedure, replay, PreconditionFailed, PostconditionFailed, StepFailed,
)
from sdna.selfbot_extensions.infrastructure.procedure_storage import InMemoryProcedureRepository  # noqa: E402
from sdna.selfbot_extensions.infrastructure.recorder import TraceRecorder, RecordingDriver  # noqa: E402
from sdna.selfbot_extensions.application.sdk_builder import SdkBuilder  # noqa: E402
from sdna.selfbot_extensions.application.immune import ImmuneSystem  # noqa: E402


# === Test double ===

class FakeDriver(PageDriver):
    """
    A PageDriver over a dict. `present` maps selector -> text.

    `on_click` lets a test make a click change the page, which is how the
    postcondition tests simulate a site that stops working.
    """

    def __init__(self, present=None, url="https://example.com/start", on_click=None):
        self.present = dict(present or {})
        self.url = url
        self.on_click = on_click or {}
        self.calls = []

    def _log(self, *args):
        self.calls.append(args)

    def navigate(self, url, timeout_ms=10_000):
        self._log("navigate", url)
        self.url = url

    def click(self, selector, timeout_ms=10_000):
        self._log("click", selector)
        if selector not in self.present:
            raise LookupError(f"no such element: {selector}")
        effect = self.on_click.get(selector)
        if effect:
            effect(self)

    def fill(self, selector, value, timeout_ms=10_000):
        self._log("fill", selector, value)
        if selector not in self.present:
            raise LookupError(f"no such element: {selector}")
        self.present[selector] = value

    def select(self, selector, value, timeout_ms=10_000):
        self._log("select", selector, value)
        self.present[selector] = value

    def press(self, selector, key, timeout_ms=10_000):
        self._log("press", selector, key)

    def upload(self, selector, path, timeout_ms=10_000):
        self._log("upload", selector, path)

    def wait_for(self, selector, timeout_ms=10_000):
        self._log("wait_for", selector)
        if selector not in self.present:
            raise TimeoutError(f"never appeared: {selector}")

    def exists(self, selector, timeout_ms=10_000):
        return selector in self.present

    def text_of(self, selector, timeout_ms=10_000):
        if selector not in self.present:
            raise LookupError(f"no such element: {selector}")
        return self.present[selector]

    def current_url(self):
        return self.url


def make_procedure(**overrides) -> Procedure:
    """A minimal valid procedure."""
    defaults = dict(
        site="demo",
        action="publish",
        args=[ArgSpec(name="title", type=ArgType.STR, description="post title")],
        steps=[
            Step(kind=StepKind.NAVIGATE, url="https://example.com/new"),
            Step(kind=StepKind.FILL, selector="#title", value="$title"),
            Step(kind=StepKind.CLICK, selector="[data-testid=publish]"),
        ],
        postcondition=Condition(description="post is live", selector=".published"),
    )
    defaults.update(overrides)
    return Procedure(**defaults)


# === Law 1: selectors, never coordinates ===

def test_step_rejects_coordinate_selector():
    for bad in ["847, 392", "(847, 392)", "[847,392]", "100 200"]:
        with pytest.raises(ValueError, match="coordinates"):
            Step(kind=StepKind.CLICK, selector=bad)


def test_step_accepts_real_selectors():
    for good in ["#title", "[data-testid=publish]", "text=Save", "div > button:nth-of-type(2)"]:
        assert Step(kind=StepKind.CLICK, selector=good).selector == good


def test_navigate_requires_url_and_others_require_selector():
    with pytest.raises(ValueError, match="requires a url"):
        Step(kind=StepKind.NAVIGATE)
    with pytest.raises(ValueError, match="requires a selector"):
        Step(kind=StepKind.CLICK)


# === Law 2: promotion is human-only ===

def test_promote_requires_a_named_human():
    proc = make_procedure()
    proc.record_replay(ok=True)
    assert proc.status is ProcedureStatus.QUARANTINE

    for empty in ["", "   ", None]:
        with pytest.raises(ValueError, match="verified_by"):
            proc.promote(verified_by=empty)

    proc.promote(verified_by="isaac")
    assert proc.status is ProcedureStatus.GOLDEN
    assert proc.promoted_by == "isaac"
    assert proc.promoted_at is not None


def test_candidate_cannot_be_promoted_without_a_green_replay():
    proc = make_procedure()
    assert proc.status is ProcedureStatus.CANDIDATE
    with pytest.raises(ValueError, match="replay it green first"):
        proc.promote(verified_by="isaac")


def test_green_replay_moves_candidate_to_quarantine_not_golden():
    proc = make_procedure()
    proc.record_replay(ok=True)
    proc.record_replay(ok=True)
    proc.record_replay(ok=True)
    assert proc.status is ProcedureStatus.QUARANTINE  # never self-promotes


# === Validation ===

def test_postcondition_is_required_to_compile():
    proc = make_procedure(postcondition=None)
    problems = proc.validate()
    assert any("postcondition" in p for p in problems)
    assert not proc.is_compilable


def test_uncheckable_postcondition_is_rejected():
    proc = make_procedure(postcondition=Condition(description="looks right"))
    assert any("postcondition" in p for p in proc.validate())


def test_undeclared_arg_reference_is_caught():
    proc = make_procedure(
        steps=[
            Step(kind=StepKind.FILL, selector="#title", value="$title"),
            Step(kind=StepKind.FILL, selector="#body", value="$body"),
            Step(kind=StepKind.CLICK, selector="[data-testid=publish]"),
        ],
    )
    assert any("$body" in p for p in proc.validate())


def test_unused_declared_arg_is_caught():
    proc = make_procedure(
        args=[
            ArgSpec(name="title"),
            ArgSpec(name="unused_thing"),
        ],
    )
    assert any("unused_thing" in p for p in proc.validate())


def test_valid_procedure_is_compilable():
    assert make_procedure().is_compilable


# === Identity / the join ===

def test_code_pointer_matches_automation_schema_shape():
    proc = make_procedure(site="etsy", action="list_item")
    assert proc.qualified_name == "etsy.list_item"
    assert proc.code_pointer == "sdk.etsy.list_item"


# === Runtime ===

def test_run_procedure_executes_steps_and_checks_postcondition():
    proc = make_procedure()
    driver = FakeDriver(present={"#title": "", "[data-testid=publish]": "", ".published": "live"})
    run_procedure(proc, driver, {"title": "Hello"})

    assert ("fill", "#title", "Hello") in driver.calls
    assert ("click", "[data-testid=publish]") in driver.calls


def test_postcondition_catches_silent_breakage():
    """Steps all succeed, nothing actually happened. The whole point."""
    proc = make_procedure()
    driver = FakeDriver(present={"#title": "", "[data-testid=publish]": ""})  # no .published

    with pytest.raises(PostconditionFailed, match="postcondition failed"):
        run_procedure(proc, driver, {"title": "Hello"})


def test_precondition_failure_is_distinct_from_step_failure():
    proc = make_procedure(
        precondition=Condition(description="on the editor", selector="#editor"),
    )
    driver = FakeDriver(present={"#title": "", "[data-testid=publish]": "", ".published": "live"})
    with pytest.raises(PreconditionFailed):
        run_procedure(proc, driver, {"title": "Hello"})


def test_step_failure_reports_which_step():
    proc = make_procedure()
    driver = FakeDriver(present={"#title": ""})  # publish button missing
    with pytest.raises(StepFailed) as excinfo:
        run_procedure(proc, driver, {"title": "Hello"})
    assert excinfo.value.index == 2


def test_missing_required_arg_raises_before_touching_the_page():
    proc = make_procedure()
    driver = FakeDriver()
    with pytest.raises(TypeError, match="missing required argument"):
        run_procedure(proc, driver, {})
    assert driver.calls == []


def test_extract_returns_named_values():
    proc = make_procedure(
        steps=[
            Step(kind=StepKind.FILL, selector="#title", value="$title"),
            Step(kind=StepKind.CLICK, selector="[data-testid=publish]"),
            Step(kind=StepKind.EXTRACT, selector=".listing-id", note="listing_id"),
        ],
        returns={"listing_id": "the new listing id"},
    )
    driver = FakeDriver(present={
        "#title": "", "[data-testid=publish]": "", ".published": "live",
        ".listing-id": "ABC-123",
    })
    result = run_procedure(proc, driver, {"title": "Hello"})
    assert result == {"listing_id": "ABC-123"}


def test_replay_never_raises_and_records_outcome():
    proc = make_procedure()
    driver = FakeDriver(present={"#title": ""})  # will fail

    ok, error, duration = replay(proc, driver, {"title": "x"})
    assert ok is False
    assert error
    assert duration >= 0
    assert proc.consecutive_failures == 1
    assert proc.replays[-1].ok is False


# === Recording ===

def test_recording_driver_captures_the_trace_as_a_by_product():
    rec = TraceRecorder("demo", "publish", explored_by="test")
    inner = FakeDriver(present={"#title": "", "[data-testid=publish]": "", ".published": "live"})
    driver = RecordingDriver(inner, rec)

    driver.navigate("https://example.com/new")
    driver.fill("#title", "My First Post")
    driver.click("[data-testid=publish]")

    assert [s.kind for s in rec.steps] == [
        StepKind.NAVIGATE, StepKind.FILL, StepKind.CLICK,
    ]
    assert rec.steps[1].value == "My First Post"


def test_parameterize_inverts_a_literal_into_an_argument():
    """The INVERT step: one concrete run becomes a generator."""
    rec = TraceRecorder("demo", "publish")
    rec.record(StepKind.FILL, selector="#title", value="My First Post")

    count = rec.parameterize("My First Post", "title", description="post title")
    assert count == 1
    assert rec.steps[0].value == "$title"
    assert [a.name for a in rec.args] == ["title"]


def test_record_raw_ingests_injected_js_entries():
    rec = TraceRecorder("demo", "publish")
    rec.record_raw([
        {"kind": "click", "selector": "[data-testid=new]", "value": None},
        {"kind": "fill", "selector": "#title", "value": "Hello"},
        {"kind": "nonsense", "selector": "#x"},  # unknown kinds are skipped
    ])
    assert len(rec.steps) == 2


def test_recorder_rejects_coordinates_from_raw_entries():
    rec = TraceRecorder("demo", "publish")
    with pytest.raises(ValueError, match="coordinates"):
        rec.record_raw([{"kind": "click", "selector": "(847, 392)"}])


# === Codegen ===

def test_generate_function_refuses_non_golden(tmp_path):
    proc = make_procedure()
    with pytest.raises(ValueError, match="not golden"):
        generate_function(proc, sdk_dir=tmp_path)


def test_generate_function_writes_callable_and_replay_test(tmp_path):
    proc = make_procedure()
    proc.record_replay(ok=True)
    proc.promote(verified_by="isaac")

    fn_path, test_path = generate_function(proc, sdk_dir=tmp_path)

    assert fn_path.name == "publish.py"
    assert test_path.name == "test_publish_replay.py"

    source = fn_path.read_text()
    assert "def publish(driver, *, title: str)" in source
    assert 'CODE_POINTER = "sdk.demo.publish"' in source
    assert "DO NOT EDIT BY HAND" in source

    test_source = test_path.read_text()
    assert "REPLACE_ME" in test_source  # unfilled replay args fail loudly


def test_generated_function_actually_runs(tmp_path):
    """The compiled artifact is executable, not just text."""
    proc = make_procedure()
    proc.record_replay(ok=True)
    proc.promote(verified_by="isaac")
    generate_site([proc], "demo", sdk_dir=tmp_path)

    sys.path.insert(0, str(tmp_path))
    try:
        for mod in [m for m in sys.modules if m.startswith("demo")]:
            del sys.modules[mod]
        import demo  # noqa

        driver = FakeDriver(present={
            "#title": "", "[data-testid=publish]": "", ".published": "live",
        })
        demo.publish(driver, title="Compiled!")
        assert ("fill", "#title", "Compiled!") in driver.calls
        assert demo.CODE_POINTERS["publish"] == "sdk.demo.publish"
    finally:
        sys.path.remove(str(tmp_path))


def test_generate_site_skips_non_golden_without_failing(tmp_path, capsys):
    golden = make_procedure(action="publish")
    golden.record_replay(ok=True)
    golden.promote(verified_by="isaac")
    candidate = make_procedure(action="draft")

    generate_site([golden, candidate], "demo", sdk_dir=tmp_path)

    assert (tmp_path / "demo" / "publish.py").exists()
    assert not (tmp_path / "demo" / "draft.py").exists()
    # Stream-agnostic: sdna's asyncio_mode="auto" shifts which stream capsys
    # attributes progress output to. What matters is that the skip is reported.
    captured = capsys.readouterr()
    assert "skip demo.draft" in (captured.out + captured.err)


# === Builder ===

def test_builder_pipeline_end_to_end(tmp_path):
    repo = InMemoryProcedureRepository()
    builder = SdkBuilder(repo, sdk_dir=tmp_path)

    inner = FakeDriver(present={"#title": "", "[data-testid=publish]": "", ".published": "live"})
    builder.begin("demo", "publish", inner_driver=inner, explored_by="agent")
    builder.driver.navigate("https://example.com/new")
    builder.driver.fill("#title", "First Post")
    builder.driver.click("[data-testid=publish]")
    builder.recorder.parameterize("First Post", "title")

    proc = builder.finish(
        postcondition=Condition(description="live", selector=".published"),
        save_trace=False,
    )
    assert proc.status is ProcedureStatus.CANDIDATE

    ok, _ = builder.verify("demo", "publish", FakeDriver(present=dict(inner.present)),
                           {"title": "Replay"})
    assert ok
    assert repo.get_by_name("demo", "publish").status is ProcedureStatus.QUARANTINE

    assert [p.qualified_name for p in builder.pending_promotion()] == ["demo.publish"]

    builder.promote("demo", "publish", verified_by="isaac")
    assert builder.code_pointers() == {"demo.publish": "sdk.demo.publish"}

    builder.compile()
    assert (tmp_path / "demo" / "publish.py").exists()


def test_builder_requires_postcondition_at_finish(tmp_path):
    builder = SdkBuilder(InMemoryProcedureRepository(), sdk_dir=tmp_path)
    builder.begin("demo", "publish", inner_driver=FakeDriver())
    with pytest.raises(ValueError, match="postcondition"):
        builder.finish(save_trace=False)


def test_builder_refuses_concurrent_recordings(tmp_path):
    builder = SdkBuilder(InMemoryProcedureRepository(), sdk_dir=tmp_path)
    builder.begin("demo", "publish")
    with pytest.raises(RuntimeError, match="already recording"):
        builder.begin("demo", "other")


def test_status_report_groups_by_status(tmp_path):
    repo = InMemoryProcedureRepository()
    builder = SdkBuilder(repo, sdk_dir=tmp_path)

    golden = make_procedure(action="publish")
    golden.record_replay(ok=True)
    golden.promote(verified_by="isaac")
    repo.save(golden)
    repo.save(make_procedure(action="draft"))

    report = builder.status_report()
    assert report["golden"] == ["demo.publish"]
    assert report["candidate"] == ["demo.draft"]


# === Immune system ===

def test_immune_demotes_after_threshold_and_recompiles(tmp_path):
    repo = InMemoryProcedureRepository()
    proc = make_procedure()
    proc.record_replay(ok=True)
    proc.promote(verified_by="isaac")
    repo.save(proc)

    SdkBuilder(repo, sdk_dir=tmp_path).compile(site="demo")
    assert (tmp_path / "demo" / "publish.py").exists()

    # The site changed: the publish button is gone.
    broken = {"#title": ""}
    immune = ImmuneSystem(
        repo,
        driver_factory=lambda: FakeDriver(present=dict(broken)),
        replay_args={"demo.publish": {"title": "x"}},
        failure_threshold=2,
        sdk_dir=tmp_path,
    )

    first = immune.sweep()
    assert first.failed == ["demo.publish"]
    assert first.demoted == []            # one bad minute is not a verdict
    assert not first.healthy

    second = immune.sweep()
    assert second.demoted == ["demo.publish"]
    assert second.recompiled == ["demo"]
    assert repo.get_by_name("demo", "publish").status is ProcedureStatus.DEMOTED
    # Demoted function is gone from the SDK rather than lingering as a trap.
    assert "publish" not in (tmp_path / "demo" / "__init__.py").read_text()


def test_immune_never_promotes():
    """Demotion is automatic; promotion is not. The asymmetry is the point."""
    repo = InMemoryProcedureRepository()
    proc = make_procedure()
    repo.save(proc)  # CANDIDATE

    immune = ImmuneSystem(
        repo,
        driver_factory=lambda: FakeDriver(present={
            "#title": "", "[data-testid=publish]": "", ".published": "live",
        }),
        replay_args={"demo.publish": {"title": "x"}},
    )
    immune.sweep()  # sweeps golden only; candidate untouched
    assert repo.get_by_name("demo", "publish").status is ProcedureStatus.CANDIDATE

    ok, _ = immune.check(proc)
    assert ok
    assert proc.status is ProcedureStatus.QUARANTINE  # never GOLDEN


def test_immune_skips_rather_than_fails_when_replay_args_missing():
    """'never checked' and 'broken' are different facts."""
    repo = InMemoryProcedureRepository()
    proc = make_procedure()
    proc.record_replay(ok=True)
    proc.promote(verified_by="isaac")
    repo.save(proc)

    immune = ImmuneSystem(repo, driver_factory=lambda: FakeDriver(), replay_args={})
    result = immune.sweep(recompile=False)

    assert result.checked == []
    assert "demo.publish" in result.skipped
    assert result.failed == []
    assert repo.get_by_name("demo", "publish").status is ProcedureStatus.GOLDEN


def test_needs_reexploration_keeps_provenance_for_a_warm_restart():
    repo = InMemoryProcedureRepository()
    proc = make_procedure()
    proc.provenance.trace_path = "/tmp/traces/demo.publish.json"
    proc.record_replay(ok=True)
    proc.promote(verified_by="isaac")
    proc.demote("button gone")
    repo.save(proc)

    queued = ImmuneSystem(repo).needs_reexploration()
    assert [p.qualified_name for p in queued] == ["demo.publish"]
    assert queued[0].provenance.trace_path == "/tmp/traces/demo.publish.json"


def test_fire_replay_sweep_reports_unverified_without_a_driver(tmp_path):
    """A sweep that cannot drive a browser must not claim to have checked."""
    from sdna.selfbot_extensions.application.immune import fire_replay_sweep
    from sdna.selfbot_extensions.infrastructure.procedure_storage import JsonProcedureRepository

    repo = JsonProcedureRepository(str(tmp_path / "procedures"))
    proc = make_procedure()
    proc.record_replay(ok=True)
    proc.promote(verified_by="isaac")
    repo.save(proc)

    result = fire_replay_sweep(
        storage_dir=str(tmp_path / "procedures"), sdk_dir=str(tmp_path / "sdk"),
    )
    assert result["checked"] == []
    assert result["skipped"]["demo.publish"] == "no driver_factory configured"


# === Round trip ===

def test_procedure_survives_serialization():
    proc = make_procedure(
        precondition=Condition(description="editor open", selector="#editor"),
        steps=[
            Step(kind=StepKind.FILL, selector="#title", value="$title"),
            Step(kind=StepKind.CLICK, selector="[data-testid=publish]"),
            Step(kind=StepKind.EXTRACT, selector=".listing-id", note="listing_id"),
        ],
        returns={"listing_id": "id"},
        tags=["etsy", "listing"],
    )
    proc.record_replay(ok=True)
    proc.promote(verified_by="isaac")

    restored = Procedure.from_dict(proc.to_dict())

    assert restored.qualified_name == proc.qualified_name
    assert restored.status is ProcedureStatus.GOLDEN
    assert restored.promoted_by == "isaac"
    assert [s.kind for s in restored.steps] == [s.kind for s in proc.steps]
    assert [a.name for a in restored.args] == [a.name for a in proc.args]
    assert restored.precondition.selector == "#editor"
    assert len(restored.replays) == 1


def test_supersede_drops_back_to_candidate():
    proc = make_procedure()
    proc.record_replay(ok=True)
    proc.promote(verified_by="isaac")

    proc.supersede(steps=[Step(kind=StepKind.CLICK, selector="#new-button")])
    assert proc.version == 2
    assert proc.status is ProcedureStatus.CANDIDATE
    assert proc.promoted_by is None
