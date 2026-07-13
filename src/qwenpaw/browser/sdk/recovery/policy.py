# -*- coding: utf-8 -*-
"""Browser SDK recovery evidence and deterministic decisions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from qwenpaw.constant import QWENPAW_MESSAGE_TAG_KEY

from ..governance.error_codes import (
    BrowserErrorCode,
    BrowserOutcome,
    classify_browser_error,
)
from ..telemetry.trace import (
    BrowserTraceEvent,
    BrowserTraceStore,
    get_browser_trace_store,
)
from ..telemetry.progress import detect_no_progress


class BrowserRecoveryAction(StrEnum):
    """Structured Browser recovery action consumed by BrowserGate."""

    NO_OP = "no_op"
    CONTINUE = "continue"
    RETRY_WITH_CONTEXT = "retry_with_context"
    WAIT_FOR_APPROVAL = "wait_for_approval"
    BLOCKED = "blocked"
    FAILED = "failed"
    HANDOFF = "handoff"


@dataclass(frozen=True)
class BrowserRequestEvidence:
    """Browser evidence scoped to one real user request."""

    session_id: str
    request_scope_key: str
    tool_call_ids: tuple[str, ...]
    trace_events: tuple[BrowserTraceEvent, ...]
    tool_metadata: tuple[dict[str, Any], ...]
    has_browser_tool_calls: bool


@dataclass(frozen=True)
class BrowserRecoveryDecision:
    """One deterministic Browser recovery decision."""

    action: BrowserRecoveryAction
    reason: str = ""
    requested_context: str = ""
    selected_context: str = ""
    next_context: str = ""
    required_next_step: str = ""
    forbidden: tuple[str, ...] = ()
    retry_budget_key: str = ""
    final_message: str = ""
    continuation_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserProductPolicy:
    """Internal Browser product-health thresholds."""

    strategy_shift_budget: int = 1
    no_progress_threshold: int = 3
    max_new_tabs_per_request: int = 3
    repeated_approval_domain_threshold: int = 3
    stale_observation_threshold: int = 3
    low_information_threshold: int = 2
    invalid_sdk_usage_threshold: int = 2


@dataclass(frozen=True)
class BrowserRuntimeOutcome:
    """Terminal or in-progress runtime classification for browser work."""

    status: str
    category: str
    reason: str = ""
    error_code: str = ""
    terminal: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "category": self.category,
            "reason": self.reason,
            "error_code": self.error_code,
            "terminal": self.terminal,
        }


@dataclass(frozen=True)
class _RecoveryTemplate:
    action: BrowserRecoveryAction
    reason: str
    required_next_step: str
    forbidden: tuple[str, ...] = ()
    next_context: str = ""


PROTOCOL_TIMEOUT_CODES = frozenset(
    {
        BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT.value,
        BrowserErrorCode.CDP_COMMAND_TIMEOUT.value,
        BrowserErrorCode.DOM_SETTLE_TIMEOUT.value,
        BrowserErrorCode.NETWORK_SETTLE_TIMEOUT.value,
        BrowserErrorCode.DOWNLOAD_TIMEOUT.value,
        BrowserErrorCode.UPLOAD_TIMEOUT.value,
        BrowserErrorCode.NETWORK_TIMEOUT.value,
    },
)
_CONTEXT_SWITCH_ERROR_CODES = frozenset(
    {
        BrowserErrorCode.LOGIN_REQUIRED.value,
        BrowserErrorCode.CAPTCHA_OR_RISK_CONTROL.value,
    },
)
_DEGRADED_FALLBACK_STOP_CODES = frozenset(
    {
        BrowserErrorCode.LOGIN_REQUIRED.value,
        BrowserErrorCode.CAPTCHA_OR_RISK_CONTROL.value,
        BrowserErrorCode.USER_BROWSER_UNAVAILABLE.value,
        BrowserErrorCode.BOUNDARY_USER_INTERVENTION_REQUIRED.value,
    },
)
_ERROR_CODE_RECOVERY_TEMPLATES = {
    BrowserErrorCode.APPROVAL_DENIED.value: _RecoveryTemplate(
        BrowserRecoveryAction.BLOCKED,
        "approval_denied",
        "stop_browser_action",
    ),
    BrowserErrorCode.APPROVAL_REQUIRED.value: _RecoveryTemplate(
        BrowserRecoveryAction.WAIT_FOR_APPROVAL,
        "approval_pending",
        "wait_for_user_approval",
    ),
    BrowserErrorCode.BRIDGE_DISCONNECTED.value: _RecoveryTemplate(
        BrowserRecoveryAction.BLOCKED,
        "bridge_disconnected",
        "reconnect_browser_bridge",
        ("isolated_fallback",),
    ),
    BrowserErrorCode.USER_BROWSER_UNAVAILABLE.value: _RecoveryTemplate(
        BrowserRecoveryAction.BLOCKED,
        BrowserErrorCode.USER_BROWSER_UNAVAILABLE.value,
        "install_or_reconnect_chrome_extension",
        ("isolated_fallback",),
    ),
    BrowserErrorCode.BOUNDARY_USER_INTERVENTION_REQUIRED.value: (
        _RecoveryTemplate(
            BrowserRecoveryAction.BLOCKED,
            BrowserErrorCode.BOUNDARY_USER_INTERVENTION_REQUIRED.value,
            "ask_user_to_complete_boundary",
            ("automate_critical_unknown_boundary",),
        )
    ),
    BrowserErrorCode.OBSERVATION_STALE.value: _RecoveryTemplate(
        BrowserRecoveryAction.CONTINUE,
        "fresh_observation_required",
        "tab.snapshot()",
        ("repeat_mutation_without_observation",),
    ),
    BrowserErrorCode.OBSERVATION_ENRICHMENT_DENIED.value: _RecoveryTemplate(
        BrowserRecoveryAction.CONTINUE,
        "observation_enrichment_denied",
        "tab.screenshot()",
        (
            "repeat_enrichment_without_fallback",
            "repeat_mutation_without_observation",
        ),
    ),
    BrowserErrorCode.INVALID_SDK_USAGE.value: _RecoveryTemplate(
        BrowserRecoveryAction.CONTINUE,
        "invalid_sdk_usage",
        "use_supported_browser_sdk_api",
        ("invent_browser_sdk_methods",),
    ),
    BrowserErrorCode.CLICK_WITHOUT_NAVIGATION.value: _RecoveryTemplate(
        BrowserRecoveryAction.CONTINUE,
        "click_without_navigation",
        "tab.snapshot()",
        ("assume_navigation_completed",),
    ),
    BrowserErrorCode.CAPABILITY_MISSING.value: _RecoveryTemplate(
        BrowserRecoveryAction.FAILED,
        "capability_missing",
        "use_generic_browser_capability",
    ),
    BrowserErrorCode.NETWORK_TIMEOUT.value: _RecoveryTemplate(
        BrowserRecoveryAction.CONTINUE,
        "network_timeout",
        "retry_after_page_settles",
    ),
}


def classify_browser_runtime_outcome(
    metadata: dict[str, Any] | None = None,
    *,
    trace_events: Iterable[BrowserTraceEvent | dict[str, Any]] = (),
) -> BrowserRuntimeOutcome:
    """Classify browser runtime state without conflating terminal causes."""
    payload = dict(metadata or {})
    status = str(payload.get("status") or "").strip().casefold()
    failure_reason = str(payload.get("failure_reason") or "").strip()
    blocked_reason = str(payload.get("blocked_reason") or "").strip()

    if _runtime_in_progress(payload, status):
        return BrowserRuntimeOutcome(
            status=BrowserOutcome.IN_PROGRESS.value,
            category="running",
            reason="long_running_browser_execution",
            terminal=False,
        )

    progress_reason = _progress_block_reason(payload)
    if progress_reason:
        return _model_loop_outcome(progress_reason)

    if failure_reason in {"no_progress", "retry_budget_exhausted"}:
        return _model_loop_outcome(failure_reason)

    code = _runtime_error_code(payload, trace_events)
    if code:
        return _outcome_for_error_code(code, blocked_reason=blocked_reason)

    return _outcome_for_status(
        status,
        blocked_reason=blocked_reason,
        failure_reason=failure_reason,
        ok=payload.get("ok") is True,
    )


def _in_progress_outcome() -> BrowserRuntimeOutcome:
    return BrowserRuntimeOutcome(
        status=BrowserOutcome.IN_PROGRESS.value,
        category="running",
        reason="long_running_browser_execution",
        terminal=False,
    )


def _model_loop_outcome(reason: str) -> BrowserRuntimeOutcome:
    return BrowserRuntimeOutcome(
        status=BrowserOutcome.FAILED.value,
        category="model_loop",
        reason=reason,
    )


def _outcome_for_error_code(
    code: str,
    *,
    blocked_reason: str,
) -> BrowserRuntimeOutcome:
    info = classify_browser_error(code)
    if info.code == BrowserErrorCode.CANCELLED:
        return BrowserRuntimeOutcome(
            status=BrowserOutcome.CANCELLED.value,
            category="cancellation",
            reason=info.code.value,
            error_code=info.code.value,
        )
    if info.code.value in PROTOCOL_TIMEOUT_CODES:
        return BrowserRuntimeOutcome(
            status=BrowserOutcome.FAILED.value,
            category="protocol_timeout",
            reason=info.code.value,
            error_code=info.code.value,
        )
    if info.code == BrowserErrorCode.CAPABILITY_MISSING:
        return BrowserRuntimeOutcome(
            status=BrowserOutcome.FAILED.value,
            category="capability_error",
            reason=info.code.value,
            error_code=info.code.value,
        )
    if info.outcome == BrowserOutcome.BLOCKED:
        return BrowserRuntimeOutcome(
            status=BrowserOutcome.BLOCKED.value,
            category="user_blocker",
            reason=info.blocked_reason or blocked_reason,
            error_code=info.code.value,
        )
    return BrowserRuntimeOutcome(
        status=info.outcome.value,
        category="browser_error",
        reason=info.failure_reason or info.blocked_reason,
        error_code=info.code.value,
    )


def _outcome_for_status(
    status: str,
    *,
    blocked_reason: str,
    failure_reason: str,
    ok: bool,
) -> BrowserRuntimeOutcome:
    if status in {"cancelled", "canceled"}:
        return BrowserRuntimeOutcome(
            status=BrowserOutcome.CANCELLED.value,
            category="cancellation",
            reason=BrowserErrorCode.CANCELLED.value,
            error_code=BrowserErrorCode.CANCELLED.value,
        )
    if status == "blocked":
        return BrowserRuntimeOutcome(
            status=BrowserOutcome.BLOCKED.value,
            category="user_blocker",
            reason=blocked_reason or "blocked",
        )
    if status == "failed":
        return BrowserRuntimeOutcome(
            status=BrowserOutcome.FAILED.value,
            category="runtime_failure",
            reason=failure_reason or "verification_failed",
        )
    if status in {"passed", "pass", "success"} or ok:
        return BrowserRuntimeOutcome(
            status=BrowserOutcome.PASS.value,
            category="completed",
            reason="completed",
            terminal=True,
        )
    return _in_progress_outcome()


def _runtime_in_progress(payload: dict[str, Any], status: str) -> bool:
    if status in {"running", "in_progress"}:
        return True
    if payload.get("in_progress") is True:
        return True
    runtime_state = str(payload.get("runtime_state") or "").casefold()
    return runtime_state in {"running", "in_progress"}


def _progress_block_reason(payload: dict[str, Any]) -> str:
    progress = payload.get("progress_decision")
    if not isinstance(progress, dict):
        return ""
    if progress.get("blocked") is not True:
        return ""
    return str(progress.get("reason") or "no_progress")


def _runtime_error_code(
    payload: dict[str, Any],
    trace_events: Iterable[BrowserTraceEvent | dict[str, Any]],
) -> str:
    for key in ("error_code", "browser_error_code"):
        value = str(payload.get(key) or "").strip()
        if value:
            return classify_browser_error(value).code.value
    for event in reversed(list(trace_events)):
        event_payload = (
            event.to_dict() if isinstance(event, BrowserTraceEvent) else event
        )
        if not isinstance(event_payload, dict):
            continue
        value = str(event_payload.get("error_code") or "").strip()
        if value:
            return classify_browser_error(value).code.value
        metadata = event_payload.get("metadata")
        if isinstance(metadata, dict):
            value = str(
                metadata.get("browser_error_code")
                or metadata.get("error_code")
                or "",
            ).strip()
            if value:
                return classify_browser_error(value).code.value
        if str(event_payload.get("status") or "").casefold() in {
            "cancelled",
            "canceled",
        }:
            return BrowserErrorCode.CANCELLED.value
    return ""


def collect_browser_request_evidence(
    agent: Any,
    *,
    trace_store: BrowserTraceStore | None = None,
) -> BrowserRequestEvidence:
    """Collect current-request Browser tool and trace evidence."""

    state = getattr(agent, "state", None)
    context = list(getattr(state, "context", ()) or ())
    session_id = _session_id(agent)
    latest_user_index = _latest_real_user_index(context)
    scoped_messages = (
        context[latest_user_index + 1 :] if latest_user_index >= 0 else context
    )
    tool_call_ids = _browser_tool_call_ids(scoped_messages)
    metadata = _browser_tool_metadata(scoped_messages, set(tool_call_ids))
    store = trace_store or get_browser_trace_store()
    trace_events = tuple(
        event
        for event in store.list(session_id)
        if event.tool_call_id in set(tool_call_ids)
    )
    return BrowserRequestEvidence(
        session_id=session_id,
        request_scope_key=f"{session_id}:{latest_user_index}",
        tool_call_ids=tool_call_ids,
        trace_events=trace_events,
        tool_metadata=metadata,
        has_browser_tool_calls=bool(tool_call_ids),
    )


def _action_truth_handoff_reason(
    metadata_items: tuple[dict[str, Any], ...],
) -> str:
    """Make unresolved or forbidden material mutation dominant over retry."""
    high_risk_intents = {
        "purchase",
        "send_message",
        "permission_change",
        "permanent_delete",
    }
    for metadata in reversed(metadata_items):
        status = str(metadata.get("status") or "").upper()
        retry = str(metadata.get("retry") or "").upper()
        intent = str(metadata.get("intent") or "").casefold()
        effects = {
            str(item).upper()
            for item in metadata.get("classified_effects", ())
        }
        if status == "UNCERTAIN" or retry == "RECONCILE_ONLY":
            return "unresolved_pending_action"
        if retry == "FORBIDDEN" and (
            intent in high_risk_intents or "UNKNOWN" in effects
        ):
            return "material_mutation_handoff"
    return ""


def fresh_attempt_is_safe(
    *,
    dispatch: str,
    trusted_abort: bool = False,
) -> bool:
    """Authorize a new operation only from definite pre-send evidence."""
    return trusted_abort or str(dispatch).upper() in {"NOT_SENT", "REJECTED"}


class BrowserRecoveryPolicy:
    """Convert Browser evidence into structured recovery decisions."""

    def __init__(
        self,
        *,
        product_policy: BrowserProductPolicy | None = None,
    ) -> None:
        self.product_policy = product_policy or BrowserProductPolicy()

    # The policy is a priority-ordered decision table; early returns keep the
    # safety branches explicit and easy to audit.
    # pylint: disable=too-many-return-statements,too-many-branches
    def decide(
        self,
        evidence: BrowserRequestEvidence,
    ) -> BrowserRecoveryDecision:
        """Return a deterministic decision for current Browser evidence."""

        if not evidence.has_browser_tool_calls:
            return BrowserRecoveryDecision(
                action=BrowserRecoveryAction.NO_OP,
                reason="no_browser_tool_calls",
            )

        event = _latest_event(evidence.trace_events)
        handoff_reason = _action_truth_handoff_reason(evidence.tool_metadata)
        if handoff_reason:
            return self._decision(
                BrowserRecoveryAction.HANDOFF,
                reason=handoff_reason,
                event=event,
                required_next_step="handoff_to_user",
                forbidden=("retry_mutation", "reuse_approval_grant"),
            )
        approval = _approval_state(evidence)
        approval_loop = _repeated_approval_domain(
            evidence,
            threshold=self.product_policy.repeated_approval_domain_threshold,
        )
        if approval_loop is not None:
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason="repeated_approval_domain",
                event=event,
                required_next_step="stop_reprompting_same_domain",
                metadata=approval_loop,
            )
        if approval == "pending":
            return self._decision(
                BrowserRecoveryAction.WAIT_FOR_APPROVAL,
                reason="approval_pending",
                event=event,
                required_next_step="wait_for_user_approval",
                metadata=_approval_metadata(evidence),
            )
        if approval in {"denied", "timeout", "error"}:
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason=f"approval_{approval}",
                event=event,
                required_next_step="stop_browser_action",
                metadata=_approval_metadata(evidence),
            )

        error_code = _latest_error_code(evidence)
        stale_loop = _repeated_stale_observation(
            evidence,
            threshold=self.product_policy.stale_observation_threshold,
        )
        if stale_loop is not None:
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason="repeated_stale_observation",
                event=event,
                required_next_step="ask_user_to_take_over",
                forbidden=("repeat_mutation_without_observation",),
                metadata=stale_loop,
            )
        invalid_loop = _repeated_invalid_sdk_usage(
            evidence,
            threshold=self.product_policy.invalid_sdk_usage_threshold,
        )
        if invalid_loop is not None:
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason="invalid_sdk_usage",
                event=event,
                required_next_step="use_supported_browser_sdk_api",
                forbidden=("invent_browser_sdk_methods",),
                metadata=invalid_loop,
            )
        if _degraded_timeout_loop(evidence, error_code):
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason="degraded_isolated_timeout_loop",
                event=event,
                required_next_step="install_or_reconnect_chrome_extension",
                forbidden=("isolated_fallback", "retry_with_user_context"),
                metadata=_degraded_fallback_metadata(event),
            )
        if _degraded_fallback_stop_required(error_code, event):
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason=error_code,
                event=event,
                required_next_step="install_or_reconnect_chrome_extension",
                forbidden=("isolated_fallback", "retry_with_user_context"),
                metadata=_degraded_fallback_metadata(event),
            )
        template = _error_code_recovery_template(error_code, event)
        if template is not None:
            return self._decision(
                template.action,
                reason=template.reason,
                event=event,
                next_context=template.next_context,
                required_next_step=template.required_next_step,
                forbidden=template.forbidden,
                metadata=(
                    _approval_metadata(evidence)
                    if template.reason == "approval_pending"
                    else None
                ),
            )
        tab_churn = _tab_churn(
            evidence,
            max_new_tabs=self.product_policy.max_new_tabs_per_request,
        )
        if tab_churn is not None:
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason="tab_churn",
                event=event,
                required_next_step="reuse_existing_workspace_tab",
                forbidden=("open_more_tabs",),
                metadata=tab_churn,
            )
        low_information = _low_information_observation(
            evidence,
            threshold=self.product_policy.low_information_threshold,
        )
        if low_information is not None:
            action = (
                BrowserRecoveryAction.BLOCKED
                if low_information["count"]
                >= self.product_policy.low_information_threshold
                else BrowserRecoveryAction.CONTINUE
            )
            return self._decision(
                action,
                reason="low_information_observation",
                event=event,
                required_next_step=(
                    "ask_user_to_take_over"
                    if action == BrowserRecoveryAction.BLOCKED
                    else "tab.screenshot()"
                ),
                forbidden=("repeat_low_information_observation",),
                metadata=low_information,
            )
        progress_decision = detect_no_progress(
            evidence.trace_events,
            threshold=self.product_policy.no_progress_threshold,
        )
        if progress_decision.blocked:
            if _degraded_fallback(evidence):
                return self._decision(
                    BrowserRecoveryAction.BLOCKED,
                    reason="degraded_isolated_no_progress",
                    event=event,
                    required_next_step=(
                        "install_or_reconnect_chrome_extension"
                    ),
                    forbidden=(
                        "isolated_fallback",
                        "repeat_identical_action",
                    ),
                    metadata={
                        **_degraded_fallback_metadata(event),
                        "progress_decision": progress_decision.to_dict(),
                    },
                )
            return self._decision(
                BrowserRecoveryAction.HANDOFF,
                reason="no_progress",
                event=event,
                required_next_step="handoff_to_user",
                forbidden=("repeat_identical_action",),
                metadata={"progress_decision": progress_decision.to_dict()},
            )
        if _no_progress(evidence):
            if _degraded_fallback(evidence):
                return self._decision(
                    BrowserRecoveryAction.BLOCKED,
                    reason="degraded_isolated_no_progress",
                    event=event,
                    required_next_step=(
                        "install_or_reconnect_chrome_extension"
                    ),
                    forbidden=(
                        "isolated_fallback",
                        "repeat_identical_action",
                    ),
                    metadata=_degraded_fallback_metadata(event),
                )
            return self._decision(
                BrowserRecoveryAction.HANDOFF,
                reason="no_progress",
                event=event,
                required_next_step="handoff_to_user",
                forbidden=("repeat_identical_action",),
            )
        if _observation_enrichment_denied(evidence):
            return self._decision(
                BrowserRecoveryAction.CONTINUE,
                reason="observation_enrichment_denied",
                event=event,
                required_next_step="tab.screenshot()",
                forbidden=(
                    "repeat_enrichment_without_fallback",
                    "repeat_mutation_without_observation",
                ),
            )
        if _invalid_sdk_usage(evidence):
            return self._decision(
                BrowserRecoveryAction.CONTINUE,
                reason="invalid_sdk_usage",
                event=event,
                required_next_step="use_supported_browser_sdk_api",
                forbidden=("invent_browser_sdk_methods",),
            )
        if _click_without_navigation(evidence):
            return self._decision(
                BrowserRecoveryAction.CONTINUE,
                reason="click_without_navigation",
                event=event,
                required_next_step="tab.snapshot()",
                forbidden=("assume_navigation_completed",),
            )
        return BrowserRecoveryDecision(
            action=BrowserRecoveryAction.NO_OP,
            reason="no_recovery_needed",
        )

    def _decision(
        self,
        action: BrowserRecoveryAction,
        *,
        reason: str,
        event: BrowserTraceEvent | None,
        next_context: str = "",
        required_next_step: str = "",
        forbidden: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> BrowserRecoveryDecision:
        requested = event.requested_context if event is not None else ""
        selected = event.selected_context if event is not None else ""
        backend = event.backend_id if event is not None else ""
        merged_metadata = dict(metadata or {})
        if backend:
            merged_metadata.setdefault("backend_id", backend)
        final_message = ""
        if action in {
            BrowserRecoveryAction.BLOCKED,
            BrowserRecoveryAction.FAILED,
            BrowserRecoveryAction.HANDOFF,
        }:
            recovery_hint = str(merged_metadata.get("recovery_hint") or "")
            final_message = (
                "Browser task blocked:\n"
                f"reason: {reason}\n"
                f"context: {selected or requested or 'unknown'}\n"
                f"backend: {backend or 'unknown'}\n"
                f"required_user_action: {required_next_step or 'none'}\n"
                f"status: {action.value}"
            )
            if recovery_hint:
                final_message = f"{final_message}\nhint: {recovery_hint}"
        continuation = ""
        if action in {
            BrowserRecoveryAction.CONTINUE,
            BrowserRecoveryAction.RETRY_WITH_CONTEXT,
            BrowserRecoveryAction.WAIT_FOR_APPROVAL,
        }:
            next_context_text = next_context or selected or requested or ""
            continuation = (
                "Browser recovery required:\n"
                f"recovery_action: {action.value}\n"
                f"reason: {reason}\n"
                f"current_context: {selected or requested or 'unknown'}\n"
                f"next_context: {next_context_text}\n"
                f"required_next_step: {required_next_step}\n"
                f"forbidden: {', '.join(forbidden)}"
            )
        return BrowserRecoveryDecision(
            action=action,
            reason=reason,
            requested_context=requested,
            selected_context=selected,
            next_context=next_context,
            required_next_step=required_next_step,
            forbidden=forbidden,
            final_message=final_message,
            continuation_message=continuation,
            metadata=merged_metadata,
        )


def _error_code_recovery_template(
    error_code: str,
    event: BrowserTraceEvent | None,
) -> _RecoveryTemplate | None:
    if error_code in _CONTEXT_SWITCH_ERROR_CODES:
        if _is_auto_isolated(event):
            return _RecoveryTemplate(
                BrowserRecoveryAction.RETRY_WITH_CONTEXT,
                error_code,
                "retry_with_user_context",
                ("isolated_fallback",),
                "user",
            )
        return _RecoveryTemplate(
            BrowserRecoveryAction.BLOCKED,
            error_code,
            "ask_user_to_prepare_browser",
        )
    return _ERROR_CODE_RECOVERY_TEMPLATES.get(error_code)


def _session_id(agent: Any) -> str:
    state = getattr(agent, "state", None)
    value = (
        getattr(state, "session_id", "")
        or getattr(agent, "session_id", "")
        or getattr(agent, "_session_id", "")
    )
    return str(value or "default")


def _latest_real_user_index(messages: list[Any]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        msg = messages[index]
        if str(getattr(msg, "role", "") or "") != "user":
            continue
        if _is_loop_continuation(msg):
            continue
        return index
    return -1


def _is_loop_continuation(msg: Any) -> bool:
    metadata = getattr(msg, "metadata", {}) or {}
    tag = metadata.get(QWENPAW_MESSAGE_TAG_KEY)
    if isinstance(tag, (list, tuple, set)):
        return "loop_continuation" in tag
    return str(tag or "") == "loop_continuation"


def _browser_tool_call_ids(messages: Iterable[Any]) -> tuple[str, ...]:
    ids: list[str] = []
    for msg in messages:
        for block in _content_blocks(msg):
            if _block_value(block, "type") not in {"tool_call", "tool_use"}:
                continue
            if _block_value(block, "name") != "browser":
                continue
            tool_call_id = str(_block_value(block, "id") or "")
            if tool_call_id and tool_call_id not in ids:
                ids.append(tool_call_id)
    return tuple(ids)


def _browser_tool_metadata(
    messages: Iterable[Any],
    tool_call_ids: set[str],
) -> tuple[dict[str, Any], ...]:
    metadata_items: list[dict[str, Any]] = []
    if not tool_call_ids:
        return ()
    for msg in messages:
        for block in _content_blocks(msg):
            if _block_value(block, "type") != "tool_result":
                continue
            if str(_block_value(block, "id") or "") not in tool_call_ids:
                continue
            metadata = _extract_metadata(block)
            if metadata:
                metadata_items.append(metadata)
    return tuple(metadata_items)


def _content_blocks(msg: Any) -> tuple[Any, ...]:
    content = getattr(msg, "content", ())
    if isinstance(content, list):
        return tuple(content)
    return ()


def _block_value(block: Any, key: str) -> Any:
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def _extract_metadata(block: Any) -> dict[str, Any]:
    metadata = _block_value(block, "metadata")
    if isinstance(metadata, dict):
        return dict(metadata)
    data = _block_value(block, "data")
    if isinstance(data, dict):
        nested = data.get("metadata")
        if isinstance(nested, dict):
            return dict(nested)
    return {}


def _latest_event(
    events: tuple[BrowserTraceEvent, ...],
) -> BrowserTraceEvent | None:
    return events[-1] if events else None


def _approval_state(evidence: BrowserRequestEvidence) -> str:
    for event in reversed(evidence.trace_events):
        if event.approval_state:
            return event.approval_state
    for metadata in reversed(evidence.tool_metadata):
        state = metadata.get("approval_state")
        if state:
            return str(state)
    return ""


def _approval_metadata(evidence: BrowserRequestEvidence) -> dict[str, Any]:
    for event in reversed(evidence.trace_events):
        value = event.metadata.get("approval_request_id")
        if value:
            return {
                "approval_request_id": value,
                "approval_state": event.approval_state,
            }
    for metadata in reversed(evidence.tool_metadata):
        value = metadata.get("approval_request_id")
        if value:
            return {
                "approval_request_id": value,
                "approval_state": str(metadata.get("approval_state") or ""),
            }
    return {}


def _repeated_approval_domain(
    evidence: BrowserRequestEvidence,
    *,
    threshold: int,
) -> dict[str, Any] | None:
    threshold = max(2, int(threshold))
    pending_events = [
        event
        for event in evidence.trace_events
        if str(event.approval_state or "").lower() == "pending"
    ]
    if len(pending_events) < threshold:
        return None
    latest = pending_events[-1]
    domain = str(latest.domain or "")
    if not domain:
        return None
    count = 0
    for event in reversed(pending_events):
        if str(event.domain or "") != domain:
            break
        count += 1
    if count < threshold:
        return None
    return {
        "domain": domain,
        "count": count,
        "threshold": threshold,
        "approval_state": "pending",
    }


def _latest_error_code(evidence: BrowserRequestEvidence) -> str:
    for event in reversed(evidence.trace_events):
        if event.error_code:
            return classify_browser_error(event.error_code).code.value
    for metadata in reversed(evidence.tool_metadata):
        value = (
            metadata.get("browser_error_code")
            or metadata.get("error_code")
            or metadata.get("code")
        )
        if value:
            return classify_browser_error(str(value)).code.value
    return ""


def _repeated_stale_observation(
    evidence: BrowserRequestEvidence,
    *,
    threshold: int,
) -> dict[str, Any] | None:
    threshold = max(2, int(threshold))
    count = 0
    for event in reversed(evidence.trace_events):
        error_code = classify_browser_error(event.error_code).code.value
        if error_code != BrowserErrorCode.OBSERVATION_STALE.value:
            break
        count += 1
    if count < threshold:
        return None
    return {
        "count": count,
        "threshold": threshold,
        "error_code": BrowserErrorCode.OBSERVATION_STALE.value,
    }


def _repeated_invalid_sdk_usage(
    evidence: BrowserRequestEvidence,
    *,
    threshold: int,
) -> dict[str, Any] | None:
    threshold = max(2, int(threshold))
    count = 0
    for event in reversed(evidence.trace_events):
        if not (
            _metadata_value(
                event.metadata,
                "browser_error_code",
                BrowserErrorCode.INVALID_SDK_USAGE.value,
            )
            or _metadata_value(
                event.metadata,
                "error_code",
                BrowserErrorCode.INVALID_SDK_USAGE.value,
            )
            or _metadata_value(
                event.metadata,
                "error_type",
                "attributeerror",
                "nameerror",
                "typeerror",
            )
        ):
            break
        count += 1
    if count < threshold:
        return None
    return {
        "count": count,
        "threshold": threshold,
        "error_code": BrowserErrorCode.INVALID_SDK_USAGE.value,
    }


def _tab_churn(
    evidence: BrowserRequestEvidence,
    *,
    max_new_tabs: int,
) -> dict[str, Any] | None:
    max_new_tabs = max(1, int(max_new_tabs))
    new_tab_events = [
        event
        for event in evidence.trace_events
        if event.action in {"new", "open_tab"}
        or (
            event.action == "open"
            and event.metadata.get("workspace_reuse") is False
        )
    ]
    tab_ids = {
        str(event.tab_id or "")
        for event in new_tab_events
        if str(event.tab_id or "")
    }
    count = len(tab_ids) or len(new_tab_events)
    if count <= max_new_tabs:
        return None
    return {
        "new_tab_count": count,
        "max_new_tabs_per_request": max_new_tabs,
    }


def _low_information_observation(
    evidence: BrowserRequestEvidence,
    *,
    threshold: int,
) -> dict[str, Any] | None:
    threshold = max(1, int(threshold))
    count = 0
    for event in reversed(evidence.trace_events):
        if not (
            _metadata_flag(event.metadata, "low_information_observation")
            or _metadata_value(event.metadata, "observation_quality", "low")
        ):
            break
        count += 1
    for metadata in reversed(evidence.tool_metadata):
        if not (
            _metadata_flag(metadata, "low_information_observation")
            or _metadata_value(metadata, "observation_quality", "low")
        ):
            continue
        count += 1
    if count <= 0:
        return None
    return {
        "count": count,
        "threshold": threshold,
        "observation_quality": "low",
    }


def _is_auto_isolated(event: BrowserTraceEvent | None) -> bool:
    if event is None:
        return False
    return (
        event.requested_context == "auto"
        and event.selected_context == "isolated"
    )


def _degraded_fallback_stop_required(
    error_code: str,
    event: BrowserTraceEvent | None,
) -> bool:
    return (
        error_code in _DEGRADED_FALLBACK_STOP_CODES
        and _is_degraded_isolated_event(event)
    )


def _degraded_timeout_loop(
    evidence: BrowserRequestEvidence,
    error_code: str,
) -> bool:
    if error_code not in PROTOCOL_TIMEOUT_CODES:
        return False
    timeout_events = [
        event
        for event in evidence.trace_events
        if _is_degraded_isolated_event(event)
        and classify_browser_error(event.error_code).code.value
        in PROTOCOL_TIMEOUT_CODES
    ]
    return len(timeout_events) >= 2


def _degraded_fallback(evidence: BrowserRequestEvidence) -> bool:
    return any(
        _is_degraded_isolated_event(event) for event in evidence.trace_events
    ) or any(
        bool(metadata.get("selected_backend_degraded"))
        or str(metadata.get("fallback_reason") or "")
        == "user_browser_unavailable"
        for metadata in evidence.tool_metadata
    )


def _is_degraded_isolated_event(event: BrowserTraceEvent | None) -> bool:
    if event is None:
        return False
    if not (
        event.requested_context == "auto"
        and event.selected_context == "isolated"
    ):
        return False
    return (
        event.metadata.get("selected_backend_degraded") is True
        or str(event.metadata.get("fallback_reason") or "")
        == "user_browser_unavailable"
        or _is_auto_isolated(event)
    )


def _degraded_fallback_metadata(
    event: BrowserTraceEvent | None,
) -> dict[str, Any]:
    metadata = dict(event.metadata if event is not None else {})
    metadata.setdefault("selected_backend_degraded", True)
    metadata.setdefault("fallback_reason", "user_browser_unavailable")
    metadata.setdefault(
        "recommended_action",
        "install_or_reconnect_chrome_extension",
    )
    metadata.setdefault(
        "recovery_hint",
        "Install or reconnect the Chrome Extension before retrying Browser "
        "auto routing.",
    )
    return metadata


def _no_progress(evidence: BrowserRequestEvidence) -> bool:
    for metadata in reversed(evidence.tool_metadata):
        decision = metadata.get("progress_decision")
        if isinstance(decision, dict) and decision.get("blocked") is True:
            return str(decision.get("reason") or "") == "no_progress"
    return False


def _observation_enrichment_denied(
    evidence: BrowserRequestEvidence,
) -> bool:
    return any(
        _metadata_flag(event.metadata, "observation_enrichment_denied")
        or _metadata_value(
            event.metadata,
            "degradation_code",
            BrowserErrorCode.OBSERVATION_ENRICHMENT_DENIED.value,
        )
        or _metadata_value(
            event.metadata,
            "observation_degradation",
            BrowserErrorCode.OBSERVATION_ENRICHMENT_DENIED.value,
        )
        for event in reversed(evidence.trace_events)
    ) or any(
        _metadata_flag(metadata, "observation_enrichment_denied")
        or _metadata_value(
            metadata,
            "degradation_code",
            BrowserErrorCode.OBSERVATION_ENRICHMENT_DENIED.value,
        )
        or _metadata_value(
            metadata,
            "observation_degradation",
            BrowserErrorCode.OBSERVATION_ENRICHMENT_DENIED.value,
        )
        for metadata in reversed(evidence.tool_metadata)
    )


def _invalid_sdk_usage(evidence: BrowserRequestEvidence) -> bool:
    invalid_error_types = {"attributeerror", "nameerror", "typeerror"}
    return any(
        _metadata_value(
            event.metadata,
            "browser_error_code",
            BrowserErrorCode.INVALID_SDK_USAGE.value,
        )
        or _metadata_value(
            event.metadata,
            "error_code",
            BrowserErrorCode.INVALID_SDK_USAGE.value,
        )
        or _metadata_value(
            event.metadata,
            "error_type",
            *invalid_error_types,
        )
        for event in reversed(evidence.trace_events)
    ) or any(
        _metadata_value(
            metadata,
            "browser_error_code",
            BrowserErrorCode.INVALID_SDK_USAGE.value,
        )
        or _metadata_value(
            metadata,
            "error_code",
            BrowserErrorCode.INVALID_SDK_USAGE.value,
        )
        or _metadata_value(metadata, "error_type", *invalid_error_types)
        for metadata in reversed(evidence.tool_metadata)
    )


def _click_without_navigation(evidence: BrowserRequestEvidence) -> bool:
    return any(
        event.action == "click"
        and event.status == "ok"
        and _metadata_flag(event.metadata, "expected_navigation")
        and _metadata_value(event.metadata, "navigation_occurred", "false")
        for event in reversed(evidence.trace_events)
    ) or any(
        _metadata_flag(metadata, "expected_navigation")
        and _metadata_value(metadata, "navigation_occurred", "false")
        for metadata in reversed(evidence.tool_metadata)
    )


def _metadata_flag(metadata: dict[str, Any], key: str) -> bool:
    return metadata.get(key) is True


def _metadata_value(
    metadata: dict[str, Any],
    key: str,
    *expected: str,
) -> bool:
    value = metadata.get(key)
    if value is None:
        return False
    normalized = str(value).strip().casefold().replace("-", "_")
    return normalized in {item.casefold() for item in expected}


__all__ = [
    "BrowserProductPolicy",
    "BrowserRecoveryAction",
    "BrowserRecoveryDecision",
    "BrowserRecoveryPolicy",
    "BrowserRequestEvidence",
    "collect_browser_request_evidence",
]
