# -*- coding: utf-8 -*-
"""Snapshot helpers shared by Browser SDK backends."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from ..canonical.contracts import (
    CaptureGap,
    ContextVersion,
    Coverage,
    CoverageGap,
    ObservationScope,
    ReadSegment,
    SelectionGap,
    TargetRef,
)
from .session_owner import (
    BrowserRequestBinding,
    BrowserSessionOwnerRegistry,
    TargetBinding,
)

INTERACTIVE_ROLES = frozenset(
    {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "combobox",
        "listbox",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "option",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
        "tab",
        "treeitem",
    },
)


SnapshotSource = Literal["AX", "DOM"]
RegionKind = Literal["FRAME", "CONTENT", "OWNER"]
SurfaceBoundary = Literal[
    "DEFAULT",
    "SAME_ORIGIN",
    "CROSS_ORIGIN",
    "OPEN_SHADOW",
    "CLOSED_SHADOW",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservationBudget:
    """Reviewed work and delivery bounds for one neutral capture."""

    capture_nodes: int
    output_targets: int
    hard_maximum: int

    def __post_init__(self) -> None:
        if (
            min(
                self.capture_nodes,
                self.output_targets,
                self.hard_maximum,
            )
            < 1
        ):
            raise ValueError("observation budgets must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeNode:
    """Private normalized source node keyed only by backend identity."""

    source: SnapshotSource
    native_identity: str
    owner: str
    role: str
    name: str
    actionable: bool
    relation_identity: str | None = None
    states: tuple[str, ...] = ()
    owner_chain: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source not in {"AX", "DOM"}:
            raise ValueError("snapshot source must be AX or DOM")
        if not self.native_identity.strip() or not self.owner.strip():
            raise ValueError("probe node requires native identity and owner")
        if not self.owner_chain:
            object.__setattr__(self, "owner_chain", (self.owner,))


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeRegion:
    """Private frame/content/owner boundary discovered during capture."""

    kind: RegionKind
    native_identity: str
    owner: str
    owner_chain: tuple[str, ...]
    boundary: SurfaceBoundary
    accessible: bool


@dataclass(frozen=True, slots=True)
class ProbeBatch:
    """One source batch with explicit surface regions and boundary gaps."""

    nodes: tuple[ProbeNode, ...] = ()
    regions: tuple[ProbeRegion, ...] = ()
    gaps: tuple[CoverageGap, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceOutcome:
    source: SnapshotSource
    available: bool
    examined: int
    error_code: str = ""


@dataclass(frozen=True, slots=True)
class SnapshotTarget:
    """Neutral merged target; native identity stays inside runtime capture."""

    native_identity: str
    owner: str
    owner_chain: tuple[str, ...]
    role: str
    name: str
    states: tuple[str, ...]
    sources: tuple[SnapshotSource, ...]
    identity_conflict: bool
    executable: bool
    ref: TargetRef | None = None


@dataclass(frozen=True, slots=True)
class RegionSummary:
    """Safe surface summary; public authority is issued later as RegionRef."""

    kind: RegionKind
    owner: str
    owner_chain: tuple[str, ...]
    boundary: SurfaceBoundary
    accessible: bool
    native_identity: str


@dataclass(frozen=True, slots=True)
class SnapshotCapture:
    context: ContextVersion
    scope: ObservationScope
    generation: str
    coverage: Coverage
    gaps: tuple[CoverageGap, ...]
    sources: tuple[SourceOutcome, ...]
    targets: tuple[SnapshotTarget, ...]
    regions: tuple[RegionSummary, ...] = ()
    frontier: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadCapture:
    """Bounded normalized content captured once before immutable paging."""

    context: ContextVersion
    scope: ObservationScope
    generation: str
    coverage: Coverage
    gaps: tuple[CoverageGap, ...]
    segments: tuple[ReadSegment, ...]

    def __post_init__(self) -> None:
        if not all(
            isinstance(segment, ReadSegment) for segment in self.segments
        ):
            raise TypeError("ReadCapture segments must be ReadSegment values")


def bind_snapshot_targets(
    capture: SnapshotCapture,
    *,
    registry: BrowserSessionOwnerRegistry,
    owner: BrowserRequestBinding,
    receiver_tab: str,
    backend_id: str,
    frame_key: str,
    expires_at: float,
) -> SnapshotCapture:
    """Bind one trusted neutral capture to opaque executable target refs."""
    registry.resolve_context(
        capture.context,
        owner=owner,
        receiver_tab=receiver_tab,
    )
    context_ref = str(capture.context.version_ref)
    targets: list[SnapshotTarget] = []
    for target in capture.targets:
        binding = TargetBinding(
            root_task_id=owner.root_task_id,
            browser_owner_id=owner.browser_owner_id,
            session_id=owner.root_session_id,
            backend_id=str(backend_id),
            receiver_tab_key=str(receiver_tab),
            frame_key=str(frame_key),
            context_ref=context_ref,
            native_identity=(("nativeIdentity", target.native_identity),),
            action_state=tuple((state, True) for state in target.states),
            geometry_digest="",
            visual_context_ref=None,
            allowed_actions=(),
            effect_ceiling=(),
            use_state="FRESH",
            expires_at=float(expires_at),
        )
        ref = registry.issue_target(
            binding,
            safe_role=target.role,
            safe_name=target.name,
        )
        targets.append(replace(target, ref=ref))
    return replace(capture, targets=tuple(targets))


class SnapshotProbe(Protocol):
    """Minimal backend capture boundary used by the neutral pipeline."""

    async def generation(self) -> str:
        ...

    async def capture_ax(
        self,
        *,
        limit: int,
    ) -> tuple[ProbeNode, ...] | ProbeBatch:
        ...

    async def capture_dom(
        self,
        *,
        limit: int,
    ) -> tuple[ProbeNode, ...] | ProbeBatch:
        ...


async def capture_snapshot(
    probe: SnapshotProbe,
    *,
    context: ContextVersion,
    scope: ObservationScope,
    budget: ObservationBudget,
) -> SnapshotCapture:
    """Capture AX and DOM together without fallback or semantic bias."""
    for attempt in range(2):
        generation_before = await probe.generation()
        ax_result, dom_result = await asyncio.gather(
            _capture_source(probe, "AX", budget.capture_nodes),
            _capture_source(probe, "DOM", budget.capture_nodes),
        )
        generation_after = await probe.generation()
        if generation_before == generation_after:
            return _assemble_capture(
                context=context,
                scope=scope,
                generation=generation_after,
                budget=budget,
                source_results=(ax_result, dom_result),
            )
        if attempt == 0:
            continue
    stale_gap = CoverageGap(
        stage="CAPTURE",
        detail=CaptureGap(
            source="DOCUMENT",
            reason="GENERATION_MISMATCH",
        ),
    )
    return SnapshotCapture(
        context=context,
        scope=scope,
        generation=generation_after,
        coverage="STALE",
        gaps=(stale_gap,),
        sources=(ax_result[0], dom_result[0]),
        targets=(),
    )


async def _capture_source(
    probe: SnapshotProbe,
    source: SnapshotSource,
    limit: int,
) -> tuple[
    SourceOutcome,
    tuple[ProbeNode, ...],
    tuple[ProbeRegion, ...],
    tuple[CoverageGap, ...],
]:
    try:
        if source == "AX":
            nodes = await probe.capture_ax(limit=limit)
        else:
            nodes = await probe.capture_dom(limit=limit)
    except Exception:  # noqa: BLE001 - source loss is typed evidence
        return (
            SourceOutcome(
                source=source,
                available=False,
                examined=0,
                error_code="source_unavailable",
            ),
            (),
            (),
            (),
        )
    if isinstance(nodes, ProbeBatch):
        batch = nodes
    else:
        batch = ProbeBatch(nodes=tuple(nodes))
    normalized = tuple(node for node in batch.nodes if node.source == source)
    return (
        SourceOutcome(
            source=source,
            available=True,
            examined=len(normalized),
        ),
        normalized,
        batch.regions,
        batch.gaps,
    )


def _assemble_capture(
    *,
    context: ContextVersion,
    scope: ObservationScope,
    generation: str,
    budget: ObservationBudget,
    source_results: tuple[
        tuple[
            SourceOutcome,
            tuple[ProbeNode, ...],
            tuple[ProbeRegion, ...],
            tuple[CoverageGap, ...],
        ],
        tuple[
            SourceOutcome,
            tuple[ProbeNode, ...],
            tuple[ProbeRegion, ...],
            tuple[CoverageGap, ...],
        ],
    ],
) -> SnapshotCapture:
    outcomes = tuple(result[0] for result in source_results)
    available_nodes = tuple(
        node for result in source_results for node in result[1]
    )
    regions = _merge_regions(
        tuple(region for result in source_results for region in result[2]),
    )
    gaps: list[CoverageGap] = [
        gap for result in source_results for gap in result[3]
    ]
    for outcome in outcomes:
        if not outcome.available:
            gaps.append(
                CoverageGap(
                    stage="CAPTURE",
                    detail=CaptureGap(
                        source=outcome.source,
                        reason="SOURCE_UNAVAILABLE",
                    ),
                ),
            )
    selected, omitted, frontier = _fair_capture_frontier(
        available_nodes,
        min(budget.capture_nodes, budget.hard_maximum),
    )
    if omitted:
        gaps.append(
            CoverageGap(
                stage="CAPTURE",
                detail=CaptureGap(
                    source="AX_DOM",
                    reason="BUDGET_EXHAUSTED",
                    examined=len(selected),
                    omitted=omitted,
                    frontier=";".join(frontier),
                ),
            ),
        )
    targets = _merge_neutral_targets(selected)
    output_limit = min(budget.output_targets, budget.hard_maximum)
    if len(targets) > output_limit:
        omitted_targets = len(targets) - output_limit
        gaps.append(
            CoverageGap(
                stage="SELECTION",
                detail=SelectionGap(
                    reason="OUTPUT_LIMIT",
                    examined=output_limit,
                    omitted=omitted_targets,
                ),
            ),
        )
        targets = targets[:output_limit]
    if not any(outcome.available for outcome in outcomes):
        coverage: Coverage = "UNAVAILABLE"
    elif gaps:
        coverage = "PARTIAL"
    else:
        coverage = "COMPLETE"
    return SnapshotCapture(
        context=context,
        scope=scope,
        generation=generation,
        coverage=coverage,
        gaps=tuple(gaps),
        sources=outcomes,
        targets=targets,
        regions=regions,
        frontier=frontier,
    )


def _fair_capture_frontier(
    nodes: tuple[ProbeNode, ...],
    limit: int,
) -> tuple[tuple[ProbeNode, ...], int, tuple[str, ...]]:
    partitions: dict[str, deque[ProbeNode]] = defaultdict(deque)
    owner_order: list[str] = []
    for node in nodes:
        if node.owner not in partitions:
            owner_order.append(node.owner)
        partitions[node.owner].append(node)
    selected: list[ProbeNode] = []
    while len(selected) < limit and any(partitions.values()):
        for owner in owner_order:
            if len(selected) >= limit:
                break
            partition = partitions[owner]
            if partition:
                selected.append(partition.popleft())
    omitted = sum(len(partition) for partition in partitions.values())
    frontier = tuple(
        f"{owner}:{len(partitions[owner])}"
        for owner in owner_order
        if partitions[owner]
    )
    return tuple(selected), omitted, frontier


def _merge_neutral_targets(
    nodes: tuple[ProbeNode, ...],
) -> tuple[SnapshotTarget, ...]:
    order: list[tuple[str, str]] = []
    grouped: dict[tuple[str, str], list[ProbeNode]] = {}
    for node in nodes:
        identity = node.relation_identity or node.native_identity
        key = (node.owner, identity)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(node)
    targets: list[SnapshotTarget] = []
    for owner, identity in order:
        group = grouped[(owner, identity)]
        first = group[0]
        owners = {node.owner for node in group}
        actions = {node.actionable for node in group}
        identities = {node.native_identity for node in group}
        identity_conflict = len(owners) != 1 or len(actions) != 1
        merged_sources: list[SnapshotSource] = []
        source_order: tuple[SnapshotSource, ...] = ("AX", "DOM")
        for source in source_order:
            if any(node.source == source for node in group):
                merged_sources.append(source)
        targets.append(
            SnapshotTarget(
                native_identity=(
                    first.native_identity if len(identities) == 1 else identity
                ),
                owner=owner,
                owner_chain=first.owner_chain,
                role=first.role,
                name=first.name,
                states=tuple(
                    dict.fromkeys(
                        state for node in group for state in node.states
                    ),
                ),
                sources=tuple(merged_sources),
                identity_conflict=identity_conflict,
                executable=(
                    not identity_conflict
                    and all(node.actionable for node in group)
                ),
            ),
        )
    return tuple(targets)


def _merge_regions(
    regions: tuple[ProbeRegion, ...],
) -> tuple[RegionSummary, ...]:
    summaries: list[RegionSummary] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for region in regions:
        key = (region.kind, region.native_identity, region.owner_chain)
        if key in seen:
            continue
        seen.add(key)
        summaries.append(
            RegionSummary(
                kind=region.kind,
                owner=region.owner,
                owner_chain=region.owner_chain,
                boundary=region.boundary,
                accessible=region.accessible,
                native_identity=region.native_identity,
            ),
        )
    return tuple(summaries)


def build_role_snapshot_from_aria(*args: Any, **kwargs: Any) -> Any:
    """Build a role snapshot from a Playwright ARIA snapshot."""
    from qwenpaw.agents.tools.browser_snapshot import (
        build_role_snapshot_from_aria as _build,
    )

    return _build(*args, **kwargs)


def from_cdp_ax_tree(*args: Any, **kwargs: Any) -> Any:
    """Build a snapshot from a Chrome DevTools accessibility tree."""
    from qwenpaw.agents.tools.browser_snapshot import (
        from_cdp_ax_tree as _build,
    )

    return _build(*args, **kwargs)


def from_cdp_dom_tree(*args: Any, **kwargs: Any) -> Any:
    """Build a snapshot from a Chrome DevTools DOM tree."""
    from qwenpaw.agents.tools.browser_snapshot import (
        from_cdp_dom_tree as _build,
    )

    return _build(*args, **kwargs)


def from_cdp_dom_snapshot(*args: Any, **kwargs: Any) -> Any:
    """Build a snapshot from a Chrome DevTools DOM snapshot."""
    from qwenpaw.agents.tools.browser_snapshot import (
        from_cdp_dom_snapshot as _build,
    )

    return _build(*args, **kwargs)


def is_trivial_snapshot(snapshot: str, *, min_length: int = 50) -> bool:
    """Return true when structured evidence is too small to act on."""
    text = str(snapshot or "").strip()
    return not text or text == "(empty)" or len(text) < min_length


def refs_from_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return refs from a snapshot-like payload."""
    refs = payload.get("refs")
    return refs if isinstance(refs, dict) else {}


__all__ = [
    "bind_snapshot_targets",
    "build_role_snapshot_from_aria",
    "capture_snapshot",
    "from_cdp_ax_tree",
    "from_cdp_dom_snapshot",
    "from_cdp_dom_tree",
    "INTERACTIVE_ROLES",
    "is_trivial_snapshot",
    "ObservationBudget",
    "ProbeBatch",
    "ProbeNode",
    "ProbeRegion",
    "RegionKind",
    "RegionSummary",
    "ReadCapture",
    "refs_from_snapshot_payload",
    "SnapshotCapture",
    "SnapshotProbe",
    "SnapshotTarget",
    "SourceOutcome",
    "SurfaceBoundary",
]
