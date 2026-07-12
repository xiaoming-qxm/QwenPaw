# -*- coding: utf-8 -*-
"""Canonical Tab, BrowserTabs, and TabActions public surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from ..governance.errors import BrowserSDKGap
from ..runtime.resources import (
    ResourceStore,
    ScreenshotCapture,
    TrustedOutputSource,
)
from ..runtime.result_delivery import RequiredBlock, record_browser_result
from ..runtime.observation_store import (
    ImmutableReadCollection,
    ObservationStore,
    ObservationStoreError,
)
from ..runtime.snapshot import (
    ObservationBudget,
    ReadCapture,
    SnapshotCapture,
    SnapshotTarget,
)
from .contracts import (
    CapabilityProblemDetails,
    CaptureGap,
    CoverageGap,
    CurrentSurface,
    EvidenceRef,
    FrameScope,
    ObservationScope,
    Problem,
    ReadCursor,
    ReadResult,
    ReadSegment,
    RegionScope,
    RegionSummary,
    SelectionGap,
    ScreenshotResult,
    SnapshotResult,
    RetryDirective,
    TargetQuery,
    TargetRef,
    TargetSummary,
    TerminalStatus,
    VisualRegion,
    VisualContextRef,
    _RUNTIME_VALUE_ISSUER,
    _issue_opaque_value,
    issue_operation_id,
)


Dispatch = Callable[..., Awaitable[Any]]


@dataclass(slots=True)
class TabActions:
    """S0 action surface; later stages activate individual capabilities."""

    dispatch: Dispatch | None = field(default=None, repr=False)

    async def click(self, *_args: Any, **_kwargs: Any) -> None:
        """Fail before backend dispatch until target/action stages activate."""
        raise _capability_blocked("tab.actions.click")


@dataclass(slots=True)
class Tab:
    """Canonical tab shell owned by this module."""

    id: str
    actions: TabActions = field(default_factory=TabActions)
    _session: Any = field(default=None, repr=False)
    _resources: ResourceStore | None = field(default=None, repr=False)
    _observations: ObservationStore | None = field(default=None, repr=False)

    async def snapshot(
        self,
        *,
        scope: ObservationScope | None = None,
        query: TargetQuery | None = None,
        limit: int | None = None,
    ) -> SnapshotResult:
        """Capture neutral bounded evidence for this exact Tab receiver."""
        requested_scope = scope or CurrentSurface()
        if isinstance(requested_scope, VisualRegion):
            return _record_snapshot_result(
                SnapshotResult(
                    operation_id=issue_operation_id(),
                    status="BLOCKED",
                    retry="AFTER_OBSERVATION",
                    problem=Problem(
                        code="capability_unavailable",
                        phase="PREFLIGHT",
                        safe_message=(
                            "VisualRegion snapshot is not available in S2."
                        ),
                        details=CapabilityProblemDetails(
                            capability="tab.snapshot.visual_region",
                        ),
                    ),
                ),
            )
        if self._session is None or self._observations is None:
            raise _capability_blocked("tab.snapshot")
        owner_chain = _scope_owner_chain(
            self._observations,
            requested_scope,
        )
        query_owner_chain = (
            _region_owner_chain(self._observations, query.region)
            if query is not None and query.region is not None
            else None
        )
        requested_limit, effective_limit, clamp_gap = _snapshot_limit(limit)
        capture = await self._session.capture_snapshot(
            self.id,
            scope=requested_scope,
            budget=ObservationBudget(
                capture_nodes=512,
                output_targets=effective_limit,
                hard_maximum=512,
            ),
        )
        if not isinstance(capture, SnapshotCapture):
            raise BrowserSDKGap(
                "Canonical snapshot producer returned invalid evidence.",
                action="tab.snapshot",
            )
        candidates = tuple(capture.targets)
        if owner_chain is not None:
            candidates = tuple(
                target
                for target in candidates
                if target.owner_chain[: len(owner_chain)] == owner_chain
            )
        if query_owner_chain is not None:
            candidates = tuple(
                target
                for target in candidates
                if target.owner_chain[: len(query_owner_chain)]
                == query_owner_chain
            )
        if query is not None:
            candidates = tuple(
                target
                for target in candidates
                if _query_matches(target, query)
            )
        gaps = list(capture.gaps)
        if clamp_gap is not None:
            gaps.append(clamp_gap)
        if len(candidates) > effective_limit:
            gaps.append(
                CoverageGap(
                    stage="SELECTION",
                    detail=SelectionGap(
                        reason="OUTPUT_LIMIT",
                        examined=effective_limit,
                        omitted=len(candidates) - effective_limit,
                        requested=requested_limit,
                        effective=effective_limit,
                    ),
                ),
            )
            candidates = candidates[:effective_limit]
        coverage = capture.coverage
        if coverage == "COMPLETE" and gaps:
            coverage = "PARTIAL"
        observation = self._observations.issue_evidence(
            kind="SNAPSHOT",
            scope=requested_scope,
            coverage=coverage,
            gaps=tuple(gaps),
        )
        target_summaries = tuple(
            _target_summary(target, index)
            for index, target in enumerate(candidates, start=1)
        )
        region_summaries = tuple(
            _region_summary(self._observations, region)
            for region in capture.regions
        )
        status, retry, problem = _snapshot_terminal(coverage)
        result = SnapshotResult(
            operation_id=issue_operation_id(),
            status=status,
            retry=retry,
            problem=problem,
            evidence=observation.ref,
            observation=observation,
            model_text=_snapshot_model_text(
                status=status,
                coverage=coverage,
                gaps=tuple(gaps),
                targets=target_summaries,
            ),
            targets=target_summaries,
            regions=region_summaries,
            grounding=None,
            source_summary=",".join(
                f"{item.source}:{'ok' if item.available else 'unavailable'}"
                for item in capture.sources
            ),
        )
        return _record_snapshot_result(result)

    async def read(
        self,
        *,
        scope: ObservationScope | None = None,
        cursor: ReadCursor | None = None,
        limit: int | None = None,
    ) -> ReadResult:
        """Read one page from a single bounded immutable capture."""
        if self._session is None or self._observations is None:
            raise _capability_blocked("tab.read")
        requested_limit, effective_limit, clamp_gap = _snapshot_limit(limit)
        if cursor is None:
            requested_scope = scope or CurrentSurface()
            if isinstance(requested_scope, VisualRegion):
                result = ReadResult(
                    operation_id=issue_operation_id(),
                    status="BLOCKED",
                    retry="AFTER_OBSERVATION",
                    problem=Problem(
                        code="capability_unavailable",
                        phase="PREFLIGHT",
                        safe_message=(
                            "VisualRegion read is not available in S2."
                        ),
                        details=CapabilityProblemDetails(
                            capability="tab.read.visual_region",
                        ),
                    ),
                )
                record_browser_result(result)
                return result
            _scope_owner_chain(self._observations, requested_scope)
            capture = await self._session.capture_read(
                self.id,
                scope=requested_scope,
                budget=ObservationBudget(
                    capture_nodes=512,
                    output_targets=512,
                    hard_maximum=512,
                ),
            )
            if not isinstance(capture, ReadCapture):
                raise BrowserSDKGap(
                    "Canonical read producer returned invalid evidence.",
                    action="tab.read",
                )
            observation = self._observations.issue_evidence(
                kind="READ",
                scope=requested_scope,
                coverage=capture.coverage,
                gaps=capture.gaps,
            )
            collection = ImmutableReadCollection(
                owner_key=self._observations.owner_key,
                root_session_id=self._observations.root_session_id,
                tab_id=self._observations.tab_id,
                context=self._observations.context,
                generation=self._observations.generation,
                evidence=observation,
                segments=capture.segments,
                expires_at=self._observations.collection_expiry(),
            )
            first_cursor = self._observations.save_collection(collection)
            page = self._observations.page(
                first_cursor,
                limit=effective_limit,
            )
        else:
            page = self._observations.page(cursor, limit=effective_limit)
            observation = page.evidence
            if scope is not None and observation.scope != scope:
                raise ObservationStoreError("cursor_scope_mismatch")
        if not all(
            isinstance(segment, ReadSegment) for segment in page.segments
        ):
            raise ObservationStoreError("read_collection_invalid")
        segments = tuple(
            segment
            for segment in page.segments
            if isinstance(segment, ReadSegment)
        )
        status, retry, problem = _read_terminal(observation.coverage)
        notices = ()
        clamp_notice = clamp_gap.notice if clamp_gap is not None else ""
        result = ReadResult(
            operation_id=issue_operation_id(),
            status=status,
            retry=retry,
            problem=problem,
            notices=notices,
            evidence=observation.ref,
            observation=observation,
            model_text=_read_model_text(
                status=status,
                observation=observation,
                clamp_notice=clamp_notice,
                segments=segments,
                end_of_collection=page.end_of_collection,
            ),
            segments=segments,
            next_cursor=page.next_cursor,
            end_of_collection=page.end_of_collection,
        )
        record_browser_result(result)
        del requested_limit
        return result

    async def screenshot(
        self,
        *,
        scope: Literal["viewport", "full_page"] = "viewport",
    ) -> ScreenshotResult:
        """Capture one exact non-mutating image variant and ingest bytes."""
        if self._session is None or self._resources is None:
            raise _capability_blocked("tab.screenshot")
        captured = await self._session.screenshot_exact(self.id, scope=scope)
        if not isinstance(captured, ScreenshotCapture):
            raise BrowserSDKGap(
                "Screenshot producer returned an invalid exact capture.",
                action="tab.screenshot",
            )
        if not captured.complete or not captured.data:
            result = ScreenshotResult(
                operation_id=issue_operation_id(),
                status="FAILED",
                retry="SAFE",
                problem=Problem(
                    code="screenshot_incomplete",
                    phase="CAPTURE",
                    safe_message=(
                        "Screenshot capture did not return complete bytes."
                    ),
                ),
                scope=scope,
            )
            record_browser_result(result)
            return result
        handle = await self._resources.ingest_output(
            TrustedOutputSource.from_bytes(captured.data),
            media_type=captured.media_type,
            name=captured.name,
            required_delivery=True,
        )
        invariant_gap = None
        if not captured.invariant_unchanged:
            invariant_gap = CoverageGap(
                stage="CAPTURE",
                detail=CaptureGap(
                    source="SCREENSHOT",
                    reason="INVARIANT_CHANGED",
                ),
            )
        observation = None
        if self._observations is not None:
            observation = self._observations.issue_evidence(
                kind="SCREENSHOT",
                scope=CurrentSurface(),
                coverage="PARTIAL" if invariant_gap else "COMPLETE",
                gaps=(invariant_gap,) if invariant_gap else (),
            )
            evidence: EvidenceRef = observation.ref
        else:
            issued_evidence = _issue_opaque_value(
                EvidenceRef,
                _RUNTIME_VALUE_ISSUER,
                id=f"evidence-{handle.id}",
            )
            assert isinstance(issued_evidence, EvidenceRef)
            evidence = issued_evidence
        visual_context: VisualContextRef | None = None
        if scope == "viewport":
            issued_visual_context = _issue_opaque_value(
                VisualContextRef,
                _RUNTIME_VALUE_ISSUER,
                id=f"visual-{handle.id}",
                tab_id=self.id,
                width=captured.width,
                height=captured.height,
                viewport=captured.before.viewport,
                layout=captured.before.layout,
            )
            assert isinstance(issued_visual_context, VisualContextRef)
            visual_context = issued_visual_context
        status: TerminalStatus = "PARTIAL" if invariant_gap else "SUCCEEDED"
        problem = (
            Problem(
                code="screenshot_invariant_changed",
                phase="VERIFY",
                safe_message=(
                    "Page state changed across screenshot capture; "
                    "image is partial evidence."
                ),
            )
            if invariant_gap
            else None
        )
        result = ScreenshotResult(
            operation_id=issue_operation_id(),
            status=status,
            retry="AFTER_OBSERVATION" if invariant_gap else "NONE",
            problem=problem,
            evidence=evidence,
            observation=observation,
            image=handle,
            visual_context=visual_context,
            scope=scope,
        )
        record_browser_result(
            result,
            required_blocks=(
                RequiredBlock(
                    kind="image",
                    resource_id=str(handle.id),
                    media_type=captured.media_type,
                    payload=handle,
                ),
            ),
        )
        return result


@dataclass(slots=True)
class BrowserTabs:
    """Canonical tab collection shell."""

    _session: Any = field(default=None, repr=False)
    _resources: ResourceStore | None = field(default=None, repr=False)

    async def active(self) -> Tab:
        raise _capability_blocked("browser.tabs.active")


def _capability_blocked(capability: str) -> BrowserSDKGap:
    return BrowserSDKGap(
        f"Canonical capability is not active in S0: {capability}",
        action=capability,
        metadata={"capability": capability, "backend_dispatch_count": 0},
    )


def _record_snapshot_result(result: SnapshotResult) -> SnapshotResult:
    record_browser_result(result)
    return result


def _scope_owner_chain(
    store: ObservationStore,
    scope: ObservationScope,
) -> tuple[str, ...] | None:
    if isinstance(scope, CurrentSurface):
        return None
    if isinstance(scope, FrameScope):
        return store.require_region(
            scope.frame_region,
            kind="FRAME",
        ).owner_chain
    if isinstance(scope, RegionScope):
        return _region_owner_chain(store, scope.region)
    return None


def _region_owner_chain(
    store: ObservationStore,
    region: Any,
) -> tuple[str, ...]:
    kinds: tuple[Literal["FRAME", "CONTENT", "OWNER"], ...] = (
        "FRAME",
        "CONTENT",
        "OWNER",
    )
    for kind in kinds:
        try:
            return store.require_region(region, kind=kind).owner_chain
        except ObservationStoreError as exc:
            if exc.code != "region_type_mismatch":
                raise
    raise ObservationStoreError("region_type_mismatch")


def _snapshot_limit(
    limit: int | None,
) -> tuple[int, int, CoverageGap | None]:
    requested = 64 if limit is None else int(limit)
    if requested < 1:
        raise ValueError("snapshot limit must be positive")
    effective = min(requested, 128)
    if requested == effective:
        return requested, effective, None
    return (
        requested,
        effective,
        CoverageGap(
            stage="SELECTION",
            detail=SelectionGap(
                reason="LIMIT_CLAMPED",
                requested=requested,
                effective=effective,
            ),
        ),
    )


def _query_matches(target: SnapshotTarget, query: TargetQuery) -> bool:
    checks: list[bool] = []
    if query.role:
        checks.append(_text_matches(target.role, query.role, query.match))
    if query.name:
        checks.append(_text_matches(target.name, query.name, query.match))
    if query.text:
        checks.append(_text_matches(target.name, query.text, query.match))
    return all(checks)


def _text_matches(value: str, expected: str, match: str) -> bool:
    value_key = value.casefold()
    expected_key = expected.casefold()
    return (
        value_key == expected_key
        if match == "exact"
        else expected_key in value_key
    )


def _target_summary(target: SnapshotTarget, index: int) -> TargetSummary:
    ref = _issue_opaque_value(
        TargetRef,
        _RUNTIME_VALUE_ISSUER,
        id=f"target-{issue_operation_id()}-{index}",
    )
    assert isinstance(ref, TargetRef)
    return TargetSummary(
        ref=ref,
        role=target.role,
        name=target.name,
        states=target.states,
        allowed_actions=(),
    )


def _region_summary(store: ObservationStore, region: Any) -> RegionSummary:
    ref = store.issue_region(
        kind=region.kind,
        native_identity=region.native_identity,
        owner_chain=region.owner_chain,
    )
    return RegionSummary(
        ref=ref,
        kind=region.kind,
        boundary=region.boundary,
        accessible=region.accessible,
    )


def _snapshot_terminal(
    coverage: str,
) -> tuple[TerminalStatus, RetryDirective, Problem | None]:
    if coverage == "COMPLETE":
        return "SUCCEEDED", "NONE", None
    if coverage == "PARTIAL":
        return (
            "PARTIAL",
            "AFTER_OBSERVATION",
            Problem(
                code="observation_partial",
                phase="CAPTURE",
                safe_message=(
                    "Snapshot evidence is partial; inspect coverage gaps."
                ),
            ),
        )
    code = (
        "observation_stale"
        if coverage == "STALE"
        else "observation_unavailable"
    )
    return (
        "BLOCKED",
        "AFTER_OBSERVATION",
        Problem(
            code=code,
            phase="CAPTURE",
            safe_message="Snapshot evidence is unavailable for this surface.",
        ),
    )


def _snapshot_model_text(
    *,
    status: str,
    coverage: str,
    gaps: tuple[CoverageGap, ...],
    targets: tuple[TargetSummary, ...],
) -> str:
    lines = [f"status={status} coverage={coverage}"]
    for gap in gaps:
        detail = gap.detail
        notice = gap.notice
        lines.append(
            " ".join(
                part
                for part in (
                    f"stage={gap.stage}",
                    f"reason={detail.reason}",
                    f"examined={detail.examined}",
                    f"omitted={detail.omitted}",
                    notice,
                )
                if part
            ),
        )
    lines.extend(
        f"target role={target.role} name={target.name}" for target in targets
    )
    return "\n".join(lines)


def _read_terminal(
    coverage: str,
) -> tuple[TerminalStatus, RetryDirective, Problem | None]:
    if coverage == "COMPLETE":
        return "SUCCEEDED", "NONE", None
    if coverage == "PARTIAL":
        return (
            "PARTIAL",
            "AFTER_OBSERVATION",
            Problem(
                code="observation_partial",
                phase="CAPTURE",
                safe_message=(
                    "Read collection is partial; inspect coverage gaps."
                ),
            ),
        )
    code = (
        "observation_stale"
        if coverage == "STALE"
        else "observation_unavailable"
    )
    return (
        "BLOCKED",
        "AFTER_OBSERVATION",
        Problem(
            code=code,
            phase="CAPTURE",
            safe_message="Read collection could not be established.",
        ),
    )


def _read_model_text(
    *,
    status: str,
    observation: Any,
    clamp_notice: str,
    segments: tuple[ReadSegment, ...],
    end_of_collection: bool,
) -> str:
    lines = [f"status={status} coverage={observation.coverage}"]
    lines.extend(
        (
            f"stage={gap.stage} reason={gap.detail.reason} "
            f"examined={gap.detail.examined} omitted={gap.detail.omitted}"
        )
        for gap in observation.gaps
    )
    if clamp_notice:
        lines.append(clamp_notice)
    lines.extend(f"{segment.kind}: {segment.text}" for segment in segments)
    lines.append(f"end_of_collection={str(end_of_collection).lower()}")
    return "\n".join(lines)


__all__ = ["BrowserTabs", "Tab", "TabActions"]
