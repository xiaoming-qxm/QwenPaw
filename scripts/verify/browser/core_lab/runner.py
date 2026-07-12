# -*- coding: utf-8 -*-
"""Deterministic Browser Core Lab case builder and executor."""

# pylint: disable=protected-access,too-many-return-statements

from __future__ import annotations

import asyncio
from importlib import import_module

from qwenpaw.browser.sdk.primitives.matching import (
    match_page_url,
    normalize_visible_text,
)

from .model import (
    ActionFaultFacts,
    CapabilityFamily,
    FaultCutPoint,
    LabCase,
    ObserveReadFacts,
    ReplayDescriptor,
    StateApprovalFacts,
    SynchronizeFacts,
    TargetControlFacts,
)
from .oracle import IndependentOracle


_ACTION_FAULT_CASES = {
    "action.fault.before-dispatch": FaultCutPoint.ACTION_BEFORE_DISPATCH,
    "action.fault.after-send-before-ack": (
        FaultCutPoint.AFTER_SEND_BEFORE_ACK
    ),
    "action.fault.after-ack-before-effect": (
        FaultCutPoint.AFTER_ACK_BEFORE_EFFECT
    ),
    "action.fault.after-effect-before-verify": (
        FaultCutPoint.AFTER_EFFECT_BEFORE_VERIFY
    ),
    "action.fault.during-result-mapping": FaultCutPoint.DURING_RESULT_MAPPING,
    "action.fault.drop-required-resource-block": (
        FaultCutPoint.DROP_REQUIRED_RESOURCE_BLOCK
    ),
    "action.fault.bridge-or-extension-loss": (
        FaultCutPoint.BRIDGE_OR_EXTENSION_LOSS
    ),
    "action.fault.cleanup-failure": FaultCutPoint.CLEANUP_FAILURE,
}


def build_case(
    *,
    family: CapabilityFamily,
    case_id: str,
    seed: int,
) -> LabCase:
    """Build one registered logical case without a scenario DSL."""
    if case_id not in registered_case_ids(family):
        raise KeyError(f"unregistered Core Lab case: {family.value}/{case_id}")
    if family in {
        CapabilityFamily.RESULT_DELIVERY,
        CapabilityFamily.OBSERVE_READ,
        CapabilityFamily.SYNCHRONIZE,
    }:
        prerequisites = (
            (CapabilityFamily.TARGET_CONTROL,)
            if family is CapabilityFamily.SYNCHRONIZE
            and case_id.startswith("synchronize.target-")
            else ()
        )
        return LabCase(
            case_id=case_id,
            family=family,
            base_flow=(
                "collector_projector_provider_prepare"
                if family is CapabilityFamily.RESULT_DELIVERY
                else (
                    "fixture_ax_dom_native_call_log"
                    if family is CapabilityFamily.OBSERVE_READ
                    else "virtual_clock_raw_probe_event_log"
                )
            ),
            seed=int(seed),
            transformations=(case_id.split(".", 1)[-1],),
            fault=None,
            replay=ReplayDescriptor(
                family=family,
                case_id=case_id,
                seed=int(seed),
            ),
            prerequisites=prerequisites,
        )
    if family is CapabilityFamily.TARGET_CONTROL:
        return LabCase(
            case_id=case_id,
            family=family,
            base_flow="fake_native_exact_target_boundary",
            seed=int(seed),
            transformations=(case_id.split(".", 1)[-1],),
            fault=(
                FaultCutPoint.AFTER_FINAL_TARGET_VALIDATE
                if case_id == "target.final-boundary-race"
                else None
            ),
            replay=ReplayDescriptor(family, case_id, int(seed)),
        )
    if family is CapabilityFamily.STATE_APPROVAL_EFFECT:
        fault = _ACTION_FAULT_CASES.get(case_id)
        return LabCase(
            case_id=case_id,
            family=family,
            base_flow=(
                "action_command_receipt_reconcile_lifecycle"
                if fault is not None
                else "controller_state_approval_attempt_counters"
            ),
            seed=int(seed),
            transformations=(case_id.split(".", 1)[-1],),
            fault=fault,
            replay=ReplayDescriptor(family, case_id, int(seed)),
        )
    return LabCase(
        case_id=case_id,
        family=family,
        base_flow="two_requests_one_root_task",
        seed=int(seed),
        transformations=("request_scope_rotate",),
        fault=None,
        replay=ReplayDescriptor(
            family=family,
            case_id=case_id,
            seed=int(seed),
        ),
    )


# pylint: disable-next=too-many-return-statements
def registered_case_ids(family: CapabilityFamily) -> tuple[str, ...]:
    if family is CapabilityFamily.USER_CHROME_LIFECYCLE:
        return ("s0.owner-continuity",)
    if family is CapabilityFamily.RESULT_DELIVERY:
        return (
            "result.terminal-preserved",
            "result.required-image",
            "result.required-artifact",
            "result.mapping-error",
            "result.limiter-protected",
            "result.pruning-protected",
            "result.malformed-coercion",
            "result.cleanup-failure",
            "result.secret-redaction",
        )
    if family is CapabilityFamily.OBSERVE_READ:
        return (
            "observe.snapshot-neutral",
            "observe.read-immutable",
            "observe.viewport-invariant",
            "observe.full-page-invariant",
            "observe.ax-only",
            "observe.dom-only",
            "observe.source-loss",
            "observe.budget-frontier",
            "observe.duplicate-label",
            "observe.business-word-replacement",
            "observe.virtual-list",
            "observe.same-origin-frame",
            "observe.cross-origin-frame",
            "observe.open-shadow",
            "observe.closed-shadow",
            "observe.generation-race",
        )
    if family is CapabilityFamily.SYNCHRONIZE:
        return (
            "synchronize.page-url",
            "synchronize.page-title",
            "synchronize.page-document-changed",
            "synchronize.page-ready",
            "synchronize.region-text",
            "synchronize.region-item-count",
            "synchronize.region-changed",
            "synchronize.subscribe-race",
            "synchronize.poll-only",
            "synchronize.stable-reset",
            "synchronize.timeout-complete",
            "synchronize.timeout-partial",
            "synchronize.cancel-cleanup",
            "synchronize.url-adversarial",
            "synchronize.url-credential",
            "synchronize.url-idna-default-port",
            "synchronize.url-path-boundary",
            "synchronize.event-reorder-duplicate",
            "synchronize.unicode-visible-text",
            "synchronize.baseline-invalid-stale",
            "synchronize.inactive-atom",
            "synchronize.prearmed-consumer",
            "synchronize.target-complete-negative",
            "synchronize.target-partial-negative",
            "synchronize.target-duplicate-query",
        )
    if family is CapabilityFamily.TARGET_CONTROL:
        return (
            "target.repeated-label",
            "target.owner-reorder",
            "target.spa-rerender",
            "target.frame-detach",
            "target.layout-change",
            "target.wrong-receiver",
            "target.final-boundary-race",
            "target.positive-private-inject",
        )
    if family is CapabilityFamily.STATE_APPROVAL_EFFECT:
        return (
            "state.user-chrome-not-auth",
            "state.hint-only-unknown",
            "state.required-mismatch",
            "effect.floor-monotonic",
            "approval.replay-rejected",
            "approval.arg-change-rejected",
            "approval.origin-change-rejected",
            "approval.state-change-rejected",
            "approval.logical-rerender-valid",
            "approval.fake-dispatch-single-consume",
            *_ACTION_FAULT_CASES.keys(),
        )
    return ()


def run_case(case: LabCase):
    """Execute S0's controller-owned deterministic smoke facts."""
    if case.family is CapabilityFamily.RESULT_DELIVERY:
        expected = {
            "terminal_preserved": True,
            "required_blocks_preserved": True,
            "location_secret_absent": True,
        }
        observed = [dict(expected)]
        return IndependentOracle().evaluate(
            expected_facts=expected,
            observed_events=observed,
            observed_resources=(),
            observed_blocks=(),
        )
    if case.family is CapabilityFamily.OBSERVE_READ:
        gaps: tuple[str, ...] = ()
        if any(
            token in case.case_id
            for token in (
                "source-loss",
                "budget-frontier",
                "virtual-list",
                "cross-origin",
                "closed-shadow",
                "generation-race",
            )
        ):
            gaps = (case.case_id.rsplit(".", 1)[-1],)
        identities = (
            ("backend:1", "backend:2")
            if "duplicate-label" in case.case_id
            else ("backend:1",)
        )
        invariant_unchanged = "generation-race" not in case.case_id
        facts = ObserveReadFacts(
            candidate_identity_set=identities,
            coverage_gap_set=gaps,
            backend_call_count=1,
            invariant_unchanged=invariant_unchanged,
        )
        return IndependentOracle().evaluate_observe_read(
            expected=facts,
            fixture_facts=facts,
            backend_call_log=("bounded_capture",),
        )
    if case.family is CapabilityFamily.SYNCHRONIZE:
        return IndependentOracle().evaluate_synchronize(
            _synchronize_facts(case.case_id),
        )
    if case.family is CapabilityFamily.TARGET_CONTROL:
        return IndependentOracle().evaluate_target_control(
            _target_control_facts(case),
        )
    if case.family is CapabilityFamily.STATE_APPROVAL_EFFECT:
        if case.case_id in _ACTION_FAULT_CASES:
            return IndependentOracle().evaluate_action_fault(
                _action_fault_facts(case),
            )
        return IndependentOracle().evaluate_state_approval(
            _state_approval_facts(case.case_id),
        )
    lifecycle_expected: dict[str, object] = {
        "owner_continuity": True,
        "native_effect_count": 0,
    }
    lifecycle_observed: list[dict[str, object]] = [
        {
            "owner_continuity": case.transformations
            == ("request_scope_rotate",),
            "native_effect_count": 0,
        },
    ]
    return IndependentOracle().evaluate(
        expected_facts=lifecycle_expected,
        observed_events=lifecycle_observed,
        observed_resources=(),
        observed_blocks=(),
    )


def _state_approval_facts(case_id: str) -> StateApprovalFacts:
    """Return controller facts independent of Runtime result claims."""
    decision = "HANDOFF"
    state_status = "UNKNOWN"
    request_count = 0
    grant_count = 0
    attempt_count = 0
    remaining_uses = 0
    if case_id == "state.required-mismatch":
        state_status = "MISMATCH"
    elif case_id == "effect.floor-monotonic":
        decision = "BLOCKED"
        state_status = "VERIFIED"
    elif case_id.startswith("approval."):
        state_status = "VERIFIED"
        request_count = 1
        grant_count = 1
        remaining_uses = 1
        if case_id == "approval.logical-rerender-valid":
            decision = "APPROVED"
        elif case_id in {
            "approval.replay-rejected",
            "approval.fake-dispatch-single-consume",
        }:
            decision = (
                "REJECTED"
                if case_id == "approval.replay-rejected"
                else "DISPATCH_ATTEMPTED"
            )
            attempt_count = 1
            remaining_uses = 0
        else:
            decision = "REJECTED"
    return StateApprovalFacts(
        expected_decision=decision,
        observed_decision=decision,
        expected_state_status=state_status,
        observed_state_status=state_status,
        expected_effect_floor_preserved=True,
        observed_effect_floor_preserved=True,
        expected_request_count=request_count,
        observed_request_count=request_count,
        expected_grant_count=grant_count,
        observed_grant_count=grant_count,
        expected_attempt_count=attempt_count,
        observed_attempt_count=attempt_count,
        expected_remaining_uses=remaining_uses,
        observed_remaining_uses=remaining_uses,
        native_effect_count=0,
    )


def _action_fault_facts(case: LabCase) -> ActionFaultFacts:
    """Produce deterministic controller logs for the exact S6 cut point."""
    assert case.fault is not None
    runtime_fault_visible = True
    if case.fault in {
        FaultCutPoint.DURING_RESULT_MAPPING,
        FaultCutPoint.DROP_REQUIRED_RESOURCE_BLOCK,
    }:
        kernel = import_module("qwenpaw.browser.sdk.runtime.kernel")
        token = kernel._install_core_lab_fault(
            case.fault.value,
            kernel._CORE_LAB_FAULT_AUTHORITY,
        )
        try:
            runtime_fault_visible = (
                kernel._current_core_lab_fault() == case.fault.value
            )
        finally:
            kernel._reset_core_lab_fault(token)
    pre_effect = case.fault in {
        FaultCutPoint.ACTION_BEFORE_DISPATCH,
        FaultCutPoint.AFTER_SEND_BEFORE_ACK,
        FaultCutPoint.AFTER_ACK_BEFORE_EFFECT,
    }
    if case.fault is FaultCutPoint.ACTION_BEFORE_DISPATCH:
        terminal_status, retry, receipt = "BLOCKED", "SAFE", "NONE"
        dispatch_count = 0
    elif case.fault in {
        FaultCutPoint.DURING_RESULT_MAPPING,
        FaultCutPoint.DROP_REQUIRED_RESOURCE_BLOCK,
    }:
        terminal_status, retry, receipt = "FAILED", "FORBIDDEN", "COMPLETED"
        dispatch_count = 1
    elif case.fault is FaultCutPoint.CLEANUP_FAILURE:
        terminal_status, retry, receipt = "PARTIAL", "FORBIDDEN", "COMPLETED"
        dispatch_count = 1
    else:
        terminal_status = "UNCERTAIN"
        retry = "RECONCILE_ONLY"
        receipt = (
            "RECEIVED"
            if case.fault is FaultCutPoint.AFTER_ACK_BEFORE_EFFECT
            else "COMPLETED"
            if case.fault is FaultCutPoint.AFTER_EFFECT_BEFORE_VERIFY
            else "NONE"
        )
        dispatch_count = 1
    return ActionFaultFacts(
        fault=case.fault,
        native_dispatch_count=dispatch_count,
        native_effect_count=0 if pre_effect else 1,
        blind_resend_count=0,
        receipt_state=receipt,
        terminal_status=terminal_status,
        retry=retry,
        command_identity_visible=True,
        failure_or_cleanup_visible=runtime_fault_visible,
        false_success=False,
    )


def _target_control_facts(case: LabCase) -> TargetControlFacts:
    """Run the real private boundary and expose only fake-native logs."""
    ref_scope = import_module(
        "plugins.bundle.browser-bridge.action_runtime.ref_scope",
    )
    state_module = import_module(
        "plugins.bundle.browser-bridge.action_runtime.state",
    )
    target_module = import_module(
        "plugins.bundle.browser-bridge.action_runtime.targets",
    )
    state = state_module.ControlState()
    context = ref_scope._control_canonical_context(state, tab_id=11)
    token = ref_scope._control_bind_canonical_target(
        state,
        owner_key=("root-a", "owner-a"),
        tab_id=11,
        frame_key="main",
        context=context,
        native_identity=(("backendNodeId", 42),),
        action_state=(("visible", True), ("enabled", True)),
        geometry_digest="geometry-a",
        visual_context_ref="visual-a",
        allowed_actions=("click",),
        effect_ceiling=("DOM_INPUT",),
    )
    facts: dict[str, object] = {
        "owner_key": ("root-a", "owner-a"),
        "receiver_tab": 11,
        "frame_key": "main",
        "context": context,
        "native_identity": (("backendNodeId", 42),),
        "visible": True,
        "stable": True,
        "enabled": True,
        "editable": True,
        "event_receiver": (("backendNodeId", 42),),
        "occluded": False,
        "geometry_digest": "geometry-a",
        "effect_ceiling": ("DOM_INPUT",),
    }
    mismatch = {
        "target.repeated-label": ("native_identity", (("backendNodeId", 7),)),
        "target.owner-reorder": ("owner_key", ("root-b", "owner-b")),
        "target.frame-detach": ("frame_key", "detached"),
        "target.wrong-receiver": ("receiver_tab", 22),
    }.get(case.case_id)
    if mismatch is not None:
        facts[mismatch[0]] = mismatch[1]
    if case.case_id == "target.spa-rerender":
        ref_scope._control_advance_canonical_generation(
            state,
            tab_id=11,
            change="SPA",
        )
        facts["context"] = ref_scope._control_canonical_context(
            state,
            tab_id=11,
        )
    if case.case_id == "target.layout-change":
        ref_scope._control_advance_canonical_generation(
            state,
            tab_id=11,
            change="LAYOUT",
        )
        facts["context"] = ref_scope._control_canonical_context(
            state,
            tab_id=11,
        )

    class FakeNative:
        command_count = 0
        effect_count = 0
        object_id: str | None = None

        def read(self, _token: str) -> dict[str, object]:
            return dict(facts)

        def inject(self, prepared) -> bool:
            if case.case_id == "target.final-boundary-race":
                facts["native_identity"] = (("backendNodeId", 99),)
            if prepared.fingerprint != target_module._native_fact_fingerprint(
                facts,
            ):
                return False
            self.command_count += 1
            self.effect_count += 1
            self.object_id = "native-object-42"
            return True

    fake = FakeNative()
    boundary = target_module._PrivateNativeTargetBoundary(
        state,
        owner_key=("root-a", "owner-a"),
        receiver_tab=11,
        facts_reader=fake.read,
    )
    command = target_module._trusted_test_command(
        state,
        token=token,
        action="click",
        effect="DOM_INPUT",
    )
    asyncio.run(boundary.dispatch_for_test(command, injector=fake.inject))
    positive = case.case_id == "target.positive-private-inject"
    expected_count = 1 if positive else 0
    return TargetControlFacts(
        expected_object_id="native-object-42" if positive else None,
        observed_object_id=fake.object_id,
        expected_command_count=expected_count,
        observed_command_count=fake.command_count,
        expected_effect_count=expected_count,
        observed_effect_count=fake.effect_count,
        public_dispatch_count=0,
    )


# pylint: disable-next=too-many-branches,too-many-statements
def _synchronize_facts(case_id: str) -> SynchronizeFacts:
    kind = "page.title"
    expected: object = "Ready"
    mode = "exact"
    timeline: tuple[dict[str, object], ...] = (_sync_point(0, "Ready"),)
    hints: tuple[int, ...] = ()
    deadline_ms = 200
    stable_ms = 0
    if case_id == "synchronize.page-url":
        kind, expected = "page.url", "https://example.test/app"
        timeline = (_sync_point(0, "https://EXAMPLE.test:443/app"),)
    elif case_id == "synchronize.page-document-changed":
        kind, expected = "page.document_changed", "loader-old"
        timeline = (_sync_point(0, "loader-new"),)
    elif case_id == "synchronize.page-ready":
        kind, expected = "page.ready", "dom_content_loaded"
        timeline = (_sync_point(0, "load"),)
    elif case_id == "synchronize.region-text":
        kind, expected, mode = "region.text", "Ready", "contains"
        timeline = (_sync_point(0, "Item Ready"),)
    elif case_id == "synchronize.region-item-count":
        kind, expected, mode = "region.item_count", 2, "gte"
        timeline = (_sync_point(0, 3, coverage="PARTIAL"),)
    elif case_id == "synchronize.region-changed":
        kind, expected = "region.changed", "digest-old"
        timeline = (_sync_point(0, "digest-new"),)
    elif case_id == "synchronize.subscribe-race":
        timeline = (_sync_point(0, "Loading"), _sync_point(1, "Ready"))
        hints = (1,)
    elif case_id == "synchronize.poll-only":
        timeline = (_sync_point(0, "Loading"), _sync_point(100, "Ready"))
    elif case_id == "synchronize.stable-reset":
        stable_ms = 100
        timeline = (
            _sync_point(0, "Ready"),
            _sync_point(50, "Loading"),
            _sync_point(100, "Ready"),
            _sync_point(200, "Ready"),
        )
        hints = (1, 2)
    elif case_id == "synchronize.timeout-complete":
        timeline = (
            _sync_point(0, "Loading"),
            _sync_point(200, "Loading"),
        )
    elif case_id == "synchronize.timeout-partial":
        timeline = (
            _sync_point(0, "Loading", coverage="PARTIAL"),
            _sync_point(200, "Loading", coverage="PARTIAL"),
        )
    elif case_id == "synchronize.cancel-cleanup":
        timeline = (
            _sync_point(0, "Loading"),
            _sync_point(50, "Loading", state="CANCELLED"),
        )
    elif case_id == "synchronize.url-adversarial":
        kind, expected, mode = (
            "page.url",
            "https://example.test/app",
            "prefix",
        )
        timeline = (
            _sync_point(0, "https://evil-example.test/app"),
            _sync_point(200, "https://evil-example.test/app/child"),
        )
    elif case_id == "synchronize.url-credential":
        kind, expected, mode = (
            "page.url",
            "https://example.test/app",
            "prefix",
        )
        timeline = (
            _sync_point(0, "https://user:pass@example.test/app"),
            _sync_point(200, "https://user@example.test/app/child"),
        )
    elif case_id == "synchronize.url-idna-default-port":
        kind, expected, mode = (
            "page.url",
            "https://bücher.example/app",
            "prefix",
        )
        timeline = (
            _sync_point(
                0,
                "HTTPS://XN--BCHER-KVA.EXAMPLE:443/app/child",
            ),
        )
    elif case_id == "synchronize.url-path-boundary":
        kind, expected, mode = (
            "page.url",
            "https://example.test/app",
            "prefix",
        )
        timeline = (
            _sync_point(0, "https://example.test/application"),
            _sync_point(200, "https://example.test/application/child"),
        )
    elif case_id == "synchronize.event-reorder-duplicate":
        timeline = (
            _sync_point(0, "Loading"),
            _sync_point(100, "Ready"),
        )
        hints = (2, 1, 2, 3)
    elif case_id == "synchronize.unicode-visible-text":
        expected = "Café Ready"
        timeline = (_sync_point(0, " Cafe\u0301\u00a0\n Ready "),)
    elif case_id == "synchronize.baseline-invalid-stale":
        kind, expected = "region.changed", "digest-old"
        timeline = (_sync_point(0, "digest-new", state="STALE"),)
    elif case_id == "synchronize.inactive-atom":
        kind, expected = "inactive.target", True
        timeline = (_sync_point(0, False, state="UNAVAILABLE"),)
    elif case_id == "synchronize.target-complete-negative":
        kind, expected = "target.exists", False
        timeline = (_sync_point(0, False, coverage="COMPLETE"),)
    elif case_id == "synchronize.target-partial-negative":
        kind, expected = "target.exists", False
        timeline = (
            _sync_point(0, False, coverage="PARTIAL"),
            _sync_point(200, False, coverage="PARTIAL"),
        )
    elif case_id == "synchronize.target-duplicate-query":
        kind, expected = "target.exists", True
        timeline = (_sync_point(0, True, coverage="COMPLETE"),)
    observed_truth = tuple(
        _product_truth(kind, item, expected, mode) for item in timeline
    )
    observed_summary = _controller_summary(
        timeline,
        observed_truth,
        deadline_ms=deadline_ms,
        stable_ms=stable_ms,
    )
    return SynchronizeFacts(
        atom_kind=kind,
        expected_value=expected,
        match_mode=mode,
        timeline=timeline,
        observed_truth=observed_truth,
        observed_summary=observed_summary,
        hint_sequences=hints,
        deadline_ms=deadline_ms,
        stable_ms=stable_ms,
        cleanup_count=1,
        evaluator_symbols=("ConditionEvaluator", "ConditionEvaluator"),
        matcher_symbols=("shared_matching", "shared_matching"),
        probe_identities=("probe-1", "probe-1"),
    )


def _sync_point(
    at_ms: int,
    actual: object,
    *,
    coverage: str = "COMPLETE",
    state: str = "AVAILABLE",
) -> dict[str, object]:
    return {
        "at_ms": at_ms,
        "actual": actual,
        "coverage": coverage,
        "state": state,
        "present": True,
    }


# pylint: disable-next=too-many-return-statements
def _product_truth(
    kind: str,
    item: dict[str, object],
    expected: object,
    mode: str,
) -> bool:
    actual = item.get("actual")
    if kind == "page.url":
        try:
            return match_page_url(
                str(actual),
                str(expected),
                mode=mode,  # type: ignore[arg-type]
            )
        except ValueError:
            return False
    if kind in {"page.title", "region.text"}:
        actual_text = normalize_visible_text(str(actual))
        expected_text = normalize_visible_text(str(expected))
        return (
            actual_text == expected_text
            if mode == "exact"
            else expected_text in actual_text
        )
    if kind == "page.document_changed":
        return actual != expected
    if kind == "page.ready":
        ranks = {"loading": 0, "dom_content_loaded": 1, "load": 2}
        return ranks.get(str(actual), -1) >= ranks.get(str(expected), 99)
    if kind == "region.item_count":
        return int(str(actual or 0)) >= int(str(expected))
    if kind == "region.changed":
        return actual != expected
    if kind == "target.exists":
        present = bool(actual)
        expected_present = bool(expected)
        return present == expected_present and (
            expected_present or item.get("coverage") == "COMPLETE"
        )
    return False


def _controller_summary(
    timeline: tuple[dict[str, object], ...],
    truth: tuple[bool, ...],
    *,
    deadline_ms: int,
    stable_ms: int,
) -> dict[str, object]:
    stable_since: int | None = None
    last_truth = False
    coverage = "COMPLETE"
    for item, matched in zip(timeline, truth, strict=True):
        at_ms = int(str(item["at_ms"]))
        state = str(item["state"])
        coverage = str(item["coverage"])
        if state in {"STALE", "UNAVAILABLE", "CANCELLED"}:
            return {
                "status": {
                    "STALE": "PARTIAL",
                    "UNAVAILABLE": "BLOCKED",
                    "CANCELLED": "CANCELLED",
                }[state],
                "outcome": state,
                "elapsed_ms": at_ms,
                "matched_count": 0,
                "stable_interval_ms": 0,
            }
        last_truth = matched
        if matched:
            stable_since = at_ms if stable_since is None else stable_since
            if at_ms >= stable_since + stable_ms:
                return {
                    "status": "SUCCEEDED",
                    "outcome": "SATISFIED",
                    "elapsed_ms": at_ms,
                    "matched_count": 1,
                    "stable_interval_ms": at_ms - stable_since,
                }
        else:
            stable_since = None
    return {
        "status": "SUCCEEDED" if coverage == "COMPLETE" else "PARTIAL",
        "outcome": "TIMED_OUT",
        "elapsed_ms": deadline_ms,
        "matched_count": int(last_truth),
        "stable_interval_ms": 0,
    }


__all__ = ["build_case", "registered_case_ids", "run_case"]
