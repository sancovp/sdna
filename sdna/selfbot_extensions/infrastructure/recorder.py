"""
Recorder - Captures an exploration run as a replayable trace.

Infrastructure layer: turns "an agent figured out how to do a thing" into a
Procedure, without the agent having to write one by hand.

Two ways in, because exploration happens two ways:

  RecordingDriver  - the agent drives the page through a PageDriver, and the
                     trace falls out for free. Exploration and recording are
                     the same act; there is no separate "now write it down"
                     step to forget.

  attach_recorder  - a human (or a pixel-clicking agent) drives the browser
                     directly, and injected JS captures each interaction with
                     a durable selector.

Both record SELECTORS, never coordinates. The selector heuristic below is the
substance of this module: a trace of `click("[data-testid=submit]")` survives a
redesign and reads clearly in a diff, while `click(847, 392)` is worthless the
moment anything moves.
"""

import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from ..domain.procedure import (
    Procedure, Step, StepKind, ArgSpec, Condition, Provenance, PageDriver,
)

logger = logging.getLogger(__name__)

DEFAULT_TRACE_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "selfbot" / "traces"


# Injected into the page to derive a durable selector for a clicked element.
# Priority order is the whole point: test hooks, then stable semantic
# attributes, then text, and only then a structural path.
SELECTOR_JS = """
(function () {
  window.__selfbotTrace = window.__selfbotTrace || [];

  function quote(v) { return String(v).replace(/"/g, '\\\\"'); }

  function selectorFor(el) {
    if (!el || el.nodeType !== 1) return null;

    for (const attr of ['data-testid', 'data-test', 'data-cy', 'data-qa']) {
      const v = el.getAttribute(attr);
      if (v) return '[' + attr + '="' + quote(v) + '"]';
    }

    // Ids that look generated (long hex, react/ember style) are not stable.
    const id = el.getAttribute('id');
    if (id && !/^[0-9]/.test(id) && !/[0-9a-f]{8,}/i.test(id) && !/^(ember|react|radix|mui)-/i.test(id)) {
      return '#' + id;
    }

    const name = el.getAttribute('name');
    if (name) return el.tagName.toLowerCase() + '[name="' + quote(name) + '"]';

    const aria = el.getAttribute('aria-label');
    if (aria) return '[aria-label="' + quote(aria) + '"]';

    const tag = el.tagName.toLowerCase();
    if (tag === 'button' || tag === 'a' || el.getAttribute('role') === 'button') {
      const text = (el.innerText || '').trim().split('\\n')[0];
      if (text && text.length <= 60) return 'text=' + text;
    }

    const ph = el.getAttribute('placeholder');
    if (ph) return '[placeholder="' + quote(ph) + '"]';

    // Structural fallback - least durable, recorded so the trace is never empty.
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 5) {
      let part = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const sibs = Array.from(parent.children).filter(c => c.tagName === node.tagName);
        if (sibs.length > 1) part += ':nth-of-type(' + (sibs.indexOf(node) + 1) + ')';
      }
      parts.unshift(part);
      if (node.id || node === document.body) break;
      node = parent;
    }
    return parts.join(' > ');
  }

  function push(kind, el, value) {
    const sel = selectorFor(el);
    if (!sel) return;
    window.__selfbotTrace.push({
      kind: kind,
      selector: sel,
      value: value === undefined ? null : value,
      url: location.href,
      at: Date.now()
    });
  }

  document.addEventListener('click', function (e) {
    push('click', e.target);
  }, true);

  document.addEventListener('change', function (e) {
    const el = e.target;
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'select') push('select', el, el.value);
    else if (tag === 'input' || tag === 'textarea') {
      if (el.type === 'file') push('upload', el, (el.files && el.files[0] && el.files[0].name) || '');
      else push('fill', el, el.value);
    }
  }, true);

  return true;
})();
"""


class TraceRecorder:
    """
    Accumulates recorded steps and turns them into a Procedure.

    Pure - no browser required, which is what makes the whole pipeline testable
    without a live site.
    """

    def __init__(self, site: str, action: str, explored_by: str = "",
                 description: str = ""):
        self.site = site
        self.action = action
        self.explored_by = explored_by
        self.description = description
        self.steps: List[Step] = []
        self.args: List[ArgSpec] = []
        self.returns: Dict[str, str] = {}
        self.precondition: Optional[Condition] = None
        self.postcondition: Optional[Condition] = None
        self.started_at = datetime.now()
        self.source_url: Optional[str] = None

    # === Recording ===

    def record(self, kind, selector: Optional[str] = None,
               value: Optional[str] = None, url: Optional[str] = None,
               note: str = "", timeout_ms: int = 10_000) -> Step:
        """Append one step. Step's own validation rejects coordinates."""
        step = Step(kind=kind, selector=selector, value=value, url=url,
                    note=note, timeout_ms=timeout_ms)
        self.steps.append(step)
        if kind is StepKind.NAVIGATE and self.source_url is None:
            self.source_url = url
        return step

    def record_raw(self, entries: List[dict]) -> List[Step]:
        """Ingest raw entries captured by the injected JS."""
        made = []
        for entry in entries:
            try:
                kind = StepKind(entry["kind"])
            except (KeyError, ValueError):
                logger.debug("skipping unrecognized trace entry: %r", entry)
                continue
            made.append(self.record(
                kind=kind,
                selector=entry.get("selector"),
                value=entry.get("value"),
                url=entry.get("url") if kind is StepKind.NAVIGATE else None,
            ))
        return made

    # === Parameterization ===

    def parameterize(self, literal: str, arg_name: str, type: str = "str",
                     description: str = "", required: bool = True) -> int:
        """
        Replace a recorded literal with a $arg reference everywhere it appears.

        This is the INVERT step: the recorded trace was a single concrete run,
        and naming its literals is what turns it into a generator. Returns the
        number of substitutions made.
        """
        if not any(a.name == arg_name for a in self.args):
            self.args.append(ArgSpec(
                name=arg_name, type=type, description=description,
                required=required,
            ))

        token = f"${arg_name}"
        count = 0
        for step in self.steps:
            if step.value and literal in step.value:
                step.value = step.value.replace(literal, token)
                count += 1
            if step.url and literal in step.url:
                step.url = step.url.replace(literal, token)
                count += 1
        if count == 0:
            logger.warning("parameterize: literal %r not found in any step", literal)
        return count

    def extract(self, selector: str, name: str, description: str = "") -> Step:
        """Record an EXTRACT step producing a named return value."""
        self.returns[name] = description
        return self.record(StepKind.EXTRACT, selector=selector, note=name)

    def expect(self, selector: str, contains: Optional[str] = None) -> Step:
        return self.record(StepKind.EXPECT, selector=selector, value=contains)

    def set_precondition(self, description: str = "", selector: Optional[str] = None,
                         expect_text: Optional[str] = None,
                         expect_url: Optional[str] = None) -> Condition:
        self.precondition = Condition(description=description, selector=selector,
                                      expect_text=expect_text, expect_url=expect_url)
        return self.precondition

    def set_postcondition(self, description: str = "", selector: Optional[str] = None,
                          expect_text: Optional[str] = None,
                          expect_url: Optional[str] = None) -> Condition:
        """
        The postcondition is not optional in practice - validate() refuses to
        compile without a checkable one, because it is the only thing that
        distinguishes success from silent breakage.
        """
        self.postcondition = Condition(description=description, selector=selector,
                                       expect_text=expect_text, expect_url=expect_url)
        return self.postcondition

    # === Output ===

    def to_procedure(self) -> Procedure:
        return Procedure(
            site=self.site,
            action=self.action,
            description=self.description,
            args=list(self.args),
            steps=list(self.steps),
            returns=dict(self.returns),
            precondition=self.precondition,
            postcondition=self.postcondition,
            provenance=Provenance(
                explored_at=self.started_at,
                explored_by=self.explored_by,
                source_url=self.source_url,
                trace_path=None,
            ),
        )

    def save_trace(self, trace_dir: Path = DEFAULT_TRACE_DIR) -> Path:
        """
        Persist the raw trace. Kept because a demoted procedure has to be
        re-explored, and starting from the last trace is cheaper than starting
        from nothing.
        """
        trace_dir = Path(trace_dir)
        trace_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        path = trace_dir / f"{self.site}.{self.action}.{stamp}.json"
        path.write_text(json.dumps({
            "site": self.site,
            "action": self.action,
            "explored_by": self.explored_by,
            "started_at": self.started_at.isoformat(),
            "source_url": self.source_url,
            "steps": [s.to_dict() for s in self.steps],
        }, indent=2))
        return path

    def __repr__(self):
        return f"TraceRecorder({self.site}.{self.action}, {len(self.steps)} steps)"


class RecordingDriver(PageDriver):
    """
    A PageDriver that records everything it is asked to do.

    Wrap the real driver in this while an agent explores, and the trace is a
    by-product of the exploration rather than a separate chore:

        rec = TraceRecorder("etsy", "list_item")
        driver = RecordingDriver(PlaywrightDriver(page), rec)
        ... agent explores through `driver` ...
        procedure = rec.to_procedure()
    """

    def __init__(self, inner: PageDriver, recorder: TraceRecorder,
                 record_reads: bool = False):
        self.inner = inner
        self.recorder = recorder
        # Reads (exists/text_of) are usually the agent looking around, not part
        # of the procedure. Off by default so traces stay clean.
        self.record_reads = record_reads

    def navigate(self, url: str, timeout_ms: int = 10_000) -> None:
        self.inner.navigate(url, timeout_ms)
        self.recorder.record(StepKind.NAVIGATE, url=url, timeout_ms=timeout_ms)

    def click(self, selector: str, timeout_ms: int = 10_000) -> None:
        self.inner.click(selector, timeout_ms)
        self.recorder.record(StepKind.CLICK, selector=selector, timeout_ms=timeout_ms)

    def fill(self, selector: str, value: str, timeout_ms: int = 10_000) -> None:
        self.inner.fill(selector, value, timeout_ms)
        self.recorder.record(StepKind.FILL, selector=selector, value=value,
                             timeout_ms=timeout_ms)

    def select(self, selector: str, value: str, timeout_ms: int = 10_000) -> None:
        self.inner.select(selector, value, timeout_ms)
        self.recorder.record(StepKind.SELECT, selector=selector, value=value,
                             timeout_ms=timeout_ms)

    def press(self, selector: str, key: str, timeout_ms: int = 10_000) -> None:
        self.inner.press(selector, key, timeout_ms)
        self.recorder.record(StepKind.PRESS, selector=selector, value=key,
                             timeout_ms=timeout_ms)

    def upload(self, selector: str, path: str, timeout_ms: int = 10_000) -> None:
        self.inner.upload(selector, path, timeout_ms)
        self.recorder.record(StepKind.UPLOAD, selector=selector, value=path,
                             timeout_ms=timeout_ms)

    def wait_for(self, selector: str, timeout_ms: int = 10_000) -> None:
        self.inner.wait_for(selector, timeout_ms)
        self.recorder.record(StepKind.WAIT_FOR, selector=selector,
                             timeout_ms=timeout_ms)

    def exists(self, selector: str, timeout_ms: int = 10_000) -> bool:
        result = self.inner.exists(selector, timeout_ms)
        if self.record_reads and result:
            self.recorder.record(StepKind.EXPECT, selector=selector,
                                 timeout_ms=timeout_ms)
        return result

    def text_of(self, selector: str, timeout_ms: int = 10_000) -> str:
        value = self.inner.text_of(selector, timeout_ms)
        if self.record_reads:
            self.recorder.record(StepKind.EXTRACT, selector=selector,
                                 note=selector, timeout_ms=timeout_ms)
        return value

    def current_url(self) -> str:
        return self.inner.current_url()


def attach_recorder(page) -> bool:
    """
    Inject the JS capture listener into a live Playwright page.

    Use when the browser is driven directly (a human logging in, or an agent
    pixel-clicking) rather than through a RecordingDriver. Re-injects on every
    navigation so the trace survives page changes.
    """
    try:
        page.add_init_script(SELECTOR_JS)
        page.evaluate(SELECTOR_JS)
        return True
    except Exception as e:
        logger.warning("failed to attach recorder: %s", e)
        return False


def drain_recorder(page) -> List[dict]:
    """Pull and clear the entries captured by the injected listener."""
    try:
        entries = page.evaluate(
            "(() => { const t = window.__selfbotTrace || []; "
            "window.__selfbotTrace = []; return t; })()"
        )
        return entries or []
    except Exception as e:
        logger.warning("failed to drain recorder: %s", e)
        return []


def load_trace(path: Path) -> TraceRecorder:
    """Rehydrate a saved trace into a recorder for re-parameterization."""
    data = json.loads(Path(path).read_text())
    rec = TraceRecorder(
        site=data["site"],
        action=data["action"],
        explored_by=data.get("explored_by", ""),
    )
    rec.started_at = datetime.fromisoformat(data["started_at"])
    rec.source_url = data.get("source_url")
    rec.steps = [Step.from_dict(s) for s in data.get("steps", [])]
    return rec
