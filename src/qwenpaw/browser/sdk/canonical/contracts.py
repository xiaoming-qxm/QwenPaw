# -*- coding: utf-8 -*-
"""Canonical Browser public contract facts for S0."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from ..governance.errors import BrowserSDKError


_RUNTIME_VALUE_ISSUER = object()


class _OpaqueRuntimeValue:
    """Base for public values whose usable instances come from Runtime."""

    __slots__ = ("_public_fields",)
    _public_fields: dict[str, object]

    def __new__(
        cls,
        *args: object,
        _issuer: object | None = None,
        **fields: object,
    ) -> "_OpaqueRuntimeValue":
        if _issuer is not _RUNTIME_VALUE_ISSUER:
            raise BrowserSDKError(
                f"{cls.__name__} values are issued by Browser Runtime",
                code="runtime_issued_value",
            )
        if args:
            raise BrowserSDKError(
                "runtime value fields must be named",
                code="runtime_issued_value",
            )
        instance = super().__new__(cls)
        object.__setattr__(instance, "_public_fields", dict(fields))
        return instance

    def __getattr__(self, name: str) -> object:
        try:
            return self._public_fields[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __repr__(self) -> str:
        return f"<{type(self).__name__} runtime-issued>"

    def to_dict(self) -> dict[str, object]:
        """Return only the value's explicitly public fields."""
        return dict(self._public_fields)


class ContextVersion(_OpaqueRuntimeValue):
    """Opaque document/context version."""


class EvidenceRef(_OpaqueRuntimeValue):
    """Opaque observation evidence reference."""


class VisualContextRef(_OpaqueRuntimeValue):
    """Opaque visual context reference."""


class TargetRef(_OpaqueRuntimeValue):
    """Opaque grounded target reference."""


class RegionRef(_OpaqueRuntimeValue):
    """Opaque grounded region reference."""


class ReadCursor(_OpaqueRuntimeValue):
    """Opaque incremental read cursor."""


@dataclass(frozen=True, slots=True, init=False)
class ResourceHandle(_OpaqueRuntimeValue):
    """Path-free task-owned output resource handle."""

    id: str
    media_type: str
    name: str
    size: int
    sha256: str
    expires_at: datetime

    # pylint: disable-next=redefined-builtin
    def __init__(
        self,
        *,
        _issuer: object | None = None,
        id: str = "",  # pylint: disable=redefined-builtin
        media_type: str = "",
        name: str = "",
        size: int = 0,
        sha256: str = "",
        expires_at: datetime | None = None,
    ) -> None:
        if _issuer is not _RUNTIME_VALUE_ISSUER or expires_at is None:
            raise BrowserSDKError(
                "ResourceHandle values are issued by Browser Runtime",
                code="runtime_issued_value",
            )
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "sha256", sha256)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(
            self,
            "_public_fields",
            {
                "id": id,
                "media_type": media_type,
                "name": name,
                "size": size,
                "sha256": sha256,
                "expires_at": expires_at,
            },
        )


class TabSummary(_OpaqueRuntimeValue):
    """Opaque public tab summary."""


class BrowserPrompt(_OpaqueRuntimeValue):
    """Opaque browser prompt reference."""


def _issue_opaque_value(
    value_type: type[_OpaqueRuntimeValue],
    issuer: object,
    **fields: object,
) -> _OpaqueRuntimeValue:
    """Issue a value only when called with the module registry token."""
    if issuer is not _RUNTIME_VALUE_ISSUER:
        raise BrowserSDKError(
            "opaque Browser value issuer is not trusted",
            code="runtime_issued_value",
        )
    if not issubclass(value_type, _OpaqueRuntimeValue):
        raise BrowserSDKError(
            "unsupported opaque Browser value type",
            code="runtime_issued_value",
        )
    return value_type(_issuer=_RUNTIME_VALUE_ISSUER, **fields)


def _require_choice(value: str, allowed: set[str], name: str) -> None:
    if value not in allowed:
        raise ValueError(f"invalid {name}: {value}")


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetQuery:
    """Safe semantic target query; selectors and coordinates are excluded."""

    role: str | None = None
    name: str | None = None
    text: str | None = None
    region: RegionRef | None = None
    match: Literal["exact", "contains"] = "exact"

    def __post_init__(self) -> None:
        if not any((self.role, self.name, self.text)):
            raise ValueError("TargetQuery requires role, name, or text")
        _require_choice(self.match, {"exact", "contains"}, "match")
        if self.region is not None and not isinstance(self.region, RegionRef):
            raise TypeError("region must be a runtime-issued RegionRef")


@dataclass(frozen=True, slots=True)
class CurrentSurface:
    """Select the current browser surface."""


@dataclass(frozen=True, slots=True)
class FrameScope:
    frame_region: RegionRef

    def __post_init__(self) -> None:
        if not isinstance(self.frame_region, RegionRef):
            raise TypeError("frame_region must be a RegionRef")


@dataclass(frozen=True, slots=True)
class RegionScope:
    region: RegionRef

    def __post_init__(self) -> None:
        if not isinstance(self.region, RegionRef):
            raise TypeError("region must be a RegionRef")


@dataclass(frozen=True, slots=True)
class VisualRegion:
    visual_context: VisualContextRef
    x: float
    y: float
    width: float
    height: float

    def __init__(
        self,
        visual_context: VisualContextRef,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> None:
        values = (x, y, width, height)
        if any(not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("VisualRegion bounds must be normalized")
        if x + width > 1.0 or y + height > 1.0:
            raise ValueError("VisualRegion must fit within its context")
        if not isinstance(visual_context, VisualContextRef):
            raise TypeError("visual_context must be a VisualContextRef")
        object.__setattr__(self, "visual_context", visual_context)
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)


ObservationScope: TypeAlias = (
    CurrentSurface | FrameScope | RegionScope | VisualRegion
)
Coverage: TypeAlias = Literal[
    "COMPLETE",
    "PARTIAL",
    "UNAVAILABLE",
    "STALE",
]
GapStage: TypeAlias = Literal["CAPTURE", "SELECTION", "DELIVERY"]
EvidenceKind: TypeAlias = Literal[
    "SNAPSHOT",
    "READ",
    "SCREENSHOT",
    "WAIT",
    "EFFECT",
]
ReadSegmentKind: TypeAlias = Literal[
    "text",
    "heading",
    "list",
    "table",
    "key_value",
    "link",
    "form_state",
    "artifact_description",
]
CaptureSource: TypeAlias = Literal[
    "AX",
    "DOM",
    "AX_DOM",
    "DOCUMENT",
    "FRAME",
    "SHADOW",
    "READ",
    "SCREENSHOT",
]
CaptureGapReason: TypeAlias = Literal[
    "BUDGET_EXHAUSTED",
    "SOURCE_UNAVAILABLE",
    "GENERATION_MISMATCH",
    "CROSS_ORIGIN",
    "CLOSED_SHADOW",
    "DETACHED",
    "PAGINATED_BOUNDARY",
    "VIRTUAL_BOUNDARY",
    "INVARIANT_CHANGED",
]
SelectionGapReason: TypeAlias = Literal[
    "LIMIT_CLAMPED",
    "OUTPUT_LIMIT",
    "QUERY_FILTERED",
]
DeliveryGapReason: TypeAlias = Literal[
    "MODEL_LIMIT",
    "PROVIDER_OMISSION",
    "RESOURCE_OMISSION",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureGap:
    """Typed capture omission without arbitrary backend metadata."""

    source: CaptureSource
    reason: CaptureGapReason
    frontier: str | None = None
    cursor: ReadCursor | None = None
    frame: RegionRef | None = None
    examined: int = 0
    omitted: int = 0

    def __post_init__(self) -> None:
        _require_choice(
            self.source,
            set(CaptureSource.__args__),  # type: ignore[attr-defined]
            "capture source",
        )
        _require_choice(
            self.reason,
            set(CaptureGapReason.__args__),  # type: ignore[attr-defined]
            "capture gap reason",
        )
        _require_gap_counts(self.examined, self.omitted)
        if self.cursor is not None:
            _require_runtime_value(self.cursor, ReadCursor, "cursor")
        if self.frame is not None:
            _require_runtime_value(self.frame, RegionRef, "frame")


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectionGap:
    """Typed selection omission applied after source merge."""

    reason: SelectionGapReason
    frontier: str | None = None
    cursor: ReadCursor | None = None
    frame: RegionRef | None = None
    examined: int = 0
    omitted: int = 0
    requested: int | None = None
    effective: int | None = None

    def __post_init__(self) -> None:
        _require_choice(
            self.reason,
            set(SelectionGapReason.__args__),  # type: ignore[attr-defined]
            "selection gap reason",
        )
        _require_gap_counts(self.examined, self.omitted)
        if (self.requested is None) != (self.effective is None):
            raise ValueError(
                "requested and effective must be supplied together",
            )
        if self.requested is not None and (
            self.requested < 0 or self.effective is None or self.effective < 0
        ):
            raise ValueError("requested and effective must be non-negative")
        if self.cursor is not None:
            _require_runtime_value(self.cursor, ReadCursor, "cursor")
        if self.frame is not None:
            _require_runtime_value(self.frame, RegionRef, "frame")


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliveryGap:
    """Typed omission introduced while delivering captured evidence."""

    reason: DeliveryGapReason
    frontier: str | None = None
    cursor: ReadCursor | None = None
    frame: RegionRef | None = None
    examined: int = 0
    omitted: int = 0

    def __post_init__(self) -> None:
        _require_choice(
            self.reason,
            set(DeliveryGapReason.__args__),  # type: ignore[attr-defined]
            "delivery gap reason",
        )
        _require_gap_counts(self.examined, self.omitted)
        if self.cursor is not None:
            _require_runtime_value(self.cursor, ReadCursor, "cursor")
        if self.frame is not None:
            _require_runtime_value(self.frame, RegionRef, "frame")


GapDetail: TypeAlias = CaptureGap | SelectionGap | DeliveryGap


@dataclass(frozen=True, slots=True, kw_only=True)
class CoverageGap:
    """One typed omission at its truth-changing pipeline stage."""

    stage: GapStage
    detail: GapDetail

    def __post_init__(self) -> None:
        expected = {
            "CAPTURE": CaptureGap,
            "SELECTION": SelectionGap,
            "DELIVERY": DeliveryGap,
        }
        _require_choice(self.stage, set(expected), "gap stage")
        if not isinstance(self.detail, expected[self.stage]):
            raise TypeError(f"{self.stage} gap has incompatible detail")

    @property
    def notice(self) -> str:
        """Return a safe top-line clamp notice when one is required."""
        if isinstance(self.detail, SelectionGap) and (
            self.detail.reason == "LIMIT_CLAMPED"
            and self.detail.requested is not None
            and self.detail.effective is not None
        ):
            return (
                f"Requested {self.detail.requested}; "
                f"effective {self.detail.effective}."
            )
        return ""


@dataclass(frozen=True, slots=True, kw_only=True)
class EvidenceMeta:
    """Truth-bearing metadata for one runtime-issued observation."""

    ref: EvidenceRef
    kind: EvidenceKind
    context: ContextVersion
    scope: ObservationScope
    captured_at: datetime
    coverage: Coverage
    gaps: tuple[CoverageGap, ...]

    def __post_init__(self) -> None:
        _require_runtime_value(self.ref, EvidenceRef, "ref")
        _require_runtime_value(self.context, ContextVersion, "context")
        _require_choice(
            self.kind,
            set(EvidenceKind.__args__),  # type: ignore[attr-defined]
            "evidence kind",
        )
        _require_choice(
            self.coverage,
            set(Coverage.__args__),  # type: ignore[attr-defined]
            "coverage",
        )
        if not isinstance(
            self.scope,
            (CurrentSurface, FrameScope, RegionScope, VisualRegion),
        ):
            raise TypeError("scope must be a closed ObservationScope")
        if not all(isinstance(gap, CoverageGap) for gap in self.gaps):
            raise TypeError("gaps must contain CoverageGap values")


@dataclass(frozen=True, slots=True)
class TargetSummary:
    """Safe read-only target evidence without host-native identity."""

    ref: TargetRef
    role: str
    name: str
    states: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ()
    observed_url: str = ""

    def __post_init__(self) -> None:
        _require_runtime_value(self.ref, TargetRef, "ref")


@dataclass(frozen=True, slots=True)
class RegionSummary:
    """Safe read-only region evidence backed by an opaque RegionRef."""

    ref: RegionRef
    kind: Literal["FRAME", "CONTENT", "OWNER"]
    boundary: Literal[
        "DEFAULT",
        "SAME_ORIGIN",
        "CROSS_ORIGIN",
        "OPEN_SHADOW",
        "CLOSED_SHADOW",
    ]
    accessible: bool

    def __post_init__(self) -> None:
        _require_runtime_value(self.ref, RegionRef, "ref")
        _require_choice(
            self.kind,
            {"FRAME", "CONTENT", "OWNER"},
            "region kind",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadSegment:
    """Immutable human-readable content with no target mutation authority."""

    kind: ReadSegmentKind
    text: str
    observed_url: str = ""

    def __post_init__(self) -> None:
        _require_choice(
            self.kind,
            set(ReadSegmentKind.__args__),  # type: ignore[attr-defined]
            "read segment kind",
        )
        if not self.text:
            raise ValueError("ReadSegment text is required")
        if self.observed_url and not self.observed_url.startswith(
            ("https://", "http://"),
        ):
            raise ValueError("ReadSegment observed_url must be safe HTTP(S)")
        if self.kind != "link" and self.observed_url:
            raise ValueError("only link segments may carry observed_url")


def _require_gap_counts(examined: int, omitted: int) -> None:
    if examined < 0 or omitted < 0:
        raise ValueError("gap counts must be non-negative")


def coverage_from_gaps(gaps: tuple[CoverageGap, ...]) -> Coverage:
    """Map typed omission facts to conservative coverage truth."""
    if not gaps:
        return "COMPLETE"
    capture = tuple(
        gap.detail for gap in gaps if isinstance(gap.detail, CaptureGap)
    )
    if any(item.reason == "GENERATION_MISMATCH" for item in capture):
        return "STALE"
    if any(
        item.reason == "SOURCE_UNAVAILABLE" and item.source == "AX_DOM"
        for item in capture
    ):
        return "UNAVAILABLE"
    return "PARTIAL"


def can_prove_negative(evidence: EvidenceMeta) -> bool:
    """Only complete evidence can prove absence inside its bound scope."""
    return evidence.coverage == "COMPLETE" and not evidence.gaps


def can_prove_global_unique(evidence: EvidenceMeta) -> bool:
    """Only a complete current-surface observation has global scope."""
    return can_prove_negative(evidence) and isinstance(
        evidence.scope,
        CurrentSurface,
    )


@dataclass(frozen=True, slots=True)
class PageCondition:
    kind: str
    subject: object
    match: str = "exact"

    @classmethod
    def url(
        cls,
        value: str,
        *,
        match: Literal["exact", "prefix"] = "exact",
    ) -> "PageCondition":
        _require_choice(match, {"exact", "prefix"}, "match")
        return cls("url", value, match)

    @classmethod
    def title(
        cls,
        value: str,
        *,
        match: Literal["exact", "contains"] = "exact",
    ) -> "PageCondition":
        _require_choice(match, {"exact", "contains"}, "match")
        return cls("title", value, match)

    @classmethod
    def document_changed(cls, context: ContextVersion) -> "PageCondition":
        _require_runtime_value(context, ContextVersion, "context")
        return cls("document_changed", context)

    @classmethod
    def ready(
        cls,
        state: Literal["dom_content_loaded", "load"],
    ) -> "PageCondition":
        _require_choice(state, {"dom_content_loaded", "load"}, "state")
        return cls("ready", state)


@dataclass(frozen=True, slots=True)
class TargetCondition:
    kind: str
    subject: object
    expected: object = True

    @classmethod
    def exists(
        cls,
        subject: TargetRef | TargetQuery,
        expected: bool = True,
    ) -> "TargetCondition":
        _require_target(subject)
        return cls("exists", subject, expected)

    @classmethod
    def visible(
        cls,
        subject: TargetRef | TargetQuery,
        expected: bool = True,
    ) -> "TargetCondition":
        _require_target(subject)
        return cls("visible", subject, expected)

    @classmethod
    def enabled(
        cls,
        target: TargetRef,
        expected: bool = True,
    ) -> "TargetCondition":
        _require_runtime_value(target, TargetRef, "target")
        return cls("enabled", target, expected)

    @classmethod
    def editable(
        cls,
        target: TargetRef,
        expected: bool = True,
    ) -> "TargetCondition":
        _require_runtime_value(target, TargetRef, "target")
        return cls("editable", target, expected)

    @classmethod
    def value(cls, target: TargetRef, value: str) -> "TargetCondition":
        _require_runtime_value(target, TargetRef, "target")
        return cls("value", target, value)

    @classmethod
    def checked(
        cls,
        target: TargetRef,
        expected: bool,
    ) -> "TargetCondition":
        _require_runtime_value(target, TargetRef, "target")
        return cls("checked", target, expected)

    @classmethod
    def selected(
        cls,
        target: TargetRef,
        option: "OptionChoice",
    ) -> "TargetCondition":
        _require_runtime_value(target, TargetRef, "target")
        if not isinstance(option, OptionChoice):
            raise TypeError("option must be an OptionChoice")
        return cls("selected", target, option)


@dataclass(frozen=True, slots=True)
class RegionCondition:
    kind: str
    region: RegionRef
    value: object
    option: object

    @classmethod
    def text(
        cls,
        region: RegionRef,
        value: str,
        *,
        present: bool = True,
        match: Literal["exact", "contains"] = "contains",
    ) -> "RegionCondition":
        _require_runtime_value(region, RegionRef, "region")
        _require_choice(match, {"exact", "contains"}, "match")
        return cls("text", region, value, (present, match))

    @classmethod
    def item_count(
        cls,
        region: RegionRef,
        value: int,
        *,
        compare: Literal["eq", "gte", "lte"] = "eq",
    ) -> "RegionCondition":
        _require_runtime_value(region, RegionRef, "region")
        _require_choice(compare, {"eq", "gte", "lte"}, "compare")
        return cls("item_count", region, value, compare)

    @classmethod
    def changed(
        cls,
        region: RegionRef,
        from_evidence: EvidenceRef,
    ) -> "RegionCondition":
        _require_runtime_value(region, RegionRef, "region")
        _require_runtime_value(from_evidence, EvidenceRef, "from_evidence")
        return cls("changed", region, from_evidence, None)


@dataclass(frozen=True, slots=True)
class SurfaceCondition:
    kind: str
    subject: object = None

    @classmethod
    def tab_opened(cls, from_context: ContextVersion) -> "SurfaceCondition":
        _require_runtime_value(from_context, ContextVersion, "from_context")
        return cls("tab_opened", from_context)

    @classmethod
    def tab_closed(cls, tab: TabSummary) -> "SurfaceCondition":
        _require_runtime_value(tab, TabSummary, "tab")
        return cls("tab_closed", tab)

    @classmethod
    def tab_selected(cls, tab: TabSummary) -> "SurfaceCondition":
        _require_runtime_value(tab, TabSummary, "tab")
        return cls("tab_selected", tab)

    @classmethod
    def prompt_present(
        cls,
        prompt_type: Literal[
            "alert",
            "confirm",
            "prompt",
            "before_unload",
            "permission",
        ]
        | None = None,
    ) -> "SurfaceCondition":
        if prompt_type is not None:
            _require_choice(
                prompt_type,
                {"alert", "confirm", "prompt", "before_unload", "permission"},
                "prompt_type",
            )
        return cls("prompt_present", prompt_type)

    @classmethod
    def prompt_absent(cls, prompt: BrowserPrompt) -> "SurfaceCondition":
        _require_runtime_value(prompt, BrowserPrompt, "prompt")
        return cls("prompt_absent", prompt)


@dataclass(frozen=True, slots=True)
class ResourceCondition:
    kind: str
    subject: object

    @classmethod
    def available(cls, resource: ResourceHandle) -> "ResourceCondition":
        _require_runtime_value(resource, ResourceHandle, "resource")
        return cls("available", resource)

    @classmethod
    def created(
        cls,
        *,
        kind: Literal["download", "page_pdf"],
        count: int = 1,
        media_type: str | None = None,
        name: str | None = None,
    ) -> "ResourceCondition":
        _require_choice(kind, {"download", "page_pdf"}, "kind")
        if count <= 0:
            raise ValueError("resource count must be positive")
        return cls("created", (kind, count, media_type, name))


ConditionAtom = (
    PageCondition
    | TargetCondition
    | RegionCondition
    | SurfaceCondition
    | ResourceCondition
)


@dataclass(frozen=True, slots=True)
class BrowserCondition:
    combinator: Literal["all", "any"]
    atoms: tuple[ConditionAtom, ...]

    @classmethod
    def all(cls, *atoms: ConditionAtom) -> "BrowserCondition":
        return cls("all", _condition_atoms(atoms))

    @classmethod
    def any(cls, *atoms: ConditionAtom) -> "BrowserCondition":
        return cls("any", _condition_atoms(atoms))


@dataclass(frozen=True, slots=True)
class ActionExpectation:
    timing: Literal["final", "transition"]
    condition: BrowserCondition
    stable_ms: int = 0

    @classmethod
    def final(
        cls,
        condition: BrowserCondition,
        *,
        stable_ms: int = 0,
    ) -> "ActionExpectation":
        return cls._create("final", condition, stable_ms)

    @classmethod
    def transition(
        cls,
        condition: BrowserCondition,
        *,
        stable_ms: int = 0,
    ) -> "ActionExpectation":
        return cls._create("transition", condition, stable_ms)

    @classmethod
    def _create(
        cls,
        timing: Literal["final", "transition"],
        condition: BrowserCondition,
        stable_ms: int,
    ) -> "ActionExpectation":
        if not isinstance(condition, BrowserCondition):
            raise TypeError("condition must be a BrowserCondition")
        if stable_ms < 0:
            raise ValueError("stable_ms cannot be negative")
        return cls(timing, condition, stable_ms)


@dataclass(frozen=True, slots=True)
class WorkflowRequirement:
    key: str
    expected: str | bool | int


@dataclass(frozen=True, slots=True, kw_only=True)
class StateRequirement:
    same_session: bool = True
    authenticated: bool | None = None
    account_hint: str | None = None
    tenant_hint: str | None = None
    workspace_hint: str | None = None
    role_hint: str | None = None
    workflow: WorkflowRequirement | None = None


@dataclass(frozen=True, slots=True)
class OptionChoice:
    by: Literal["value", "label"]
    value: str

    def __post_init__(self) -> None:
        _require_choice(self.by, {"value", "label"}, "by")


@dataclass(frozen=True, slots=True, kw_only=True)
class PagePdfOptions:
    paper: Literal["a4", "letter", "legal"] = "a4"
    landscape: bool = False
    print_background: bool = True
    margins: Literal["default", "none"] = "default"

    def __post_init__(self) -> None:
        _require_choice(self.paper, {"a4", "letter", "legal"}, "paper")
        _require_choice(self.margins, {"default", "none"}, "margins")


def _require_runtime_value(
    value: object,
    value_type: type[_OpaqueRuntimeValue],
    name: str,
) -> None:
    if not isinstance(value, value_type):
        raise TypeError(
            f"{name} must be a runtime-issued {value_type.__name__}",
        )


def _require_target(value: object) -> None:
    if not isinstance(value, (TargetRef, TargetQuery)):
        raise TypeError("subject must be a TargetRef or TargetQuery")


def _condition_atoms(
    atoms: tuple[ConditionAtom, ...],
) -> tuple[ConditionAtom, ...]:
    if not atoms:
        raise ValueError("BrowserCondition requires at least one atom")
    if any(
        not isinstance(
            atom,
            (
                PageCondition,
                TargetCondition,
                RegionCondition,
                SurfaceCondition,
                ResourceCondition,
            ),
        )
        for atom in atoms
    ):
        raise TypeError("BrowserCondition accepts only closed condition atoms")
    return atoms


TerminalStatus: TypeAlias = Literal[
    "SUCCEEDED",
    "PARTIAL",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
    "UNCERTAIN",
]
RetryDirective: TypeAlias = Literal[
    "NONE",
    "SAFE",
    "AFTER_OBSERVATION",
    "RECONCILE_ONLY",
    "FORBIDDEN",
]
ProblemPhase: TypeAlias = Literal[
    "PREFLIGHT",
    "CAPTURE",
    "DISPATCH",
    "COMMIT",
    "VERIFY",
    "CLEANUP",
    "TRANSPORT",
]


class ResultContractError(BrowserSDKError):
    """Raised when a canonical producer emits contradictory result facts."""

    code = "result_contract_error"


@dataclass(frozen=True, slots=True)
class CapabilityProblemDetails:
    capability: str


@dataclass(frozen=True, slots=True)
class TransportProblemDetails:
    block_kind: Literal["text", "data", "image", "artifact"]
    media_type: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationProblemDetails:
    contract: str
    field: str


ProblemDetails: TypeAlias = (
    CapabilityProblemDetails
    | TransportProblemDetails
    | ValidationProblemDetails
)


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    phase: ProblemPhase
    safe_message: str
    remediation: str | None = None
    details: ProblemDetails | None = None

    def __post_init__(self) -> None:
        _require_choice(
            self.phase,
            {
                "PREFLIGHT",
                "CAPTURE",
                "DISPATCH",
                "COMMIT",
                "VERIFY",
                "CLEANUP",
                "TRANSPORT",
            },
            "problem phase",
        )
        if not self.code or not self.safe_message:
            raise ValueError("Problem requires code and safe_message")
        if self.details is not None and not isinstance(
            self.details,
            (
                CapabilityProblemDetails,
                TransportProblemDetails,
                ValidationProblemDetails,
            ),
        ):
            raise TypeError("Problem details must use a closed details type")
        if self.code == "capability_unavailable" and not isinstance(
            self.details,
            CapabilityProblemDetails,
        ):
            raise ValueError(
                "capability_unavailable requires capability details",
            )


@dataclass(frozen=True, slots=True)
class Notice:
    code: str
    safe_message: str


@dataclass(frozen=True, slots=True)
class CleanupInfo:
    complete: bool = True
    warnings: tuple[Notice, ...] = ()


def issue_operation_id() -> str:
    """Issue a globally unique operation id in the trusted main process."""
    return f"browser-op-{uuid4().hex}"


@dataclass(frozen=True, slots=True, kw_only=True)
class _TerminalFields:
    operation_id: str
    status: TerminalStatus
    retry: RetryDirective
    problem: Problem | None = None
    notices: tuple[Notice, ...] = ()
    cleanup: CleanupInfo = CleanupInfo()

    def validate_terminal(self) -> None:
        if not self.operation_id:
            raise ResultContractError("operation_id is required")
        _require_choice(
            self.status,
            {
                "SUCCEEDED",
                "PARTIAL",
                "BLOCKED",
                "FAILED",
                "CANCELLED",
                "UNCERTAIN",
            },
            "terminal status",
        )
        _require_choice(
            self.retry,
            {
                "NONE",
                "SAFE",
                "AFTER_OBSERVATION",
                "RECONCILE_ONLY",
                "FORBIDDEN",
            },
            "retry directive",
        )
        if self.status == "SUCCEEDED" and self.problem is not None:
            raise ResultContractError("SUCCEEDED cannot contain a problem")
        if self.status != "SUCCEEDED" and self.problem is None:
            raise ResultContractError(
                f"{self.status} requires a typed problem",
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotResult(_TerminalFields):
    evidence: EvidenceRef | None = None
    observation: EvidenceMeta | None = None
    model_text: str = ""
    targets: tuple[TargetSummary, ...] = ()
    regions: tuple[RegionSummary, ...] = ()
    grounding: object | None = None
    source_summary: str = ""

    def __post_init__(self) -> None:
        validate_result_contract(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadResult(_TerminalFields):
    evidence: EvidenceRef | None = None
    observation: EvidenceMeta | None = None
    model_text: str = ""
    segments: tuple[ReadSegment, ...] = ()
    next_cursor: ReadCursor | None = None
    end_of_collection: bool | None = None

    def __post_init__(self) -> None:
        validate_result_contract(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreenshotResult(_TerminalFields):
    evidence: EvidenceRef | None = None
    observation: EvidenceMeta | None = None
    image: ResourceHandle | None = None
    visual_context: VisualContextRef | None = None
    scope: Literal["viewport", "full_page"] = "viewport"

    def __post_init__(self) -> None:
        _require_choice(
            self.scope,
            {"viewport", "full_page"},
            "screenshot scope",
        )
        validate_result_contract(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class WaitResult(_TerminalFields):
    evidence: EvidenceRef | None = None
    outcome: str | None = None
    matched_atoms: tuple[ConditionAtom, ...] = ()
    last_observed: ContextVersion | None = None
    elapsed_ms: int = 0

    def __post_init__(self) -> None:
        validate_result_contract(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionResult(_TerminalFields):
    target: TargetRef | None = None
    source: TargetRef | None = None
    destination: TargetRef | None = None
    classified_effects: tuple[str, ...] = ()
    effect_facts: tuple[object, ...] = ()
    commands: tuple[object, ...] = ()
    context_before: ContextVersion | None = None
    context_after: ContextVersion | None = None
    context_outcome: str | None = None
    dispatch: object | None = None
    commit: object | None = None
    effect: object | None = None
    postcondition: object | None = None
    already_satisfied: bool = False
    evidence_refs: tuple[EvidenceRef, ...] = ()
    opened_tabs: tuple[TabSummary, ...] = ()
    resources: tuple[ResourceHandle, ...] = ()
    upload: object | None = None
    prompt: BrowserPrompt | None = None

    def __post_init__(self) -> None:
        validate_result_contract(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class PagePdfResult(_TerminalFields):
    classified_effects: tuple[str, ...] = ()
    effect_facts: tuple[object, ...] = ()
    commands: tuple[object, ...] = ()
    context_before: ContextVersion | None = None
    context_after: ContextVersion | None = None
    context_outcome: str | None = None
    dispatch: object | None = None
    commit: object | None = None
    effect: object | None = None
    postcondition: object | None = None
    resource: ResourceHandle | None = None
    page_info: object | None = None

    def __post_init__(self) -> None:
        validate_result_contract(self)


RichBrowserResult: TypeAlias = (
    SnapshotResult
    | ReadResult
    | ScreenshotResult
    | WaitResult
    | ActionResult
    | PagePdfResult
)


def validate_result_contract(result: RichBrowserResult) -> None:
    """Reject status and payload combinations that claim false truth."""
    if not isinstance(
        result,
        (
            SnapshotResult,
            ReadResult,
            ScreenshotResult,
            WaitResult,
            ActionResult,
            PagePdfResult,
        ),
    ):
        raise ResultContractError("unsupported canonical result type")
    result.validate_terminal()
    if result.status not in {"SUCCEEDED", "PARTIAL"}:
        return
    if isinstance(result, SnapshotResult) and result.evidence is None:
        raise ResultContractError("SnapshotResult requires evidence")
    if isinstance(result, ReadResult) and (
        result.evidence is None or result.end_of_collection is None
    ):
        raise ResultContractError(
            "ReadResult requires evidence and collection state",
        )
    if isinstance(result, ScreenshotResult):
        if result.image is None or result.evidence is None:
            raise ResultContractError(
                "ScreenshotResult requires image and evidence",
            )
        if result.scope == "viewport" and result.visual_context is None:
            raise ResultContractError(
                "viewport ScreenshotResult requires visual context",
            )
        if result.scope == "full_page" and result.visual_context is not None:
            raise ResultContractError(
                "full_page ScreenshotResult cannot provide visual context",
            )
    if isinstance(result, WaitResult) and (
        result.evidence is None or result.outcome is None
    ):
        raise ResultContractError("WaitResult requires evidence and outcome")
    if isinstance(result, ActionResult) and not any(
        (
            result.already_satisfied,
            result.effect_facts,
            result.resources,
            result.opened_tabs,
            result.upload,
            result.prompt,
        ),
    ):
        raise ResultContractError(
            "ActionResult requires verified action facts",
        )
    if isinstance(result, PagePdfResult) and (
        result.resource is None or result.page_info is None
    ):
        raise ResultContractError(
            "PagePdfResult requires resource and page info",
        )


@dataclass(frozen=True, slots=True)
class CapabilityBlocked:
    """Machine-readable result for a not-yet-activated capability."""

    capability: str
    code: str = "browser_sdk_gap"


def canonical_api_catalog() -> dict[str, Any]:
    """Return the S0 canonical lifecycle-only API catalog."""
    return {
        "version": 1,
        "mode": "CANONICAL",
        "source": "canonical_browser_api",
        "apis": [
            _entry(
                "browser.close",
                "qwenpaw.browser.sdk.canonical.facade:Browser.close",
                "async close() -> None",
                mutates=True,
                summary="Release the current SDK lease only.",
            ),
            _entry(
                "browser.connect",
                "qwenpaw.browser.sdk.canonical.facade:Browser.connect",
                (
                    "async connect(context: Literal['auto', 'user', "
                    "'isolated'] = 'auto') -> Browser"
                ),
                mutates=False,
                summary="Connect with the trusted root-task binding.",
                parameters=[
                    {
                        "name": "context",
                        "kind": "POSITIONAL_OR_KEYWORD",
                        "required": False,
                        "default": "auto",
                        "annotation": "Literal['auto', 'user', 'isolated']",
                    },
                ],
            ),
            _entry(
                "tab.snapshot",
                "qwenpaw.browser.sdk.canonical.tabs:Tab.snapshot",
                (
                    "async snapshot(*, scope: ObservationScope | None = None, "
                    "query: TargetQuery | None = None, "
                    "limit: int | None = None) "
                    "-> SnapshotResult"
                ),
                mutates=False,
                kind="primitive",
                satisfies_observation=True,
                return_type="SnapshotResult",
                summary=(
                    "Capture neutral bounded evidence for this Tab receiver."
                ),
                parameters=[
                    {
                        "name": "scope",
                        "kind": "KEYWORD_ONLY",
                        "required": False,
                        "default": None,
                        "annotation": "ObservationScope | None",
                    },
                    {
                        "name": "query",
                        "kind": "KEYWORD_ONLY",
                        "required": False,
                        "default": None,
                        "annotation": "TargetQuery | None",
                    },
                    {
                        "name": "limit",
                        "kind": "KEYWORD_ONLY",
                        "required": False,
                        "default": None,
                        "annotation": "int | None",
                    },
                ],
            ),
            _entry(
                "tab.read",
                "qwenpaw.browser.sdk.canonical.tabs:Tab.read",
                (
                    "async read(*, scope: ObservationScope | None = None, "
                    "cursor: ReadCursor | None = None, "
                    "limit: int | None = None) "
                    "-> ReadResult"
                ),
                mutates=False,
                kind="primitive",
                satisfies_observation=True,
                return_type="ReadResult",
                summary="Read one page from an immutable bounded collection.",
                parameters=[
                    {
                        "name": "scope",
                        "kind": "KEYWORD_ONLY",
                        "required": False,
                        "default": None,
                        "annotation": "ObservationScope | None",
                    },
                    {
                        "name": "cursor",
                        "kind": "KEYWORD_ONLY",
                        "required": False,
                        "default": None,
                        "annotation": "ReadCursor | None",
                    },
                    {
                        "name": "limit",
                        "kind": "KEYWORD_ONLY",
                        "required": False,
                        "default": None,
                        "annotation": "int | None",
                    },
                ],
            ),
            _entry(
                "tab.screenshot",
                "qwenpaw.browser.sdk.canonical.tabs:Tab.screenshot",
                (
                    "async screenshot(*, scope: Literal['viewport', "
                    "'full_page'] = 'viewport') -> ScreenshotResult"
                ),
                mutates=False,
                kind="primitive",
                satisfies_observation=True,
                return_type="ScreenshotResult",
                summary="Capture a non-mutating exact screenshot variant.",
                parameters=[
                    {
                        "name": "scope",
                        "kind": "KEYWORD_ONLY",
                        "required": False,
                        "default": "viewport",
                        "annotation": "Literal['viewport', 'full_page']",
                    },
                ],
            ),
        ],
    }


def _entry(
    api_id: str,
    callable_path: str,
    signature: str,
    *,
    mutates: bool,
    summary: str,
    parameters: list[dict[str, Any]] | None = None,
    kind: str = "lifecycle",
    satisfies_observation: bool = False,
    return_type: str | None = None,
) -> dict[str, Any]:
    return {
        "api_id": api_id,
        "public_name": api_id,
        "kind": kind,
        "visibility": "default",
        "mutates": mutates,
        "requires_observation": False,
        "satisfies_observation": satisfies_observation,
        "invalidates_observation": False,
        "callable_path": callable_path,
        "signature": signature,
        "parameters": parameters or [],
        "return_type": return_type
        or ("None" if api_id == "browser.close" else "Browser"),
        "summary": summary,
    }


PUBLIC_CONSTRUCTOR_NAMES = (
    "TargetQuery",
    "CurrentSurface",
    "FrameScope",
    "RegionScope",
    "VisualRegion",
    "PageCondition",
    "TargetCondition",
    "RegionCondition",
    "SurfaceCondition",
    "ResourceCondition",
    "BrowserCondition",
    "ActionExpectation",
    "StateRequirement",
    "WorkflowRequirement",
    "OptionChoice",
    "PagePdfOptions",
)

OPAQUE_VALUE_NAMES = (
    "ContextVersion",
    "EvidenceRef",
    "VisualContextRef",
    "TargetRef",
    "RegionRef",
    "ReadCursor",
    "ReadSegment",
    "ReadSegmentKind",
    "ResourceHandle",
    "TabSummary",
    "BrowserPrompt",
)


def canonical_value_namespace() -> dict[str, type[Any]]:
    """Return the canonical public values from this single defining module."""
    names = PUBLIC_CONSTRUCTOR_NAMES + OPAQUE_VALUE_NAMES
    return {name: globals()[name] for name in names}


__all__ = [
    "ActionExpectation",
    "ActionResult",
    "BrowserCondition",
    "BrowserPrompt",
    "CaptureGap",
    "CaptureGapReason",
    "CaptureSource",
    "CapabilityBlocked",
    "CapabilityProblemDetails",
    "CleanupInfo",
    "ContextVersion",
    "Coverage",
    "CoverageGap",
    "CurrentSurface",
    "DeliveryGap",
    "DeliveryGapReason",
    "EvidenceKind",
    "EvidenceMeta",
    "EvidenceRef",
    "FrameScope",
    "GapDetail",
    "GapStage",
    "Notice",
    "ObservationScope",
    "OPAQUE_VALUE_NAMES",
    "OptionChoice",
    "PUBLIC_CONSTRUCTOR_NAMES",
    "PageCondition",
    "PagePdfOptions",
    "PagePdfResult",
    "Problem",
    "ReadCursor",
    "ReadResult",
    "RegionCondition",
    "RegionRef",
    "RegionScope",
    "RegionSummary",
    "ResourceCondition",
    "ResourceHandle",
    "ResultContractError",
    "RetryDirective",
    "RichBrowserResult",
    "ScreenshotResult",
    "SelectionGap",
    "SelectionGapReason",
    "SnapshotResult",
    "StateRequirement",
    "SurfaceCondition",
    "TabSummary",
    "TargetCondition",
    "TargetQuery",
    "TargetRef",
    "TargetSummary",
    "TerminalStatus",
    "TransportProblemDetails",
    "ValidationProblemDetails",
    "VisualContextRef",
    "VisualRegion",
    "WaitResult",
    "WorkflowRequirement",
    "can_prove_global_unique",
    "can_prove_negative",
    "canonical_api_catalog",
    "canonical_value_namespace",
    "coverage_from_gaps",
    "issue_operation_id",
    "validate_result_contract",
]
