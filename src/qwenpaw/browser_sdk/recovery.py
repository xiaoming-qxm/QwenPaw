# -*- coding: utf-8 -*-
"""Browser SDK recovery evidence and deterministic decisions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from qwenpaw.constant import QWENPAW_MESSAGE_TAG_KEY

from .error_codes import BrowserErrorCode
from .trace import (
    BrowserTraceEvent,
    BrowserTraceStore,
    get_browser_trace_store,
)


class BrowserRecoveryAction(StrEnum):
    """Structured Browser recovery action consumed by BrowserGate."""

    NO_OP = "no_op"
    CONTINUE = "continue"
    RETRY_WITH_CONTEXT = "retry_with_context"
    WAIT_FOR_APPROVAL = "wait_for_approval"
    BLOCKED = "blocked"
    FAILED = "failed"


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
        context[latest_user_index + 1 :]
        if latest_user_index >= 0
        else context
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


class BrowserRecoveryPolicy:
    """Convert Browser evidence into structured recovery decisions."""

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
        approval = _approval_state(evidence)
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
        if error_code == BrowserErrorCode.APPROVAL_DENIED.value:
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason="approval_denied",
                event=event,
                required_next_step="stop_browser_action",
            )
        if error_code == BrowserErrorCode.APPROVAL_REQUIRED.value:
            return self._decision(
                BrowserRecoveryAction.WAIT_FOR_APPROVAL,
                reason="approval_pending",
                event=event,
                required_next_step="wait_for_user_approval",
                metadata=_approval_metadata(evidence),
            )
        if error_code == BrowserErrorCode.BRIDGE_DISCONNECTED.value:
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason="bridge_disconnected",
                event=event,
                required_next_step="reconnect_browser_bridge",
            )
        if error_code in {
            BrowserErrorCode.LOGIN_REQUIRED.value,
            BrowserErrorCode.CAPTCHA_OR_RISK_CONTROL.value,
        }:
            if _is_auto_isolated(event):
                return self._decision(
                    BrowserRecoveryAction.RETRY_WITH_CONTEXT,
                    reason=error_code,
                    event=event,
                    next_context="user",
                    required_next_step="retry_with_user_context",
                    forbidden=("isolated_fallback",),
                )
            return self._decision(
                BrowserRecoveryAction.BLOCKED,
                reason=error_code,
                event=event,
                required_next_step="ask_user_to_prepare_browser",
            )
        if error_code == BrowserErrorCode.OBSERVATION_STALE.value:
            return self._decision(
                BrowserRecoveryAction.CONTINUE,
                reason="fresh_observation_required",
                event=event,
                required_next_step="tab.snapshot()",
                forbidden=("repeat_mutation_without_observation",),
            )
        if error_code == BrowserErrorCode.CAPABILITY_MISSING.value:
            return self._decision(
                BrowserRecoveryAction.FAILED,
                reason="capability_missing",
                event=event,
                required_next_step="use_generic_browser_capability",
            )
        if error_code == BrowserErrorCode.NETWORK_TIMEOUT.value:
            return self._decision(
                BrowserRecoveryAction.CONTINUE,
                reason="network_timeout",
                event=event,
                required_next_step="retry_after_page_settles",
            )
        if _no_progress(evidence):
            return self._decision(
                BrowserRecoveryAction.CONTINUE,
                reason="no_progress",
                event=event,
                required_next_step="change_strategy_or_observe",
                forbidden=("repeat_identical_action",),
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
        final_message = ""
        if action in {
            BrowserRecoveryAction.BLOCKED,
            BrowserRecoveryAction.FAILED,
        }:
            final_message = (
                "Browser task blocked:\n"
                f"reason: {reason}\n"
                f"context: {selected or requested or 'unknown'}\n"
                f"backend: {backend or 'unknown'}\n"
                f"required_user_action: {required_next_step or 'none'}\n"
                f"status: {action.value}"
            )
        continuation = ""
        if action in {
            BrowserRecoveryAction.CONTINUE,
            BrowserRecoveryAction.RETRY_WITH_CONTEXT,
            BrowserRecoveryAction.WAIT_FOR_APPROVAL,
        }:
            continuation = (
                "Browser recovery required:\n"
                f"recovery_action: {action.value}\n"
                f"reason: {reason}\n"
                f"current_context: {selected or requested or 'unknown'}\n"
                f"next_context: {next_context or selected or requested or ''}\n"
                f"required_next_step: {required_next_step}\n"
                f"forbidden: {', '.join(forbidden)}"
            )
        merged_metadata = dict(metadata or {})
        if backend:
            merged_metadata.setdefault("backend_id", backend)
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


def _latest_error_code(evidence: BrowserRequestEvidence) -> str:
    for event in reversed(evidence.trace_events):
        if event.error_code:
            return event.error_code
    for metadata in reversed(evidence.tool_metadata):
        value = (
            metadata.get("browser_error_code")
            or metadata.get("error_code")
            or metadata.get("code")
        )
        if value:
            return str(value)
    return ""


def _is_auto_isolated(event: BrowserTraceEvent | None) -> bool:
    if event is None:
        return False
    return event.requested_context == "auto" and event.selected_context == "isolated"


def _no_progress(evidence: BrowserRequestEvidence) -> bool:
    for metadata in reversed(evidence.tool_metadata):
        decision = metadata.get("progress_decision")
        if isinstance(decision, dict) and decision.get("blocked") is True:
            return str(decision.get("reason") or "") == "no_progress"
    return False


__all__ = [
    "BrowserRecoveryAction",
    "BrowserRecoveryDecision",
    "BrowserRecoveryPolicy",
    "BrowserRequestEvidence",
    "collect_browser_request_evidence",
]
