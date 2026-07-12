# -*- coding: utf-8 -*-
"""Canonical Tab, BrowserTabs, and TabActions public surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Awaitable, Callable, Literal, cast

from ..backends.protocols import BackendProfile
from ..condition_evaluator import (
    ConditionEvaluation,
    ConditionEvaluator,
    ConditionReceiver,
    TargetFacts,
)
from ..governance.errors import BrowserSDKError, BrowserSDKGap
from ..primitives.matching import normalize_visible_text
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
from ..runtime.session_owner import (
    BrowserRequestBinding,
    BrowserSessionOwnerRegistry,
)
from .contracts import (
    ActionResult,
    CapabilityProblemDetails,
    BrowserCondition,
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
    ResourceCondition,
    SelectionGap,
    ScreenshotResult,
    SnapshotResult,
    SurfaceCondition,
    RetryDirective,
    TargetQuery,
    TargetRef,
    TargetSummary,
    TerminalStatus,
    VisualRegion,
    VisualContextRef,
    WaitResult,
    _condition_usage,
    _RUNTIME_VALUE_ISSUER,
    _issue_opaque_value,
    issue_operation_id,
)


Dispatch = Callable[..., Awaitable[Any]]


@dataclass(slots=True)
class TabActions:
    """S0 action surface; later stages activate individual capabilities."""

    dispatch: Dispatch | None = field(default=None, repr=False)
    _target_registry: BrowserSessionOwnerRegistry | None = field(
        default=None,
        repr=False,
    )
    _owner_binding: BrowserRequestBinding | None = field(
        default=None,
        repr=False,
    )
    _receiver_tab: str = field(default="", repr=False)

    async def click(self, target: TargetRef) -> ActionResult:
        """Fail before backend dispatch until target/action stages activate."""
        if isinstance(target, str):
            # Preserve the S0 zero-dispatch characterization while the
            # canonical signature and all executable authority are TargetRef.
            raise _capability_blocked("tab.actions.click")
        self._require_target(target)
        return _blocked_canonical_action("tab.actions.click", target=target)

    async def drag(
        self,
        source: TargetRef,
        destination: TargetRef,
    ) -> ActionResult:
        """Validate ordered endpoints without enabling native dispatch."""
        self._require_target(source)
        self._require_target(destination)
        return _blocked_canonical_action(
            "tab.actions.drag",
            source=source,
            destination=destination,
        )

    def _require_target(self, target: TargetRef) -> None:
        if not isinstance(target, TargetRef):
            raise BrowserSDKError(
                "Canonical mutation target must be a TargetRef.",
                code="target_invalid",
                action="tab.actions",
            )
        if (
            self._target_registry is None
            or self._owner_binding is None
            or not self._receiver_tab
        ):
            raise BrowserSDKError(
                "runtime_issued_value: target authority is unavailable",
                code="runtime_issued_value",
                action="tab.actions",
            )
        self._target_registry.resolve_target(
            target,
            receiver_tab=self._receiver_tab,
            owner=self._owner_binding,
        )


@dataclass(slots=True)
class Tab:
    """Canonical tab shell owned by this module."""

    id: str
    actions: TabActions = field(default_factory=TabActions)
    _session: Any = field(default=None, repr=False)
    _resources: ResourceStore | None = field(default=None, repr=False)
    _observations: ObservationStore | None = field(default=None, repr=False)
    _condition_evaluator: ConditionEvaluator | Any = field(
        default=None,
        repr=False,
    )
    _profile: BackendProfile | None = field(default=None, repr=False)
    _target_registry: BrowserSessionOwnerRegistry | None = field(
        default=None,
        repr=False,
    )
    _owner_binding: BrowserRequestBinding | None = field(
        default=None,
        repr=False,
    )
    _target_facts: tuple[TargetFacts, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        self.actions = TabActions(
            dispatch=self.actions.dispatch,
            _target_registry=self._target_registry,
            _owner_binding=self._owner_binding,
            _receiver_tab=self.id,
        )

    async def wait_for(
        self,
        condition: BrowserCondition,
        *,
        timeout_ms: int,
        stable_ms: int = 0,
    ) -> WaitResult:
        """Wait for one bounded flat typed condition on this Tab receiver."""
        preflight = _wait_preflight(
            condition,
            timeout_ms=timeout_ms,
            stable_ms=stable_ms,
            profile=self._profile,
        )
        if preflight is not None:
            return _record_wait_result(preflight)
        if self._observations is None:
            raise _capability_blocked("tab.wait_for")
        unsupported = tuple(
            atom
            for atom in condition.atoms
            if isinstance(
                atom,
                (SurfaceCondition, ResourceCondition),
            )
        )
        if unsupported:
            observation = self._observations.issue_evidence(
                kind="SNAPSHOT",
                scope=CurrentSurface(),
                coverage="UNAVAILABLE",
                gaps=(),
            )
            return _record_wait_result(
                WaitResult(
                    operation_id=issue_operation_id(),
                    status="BLOCKED",
                    retry="AFTER_OBSERVATION",
                    problem=Problem(
                        code="capability_unavailable",
                        phase="PREFLIGHT",
                        safe_message=(
                            "One or more condition families are not active."
                        ),
                        details=CapabilityProblemDetails(
                            capability="tab.wait_for.condition_family",
                        ),
                    ),
                    evidence=observation.ref,
                    outcome="UNAVAILABLE",
                    last_observed=observation.context,
                ),
            )
        if self._session is None or self._condition_evaluator is None:
            raise _capability_blocked("tab.wait_for")
        probe = self._session.condition_probe(self.id)
        receiver = ConditionReceiver(
            owner_key=self._observations.owner_key,
            root_session_id=self._observations.root_session_id,
            tab_id=self.id,
            context=self._observations.context,
            generation=self._observations.generation,
            observation_store=self._observations,
            target_registry=self._target_registry,
            owner_binding=self._owner_binding,
            target_facts=self._target_facts,
        )
        evaluation = await self._condition_evaluator.evaluate(
            receiver,
            condition,
            probe=probe,
            timeout_ms=timeout_ms,
            stable_ms=stable_ms,
            baseline=None,
            armed=None,
        )
        if not isinstance(evaluation, ConditionEvaluation):
            raise BrowserSDKGap(
                "Condition evaluator returned invalid terminal facts.",
                action="tab.wait_for",
            )
        return _record_wait_result(_wait_result(evaluation))

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
        if query is not None:
            candidates = apply_target_query(
                candidates,
                query,
                region_owner_chain=query_owner_chain,
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
        self._target_facts = tuple(
            TargetFacts(
                ref=summary.ref,
                role=summary.role,
                name=summary.name,
                text=summary.name,
                states=summary.states,
                checked=(True if "checked" in summary.states else None),
            )
            for summary in target_summaries
        )
        region_summaries = tuple(
            _region_summary(self._observations, region)
            for region in capture.regions
        )
        register_baseline = getattr(
            self._session,
            "_register_condition_region_baseline",
            None,
        )
        if callable(register_baseline):
            register = cast(Callable[[Any, Any, str], None], register_baseline)
            for captured_region, summary in zip(
                capture.regions,
                region_summaries,
                strict=True,
            ):
                text = normalize_visible_text(
                    " ".join(
                        target.name
                        for target in capture.targets
                        if tuple(target.owner_chain)
                        == tuple(captured_region.owner_chain)
                    ),
                )
                # pylint: disable-next=not-callable
                register(
                    summary.ref,
                    observation.ref,
                    sha256(text.encode()).hexdigest(),
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
    _condition_evaluator: ConditionEvaluator | None = field(
        default=None,
        repr=False,
    )
    _profile: BackendProfile | None = field(default=None, repr=False)
    _target_registry: BrowserSessionOwnerRegistry | None = field(
        default=None,
        repr=False,
    )
    _owner_binding: BrowserRequestBinding | None = field(
        default=None,
        repr=False,
    )
    _selected: Tab | None = field(default=None, repr=False)

    async def active(self) -> Tab:
        if self._selected is not None:
            return self._selected
        raise _capability_blocked("browser.tabs.active")

    async def select(self, tab: Tab) -> Tab:
        """Select only the collection pointer; never rebind the Tab."""
        if not isinstance(tab, Tab):
            raise TypeError("tabs.select requires a Tab")
        self._selected = tab
        return tab


def _capability_blocked(capability: str) -> BrowserSDKGap:
    return BrowserSDKGap(
        f"Canonical capability is not active in S0: {capability}",
        action=capability,
        metadata={"capability": capability, "backend_dispatch_count": 0},
    )


def _blocked_canonical_action(
    capability: str,
    *,
    target: TargetRef | None = None,
    source: TargetRef | None = None,
    destination: TargetRef | None = None,
) -> ActionResult:
    """Return structured zero-dispatch truth for a valid grounded target."""
    return ActionResult(
        operation_id=issue_operation_id(),
        status="BLOCKED",
        retry="AFTER_OBSERVATION",
        problem=Problem(
            code="canonical_action_dispatch_not_enabled",
            phase="PREFLIGHT",
            safe_message=(
                f"Canonical action dispatch is not enabled: {capability}."
            ),
        ),
        target=target,
        source=source,
        destination=destination,
        commands=(),
        effect_facts=(),
    )


def _record_snapshot_result(result: SnapshotResult) -> SnapshotResult:
    record_browser_result(result)
    return result


def _record_wait_result(result: WaitResult) -> WaitResult:
    record_browser_result(result)
    return result


# pylint: disable-next=too-many-return-statements
def _wait_preflight(
    condition: BrowserCondition,
    *,
    timeout_ms: int,
    stable_ms: int,
    profile: BackendProfile | None,
) -> WaitResult | None:
    if not isinstance(condition, BrowserCondition):
        return _invalid_wait("condition must be a BrowserCondition")
    action_only = any(
        _condition_usage(atom) == "ACTION_EXPECTATION_ONLY"
        for atom in condition.atoms
    )
    if action_only:
        return _invalid_wait(
            "ResourceCondition.created is action-expectation-only",
        )
    limits = profile.hard_limits if profile is not None else {}
    max_wait_ms = int(limits.get("max_wait_ms", 30_000))
    max_stable_ms = int(limits.get("max_stable_ms", 5_000))
    max_atoms = int(limits.get("max_condition_atoms", 16))
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool):
        return _invalid_wait("timeout_ms must be an integer")
    if not isinstance(stable_ms, int) or isinstance(stable_ms, bool):
        return _invalid_wait("stable_ms must be an integer")
    if timeout_ms < 1 or timeout_ms > max_wait_ms:
        return _invalid_wait("timeout_ms exceeds the backend profile")
    if stable_ms < 0 or stable_ms > min(timeout_ms, max_stable_ms):
        return _invalid_wait("stable_ms exceeds the backend profile")
    if len(condition.atoms) > max_atoms:
        return _invalid_wait("condition exceeds max_condition_atoms")
    return None


def _invalid_wait(message: str) -> WaitResult:
    return WaitResult(
        operation_id=issue_operation_id(),
        status="FAILED",
        retry="NONE",
        problem=Problem(
            code="condition_invalid_argument",
            phase="PREFLIGHT",
            safe_message=message,
        ),
        outcome="INVALID_ARGUMENT",
    )


def _wait_result(evaluation: ConditionEvaluation) -> WaitResult:
    problem = _wait_problem(evaluation)
    retry: RetryDirective = "NONE"
    if evaluation.status in {"PARTIAL", "BLOCKED"}:
        retry = "AFTER_OBSERVATION"
    elif evaluation.status == "FAILED":
        retry = "SAFE"
    return WaitResult(
        operation_id=issue_operation_id(),
        status=evaluation.status,
        retry=retry,
        problem=problem,
        cleanup=evaluation.cleanup,
        evidence=(
            evaluation.evidence.ref
            if evaluation.evidence is not None
            else None
        ),
        outcome=evaluation.outcome,
        matched_atoms=evaluation.matched_atoms,
        last_observed=evaluation.last_observed,
        elapsed_ms=evaluation.elapsed_ms,
    )


def _wait_problem(evaluation: ConditionEvaluation) -> Problem | None:
    if evaluation.status == "SUCCEEDED":
        return None
    code = {
        "TIMED_OUT": "condition_timeout_partial",
        "STALE": "condition_baseline_stale",
        "UNAVAILABLE": "condition_probe_unavailable",
        "INVALID_ARGUMENT": "condition_invalid_argument",
        None: "condition_evaluator_startup",
    }[evaluation.outcome]
    phase: Literal["PREFLIGHT", "CAPTURE", "VERIFY", "TRANSPORT"]
    if evaluation.outcome == "INVALID_ARGUMENT":
        phase = "PREFLIGHT"
    elif evaluation.outcome in {"TIMED_OUT", "STALE"}:
        phase = "VERIFY"
    elif evaluation.status == "FAILED":
        phase = "TRANSPORT"
    else:
        phase = "CAPTURE"
    return Problem(
        code=code,
        phase=phase,
        safe_message="Condition evaluation did not prove satisfaction.",
    )


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
        checks.append(normalize_visible_text(target.role) == query.role)
    if query.name:
        checks.append(_text_matches(target.name, query.name, query.match))
    if query.text:
        checks.append(_text_matches(target.name, query.text, query.match))
    return all(checks)


def _text_matches(value: str, expected: str, match: str) -> bool:
    value_key = normalize_visible_text(value)
    expected_key = normalize_visible_text(expected)
    return (
        value_key == expected_key
        if match == "exact"
        else expected_key in value_key
    )


def apply_target_query(
    targets: tuple[SnapshotTarget, ...],
    query: TargetQuery,
    *,
    region_owner_chain: tuple[str, ...] | None = None,
) -> tuple[SnapshotTarget, ...]:
    """Filter immutable evidence without selecting or issuing authority."""
    if not isinstance(query, TargetQuery):
        raise TypeError("query must be a TargetQuery")
    if query.region is not None and region_owner_chain is None:
        raise ValueError("region query requires a resolved owner chain")
    candidates = targets
    if region_owner_chain is not None:
        candidates = tuple(
            target
            for target in candidates
            if target.owner_chain[: len(region_owner_chain)]
            == region_owner_chain
        )
    return tuple(
        target for target in candidates if _query_matches(target, query)
    )


def _target_summary(target: SnapshotTarget, index: int) -> TargetSummary:
    del index
    ref = target.ref
    if not isinstance(ref, TargetRef):
        raise BrowserSDKGap(
            "Canonical snapshot target is not registry-bound.",
            code="runtime_issued_value",
            action="tab.snapshot",
        )
    return TargetSummary(
        ref=ref,
        role=target.role,
        name=target.name,
        states=target.states,
        allowed_actions=tuple(cast(Any, ref.allowed_actions)),
        observed_url=str(ref.observed_url or ""),
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
