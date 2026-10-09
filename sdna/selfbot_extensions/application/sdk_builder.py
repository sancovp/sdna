"""
SdkBuilder - Drives the explore -> record -> compile -> library pipeline.

Application layer: orchestrates domain objects with injected infrastructure.

This is the use-case surface an agent (or a human) actually touches:

    builder.begin("etsy", "list_item")      # start recording an exploration
    ... drive the site through builder.driver ...
    builder.finish(postcondition=...)       # -> CANDIDATE procedure, saved
    builder.verify("etsy", "list_item")     # replay -> QUARANTINE if green
    builder.promote("etsy", "list_item", verified_by="isaac")   # -> GOLDEN
    builder.compile()                       # -> sdk/etsy/list_item.py
"""

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from ..domain.procedure import (
    Procedure, ProcedureStatus, ProcedureRepository, PageDriver, Condition,
)
from ..domain.procedure_codegen import generate_all, generate_site, DEFAULT_SDK_DIR
from ..infrastructure.recorder import TraceRecorder, RecordingDriver
from ..infrastructure.procedure_runtime import replay

logger = logging.getLogger(__name__)


class SdkBuilder:
    """
    Turns exploration runs into a site SDK.

    Dependencies injected - doesn't know about JSON files, Playwright, or where
    the SDK is written.
    """

    def __init__(
        self,
        procedure_repo: ProcedureRepository,
        sdk_dir: Path = DEFAULT_SDK_DIR,
    ):
        self.procedure_repo = procedure_repo
        self.sdk_dir = Path(sdk_dir)

        # Live recording session, if any
        self.recorder: Optional[TraceRecorder] = None
        self.driver: Optional[RecordingDriver] = None

    # === Explore + record ===

    def begin(self, site: str, action: str, inner_driver: Optional[PageDriver] = None,
              explored_by: str = "", description: str = "") -> TraceRecorder:
        """
        Start recording an exploration.

        If `inner_driver` is given, `self.driver` becomes a RecordingDriver
        wrapping it - drive the site through that and the trace accumulates by
        itself.
        """
        if self.recorder is not None:
            raise RuntimeError(
                f"already recording {self.recorder.site}.{self.recorder.action}; "
                "call finish() or abandon() first"
            )

        self.recorder = TraceRecorder(
            site=site, action=action, explored_by=explored_by,
            description=description,
        )
        self.driver = RecordingDriver(inner_driver, self.recorder) if inner_driver else None
        logger.info("recording %s.%s", site, action)
        return self.recorder

    def finish(
        self,
        postcondition: Optional[Condition] = None,
        precondition: Optional[Condition] = None,
        save_trace: bool = True,
        supersede: bool = True,
    ) -> Procedure:
        """
        Close the recording and persist the resulting CANDIDATE procedure.

        A postcondition is required here rather than at compile time so the
        failure lands while the exploration is still fresh in mind - that is
        the only moment anyone actually knows what "it worked" looked like.
        """
        if self.recorder is None:
            raise RuntimeError("not recording; call begin() first")

        if postcondition is not None:
            self.recorder.postcondition = postcondition
        if precondition is not None:
            self.recorder.precondition = precondition

        if self.recorder.postcondition is None or not self.recorder.postcondition.is_checkable:
            raise ValueError(
                f"{self.recorder.site}.{self.recorder.action} has no checkable "
                "postcondition. Record what 'it worked' looks like now, while "
                "you can still see it - without it the replay test cannot tell "
                "success from silent breakage."
            )

        trace_path = self.recorder.save_trace() if save_trace else None
        procedure = self.recorder.to_procedure()
        if trace_path:
            procedure.provenance.trace_path = str(trace_path)

        existing = self.procedure_repo.get_by_name(procedure.site, procedure.action)
        if existing and supersede:
            existing.supersede(procedure.steps, procedure.provenance)
            existing.args = procedure.args
            existing.returns = procedure.returns
            existing.precondition = procedure.precondition
            existing.postcondition = procedure.postcondition
            procedure = existing

        self.procedure_repo.save(procedure)
        logger.info("recorded %s (%d steps)", procedure.qualified_name, len(procedure.steps))

        self.recorder = None
        self.driver = None
        return procedure

    def abandon(self) -> None:
        """Throw away the in-flight recording."""
        if self.recorder:
            logger.info("abandoned recording %s", self.recorder)
        self.recorder = None
        self.driver = None

    # === Verify + promote ===

    def verify(self, site: str, action: str, driver: PageDriver,
               args: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
        """
        Replay a procedure against the live site.

        A green replay moves CANDIDATE -> QUARANTINE. It does NOT promote:
        promotion is a human act, always.
        """
        procedure = self._require(site, action)
        ok, error, _duration = replay(procedure, driver, args)
        self.procedure_repo.save(procedure)
        logger.info("verify %s: %s", procedure.qualified_name, "ok" if ok else error)
        return ok, error

    def promote(self, site: str, action: str, verified_by: str) -> Procedure:
        """QUARANTINE -> GOLDEN. Requires a named human."""
        procedure = self._require(site, action)
        procedure.promote(verified_by=verified_by)
        self.procedure_repo.save(procedure)
        logger.info("promoted %s by %s", procedure.qualified_name, verified_by)
        return procedure

    def demote(self, site: str, action: str, reason: str) -> Procedure:
        procedure = self._require(site, action)
        procedure.demote(reason)
        self.procedure_repo.save(procedure)
        logger.info("demoted %s: %s", procedure.qualified_name, reason)
        return procedure

    # === Compile ===

    def compile(self, site: Optional[str] = None) -> List[Path]:
        """
        Compile golden procedures into the SDK.

        With no `site`, compiles every site. Non-golden procedures are skipped.
        """
        procedures = self.procedure_repo.list_all()
        if site:
            return generate_site(procedures, site, self.sdk_dir)
        return generate_all(procedures, self.sdk_dir)

    # === Inspection ===

    def status_report(self) -> Dict[str, List[str]]:
        """Every procedure grouped by status - the pipeline at a glance."""
        report: Dict[str, List[str]] = {s.value: [] for s in ProcedureStatus}
        for procedure in self.procedure_repo.list_all():
            report[procedure.status.value].append(procedure.qualified_name)
        return report

    def pending_promotion(self) -> List[Procedure]:
        """Procedures that have proven themselves and are waiting on a human."""
        return self.procedure_repo.list_by_status(ProcedureStatus.QUARANTINE)

    def code_pointers(self) -> Dict[str, str]:
        """
        qualified name -> code_pointer for every golden procedure.

        These drop straight into AutomationSchema.code_pointer, which is what
        makes a compiled procedure schedulable with no new plumbing.
        """
        return {
            p.qualified_name: p.code_pointer
            for p in self.procedure_repo.list_by_status(ProcedureStatus.GOLDEN)
        }

    def _require(self, site: str, action: str) -> Procedure:
        procedure = self.procedure_repo.get_by_name(site, action)
        if not procedure:
            raise LookupError(f"no such procedure: {site}.{action}")
        return procedure
