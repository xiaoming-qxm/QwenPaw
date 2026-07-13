# -*- coding: utf-8 -*-
"""Canonical Tab, BrowserTabs, and TabActions public surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from time import monotonic
from typing import Any, Awaitable, Callable, Literal, cast
from urllib.parse import urlsplit

from ..action_runner import ActionRunner
from ..backends.protocols import BackendProfile
from ..condition_evaluator import (
    ConditionEvaluation,
    ConditionEvaluator,
    ConditionReceiver,
    TargetFacts,
)
from ..contract_runtime import canonical_mutation_contract
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
    ActionExpectation,
    CapabilityProblemDetails,
    BrowserCondition,
    BrowserPrompt,
    CaptureGap,
    CoverageGap,
    CurrentSurface,
    EvidenceRef,
    FrameScope,
    ObservationScope,
    OptionChoice,
    PagePdfOptions,
    PagePdfResult,
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
    StateRequirement,
    TabSummary,
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
    _receiver_summary: TabSummary | None = field(default=None, repr=False)
    _action_runner: ActionRunner | Any | None = field(
        default=None,
        repr=False,
    )

    async def navigate(
        self,
        url: str,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Navigate this exact receiver to one safe HTTP(S) URL."""
        _require_safe_http_url(url)
        return await self._run_mutation(
            "tab.actions.navigate",
            ordered_targets=(),
            arguments={"url": url},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def back(
        self,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Navigate backward in this receiver's history."""
        return await self._run_mutation(
            "tab.actions.back",
            ordered_targets=(),
            arguments={},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def forward(
        self,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Navigate forward in this receiver's history."""
        return await self._run_mutation(
            "tab.actions.forward",
            ordered_targets=(),
            arguments={},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def reload(
        self,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Reload this exact receiver."""
        return await self._run_mutation(
            "tab.actions.reload",
            ordered_targets=(),
            arguments={},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def click(
        self,
        target: TargetRef,
        *,
        button: Literal["primary", "secondary", "middle"] = "primary",
        count: Literal[1, 2] = 1,
        modifiers: tuple[
            Literal["alt", "control", "meta", "shift"],
            ...,
        ] = (),
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Click one Runtime-issued target with closed input values."""
        _require_choice(button, {"primary", "secondary", "middle"}, "button")
        _require_choice(count, {1, 2}, "count")
        _require_modifiers(
            modifiers,
            allowed={"alt", "control", "meta", "shift"},
        )
        if isinstance(target, str):
            # Preserve the frozen S0 characterization while rejecting all
            # string/native-id authority before the runner or backend.
            raise _capability_blocked("tab.actions.click")
        self._require_target(target)
        if self._action_runner is None:
            return _blocked_canonical_action(
                "tab.actions.click",
                target=target,
            )
        return await self._run_mutation(
            "tab.actions.click",
            ordered_targets=(("target", target),),
            arguments={
                "button": button,
                "count": count,
                "modifiers": modifiers,
            },
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def hover(
        self,
        target: TargetRef,
        *,
        expect: ActionExpectation | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Hover one Runtime-issued target."""
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.hover",
            ordered_targets=(("target", target),),
            arguments={},
            expectation=expect,
            timeout_ms=timeout_ms,
        )

    async def drag(
        self,
        source: TargetRef,
        destination: TargetRef,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Drag between two ordered Runtime-issued endpoints."""
        self._require_target(source)
        self._require_target(destination)
        return await self._run_mutation(
            "tab.actions.drag",
            ordered_targets=(
                ("source", source),
                ("destination", destination),
            ),
            arguments={},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def scroll(
        self,
        *,
        target: TargetRef | None = None,
        direction: Literal["up", "down", "left", "right"] = "down",
        amount: Literal["line", "page", "start", "end"] = "page",
        expect: ActionExpectation | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Scroll the receiver or one explicit Runtime-issued target."""
        _require_choice(
            direction,
            {"up", "down", "left", "right"},
            "direction",
        )
        _require_choice(amount, {"line", "page", "start", "end"}, "amount")
        if target is not None:
            self._require_target(target)
        ordered_targets = () if target is None else (("target", target),)
        return await self._run_mutation(
            "tab.actions.scroll",
            ordered_targets=ordered_targets,
            arguments={"direction": direction, "amount": amount},
            expectation=expect,
            timeout_ms=timeout_ms,
        )

    async def fill(
        self,
        target: TargetRef,
        value: str,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Replace the complete value of one Runtime-issued target."""
        _require_string(value, "value")
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.fill",
            ordered_targets=(("target", target),),
            arguments={"value": value},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def type_text(
        self,
        target: TargetRef,
        text: str,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Append browser input events to one Runtime-issued target."""
        _require_string(text, "text")
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.type_text",
            ordered_targets=(("target", target),),
            arguments={"text": text},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def press_key(
        self,
        target: TargetRef,
        key: str,
        *,
        modifiers: tuple[Literal["shift"], ...] = (),
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Press one closed key value on an explicit target."""
        _require_key(key)
        _require_modifiers(modifiers, allowed={"shift"})
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.press_key",
            ordered_targets=(("target", target),),
            arguments={"key": key, "modifiers": modifiers},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def set_checked(
        self,
        target: TargetRef,
        checked: bool,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Ensure one target has the exact checked state."""
        if not isinstance(checked, bool):
            raise TypeError("checked must be a bool")
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.set_checked",
            ordered_targets=(("target", target),),
            arguments={"checked": checked},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def select_option(
        self,
        target: TargetRef,
        option: OptionChoice,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Select one exact option choice on a Runtime-issued target."""
        if not isinstance(option, OptionChoice):
            raise TypeError("option must be an OptionChoice")
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.select_option",
            ordered_targets=(("target", target),),
            arguments={"option": option},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def respond_prompt(
        self,
        prompt: BrowserPrompt,
        decision: Literal["accept", "dismiss", "allow", "deny"],
        *,
        text: str | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Continue one exact prompt under its parent PendingAction."""
        if not isinstance(prompt, BrowserPrompt):
            raise TypeError("prompt must be a Runtime-issued BrowserPrompt")
        if decision not in {"accept", "dismiss", "allow", "deny"}:
            raise ValueError("invalid prompt decision")
        _deadline(timeout_ms)
        if self._action_runner is None or self._owner_binding is None:
            raise BrowserSDKError(
                "Canonical ActionRunner is unavailable",
                code="action_runner_missing",
                action="tab.actions.respond_prompt",
            )
        dispatcher = getattr(self.dispatch, "respond_prompt", None)
        if dispatcher is None and callable(self.dispatch):
            dispatcher = self.dispatch
        return await self._action_runner.continue_prompt(
            binding=self._owner_binding,
            prompt=prompt,
            decision=decision,
            text=text,
            dispatcher=dispatcher,
        )

    async def _run_mutation(
        self,
        api_id: str,
        *,
        ordered_targets: tuple[tuple[str, TargetRef], ...],
        arguments: dict[str, object],
        expectation: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        if self._action_runner is None:
            raise BrowserSDKError(
                "Canonical ActionRunner is unavailable",
                code="action_runner_missing",
                action=api_id,
            )
        result = await self._action_runner.run(
            binding=cast(BrowserRequestBinding, self._owner_binding),
            receiver_tab=self._receiver_summary,
            contract=canonical_mutation_contract(api_id),
            ordered_targets=ordered_targets,
            arguments=arguments,
            expectation=expectation,
            state=state,
            deadline=_deadline(timeout_ms),
        )
        return cast(ActionResult, result)

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
    _tab_summary: TabSummary | None = field(default=None, repr=False)
    _action_runner: ActionRunner | Any | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.actions = TabActions(
            dispatch=self.actions.dispatch,
            _target_registry=self._target_registry,
            _owner_binding=self._owner_binding,
            _receiver_tab=self.id,
            _receiver_summary=self._tab_summary,
            _action_runner=self._action_runner,
        )

    async def close(self) -> ActionResult:
        """Route explicit close through the sole ActionRunner."""
        if not isinstance(self._tab_summary, TabSummary):
            raise BrowserSDKError(
                "tab.close requires an owner-bound receiver summary",
                code="runtime_issued_value",
            )
        expectation = ActionExpectation.transition(
            BrowserCondition.all(
                SurfaceCondition.tab_closed(self._tab_summary),
            ),
        )
        result = await self._run_mutation(
            "tab.close",
            expectation=expectation,
        )
        return cast(ActionResult, result)

    async def current_prompt(self) -> BrowserPrompt | None:
        """Return the exact non-mutating prompt waiting on this tab."""
        if (
            self._target_registry is None
            or self._owner_binding is None
            or not isinstance(self._tab_summary, TabSummary)
        ):
            raise BrowserSDKError(
                "current_prompt requires owner-bound tab authority",
                code="browser_ownership_context_missing",
            )
        current = self._target_registry.current_browser_prompt(
            self._owner_binding,
            tab=self._tab_summary,
        )
        if current is not None:
            return current
        capture = getattr(self._session, "current_prompt", None)
        if callable(capture):
            capture_prompt = cast(
                Callable[[TabSummary], Awaitable[BrowserPrompt | None]],
                capture,
            )
            # pylint: disable-next=not-callable
            captured = await capture_prompt(self._tab_summary)
            if captured is not None and not isinstance(
                captured,
                BrowserPrompt,
            ):
                raise BrowserSDKError(
                    "backend returned an invalid BrowserPrompt",
                    code="prompt_binding_invalid",
                )
            return cast(BrowserPrompt | None, captured)
        return None

    async def print_to_pdf(
        self,
        *,
        options: PagePdfOptions | None = None,
    ) -> PagePdfResult:
        """Route page PDF through the runner before S8 native support."""
        result = await self._run_mutation(
            "tab.print_to_pdf",
            arguments={"options": options},
        )
        return cast(PagePdfResult, result)

    async def _run_mutation(
        self,
        api_id: str,
        *,
        arguments: dict[str, object] | None = None,
        expectation: ActionExpectation | None = None,
    ) -> ActionResult | PagePdfResult:
        if self._action_runner is None:
            raise BrowserSDKError(
                "Canonical ActionRunner is unavailable",
                code="action_runner_missing",
                action=api_id,
            )
        return await self._action_runner.run(
            binding=cast(BrowserRequestBinding, self._owner_binding),
            receiver_tab=self._tab_summary,
            contract=canonical_mutation_contract(api_id),
            ordered_targets=(),
            arguments=arguments or {},
            expectation=expectation,
            state=None,
            deadline=None,
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
    _action_runner: ActionRunner | Any | None = field(
        default=None,
        repr=False,
    )
    _max_visible_tabs: int = field(default=64, repr=False)
    _max_task_created_tabs: int = field(default=16, repr=False)

    async def open(self, url: str) -> ActionResult:
        """Route create-and-navigate without changing selected Tab."""
        _require_safe_http_url(url)
        self._require_create_capacity()
        return await self._run_mutation(
            "browser.tabs.open",
            arguments={"url": url},
        )

    async def new(self) -> ActionResult:
        """Route blank task-tab creation without implicit selection."""
        self._require_create_capacity()
        return await self._run_mutation("browser.tabs.new", arguments={})

    async def list(self) -> list[TabSummary]:
        """Return a complete owner-bound visible set or a typed error."""
        if self._target_registry is None or self._owner_binding is None:
            raise BrowserSDKError(
                "Canonical tab registry is unavailable",
                code="browser_ownership_context_missing",
            )
        return self._target_registry.list_tab_summaries(
            self._owner_binding,
            max_visible_tabs=self._max_visible_tabs,
        )

    async def _run_mutation(
        self,
        api_id: str,
        *,
        arguments: dict[str, object],
    ) -> ActionResult:
        if self._action_runner is None:
            raise BrowserSDKError(
                "Canonical ActionRunner is unavailable",
                code="action_runner_missing",
                action=api_id,
            )
        result = await self._action_runner.run(
            binding=cast(BrowserRequestBinding, self._owner_binding),
            receiver_tab=None,
            contract=canonical_mutation_contract(api_id),
            ordered_targets=(),
            arguments=arguments,
            expectation=None,
            state=None,
            deadline=None,
        )
        return cast(ActionResult, result)

    async def active(self) -> Tab:
        if (
            self._target_registry is not None
            and self._owner_binding is not None
        ):
            summary = self._target_registry.selected_tab_summary(
                self._owner_binding,
            )
            if summary is not None:
                return self._tab_from_summary(summary)
        if self._selected is not None:
            return self._selected
        raise BrowserSDKError(
            "No SDK tab is currently selected",
            code="no_current_tab",
            action="browser.tabs.active",
        )

    async def select(self, tab: TabSummary) -> Tab:
        """Select only one Runtime-issued owner-bound summary."""
        if not isinstance(tab, TabSummary):
            raise TypeError("tabs.select requires a TabSummary")
        if self._target_registry is None or self._owner_binding is None:
            raise BrowserSDKError(
                "Canonical tab registry is unavailable",
                code="browser_ownership_context_missing",
            )
        self._target_registry.select_tab_summary(self._owner_binding, tab)
        selected = self._tab_from_summary(tab)
        self._selected = selected
        return selected

    def _tab_from_summary(self, summary: TabSummary) -> Tab:
        assert self._target_registry is not None
        assert self._owner_binding is not None
        resolved = self._target_registry.resolve_tab_summary(
            summary,
            owner=self._owner_binding,
        )
        return Tab(
            id=resolved.receiver_tab_key,
            _session=self._session,
            _resources=self._resources,
            _condition_evaluator=self._condition_evaluator,
            _profile=self._profile,
            _target_registry=self._target_registry,
            _owner_binding=self._owner_binding,
            _tab_summary=summary,
            _action_runner=self._action_runner,
        )

    def _require_create_capacity(self) -> None:
        if self._target_registry is None or self._owner_binding is None:
            return
        if (
            self._target_registry.task_created_tab_count(self._owner_binding)
            >= self._max_task_created_tabs
        ):
            raise BrowserSDKError(
                "task-created tab limit reached",
                code="tab_limit_exceeded",
            )


def _require_choice(value: object, allowed: set[object], name: str) -> None:
    if value not in allowed:
        raise ValueError(f"invalid {name}: {value}")


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _require_modifiers(
    modifiers: object,
    *,
    allowed: set[str],
) -> None:
    if not isinstance(modifiers, tuple):
        raise TypeError("modifiers must be a tuple")
    if len(set(modifiers)) != len(modifiers):
        raise ValueError("modifiers cannot contain duplicates")
    if any(
        not isinstance(item, str) or item not in allowed for item in modifiers
    ):
        raise ValueError("invalid modifier")


def _require_key(key: object) -> str:
    key = _require_string(key, "key")
    named = {
        "Enter",
        "Tab",
        "Escape",
        "Space",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Backspace",
        "Delete",
    }
    printable_scalar = (
        len(key) == 1
        and key.isprintable()
        and not 0xD800 <= ord(key) <= 0xDFFF
    )
    if key not in named and not printable_scalar:
        raise ValueError("key must be one printable scalar or a supported key")
    return key


def _require_safe_http_url(url: object) -> str:
    url = _require_string(url, "url")
    if not url or any(ord(character) < 0x20 for character in url):
        raise ValueError("url must be a non-empty safe URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("url must be a valid HTTP(S) URL") from exc
    del port
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("url must be HTTP(S) without embedded credentials")
    return url


def _deadline(timeout_ms: int | None) -> float | None:
    if timeout_ms is None:
        return None
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool):
        raise TypeError("timeout_ms must be an integer")
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    return monotonic() + timeout_ms / 1000


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
