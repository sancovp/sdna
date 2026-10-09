"""
ImmuneSystem - Keeps the SDK honest as sites change.

Application layer: replays every golden procedure on a schedule, demotes the
ones that no longer work, and recompiles the SDK without them.

Why this exists. A compiled SDK is a frozen claim about a site that keeps
changing underneath it. Without a sweep, the failure mode is not an exception -
it is `etsy.list_item()` reporting success while listing nothing, for weeks.
The postcondition is what detects that, and this is what runs the postcondition
on a clock.

The asymmetry is deliberate and matches the rest of the ecosystem:

    demotion is AUTOMATIC   - removing a broken thing is safe and reversible
    promotion is HUMAN-ONLY - adding a trusted thing is an attestation

So this module can take a procedure out of the SDK, and can never put one back.
A demoted procedure re-enters the explore lane with its provenance intact, so
re-exploration starts from what the last run saw rather than from nothing.

Scheduling: `fire_replay_sweep` is a module-level callable, which is exactly
the shape AutomationSchema.code_pointer imports and calls:

    {"name": "selfbot_replay_sweep",
     "schedule": "0 4 * * *",
     "code_pointer": "selfbot.application.immune.fire_replay_sweep"}
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from ..domain.procedure import Procedure, ProcedureStatus, ProcedureRepository, PageDriver
from ..domain.procedure_codegen import DEFAULT_SDK_DIR
from ..infrastructure.procedure_runtime import replay

logger = logging.getLogger(__name__)

# Consecutive failed replays before a golden procedure leaves the SDK.
# Above 1 because sites have bad minutes; low because a broken SDK function is
# worse than a missing one.
DEFAULT_FAILURE_THRESHOLD = 2


@dataclass
class SweepResult:
    """What one sweep did. Reported, never inferred."""
    started_at: datetime
    finished_at: Optional[datetime] = None
    checked: List[str] = field(default_factory=list)
    passed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    demoted: List[str] = field(default_factory=list)
    skipped: Dict[str, str] = field(default_factory=dict)
    recompiled: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        return not self.failed and not self.demoted

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "checked": self.checked,
            "passed": self.passed,
            "failed": self.failed,
            "demoted": self.demoted,
            "skipped": self.skipped,
            "recompiled": self.recompiled,
            "errors": self.errors,
            "healthy": self.healthy,
        }

    def __repr__(self):
        return (
            f"SweepResult({len(self.passed)} passed, {len(self.failed)} failed, "
            f"{len(self.demoted)} demoted)"
        )


class ImmuneSystem:
    """
    Replays golden procedures and demotes the broken ones.

    `driver_factory` is a zero-arg callable returning a fresh PageDriver. It is
    a factory rather than a driver because each replay wants a clean page - a
    procedure that only passes when it inherits the previous one's state is not
    actually verified.

    `replay_args` supplies per-procedure arguments, keyed by qualified name. A
    procedure with required args and no entry is SKIPPED rather than failed:
    "we never checked this" and "this is broken" are different facts and
    collapsing them would make the sweep lie.
    """

    def __init__(
        self,
        procedure_repo: ProcedureRepository,
        driver_factory: Optional[Callable[[], PageDriver]] = None,
        replay_args: Optional[Dict[str, Dict[str, Any]]] = None,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        sdk_dir: Path = DEFAULT_SDK_DIR,
    ):
        self.procedure_repo = procedure_repo
        self.driver_factory = driver_factory
        self.replay_args = replay_args or {}
        self.failure_threshold = failure_threshold
        self.sdk_dir = Path(sdk_dir)

    def check(self, procedure: Procedure,
              driver: Optional[PageDriver] = None) -> tuple[bool, str]:
        """
        Replay one procedure and demote it if it has failed enough times.

        Returns (ok, error). Records the replay on the procedure either way.
        """
        if driver is None:
            if not self.driver_factory:
                raise RuntimeError("no driver and no driver_factory configured")
            driver = self.driver_factory()

        args = self.replay_args.get(procedure.qualified_name, {})
        ok, error, _duration = replay(procedure, driver, args)

        if not ok and procedure.consecutive_failures >= self.failure_threshold:
            procedure.demote(
                f"replay failed {procedure.consecutive_failures}x: {error}"
            )
            logger.warning(
                "demoted %s after %d consecutive failures",
                procedure.qualified_name, procedure.consecutive_failures,
            )

        self.procedure_repo.save(procedure)
        return ok, error

    def sweep(self, site: Optional[str] = None, recompile: bool = True) -> SweepResult:
        """
        Replay every golden procedure (optionally for one site only).

        Recompiles the SDK for any site that lost a procedure, so a demoted
        function stops being importable rather than lingering as a trap.
        """
        result = SweepResult(started_at=datetime.now())

        procedures = [
            p for p in self.procedure_repo.list_by_status(ProcedureStatus.GOLDEN)
            if site is None or p.site == site
        ]

        touched_sites = set()

        for procedure in procedures:
            name = procedure.qualified_name

            required = [a.name for a in procedure.args if a.required and a.default is None]
            supplied = self.replay_args.get(name, {})
            missing = [a for a in required if a not in supplied]
            if missing:
                result.skipped[name] = f"no replay args for: {', '.join(missing)}"
                logger.info("skipping %s: %s", name, result.skipped[name])
                continue

            result.checked.append(name)
            try:
                ok, error = self.check(procedure)
            except Exception as e:
                # A sweep never dies on one procedure.
                result.errors[name] = f"{type(e).__name__}: {e}"
                logger.exception("sweep error on %s", name)
                continue

            if ok:
                result.passed.append(name)
            else:
                result.failed.append(name)
                if procedure.status is ProcedureStatus.DEMOTED:
                    result.demoted.append(name)
                    touched_sites.add(procedure.site)

        if recompile and touched_sites:
            from .sdk_builder import SdkBuilder
            builder = SdkBuilder(self.procedure_repo, self.sdk_dir)
            for s in sorted(touched_sites):
                try:
                    builder.compile(site=s)
                    result.recompiled.append(s)
                except Exception as e:
                    result.errors[f"recompile:{s}"] = str(e)
                    logger.exception("recompile failed for %s", s)

        result.finished_at = datetime.now()
        logger.info("sweep finished: %r", result)
        return result

    def needs_reexploration(self) -> List[Procedure]:
        """
        Demoted procedures, i.e. the explore queue.

        This is the hand-back to the discovery channel: each of these is a
        thing the SDK used to do and no longer can, with a saved trace showing
        how it used to work.
        """
        return self.procedure_repo.list_by_status(ProcedureStatus.DEMOTED)


def fire_replay_sweep(
    storage_dir: Optional[str] = None,
    sdk_dir: Optional[str] = None,
    site: Optional[str] = None,
    replay_args: Optional[Dict[str, Dict[str, Any]]] = None,
    driver_factory: Optional[Callable[[], PageDriver]] = None,
    recompile: bool = True,
) -> dict:
    """
    Scheduled entry point - the SDK's immune sweep as a CronAutomation.

    Registered as `code_pointer` in an automation schema:

        {"name": "selfbot_replay_sweep",
         "schedule": "0 4 * * *",
         "code_pointer": "selfbot.application.immune.fire_replay_sweep",
         "code_args": {"site": "etsy"}}

    Returns the SweepResult as a dict. Without a `driver_factory` this reports
    every golden procedure as skipped rather than pretending to have checked
    them - a sweep that cannot drive a browser has verified nothing, and should
    say so.
    """
    from ..infrastructure.procedure_storage import (
        JsonProcedureRepository, DEFAULT_PROCEDURE_DIR,
    )

    repo = JsonProcedureRepository(storage_dir or DEFAULT_PROCEDURE_DIR)
    immune = ImmuneSystem(
        procedure_repo=repo,
        driver_factory=driver_factory,
        replay_args=replay_args,
        sdk_dir=Path(sdk_dir) if sdk_dir else DEFAULT_SDK_DIR,
    )

    if driver_factory is None:
        result = SweepResult(started_at=datetime.now())
        for procedure in repo.list_by_status(ProcedureStatus.GOLDEN):
            result.skipped[procedure.qualified_name] = "no driver_factory configured"
        result.finished_at = datetime.now()
        logger.warning(
            "replay sweep ran with no driver_factory: %d procedures unverified",
            len(result.skipped),
        )
        return result.to_dict()

    return immune.sweep(site=site, recompile=recompile).to_dict()
