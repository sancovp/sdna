"""
Procedure - A verified way to do one thing on one site.

This is the domain object the SDK pipeline is built around:

    explore -> record -> compile -> library
    (computer use)  (Procedure)  (codegen)  (sdk.<site>.<action>)

A Procedure is what an expensive exploration run LEARNED, frozen into a form
that can be replayed cheaply forever. Computer use is the discovery channel;
the Procedure is what discovery produces; the SDK is what Procedures compose
into.

Pure domain - no external dependencies. Says WHAT a procedure is, never HOW it
is recorded, stored, executed, or compiled.

Two laws are enforced structurally here rather than by convention:

1. SELECTORS, NEVER COORDINATES. A Step that carries pixel coordinates is
   rejected at construction. Coordinates are for exploring; a compiled
   procedure that clicks (847, 392) is broken the moment the layout shifts,
   and it breaks SILENTLY. See Step.__post_init__.

2. PROMOTION IS HUMAN-ONLY. Nothing reaches GOLDEN without a named human.
   A procedure can prove itself green a thousand times and still only sit in
   QUARANTINE. See Procedure.promote.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
import re
import uuid


# The template syntax a Step uses to reference a procedure argument: $name
ARG_PATTERN = re.compile(r"\$(\w+)")

# Selector shapes that are really coordinates wearing a costume.
_COORDINATE_SHAPED = re.compile(
    r"^\s*[\(\[]?\s*\d+\s*[, ]\s*\d+\s*[\)\]]?\s*$"
)


class ProcedureStatus(Enum):
    """
    Lifecycle of a procedure.

    CANDIDATE  - recorded from an exploration run, never replayed
    QUARANTINE - replayed green at least once, awaiting a human
    GOLDEN     - human-promoted; compiled into the SDK; callable
    DEMOTED    - was golden, then a replay failed; back to the explore lane
    ARCHIVED   - deliberately retired

    Only GOLDEN procedures are compiled. Only a human moves QUARANTINE -> GOLDEN.
    """
    CANDIDATE = "candidate"
    QUARANTINE = "quarantine"
    GOLDEN = "golden"
    DEMOTED = "demoted"
    ARCHIVED = "archived"


class StepKind(Enum):
    """What a single recorded action does."""
    NAVIGATE = "navigate"      # go to a url
    CLICK = "click"            # click the element at selector
    FILL = "fill"              # type value into the element at selector
    SELECT = "select"          # choose value in the <select> at selector
    PRESS = "press"            # send a key to the element at selector
    UPLOAD = "upload"          # attach a file to the input at selector
    WAIT_FOR = "wait_for"      # block until selector appears
    EXPECT = "expect"          # assert selector exists / contains value
    EXTRACT = "extract"        # read text from selector into the return dict


class ArgType(Enum):
    """Types a procedure argument may take. Kept narrow on purpose."""
    STR = "str"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    PATH = "path"


@dataclass
class ArgSpec:
    """
    One argument of the compiled function.

    These become the typed keyword arguments of the generated SDK callable,
    which is the whole ergonomic point: sdk.etsy.list_item(title=..., price=...)
    rather than a wall of screenshots.
    """
    name: str
    type: ArgType = ArgType.STR
    required: bool = True
    default: Optional[Any] = None
    description: str = ""

    def __post_init__(self):
        if isinstance(self.type, str):
            self.type = ArgType(self.type)
        if not self.name.isidentifier():
            raise ValueError(f"Arg name is not a valid identifier: {self.name!r}")

    @property
    def python_type(self) -> str:
        return {
            ArgType.STR: "str",
            ArgType.INT: "int",
            ArgType.FLOAT: "float",
            ArgType.BOOL: "bool",
            ArgType.PATH: "str",
        }[self.type]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type.value,
            "required": self.required,
            "default": self.default,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArgSpec":
        return cls(**data)


@dataclass
class Step:
    """
    One recorded action.

    `selector` is a CSS/text selector - the thing that survives a redesign and
    that a human can read in a diff. Coordinates are rejected: see the module
    docstring, law 1.

    `value` may reference procedure arguments with $name templating.
    """
    kind: StepKind
    selector: Optional[str] = None
    value: Optional[str] = None
    url: Optional[str] = None
    timeout_ms: int = 10_000
    note: str = ""

    def __post_init__(self):
        if isinstance(self.kind, str):
            self.kind = StepKind(self.kind)

        # LAW 1 - selectors, never coordinates.
        if self.selector and _COORDINATE_SHAPED.match(self.selector):
            raise ValueError(
                f"Step selector looks like coordinates: {self.selector!r}. "
                "Compiled procedures address elements by selector, never by "
                "pixel - a coordinate breaks silently on any layout change. "
                "Record a CSS/text selector instead."
            )

        if self.kind is StepKind.NAVIGATE and not self.url:
            raise ValueError("NAVIGATE step requires a url")
        if self.kind not in (StepKind.NAVIGATE,) and not self.selector:
            raise ValueError(f"{self.kind.value} step requires a selector")

    @property
    def referenced_args(self) -> List[str]:
        """Argument names this step interpolates, in order of appearance."""
        found = []
        for text in (self.value, self.url, self.selector):
            if text:
                for name in ARG_PATTERN.findall(text):
                    if name not in found:
                        found.append(name)
        return found

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "selector": self.selector,
            "value": self.value,
            "url": self.url,
            "timeout_ms": self.timeout_ms,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Step":
        return cls(**data)

    def __repr__(self):
        target = self.url or self.selector
        val = f" <- {self.value!r}" if self.value else ""
        return f"Step({self.kind.value} {target!r}{val})"


@dataclass
class Condition:
    """
    A checkable claim about page state.

    As a PRECONDITION it says "we are where this procedure expects to start".
    As a POSTCONDITION it says "the thing actually happened" - which is the
    only reason a replay test can distinguish success from silent breakage.
    """
    description: str = ""
    selector: Optional[str] = None
    expect_text: Optional[str] = None
    expect_url: Optional[str] = None

    @property
    def is_checkable(self) -> bool:
        """A condition with nothing to check is decoration, not a gate."""
        return bool(self.selector or self.expect_text or self.expect_url)

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "selector": self.selector,
            "expect_text": self.expect_text,
            "expect_url": self.expect_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Condition":
        return cls(**data)


@dataclass
class Provenance:
    """
    Where this procedure came from.

    Kept because a demoted procedure has to be re-explored, and the cheapest
    way to re-explore is to start from what the last exploration saw.
    """
    explored_at: Optional[datetime] = None
    explored_by: str = ""
    trace_path: Optional[str] = None
    source_url: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "explored_at": self.explored_at.isoformat() if self.explored_at else None,
            "explored_by": self.explored_by,
            "trace_path": self.trace_path,
            "source_url": self.source_url,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Provenance":
        explored_at = data.get("explored_at")
        return cls(
            explored_at=datetime.fromisoformat(explored_at) if explored_at else None,
            explored_by=data.get("explored_by", ""),
            trace_path=data.get("trace_path"),
            source_url=data.get("source_url"),
            notes=data.get("notes", ""),
        )


@dataclass
class ReplayRecord:
    """One replay-test result. The immune system writes these."""
    at: datetime
    ok: bool
    error: str = ""
    duration_seconds: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "at": self.at.isoformat(),
            "ok": self.ok,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReplayRecord":
        return cls(
            at=datetime.fromisoformat(data["at"]),
            ok=data["ok"],
            error=data.get("error", ""),
            duration_seconds=data.get("duration_seconds"),
        )


@dataclass
class Procedure:
    """
    A verified way to do ONE action on ONE site.

    Compiles to a single typed function in that site's SDK:

        Procedure(site="etsy", action="list_item", args=[...])
          -> sdk/etsy/list_item.py :: list_item(title: str, price: float)
          -> code_pointer "sdk.etsy.list_item"

    The code_pointer is the join to the rest of the ecosystem: it is exactly
    the shape AutomationSchema.code_pointer already imports and calls, so a
    compiled procedure is schedulable the moment it exists.
    """
    site: str
    action: str

    args: List[ArgSpec] = field(default_factory=list)
    steps: List[Step] = field(default_factory=list)
    returns: Dict[str, str] = field(default_factory=dict)  # name -> description

    precondition: Optional[Condition] = None
    postcondition: Optional[Condition] = None

    provenance: Provenance = field(default_factory=Provenance)
    status: ProcedureStatus = ProcedureStatus.CANDIDATE

    # Promotion record - only ever set by a human, see promote()
    promoted_by: Optional[str] = None
    promoted_at: Optional[datetime] = None

    # Immune-system state
    replays: List[ReplayRecord] = field(default_factory=list)
    consecutive_failures: int = 0
    demotion_reason: str = ""

    version: int = 1
    description: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.status, str):
            self.status = ProcedureStatus(self.status)
        if not self.site.isidentifier():
            raise ValueError(f"site must be a valid identifier: {self.site!r}")
        if not self.action.isidentifier():
            raise ValueError(f"action must be a valid identifier: {self.action!r}")

    # === Identity ===

    @property
    def qualified_name(self) -> str:
        """`etsy.list_item` - how a human refers to it."""
        return f"{self.site}.{self.action}"

    @property
    def function_name(self) -> str:
        return self.action

    @property
    def code_pointer(self) -> str:
        """
        `sdk.etsy.list_item` - the AutomationSchema.code_pointer for this
        procedure. This is the seam that makes compiled procedures schedulable
        with zero new plumbing.
        """
        return f"sdk.{self.site}.{self.action}"

    # === Validation ===

    def validate(self) -> List[str]:
        """
        Return the list of reasons this procedure cannot be compiled.
        Empty list == compilable.
        """
        problems = []

        if not self.steps:
            problems.append("no steps recorded")

        if self.postcondition is None or not self.postcondition.is_checkable:
            problems.append(
                "no checkable postcondition - a procedure without one cannot "
                "tell success from silent breakage, so its replay test would "
                "be worthless"
            )

        declared = {a.name for a in self.args}
        for i, step in enumerate(self.steps):
            for name in step.referenced_args:
                if name not in declared:
                    problems.append(
                        f"step {i} ({step.kind.value}) references ${name}, "
                        f"which is not a declared arg"
                    )

        used = {n for s in self.steps for n in s.referenced_args}
        for arg in self.args:
            if arg.name not in used:
                problems.append(f"arg {arg.name!r} is declared but never used")

        for name in self.returns:
            if not any(
                s.kind is StepKind.EXTRACT and s.note == name for s in self.steps
            ):
                problems.append(
                    f"return {name!r} has no EXTRACT step producing it "
                    f"(set the step's note to the return name)"
                )

        return problems

    @property
    def is_compilable(self) -> bool:
        return not self.validate()

    @property
    def is_callable(self) -> bool:
        """Only golden procedures are in the SDK."""
        return self.status is ProcedureStatus.GOLDEN

    # === Lifecycle ===

    def record_replay(self, ok: bool, error: str = "",
                      duration_seconds: Optional[float] = None,
                      at: Optional[datetime] = None) -> ReplayRecord:
        """
        Record a replay-test result and update failure tracking.

        Does NOT itself demote - the immune system decides that, because the
        demotion threshold is policy and this is the domain.
        """
        record = ReplayRecord(
            at=at or datetime.now(),
            ok=ok,
            error=error,
            duration_seconds=duration_seconds,
        )
        self.replays.append(record)

        if ok:
            self.consecutive_failures = 0
            # A green replay is what earns a candidate its way to quarantine.
            if self.status is ProcedureStatus.CANDIDATE:
                self.status = ProcedureStatus.QUARANTINE
        else:
            self.consecutive_failures += 1

        return record

    def promote(self, verified_by: str) -> "Procedure":
        """
        QUARANTINE -> GOLDEN. Human-only.

        LAW 2. `verified_by` is a person, and the call refuses without one.
        A procedure that has never replayed green cannot be promoted at all -
        promotion attests to a thing that was actually observed to work, not
        to a thing that was recorded.
        """
        if not verified_by or not verified_by.strip():
            raise ValueError(
                "promote() requires verified_by - promotion to GOLDEN is a "
                "human act, and the name is the attestation"
            )
        if self.status is not ProcedureStatus.QUARANTINE:
            raise ValueError(
                f"only a QUARANTINE procedure can be promoted; "
                f"{self.qualified_name} is {self.status.value}"
                + (
                    " (replay it green first)"
                    if self.status is ProcedureStatus.CANDIDATE
                    else ""
                )
            )
        problems = self.validate()
        if problems:
            raise ValueError(
                f"{self.qualified_name} is not compilable: " + "; ".join(problems)
            )

        self.status = ProcedureStatus.GOLDEN
        self.promoted_by = verified_by.strip()
        self.promoted_at = datetime.now()
        self.demotion_reason = ""
        return self

    def demote(self, reason: str) -> "Procedure":
        """
        GOLDEN -> DEMOTED. The immune system's only write.

        A demoted procedure leaves the SDK and re-enters the explore lane. The
        provenance survives so re-exploration starts warm.
        """
        self.status = ProcedureStatus.DEMOTED
        self.demotion_reason = reason
        self.promoted_by = None
        self.promoted_at = None
        return self

    def supersede(self, steps: List[Step],
                  provenance: Optional[Provenance] = None) -> "Procedure":
        """
        Re-exploration produced a new way to do this. Bump the version and
        drop back to CANDIDATE - a new body has to earn golden on its own.
        """
        self.steps = steps
        if provenance:
            self.provenance = provenance
        self.version += 1
        self.status = ProcedureStatus.CANDIDATE
        self.consecutive_failures = 0
        self.promoted_by = None
        self.promoted_at = None
        return self

    # === Serialization ===

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "site": self.site,
            "action": self.action,
            "description": self.description,
            "args": [a.to_dict() for a in self.args],
            "steps": [s.to_dict() for s in self.steps],
            "returns": self.returns,
            "precondition": self.precondition.to_dict() if self.precondition else None,
            "postcondition": self.postcondition.to_dict() if self.postcondition else None,
            "provenance": self.provenance.to_dict(),
            "status": self.status.value,
            "promoted_by": self.promoted_by,
            "promoted_at": self.promoted_at.isoformat() if self.promoted_at else None,
            "replays": [r.to_dict() for r in self.replays],
            "consecutive_failures": self.consecutive_failures,
            "demotion_reason": self.demotion_reason,
            "version": self.version,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Procedure":
        promoted_at = data.get("promoted_at")
        pre = data.get("precondition")
        post = data.get("postcondition")
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            site=data["site"],
            action=data["action"],
            description=data.get("description", ""),
            args=[ArgSpec.from_dict(a) for a in data.get("args", [])],
            steps=[Step.from_dict(s) for s in data.get("steps", [])],
            returns=data.get("returns", {}),
            precondition=Condition.from_dict(pre) if pre else None,
            postcondition=Condition.from_dict(post) if post else None,
            provenance=Provenance.from_dict(data.get("provenance", {})),
            status=ProcedureStatus(data.get("status", "candidate")),
            promoted_by=data.get("promoted_by"),
            promoted_at=datetime.fromisoformat(promoted_at) if promoted_at else None,
            replays=[ReplayRecord.from_dict(r) for r in data.get("replays", [])],
            consecutive_failures=data.get("consecutive_failures", 0),
            demotion_reason=data.get("demotion_reason", ""),
            version=data.get("version", 1),
            tags=data.get("tags", []),
        )

    def __repr__(self):
        return (
            f"Procedure({self.qualified_name} v{self.version}, "
            f"{self.status.value}, {len(self.steps)} steps)"
        )


# Protocols for dependency inversion (domain defines what it needs)

class ProcedureRepository:
    """Protocol for procedure storage - domain says WHAT, infra says HOW."""

    def save(self, procedure: Procedure) -> None:
        raise NotImplementedError

    def get(self, procedure_id: str) -> Optional[Procedure]:
        raise NotImplementedError

    def get_by_name(self, site: str, action: str) -> Optional[Procedure]:
        raise NotImplementedError

    def list_all(self) -> List[Procedure]:
        raise NotImplementedError

    def list_by_site(self, site: str) -> List[Procedure]:
        raise NotImplementedError

    def list_by_status(self, status: ProcedureStatus) -> List[Procedure]:
        raise NotImplementedError

    def list_sites(self) -> List[str]:
        raise NotImplementedError

    def delete(self, procedure_id: str) -> bool:
        raise NotImplementedError


class PageDriver:
    """
    Protocol for whatever actually drives a browser page.

    Domain says WHAT a step needs done; infrastructure decides whether that is
    Playwright, CloakBrowser, or anything else. Deliberately tiny - this is the
    entire surface a compiled procedure needs, which is why swapping the
    browser underneath is a one-adapter change.
    """

    def navigate(self, url: str, timeout_ms: int = 10_000) -> None:
        raise NotImplementedError

    def click(self, selector: str, timeout_ms: int = 10_000) -> None:
        raise NotImplementedError

    def fill(self, selector: str, value: str, timeout_ms: int = 10_000) -> None:
        raise NotImplementedError

    def select(self, selector: str, value: str, timeout_ms: int = 10_000) -> None:
        raise NotImplementedError

    def press(self, selector: str, key: str, timeout_ms: int = 10_000) -> None:
        raise NotImplementedError

    def upload(self, selector: str, path: str, timeout_ms: int = 10_000) -> None:
        raise NotImplementedError

    def wait_for(self, selector: str, timeout_ms: int = 10_000) -> None:
        raise NotImplementedError

    def exists(self, selector: str, timeout_ms: int = 10_000) -> bool:
        raise NotImplementedError

    def text_of(self, selector: str, timeout_ms: int = 10_000) -> str:
        raise NotImplementedError

    def current_url(self) -> str:
        raise NotImplementedError
