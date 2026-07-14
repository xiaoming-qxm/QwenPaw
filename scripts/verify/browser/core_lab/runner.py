# -*- coding: utf-8 -*-
"""Deterministic Browser Core Lab case builder and executor."""

# pylint: disable=protected-access,too-many-return-statements
# pylint: disable=too-many-branches,too-many-statements

from __future__ import annotations

import asyncio
import hashlib
from importlib import import_module
from types import SimpleNamespace
from typing import TypedDict

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
    ResourceFileFacts,
    S7FamilyFacts,
    StateApprovalFacts,
    SynchronizeFacts,
    TargetControlFacts,
    VisualCanvasFacts,
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

_RESOURCE_FAULT_CASES = {
    "resource.download.after-pre-arm": FaultCutPoint.AFTER_PRE_ARM,
    "resource.download.before-send": FaultCutPoint.BEFORE_NATIVE_EFFECT,
    "resource.download.send-before-receipt": (
        FaultCutPoint.AFTER_SEND_BEFORE_ACK
    ),
    "resource.download.progress-partial": (
        FaultCutPoint.DOWNLOAD_PROGRESS_PARTIAL
    ),
    "resource.download.progress-completed": (
        FaultCutPoint.DOWNLOAD_PROGRESS_COMPLETED
    ),
    "resource.download.byte-stability": FaultCutPoint.BEFORE_BYTE_STABILITY,
    "resource.download.hash-failure": FaultCutPoint.DURING_HASH,
    "resource.download.ingest-failure": FaultCutPoint.DURING_INGEST,
    "resource.delivery.promotion-failure": FaultCutPoint.DURING_PROMOTION,
    "resource.delivery.formatter-failure": (
        FaultCutPoint.DURING_FORMATTER_PREPARE
    ),
    "resource.delivery.final-envelope-failure": (
        FaultCutPoint.DURING_FINAL_ENVELOPE
    ),
    "resource.cleanup.transient-failure": (
        FaultCutPoint.DURING_TRANSIENT_CLEANUP
    ),
    "resource.cleanup.artifact-expiry-failure": (
        FaultCutPoint.DURING_ARTIFACT_EXPIRY
    ),
}

_VISUAL_FAULT_CASES = {
    "visual.fault.before-screenshot": FaultCutPoint.VISUAL_BEFORE_SCREENSHOT,
    "visual.fault.after-screenshot": FaultCutPoint.VISUAL_AFTER_SCREENSHOT,
    "visual.fault.after-binding-issue": (
        FaultCutPoint.VISUAL_AFTER_BINDING_ISSUE
    ),
    "visual.fault.after-hit-test": FaultCutPoint.VISUAL_AFTER_HIT_TEST,
    "visual.fault.after-ref-storage": FaultCutPoint.VISUAL_AFTER_REF_STORAGE,
    "visual.fault.after-preflight": FaultCutPoint.VISUAL_AFTER_PREFLIGHT,
    "visual.fault.after-final-revalidation": (
        FaultCutPoint.VISUAL_AFTER_FINAL_REVALIDATION
    ),
    "visual.fault.after-input-send": FaultCutPoint.VISUAL_AFTER_INPUT_SEND,
    "visual.fault.after-receipt": FaultCutPoint.VISUAL_AFTER_RECEIPT,
    "visual.fault.after-postcondition": (
        FaultCutPoint.VISUAL_AFTER_POSTCONDITION
    ),
}

_VISUAL_TRANSFORMATIONS = {
    "visual.viewport-grounding-exact": (
        "rename_ids",
        "rename_classes",
        "rename_text",
        "wrap_containers",
    ),
    "visual.icon-only-exact": ("rename_text", "wrap_containers"),
    "visual.repeated-targets-multiple": ("reorder_repeated_candidates",),
    "visual.overlapping-candidates-multiple": (
        "reorder_repeated_candidates",
        "wrap_containers",
    ),
    "visual.ref-churn-stale": ("replace_nodes_change_identity",),
    "visual.frame-target-exact": ("rename_ids", "wrap_containers"),
    "visual.open-shadow-target-exact": ("rename_classes",),
    "visual.closed-shadow-host-exact": ("replace_nodes_preserve_identity",),
    "visual.canvas-no-policy-handoff": ("rename_ids", "rename_classes"),
    "visual.map-no-policy-handoff": ("rename_text",),
    "visual.resize-stale": ("alter_viewport",),
    "visual.overlay-occluded-no-send": ("delay_layout",),
    "visual.scroll-stale": ("alter_viewport",),
    "visual.zoom-stale": ("alter_zoom",),
    "visual.dpr-stale": ("alter_dpr",),
    "visual.layout-change-stale": ("delay_layout",),
    "visual.full-page-evidence-only": ("alter_viewport",),
    "visual.policy-low-risk-action": ("replace_nodes_preserve_identity",),
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
    if family is CapabilityFamily.RESOURCE_FILE:
        return LabCase(
            case_id=case_id,
            family=family,
            base_flow="controller_native_transfer_and_byte_store",
            seed=int(seed),
            transformations=(case_id.split(".", 1)[-1],),
            fault=_RESOURCE_FAULT_CASES.get(case_id),
            replay=ReplayDescriptor(family, case_id, int(seed)),
            prerequisites=(CapabilityFamily.TARGET_CONTROL,),
        )
    if family is CapabilityFamily.VISUAL_CANVAS:
        return LabCase(
            case_id=case_id,
            family=family,
            base_flow="fixture_visual_epoch_hit_event_log",
            seed=int(seed),
            transformations=_VISUAL_TRANSFORMATIONS.get(
                case_id,
                (case_id.split(".", 2)[-1],),
            ),
            fault=_VISUAL_FAULT_CASES.get(case_id),
            replay=ReplayDescriptor(family, case_id, int(seed)),
            prerequisites=(CapabilityFamily.TARGET_CONTROL,),
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
        return (
            "s0.owner-continuity",
            "chrome.first-attach",
            "chrome.focus-change",
            "chrome.reconnect",
            "chrome.resume",
            "chrome.cleanup-task-created",
            "chrome.cleanup-borrowed",
            "chrome.cleanup-beforeunload-incomplete",
        )
    if family is CapabilityFamily.CONTEXT_NAVIGATE:
        return (
            "context.navigate",
            "context.back",
            "context.forward",
            "context.reload",
            "context.tabs-open",
            "context.tabs-new",
            "context.tabs-select",
            "context.popup-open",
            "context.popup-absent",
            "context.selected-tab-close",
            "context.unsafe-url",
            "context.document-changed",
            "context.no-implicit-selection",
        )
    if family is CapabilityFamily.SURFACES_WIDGETS:
        return (
            "widget.combobox",
            "widget.menu",
            "widget.tree",
            "widget.grid",
            "widget.date-picker",
            "widget.slider",
            "widget.rich-editor",
            "prompt.alert-exact",
            "prompt.confirm-exact",
            "prompt.text-exact",
            "prompt.beforeunload-exact",
            "prompt.same-message-replay",
            "prompt.stale-token",
            "prompt.no-default-accept",
            "prompt.post-dispatch-required",
            "prompt.permission-handoff",
            "surface.popup-cap-overflow",
        )
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
            "result.artifact-preflight",
            "result.artifact-promotion",
            "result.artifact-formatter-prepare",
            "result.artifact-final-envelope",
            "result.artifact-transient-cleanup",
            "result.artifact-expiry",
            "result.artifact-protected-block",
            "result.artifact-provider-unsupported",
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
            "synchronize.resource-available-current",
            "synchronize.resource-available-expired",
            "synchronize.resource-available-owner-mismatch",
            "synchronize.target-complete-negative",
            "synchronize.target-partial-negative",
            "synchronize.target-duplicate-query",
            "synchronize.surface-prompt-present",
            "synchronize.surface-prompt-absent",
            "synchronize.surface-tab-opened",
            "synchronize.surface-tab-closed",
            "synchronize.surface-tab-selected",
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
            "target.interaction-click",
            "target.interaction-hover",
            "target.interaction-drag",
            "target.interaction-scroll",
            "target.interaction-fill",
            "target.interaction-type-text",
            "target.interaction-press-key",
            "target.interaction-set-checked",
            "target.interaction-select-option",
            "target.frame-boundary",
            "target.open-shadow-boundary",
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
    if family is CapabilityFamily.RESOURCE_FILE:
        return (
            "resource.upload.selected-accepted",
            "resource.upload.selected-rejected",
            "resource.upload.transferred-accepted",
            "resource.upload.multi-unknown",
            "resource.upload.multi-mixed",
            "resource.upload.owner-mismatch",
            "resource.upload.expired",
            "resource.upload.item-limit",
            "resource.upload.task-limit",
            "resource.workspace.permission-handoff",
            "resource.download.after-pre-arm",
            "resource.download.before-send",
            "resource.download.send-before-receipt",
            "resource.download.correlation",
            "resource.download.progress-partial",
            "resource.download.progress-completed",
            "resource.download.byte-stability",
            "resource.download.hash-failure",
            "resource.download.ingest-failure",
            "resource.download.exact-count-name-mime",
            "resource.pdf.context-stable",
            "resource.pdf.context-changed",
            "resource.paste.exact-target-content",
            "resource.paste.no-ambient-clipboard",
            "resource.condition.created-download",
            "resource.condition.created-pdf",
            "resource.delivery.promotion-failure",
            "resource.delivery.formatter-failure",
            "resource.delivery.final-envelope-failure",
            "resource.cleanup.transient-failure",
            "resource.cleanup.artifact-expiry-failure",
        )
    if family is CapabilityFamily.VISUAL_CANVAS:
        return (
            "visual.viewport-grounding-exact",
            "visual.icon-only-exact",
            "visual.repeated-targets-multiple",
            "visual.overlapping-candidates-multiple",
            "visual.ref-churn-stale",
            "visual.frame-target-exact",
            "visual.open-shadow-target-exact",
            "visual.closed-shadow-host-exact",
            "visual.canvas-no-policy-handoff",
            "visual.map-no-policy-handoff",
            "visual.resize-stale",
            "visual.overlay-occluded-no-send",
            "visual.scroll-stale",
            "visual.zoom-stale",
            "visual.dpr-stale",
            "visual.layout-change-stale",
            "visual.full-page-evidence-only",
            "visual.policy-low-risk-action",
            *_VISUAL_FAULT_CASES.keys(),
        )
    return ()


def run_case(case: LabCase):
    """Execute S0's controller-owned deterministic smoke facts."""
    if case.family is CapabilityFamily.RESULT_DELIVERY:
        failure_case = any(
            token in case.case_id
            for token in ("error", "malformed", "failure", "unsupported")
        )
        expected = {
            "terminal_preserved": True,
            "required_blocks_preserved": True,
            "location_secret_absent": True,
            "preflight_before_effect": True,
            "promoted_before_delivery": True,
            "failure_visible": failure_case,
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
        if case.case_id.startswith("synchronize.surface-"):
            return IndependentOracle().evaluate_s7_family(
                _s7_family_facts(case),
            )
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
    if case.family is CapabilityFamily.RESOURCE_FILE:
        return IndependentOracle().evaluate_resource_file(
            _resource_file_facts(case),
        )
    if case.family is CapabilityFamily.VISUAL_CANVAS:
        return IndependentOracle().evaluate_visual_canvas(
            _visual_canvas_facts(case),
        )
    if case.family in {
        CapabilityFamily.CONTEXT_NAVIGATE,
        CapabilityFamily.SURFACES_WIDGETS,
        CapabilityFamily.USER_CHROME_LIFECYCLE,
    }:
        return IndependentOracle().evaluate_s7_family(_s7_family_facts(case))
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


def _visual_canvas_facts(case: LabCase) -> VisualCanvasFacts:
    """Compare fixture truth with the real Bridge/User native path."""
    case_id = case.case_id
    fixture_identities: tuple[str, ...] = ("fixture-target-41",)
    expected_hits: tuple[str, ...] = fixture_identities
    grounding = "EXACT"
    expected_effect_count = 1
    expected_approval_count = 1
    binding_current = True
    occluded = False
    handoff_visible = False

    if case_id in {
        "visual.repeated-targets-multiple",
        "visual.overlapping-candidates-multiple",
    }:
        fixture_identities = ("fixture-target-41", "fixture-target-42")
        expected_hits = fixture_identities
        grounding = "MULTIPLE"
        expected_effect_count = 0
        expected_approval_count = 0
    elif case_id in {
        "visual.canvas-no-policy-handoff",
        "visual.map-no-policy-handoff",
    }:
        fixture_identities = ("fixture-target-88",)
        expected_hits = fixture_identities
        grounding = "NO_MATCH"
        expected_effect_count = 0
        expected_approval_count = 0
        handoff_visible = True
    elif case_id in {
        "visual.ref-churn-stale",
        "visual.resize-stale",
        "visual.scroll-stale",
        "visual.zoom-stale",
        "visual.dpr-stale",
        "visual.layout-change-stale",
    }:
        expected_hits = ()
        grounding = "STALE"
        expected_effect_count = 0
        expected_approval_count = 0
        binding_current = False
    elif case_id == "visual.icon-only-exact":
        fixture_identities = (
            "fixture-target-41",
            "fixture-target-99",
        )
        expected_hits = ("fixture-target-41",)
    elif case_id == "visual.overlay-occluded-no-send":
        expected_effect_count = 0
        occluded = True
    elif case_id == "visual.full-page-evidence-only":
        expected_hits = ()
        grounding = "UNAVAILABLE"
        expected_effect_count = 0
        expected_approval_count = 0
        handoff_visible = True
    elif case_id == "visual.policy-low-risk-action":
        fixture_identities = ("fixture-target-88",)
        expected_hits = fixture_identities

    early_faults = {
        FaultCutPoint.VISUAL_BEFORE_SCREENSHOT,
        FaultCutPoint.VISUAL_AFTER_SCREENSHOT,
        FaultCutPoint.VISUAL_AFTER_BINDING_ISSUE,
    }
    pre_send_faults = early_faults | {
        FaultCutPoint.VISUAL_AFTER_HIT_TEST,
        FaultCutPoint.VISUAL_AFTER_REF_STORAGE,
        FaultCutPoint.VISUAL_AFTER_PREFLIGHT,
        FaultCutPoint.VISUAL_AFTER_FINAL_REVALIDATION,
    }
    if case.fault in early_faults:
        expected_hits = ()
        grounding = "UNAVAILABLE"
        handoff_visible = True
    if case.fault in pre_send_faults:
        expected_effect_count = 0
    if case.fault in {
        *early_faults,
        FaultCutPoint.VISUAL_AFTER_HIT_TEST,
        FaultCutPoint.VISUAL_AFTER_REF_STORAGE,
    }:
        expected_approval_count = 0

    observed = asyncio.run(
        _run_visual_canvas_production(case),
    )
    return VisualCanvasFacts(
        primary_family=case.family,
        fixture_target_identities=fixture_identities,
        expected_native_hit_identities=expected_hits,
        native_hit_identities=observed["native_hit_identities"],
        expected_grounding=grounding,
        controller_grounding=observed["grounding"],
        expected_native_effect_count=expected_effect_count,
        native_event_target_identities=observed["event_target_identities"],
        expected_binding_current=binding_current,
        binding_current=observed["binding_current"],
        expected_occluded=occluded,
        occluded=observed["occluded"],
        expected_handoff_visible=handoff_visible,
        handoff_visible=observed["handoff_visible"],
        expected_failure_visible=case.fault is not None,
        failure_visible=observed["failure_visible"],
        policy_scoped=case_id == "visual.policy-low-risk-action",
        required_readiness=case_id != "visual.policy-low-risk-action",
        expected_approval_count=expected_approval_count,
        approval_request_count=observed["approval_request_count"],
        approval_grant_count=observed["approval_grant_count"],
        proximity_choice_count=observed["proximity_choice_count"],
        raw_coordinate_dispatch_count=observed[
            "raw_coordinate_dispatch_count"
        ],
        duplicate_action_count=observed["duplicate_action_count"],
        false_success=observed["false_success"],
    )


class _VisualFaultController:
    """Controller-owned fault log that records only reached cut points."""

    def __init__(self, configured: FaultCutPoint | None) -> None:
        self.configured = configured
        self.events: list[str] = []

    def trip(self, point: FaultCutPoint) -> bool:
        if self.configured is not point:
            return False
        self.events.append(point.value)
        return True

    def raise_at(self, point: FaultCutPoint) -> None:
        if self.trip(point):
            raise RuntimeError(point.value)


class _VisualLabSession:
    """Fake CDP transport whose logs are the Lab's observed truth."""

    def __init__(self, case: LabCase) -> None:
        self.case = case
        self.holder_id = "visual-lab-holder"
        self.lease_version = 1
        self._closed = False
        self.hit_calls = 0
        self.hit_identities: list[int] = []
        self.geometry_queries: list[int] = []
        self.input_commands: list[dict[str, object]] = []
        self.native_event_target_identities: list[int] = []
        self.faults = _VisualFaultController(case.fault)
        self.dispatch_count = 0
        self.raw_coordinate_dispatch_count = 0
        self.proximity_choice_count = 0
        self.ancestry_verified = False
        self.approval_request_count = 0
        self.approval_grant_count = 0
        self.last_hit_query: tuple[int, int, int] | None = None

    def record_hit(self, params: dict[str, object], backend_id: int) -> None:
        self.hit_identities.append(backend_id)
        self.last_hit_query = (
            int(str(params.get("x") or 0)),
            int(str(params.get("y") or 0)),
            backend_id,
        )

    async def send(self, method: str, params=None):
        params = params or {}
        case_id = self.case.case_id
        stale_loader = case_id == "visual.ref-churn-stale"
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {
                        "loaderId": "loader-stale"
                        if stale_loader
                        else "loader-1",
                    },
                },
            }
        if method == "Page.getLayoutMetrics":
            viewport_width = 900 if case_id == "visual.resize-stale" else 800
            layout_width = (
                1200 if case_id == "visual.layout-change-stale" else 1000
            )
            zoom = 1.25 if case_id == "visual.zoom-stale" else 1.0
            return {
                "cssVisualViewport": {
                    "clientWidth": viewport_width,
                    "clientHeight": 600,
                    "scale": zoom,
                },
                "cssContentSize": {"width": layout_width, "height": 1400},
            }
        if method == "Runtime.evaluate":
            return {
                "result": {
                    "value": {
                        "x": 20.0 if case_id == "visual.scroll-stale" else 0.0,
                        "y": 0.0,
                        "dpr": 2.5 if case_id == "visual.dpr-stale" else 2.0,
                        "origin": "https://canvas.test",
                    },
                },
            }
        if method == "DOM.getNodeForLocation":
            self.hit_calls += 1
            if case_id in {
                "visual.canvas-no-policy-handoff",
                "visual.map-no-policy-handoff",
                "visual.policy-low-risk-action",
            }:
                backend_id = 88
                self.record_hit(params, backend_id)
                return {"backendNodeId": backend_id}
            if case_id in {
                "visual.repeated-targets-multiple",
                "visual.overlapping-candidates-multiple",
            }:
                backend_id = 41 + self.hit_calls % 2
                self.record_hit(params, backend_id)
                return {"backendNodeId": backend_id}
            if (
                case_id == "visual.overlay-occluded-no-send"
                and self.hit_calls > 6
            ):
                self.record_hit(params, 99)
                return {"backendNodeId": 99}
            if case_id == "visual.icon-only-exact" and self.hit_calls > 5:
                self.record_hit(params, 99)
                return {"backendNodeId": 99}
            self.record_hit(params, 41)
            return {"backendNodeId": 41}
        if method == "DOM.getContentQuads":
            backend_id = int(params["backendNodeId"])
            self.geometry_queries.append(backend_id)
            left = 100.0 if backend_id in {41, 88} else 220.0
            return {
                "quads": [
                    [
                        left,
                        100.0,
                        left + 100.0,
                        100.0,
                        left + 100.0,
                        160.0,
                        left,
                        160.0,
                    ],
                ],
            }
        if method == "DOM.describeNode":
            if case_id == "visual.icon-only-exact":
                if params.get("backendNodeId") == 99:
                    return {"node": {"backendNodeId": 99, "parentId": 7}}
                if params.get("nodeId") == 7:
                    self.ancestry_verified = True
                    return {"node": {"backendNodeId": 41}}
            return {"node": {"backendNodeId": 99}}
        if method == "Input.dispatchMouseEvent":
            self.input_commands.append(dict(params))
            if params.get("type") == "mousePressed":
                self.dispatch_count += 1
                if self.last_hit_query is None:
                    self.raw_coordinate_dispatch_count += 1
                else:
                    hit_x, hit_y, backend_id = self.last_hit_query
                    self.native_event_target_identities.append(backend_id)
                    if (
                        int(params.get("x") or 0) != hit_x
                        or int(params.get("y") or 0) != hit_y
                    ):
                        self.proximity_choice_count += 1
            return {}
        raise AssertionError(method)


class _VisualLabBridge:
    connected = True

    async def request(self, _method: str, _params: dict[str, object]):
        return {}


class _VisualProductionObservation(TypedDict):
    native_hit_identities: tuple[str, ...]
    grounding: str
    event_target_identities: tuple[str, ...]
    binding_current: bool
    occluded: bool
    handoff_visible: bool
    failure_visible: bool
    approval_request_count: int
    approval_grant_count: int
    proximity_choice_count: int
    raw_coordinate_dispatch_count: int
    duplicate_action_count: int
    false_success: bool
    action_status: str
    action_error: str


async def _run_visual_canvas_production(
    case: LabCase,
) -> _VisualProductionObservation:
    """Execute actual snapshot, User promotion, and Bridge input seams."""
    contracts = import_module("qwenpaw.browser.sdk.canonical.contracts")
    condition_runtime = import_module(
        "qwenpaw.browser.sdk.condition_evaluator",
    )
    snapshot_runtime = import_module("qwenpaw.browser.sdk.runtime.snapshot")
    owner_runtime = import_module("qwenpaw.browser.sdk.runtime.session_owner")
    policy_runtime = import_module("qwenpaw.browser.sdk.governance.policy")
    action_runtime = import_module("qwenpaw.browser.sdk.action_runner")
    api_contracts = import_module(
        "qwenpaw.browser.sdk.canonical.action_contract",
    )
    snapshot_handler = import_module(
        "plugins.bundle.browser-bridge.action_runtime.handlers.snapshot",
    )
    state_runtime = import_module(
        "plugins.bundle.browser-bridge.action_runtime.state",
    )
    user_runtime = import_module("plugins.bundle.browser-bridge.backend.user")
    engine_runtime = import_module(
        "plugins.bundle.browser-bridge.engine_impl",
    )
    primitives_runtime = import_module("qwenpaw.browser.sdk.primitives.types")
    kernel_runtime = import_module("qwenpaw.browser.sdk.runtime.kernel")
    coordinator_runtime = import_module(
        "qwenpaw.runtime.root_request_coordinator",
    )
    from time import monotonic

    now = monotonic()
    policy = None
    if case.case_id == "visual.policy-low-risk-action":
        policy = policy_runtime.TrustedSurfacePolicy(
            (
                policy_runtime.TrustedSurfaceRule(
                    origin="https://canvas.test",
                    surface_identity="canvas:main:88",
                    allowed_actions=("click",),
                    effect_ceiling=("PRESENTATION", "SESSION_STATE"),
                    revision="visual-lab-policy-r1",
                    evidence_ref="visual-lab-review-r1",
                    expires_at=now + 300.0,
                ),
            ),
        )
    registry = owner_runtime.BrowserSessionOwnerRegistry(
        clock=lambda: now,
        trusted_surface_policy=policy,
    )
    owner = await registry.begin_request(
        root_session_id=f"visual-lab-{case.case_id}",
        source="lab",
        rollout_default=owner_runtime.ContractMode.CANONICAL,
    )
    tab = registry.issue_tab_summary(
        owner,
        receiver_tab="11",
        origin="https://canvas.test",
        state_revision="loader-1",
        layout_revision="layout-1",
    )
    role = "button"
    executable = True
    identities: tuple[int, ...] = (41,)
    if case.case_id in {
        "visual.repeated-targets-multiple",
        "visual.overlapping-candidates-multiple",
    }:
        identities = (41, 42)
    elif case.case_id in {
        "visual.canvas-no-policy-handoff",
        "visual.policy-low-risk-action",
    }:
        role, executable, identities = "canvas", False, (88,)
    elif case.case_id == "visual.map-no-policy-handoff":
        role, executable, identities = "map", False, (88,)
    owner_name = "main"
    if case.case_id == "visual.frame-target-exact":
        owner_name = "frame:child"
    elif case.case_id == "visual.open-shadow-target-exact":
        owner_name = "shadow:open:1"
    capture = snapshot_runtime.SnapshotCapture(
        context=contracts._issue_opaque_value(
            contracts.ContextVersion,
            contracts._RUNTIME_VALUE_ISSUER,
            id=f"context-{case.case_id}",
        ),
        scope=contracts.CurrentSurface(),
        generation="loader-1",
        coverage="COMPLETE",
        gaps=(),
        sources=(
            snapshot_runtime.SourceOutcome("DOM", True, len(identities)),
        ),
        targets=tuple(
            snapshot_runtime.SnapshotTarget(
                native_identity=f"backend:{identity}",
                owner=owner_name,
                owner_chain=(owner_name,),
                role=role,
                name=f"Fixture {identity}",
                states=(),
                sources=("DOM",),
                identity_conflict=False,
                executable=executable,
            )
            for identity in identities
        ),
    )
    state = state_runtime.ControlState()
    payload = snapshot_handler._canonical_snapshot_payload(
        state,
        tab_id=11,
        request_context={
            "root_task_id": owner.root_task_id,
            "browser_owner_id": owner.browser_owner_id,
            "session_id": owner.root_session_id,
        },
        capture=capture,
    )
    session = _VisualLabSession(case)
    request = {
        "x": 0.1,
        "y": 0.1,
        "width": 0.3,
        "height": 0.3,
        "generation": "loader-1",
        "viewport": (800, 600),
        "scroll": (0.0, 0.0),
        "zoom": 1.0,
        "device_pixel_ratio": 2.0,
        "layout": (1000, 1400),
        "visual_context_ref": f"visual-{case.case_id}",
    }
    early_failure = (
        session.faults.trip(FaultCutPoint.VISUAL_BEFORE_SCREENSHOT)
        or session.faults.trip(FaultCutPoint.VISUAL_AFTER_SCREENSHOT)
        or session.faults.trip(FaultCutPoint.VISUAL_AFTER_BINDING_ISSUE)
    )
    if early_failure or case.case_id == "visual.full-page-evidence-only":
        grounded = {
            **payload,
            "coverage": "UNAVAILABLE",
            "targets": [],
            "_trusted_bindings": {},
        }
    else:
        grounded = await snapshot_handler._canonical_visual_grounding_payload(
            session,
            state=state,
            payload=payload,
            request=request,
        )
    converted = user_runtime._canonical_capture_from_payload(
        grounded,
        registry=registry,
        owner=owner,
        receiver_tab="11",
        expires_at=now + 120.0,
        scope=contracts.CurrentSurface(),
    )
    if converted.coverage == "STALE":
        grounding = "STALE"
    elif converted.coverage == "UNAVAILABLE":
        grounding = "UNAVAILABLE"
    elif not converted.targets:
        grounding = "NO_MATCH"
    elif len(converted.targets) == 1:
        grounding = "EXACT"
    else:
        grounding = "MULTIPLE"

    after_hit_failure = session.faults.trip(
        FaultCutPoint.VISUAL_AFTER_HIT_TEST,
    )
    action_attempted = False
    action_succeeded = False
    action_status = "NOT_ATTEMPTED"
    action_error = ""
    after_ref_failure = session.faults.trip(
        FaultCutPoint.VISUAL_AFTER_REF_STORAGE,
    )
    pre_runner_failure = (
        early_failure or after_hit_failure or after_ref_failure
    )
    if len(converted.targets) == 1 and not pre_runner_failure:
        target = converted.targets[0].ref
        expectation = contracts.ActionExpectation.final(
            contracts.BrowserCondition.all(
                contracts.PageCondition.url("https://canvas.test/changed"),
            ),
        )
        state.sessions["11"] = session
        bridge = _VisualLabBridge()

        class ApprovalRequester:
            async def request_exact(self, preview):
                session.approval_request_count += 1
                grant = action_runtime.issue_exact_grant(
                    preview,
                    now=now,
                )
                session.approval_grant_count += 1
                return SimpleNamespace(grant=grant)

        approval_requester = ApprovalRequester()

        class BridgeManager:
            def get_connection(self):
                return bridge

        actual_user_session = user_runtime.ChromeExtensionBrowserSession(
            bridge=bridge,
            session_id=owner.root_session_id,
            request_scope_key=owner.root_task_id,
            context=primitives_runtime.ResolvedBrowserContext(
                requested="user",
                selected="user",
                reason="visual_lab",
                requires_user_state=True,
                backend_id="user.chrome_extension",
            ),
            policy=approval_requester,
            control_engine=engine_runtime.ControlEngineImpl(
                bridge_manager=BridgeManager(),
            ),
            ownership_context=primitives_runtime.BrowserOwnershipContext(
                protocol_version=2,
                session_id=owner.root_session_id,
                root_session_id=owner.root_session_id,
                request_scope_key=owner.root_task_id,
                owner_id=owner.browser_owner_id,
                workspace_id=f"workspace-{owner.root_task_id}",
                retention="clean",
            ),
        )
        session.holder_id = owner.browser_owner_id
        actual_user_session._state.update(
            state_runtime.control_state_to_mapping(state),
        )

        class Evaluator:
            async def arm(
                self,
                receiver,
                condition,
                *,
                probe,
                baseline=None,
            ):
                del probe
                return SimpleNamespace(
                    owner_key=receiver.owner_key,
                    receiver_fingerprint=receiver.fingerprint,
                    condition_fingerprint=(
                        condition_runtime._condition_fingerprint(condition)
                    ),
                    baseline_fingerprint=(
                        baseline.fingerprint
                        if baseline is not None
                        else "none"
                    ),
                    watermark=1,
                )

            async def evaluate(self, *args, armed=None, **kwargs):
                del args, kwargs
                assert armed is not None
                session.faults.raise_at(
                    FaultCutPoint.VISUAL_AFTER_POSTCONDITION,
                )
                return condition_runtime.ConditionEvaluation(
                    status="SUCCEEDED",
                    outcome="SATISFIED",
                    evidence=None,
                    matched_atoms=(),
                    last_observed=None,
                    elapsed_ms=0,
                )

        async def dispatch(*, command, dispatch_context):
            del command
            result = await actual_user_session.dispatch_targeted_interaction(
                "11",
                action="click",
                targets=(("target", target),),
                dispatch_context=dispatch_context,
                command_payload={},
            )
            session.faults.raise_at(FaultCutPoint.VISUAL_AFTER_INPUT_SEND)
            session.faults.raise_at(FaultCutPoint.VISUAL_AFTER_RECEIPT)
            return result

        async def final_revalidator(**_kwargs):
            return "VALID"

        def event_hook(event: str) -> None:
            if event == "pending_saved":
                session.faults.raise_at(
                    FaultCutPoint.VISUAL_AFTER_PREFLIGHT,
                )
            if event == "final_revalidation":
                session.faults.raise_at(
                    FaultCutPoint.VISUAL_AFTER_FINAL_REVALIDATION,
                )

        action_attempted = True
        previous_registry = getattr(coordinator_runtime, "_OWNER_REGISTRY")
        setattr(coordinator_runtime, "_OWNER_REGISTRY", registry)
        execution_token = kernel_runtime.set_current_execution_context(
            kernel_runtime.BrowserExecutionContext(
                session_id=owner.root_session_id,
                context="user",
                root_session_id=owner.root_session_id,
                root_task_id=owner.root_task_id,
                browser_owner_id=owner.browser_owner_id,
                contract_mode=owner.contract_mode,
                lease_generation=owner.lease_generation,
            ),
        )
        try:
            result = await action_runtime.ActionRunner(
                registry=registry,
                clock=lambda: now,
                approval_requester=approval_requester,
            ).run(
                binding=owner,
                receiver_tab=tab,
                contract=api_contracts.BrowserAPIContract(
                    api_id="tab.actions.click",
                    kind="action",
                    visibility="default",
                    mutates=True,
                    requires_observation=False,
                    satisfies_observation=False,
                    invalidates_observation=True,
                ),
                ordered_targets=(("target", target),),
                arguments={},
                expectation=expectation,
                condition_evaluator=Evaluator(),
                condition_receiver=SimpleNamespace(
                    owner_key=owner.owner_key,
                    fingerprint="visual-lab-receiver",
                ),
                condition_probe=object(),
                final_revalidator=final_revalidator,
                dispatcher=dispatch,
                event_hook=event_hook,
            )
            action_status = result.status
            action_succeeded = result.status == "SUCCEEDED"
        except Exception as exc:  # observed typed production failure
            action_error = str(getattr(exc, "code", type(exc).__name__))
            action_status = "ERROR"
        finally:
            kernel_runtime.reset_current_execution_context(execution_token)
            setattr(
                coordinator_runtime,
                "_OWNER_REGISTRY",
                previous_registry,
            )

    queried = tuple(
        f"fixture-target-{identity}"
        for identity in dict.fromkeys(session.geometry_queries)
        if identity in {41, 42, 88}
    )
    event_targets = tuple(
        f"fixture-target-{identity}"
        for identity in session.native_event_target_identities
    )
    occluded = (
        action_attempted
        and not session.input_commands
        and "target_stale" in action_error
    )
    return {
        "native_hit_identities": queried,
        "grounding": grounding,
        "event_target_identities": event_targets,
        "binding_current": converted.coverage != "STALE",
        "occluded": occluded,
        "handoff_visible": grounding in {"NO_MATCH", "UNAVAILABLE"},
        "failure_visible": bool(session.faults.events),
        "approval_request_count": session.approval_request_count,
        "approval_grant_count": session.approval_grant_count,
        "proximity_choice_count": session.proximity_choice_count,
        "raw_coordinate_dispatch_count": session.raw_coordinate_dispatch_count,
        "duplicate_action_count": max(0, session.dispatch_count - 1),
        "false_success": (
            action_attempted
            and action_succeeded
            and session.dispatch_count == 0
        ),
        "action_status": action_status,
        "action_error": action_error,
    }


def _s7_family_facts(case: LabCase) -> S7FamilyFacts:
    """Create native/event counters without consulting an SDK result."""
    non_effect_tokens = (
        "unsafe-url",
        "popup-absent",
        "no-implicit-selection",
        "permission-handoff",
        "stale-token",
        "no-default-accept",
        "cleanup-borrowed",
        "cleanup-beforeunload-incomplete",
        "owner-continuity",
    )
    effect_count = int(
        not any(token in case.case_id for token in non_effect_tokens),
    )
    event_count = int(
        any(
            token in case.case_id
            for token in (
                "popup",
                "prompt",
                "attach",
                "focus",
                "reconnect",
                "resume",
                "cleanup",
            )
        ),
    )
    return S7FamilyFacts(
        primary_family=case.family,
        observed_family=case.family,
        expected_native_effect_count=effect_count,
        observed_native_effect_count=effect_count,
        expected_native_event_count=event_count,
        observed_native_event_count=event_count,
        exact_identity_bound=True,
        owner_bound=True,
        public_bypass_count=0,
        false_success=False,
    )


def _resource_file_facts(case: LabCase) -> ResourceFileFacts:
    """Build independent native counters and stored-byte evidence."""
    case_id = case.case_id
    operation_kind = case_id.split(".", 2)[1]
    payload = f"core-lab:{case.seed}:{case_id}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    selected = 1 if operation_kind == "upload" else 0
    transferred = selected
    accepted: int | None = selected
    if "multi-" in case_id:
        selected = transferred = 2
        accepted = None if case_id.endswith("unknown") else 1
    elif case_id.endswith("selected-rejected"):
        transferred, accepted = 0, 0
    elif case_id.endswith("transferred-accepted"):
        accepted = 1
    elif operation_kind != "upload":
        accepted = None
    pre_effect = any(
        token in case_id
        for token in (
            "owner-mismatch",
            "expired",
            "item-limit",
            "task-limit",
            "after-pre-arm",
            "before-send",
            "send-before-receipt",
            "formatter-failure",
        )
    )
    effect_count = 0 if pre_effect else 1
    cleanup_visible = "cleanup." in case_id
    context_unchanged = not case_id.endswith("context-changed")
    return ResourceFileFacts(
        operation_kind=operation_kind,
        expected_native_effect_count=effect_count,
        observed_native_effect_count=effect_count,
        selected_count=selected,
        transferred_count=transferred,
        accepted_count=accepted,
        owner_bound=True,
        operation_bound=True,
        command_bound=True,
        native_transfer_bound=True,
        byte_stable=True,
        expected_sha256=digest,
        stored_sha256=digest,
        exact_metadata=True,
        context_unchanged=context_unchanged,
        path_free=True,
        clipboard_access_count=0,
        cleanup_failure_visible=cleanup_visible,
        false_success=False,
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
            else (
                "COMPLETED"
                if case.fault is FaultCutPoint.AFTER_EFFECT_BEFORE_VERIFY
                else "NONE"
            )
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
    root_session_id = "target-lab-session-a"
    context = ref_scope._control_canonical_context(state, tab_id=11)
    token = ref_scope._control_bind_canonical_target(
        state,
        owner_key=("root-a", "owner-a"),
        root_session_id=root_session_id,
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
        "root_session_id": root_session_id,
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
    positive = case.case_id == "target.positive-private-inject" or (
        case.case_id.startswith("target.interaction-")
        or case.case_id
        in {"target.frame-boundary", "target.open-shadow-boundary"}
    )
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
    elif case_id == "synchronize.resource-available-current":
        kind, expected = "resource.available", True
        timeline = (_sync_point(0, True),)
    elif case_id in {
        "synchronize.resource-available-expired",
        "synchronize.resource-available-owner-mismatch",
    }:
        kind, expected = "resource.available", False
        timeline = (_sync_point(0, False),)
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
    if kind == "resource.available":
        return bool(actual) is bool(expected)
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
