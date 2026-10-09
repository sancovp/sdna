"""
Procedure Runtime - Executes a Procedure against a PageDriver.

Infrastructure layer: the interpreter for the domain's step language, plus the
Playwright adapter that implements PageDriver.

Generated SDK functions stay thin by delegating here. That is deliberate: the
generated file should be readable at a glance (signature, docstring, one call),
because a human has to be able to diff it when a site changes. All the
machinery lives in one place that gets fixed once.
"""

import logging
import time
from datetime import datetime
from string import Template
from typing import Optional, Dict, Any

from ..domain.procedure import (
    Procedure, Step, StepKind, Condition, PageDriver,
)

logger = logging.getLogger(__name__)


class PreconditionFailed(RuntimeError):
    """The page was not where the procedure expected to start."""


class PostconditionFailed(RuntimeError):
    """
    The steps ran without error but the observable outcome did not happen.

    This is the important failure. A procedure whose steps all "succeed" while
    achieving nothing is exactly the silent breakage the postcondition exists
    to catch.
    """


class StepFailed(RuntimeError):
    """A step could not be executed."""

    def __init__(self, index: int, step: Step, cause: Exception):
        self.index = index
        self.step = step
        self.cause = cause
        super().__init__(f"step {index} ({step.kind.value} {step.selector or step.url!r}): {cause}")


def _render(text: Optional[str], args: Dict[str, Any]) -> Optional[str]:
    """Interpolate $name references against the call's arguments."""
    if text is None:
        return None
    return Template(text).safe_substitute(
        {k: ("" if v is None else str(v)) for k, v in args.items()}
    )


def check_condition(driver: PageDriver, condition: Optional[Condition],
                    args: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
    """
    Evaluate a Condition against the live page.

    Returns (ok, reason). A condition with nothing checkable passes vacuously -
    validate() is what refuses to compile those, not this.
    """
    if condition is None or not condition.is_checkable:
        return True, ""

    args = args or {}

    if condition.expect_url:
        want = _render(condition.expect_url, args)
        got = driver.current_url()
        if want not in got:
            return False, f"url {got!r} does not contain {want!r}"

    if condition.selector:
        selector = _render(condition.selector, args)
        if not driver.exists(selector):
            return False, f"selector {selector!r} not present"

        if condition.expect_text:
            want = _render(condition.expect_text, args)
            got = driver.text_of(selector)
            if want not in got:
                return False, f"text of {selector!r} is {got!r}, expected to contain {want!r}"

    elif condition.expect_text:
        return False, "expect_text given with no selector to read it from"

    return True, ""


def execute_step(driver: PageDriver, step: Step, args: Dict[str, Any]) -> Optional[tuple[str, str]]:
    """
    Run one step. Returns (name, value) if the step extracts something.
    """
    selector = _render(step.selector, args)
    value = _render(step.value, args)
    url = _render(step.url, args)
    t = step.timeout_ms

    if step.kind is StepKind.NAVIGATE:
        driver.navigate(url, t)
    elif step.kind is StepKind.CLICK:
        driver.click(selector, t)
    elif step.kind is StepKind.FILL:
        driver.fill(selector, value or "", t)
    elif step.kind is StepKind.SELECT:
        driver.select(selector, value or "", t)
    elif step.kind is StepKind.PRESS:
        driver.press(selector, value or "Enter", t)
    elif step.kind is StepKind.UPLOAD:
        driver.upload(selector, value or "", t)
    elif step.kind is StepKind.WAIT_FOR:
        driver.wait_for(selector, t)
    elif step.kind is StepKind.EXPECT:
        if not driver.exists(selector, t):
            raise AssertionError(f"expected {selector!r} to exist")
        if value:
            got = driver.text_of(selector, t)
            if value not in got:
                raise AssertionError(f"expected {selector!r} to contain {value!r}, got {got!r}")
    elif step.kind is StepKind.EXTRACT:
        name = step.note or "value"
        return name, driver.text_of(selector, t)
    else:
        raise ValueError(f"unhandled step kind: {step.kind}")

    return None


def run_procedure(procedure: Procedure, driver: PageDriver,
                  args: Optional[Dict[str, Any]] = None,
                  check_pre: bool = True) -> Dict[str, Any]:
    """
    Execute a procedure end to end.

    1. check precondition   (are we where this starts?)
    2. run every step
    3. check postcondition  (did the thing actually happen?)

    Returns the dict of EXTRACT results. Raises PreconditionFailed,
    StepFailed, or PostconditionFailed.
    """
    args = dict(args or {})

    # Fill defaults and enforce required args before touching the page.
    for spec in procedure.args:
        if spec.name not in args:
            if spec.required and spec.default is None:
                raise TypeError(
                    f"{procedure.qualified_name} missing required argument: {spec.name}"
                )
            args[spec.name] = spec.default

    if check_pre:
        ok, why = check_condition(driver, procedure.precondition, args)
        if not ok:
            raise PreconditionFailed(f"{procedure.qualified_name}: {why}")

    extracted: Dict[str, Any] = {}
    for i, step in enumerate(procedure.steps):
        try:
            result = execute_step(driver, step, args)
        except Exception as e:
            raise StepFailed(i, step, e) from e
        if result:
            extracted[result[0]] = result[1]

    ok, why = check_condition(driver, procedure.postcondition, args)
    if not ok:
        raise PostconditionFailed(
            f"{procedure.qualified_name}: steps ran but postcondition failed - {why}"
        )

    return extracted


def replay(procedure: Procedure, driver: PageDriver,
           args: Optional[Dict[str, Any]] = None) -> tuple[bool, str, float]:
    """
    Run a procedure as a TEST and record the outcome on it.

    This is what the immune system calls. Never raises - a replay that blows up
    is a data point, not an incident. Returns (ok, error, duration_seconds).
    """
    started = time.time()
    ok, error = True, ""
    try:
        run_procedure(procedure, driver, args)
    except Exception as e:
        ok = False
        error = f"{type(e).__name__}: {e}"
        logger.warning("replay failed for %s: %s", procedure.qualified_name, error)

    duration = time.time() - started
    procedure.record_replay(ok=ok, error=error, duration_seconds=duration,
                            at=datetime.now())
    return ok, error, duration


class PlaywrightDriver(PageDriver):
    """
    PageDriver over a Playwright (or CloakBrowser) page.

    CloakBrowser is a drop-in Playwright replacement, so swapping to it is a
    change of how the page is created, not of this class.
    """

    def __init__(self, page):
        self.page = page

    def navigate(self, url: str, timeout_ms: int = 10_000) -> None:
        self.page.goto(url, timeout=timeout_ms)

    def click(self, selector: str, timeout_ms: int = 10_000) -> None:
        self.page.click(selector, timeout=timeout_ms)

    def fill(self, selector: str, value: str, timeout_ms: int = 10_000) -> None:
        self.page.fill(selector, value, timeout=timeout_ms)

    def select(self, selector: str, value: str, timeout_ms: int = 10_000) -> None:
        self.page.select_option(selector, value, timeout=timeout_ms)

    def press(self, selector: str, key: str, timeout_ms: int = 10_000) -> None:
        self.page.press(selector, key, timeout=timeout_ms)

    def upload(self, selector: str, path: str, timeout_ms: int = 10_000) -> None:
        self.page.set_input_files(selector, path, timeout=timeout_ms)

    def wait_for(self, selector: str, timeout_ms: int = 10_000) -> None:
        self.page.wait_for_selector(selector, timeout=timeout_ms)

    def exists(self, selector: str, timeout_ms: int = 10_000) -> bool:
        try:
            self.page.wait_for_selector(selector, timeout=timeout_ms)
            return True
        except Exception:
            return False

    def text_of(self, selector: str, timeout_ms: int = 10_000) -> str:
        return self.page.inner_text(selector, timeout=timeout_ms)

    def current_url(self) -> str:
        return self.page.url
