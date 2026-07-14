# -*- coding: utf-8 -*-
"""Scenario matrix definitions for Browser product verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BrowserProductScenario:
    """One Browser product verification scenario definition."""

    scenario_id: str
    context: str
    required_backend: str
    live_opt_in: bool = False
    expectations: dict[str, Any] = field(default_factory=dict)


REQUIRED_TRACE_FIELDS: tuple[str, ...] = (
    "backend_id",
    "context",
    "action",
    "status",
    "duration_ms",
    "error_code",
)


def _scenario_expectations(
    *,
    fresh_observe_after_mutation: bool = False,
    max_repeated_no_progress_actions: int = 3,
    requires_confirmation: bool = False,
    reconnect_delta_required: bool = False,
) -> dict[str, Any]:
    return {
        "trace_required_fields": REQUIRED_TRACE_FIELDS,
        "forbidden_tools": (
            "legacy_browser_tool",
            "desktop_capture_tool",
            "video_view_tool",
        ),
        "max_repeated_no_progress_actions": max_repeated_no_progress_actions,
        "fresh_observe_after_mutation": fresh_observe_after_mutation,
        "cleanup": {
            "residual_tab_count": 0,
            "kernel_idle_count": 0,
            "cleanup_trace_required": True,
        },
        "requires_confirmation": requires_confirmation,
        "reconnect_delta_required": reconnect_delta_required,
    }


def default_scenarios(
    *,
    include_live_taobao: bool = False,
) -> list[BrowserProductScenario]:
    """Return the default-safe Browser product scenario matrix."""
    scenarios = [
        BrowserProductScenario(
            "public-search-isolated",
            context="isolated",
            required_backend="isolated.playwright",
            expectations=_scenario_expectations(),
        ),
        BrowserProductScenario(
            "user-observation",
            context="user",
            required_backend="user.chrome_extension",
            expectations=_scenario_expectations(),
        ),
        BrowserProductScenario(
            "local-cart-approval",
            context="isolated",
            required_backend="isolated.playwright",
            expectations=_scenario_expectations(
                fresh_observe_after_mutation=True,
            ),
        ),
        BrowserProductScenario(
            "local-cart-auto",
            context="isolated",
            required_backend="isolated.playwright",
            expectations=_scenario_expectations(
                fresh_observe_after_mutation=True,
            ),
        ),
        BrowserProductScenario(
            "complex-isolated-fixture",
            context="isolated",
            required_backend="isolated.playwright",
            expectations=_scenario_expectations(
                max_repeated_no_progress_actions=5,
            ),
        ),
        BrowserProductScenario(
            "complex-user-fixture",
            context="user",
            required_backend="user.chrome_extension",
            expectations=_scenario_expectations(
                max_repeated_no_progress_actions=5,
            ),
        ),
        BrowserProductScenario(
            "bridge-disconnect",
            context="user",
            required_backend="user.chrome_extension",
            expectations=_scenario_expectations(
                reconnect_delta_required=True,
            ),
        ),
        BrowserProductScenario(
            "cleanup-cancel",
            context="user",
            required_backend="user.chrome_extension",
            expectations=_scenario_expectations(),
        ),
    ]
    if include_live_taobao:
        scenarios.append(
            BrowserProductScenario(
                "live-taobao-opt-in",
                context="user",
                required_backend="user.chrome_extension",
                live_opt_in=True,
                expectations=_scenario_expectations(
                    fresh_observe_after_mutation=True,
                    requires_confirmation=True,
                ),
            ),
        )
    return scenarios


def validate_trace_contract(
    trace_events: tuple[Any, ...] | list[Any],
) -> dict[str, Any]:
    """Validate that Browser SDK trace evidence exposes product fields."""
    missing_fields: list[str] = []
    for field_name in REQUIRED_TRACE_FIELDS:
        if any(
            not _trace_field_present(_event_payload(event), field_name)
            for event in trace_events
        ):
            missing_fields.append(field_name)
    return {
        "status": "failed" if missing_fields else "passed",
        "missing_fields": missing_fields,
        "required_fields": list(REQUIRED_TRACE_FIELDS),
        "event_count": len(trace_events),
    }


def evaluate_lifecycle_gate(
    trace_events: tuple[Any, ...] | list[Any],
    *,
    terminal_reasons: tuple[str, ...],
) -> dict[str, Any]:
    """Evaluate lifecycle cleanup evidence for terminal Browser paths."""
    events = [_event_payload(event) for event in trace_events]
    cleanup_events = [
        event
        for event in events
        if event.get("phase") == "cleanup"
        and event.get("action") == "chrome_lifecycle_cleanup"
    ]
    cleanup_start_events = [
        event
        for event in events
        if event.get("phase") == "cleanup"
        and event.get("action") == "chrome_lifecycle_cleanup_start"
    ]
    kernel_sweep_events = [
        event
        for event in events
        if event.get("phase") == "cleanup"
        and event.get("action") == "browser_kernel_idle_sweep"
    ]
    expected = tuple(str(reason) for reason in terminal_reasons)
    missing = [
        reason
        for reason in expected
        if not _has_cleanup_reason(cleanup_start_events, reason)
        or not _has_cleanup_reason(cleanup_events, reason, status="ok")
        or not _has_cleanup_reason(kernel_sweep_events, reason, status="ok")
    ]
    residual_tab_count = max(
        [_residual_tabs(event) for event in cleanup_events] or [0],
    )
    kernel_idle_count = max(
        [
            _metadata_int(event, "kernel_idle_count")
            for event in kernel_sweep_events
        ]
        or [0],
    )
    failure_category = ""
    if missing:
        failure_category = "missing_lifecycle_trace"
    elif residual_tab_count:
        failure_category = "residual_lifecycle_state"
    elif kernel_idle_count:
        failure_category = "kernel_idle_residue"

    return {
        "status": "failed" if failure_category else "passed",
        "failure_category": failure_category,
        "recovery_hint": _lifecycle_recovery_hint(failure_category),
        "cleanup_result": {
            "terminal_reasons": list(expected),
            "missing_terminal_reasons": missing,
            "residual_tab_count": residual_tab_count,
            "kernel_idle_count": kernel_idle_count,
            "cleanup_trace_present": bool(cleanup_events),
            "cleanup_start_trace_present": bool(cleanup_start_events),
            "kernel_sweep_trace_present": bool(kernel_sweep_events),
        },
    }


def evaluate_reconnect_evidence(
    *,
    before_count: int,
    after_disconnect_count: int,
    after_reconnect_count: int,
    trace_events: tuple[Any, ...] | list[Any],
) -> dict[str, Any]:
    """Evaluate controlled bridge reconnect event-count evidence."""
    events = [_event_payload(event) for event in trace_events]
    lifecycle_phases = sorted(
        {
            str(event.get("action") or "")
            for event in events
            if event.get("phase") == "bridge_lifecycle"
            and event.get("action") in {"connect", "reconnect"}
        },
    )
    reconnect_delta = max(0, int(after_reconnect_count) - int(before_count))
    disconnect_delta = max(
        0,
        int(after_disconnect_count) - int(before_count),
    )
    failure_category = ""
    if reconnect_delta <= 0:
        failure_category = "missing_reconnect_delta"
    elif "reconnect" not in lifecycle_phases:
        failure_category = "missing_reconnect_trace"

    return {
        "status": "failed" if failure_category else "passed",
        "failure_category": failure_category,
        "recovery_hint": (
            "record bridge lifecycle connect/reconnect traces and compare event counts"
            if failure_category
            else ""
        ),
        "reconnect_delta": reconnect_delta,
        "disconnect_delta": disconnect_delta,
        "before_count": int(before_count),
        "after_disconnect_count": int(after_disconnect_count),
        "after_reconnect_count": int(after_reconnect_count),
        "lifecycle_phases": lifecycle_phases,
    }


def _event_payload(event: Any) -> dict[str, Any]:
    if hasattr(event, "to_dict"):
        payload = event.to_dict()
    elif isinstance(event, dict):
        payload = dict(event)
    else:
        payload = {}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        payload["metadata"] = {}
    return payload


def _trace_field_present(event: dict[str, Any], field_name: str) -> bool:
    if field_name == "context":
        return any(
            key in event
            for key in ("context", "requested_context", "selected_context")
        )
    return field_name in event


def _has_cleanup_reason(
    events: list[dict[str, Any]],
    reason: str,
    *,
    status: str = "",
) -> bool:
    for event in events:
        if status and str(event.get("status") or "") != status:
            continue
        if (
            str(event.get("metadata", {}).get("cleanup_reason") or "")
            == reason
        ):
            return True
    return False


def _residual_tabs(event: dict[str, Any]) -> int:
    return _metadata_int(event, "remaining_orphaned_tabs") + _metadata_int(
        event,
        "owned_tabs_remaining",
    )


def _metadata_int(event: dict[str, Any], key: str) -> int:
    try:
        return int(event.get("metadata", {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _lifecycle_recovery_hint(failure_category: str) -> str:
    if failure_category == "missing_lifecycle_trace":
        return "ensure cleanup start, cleanup success, and kernel sweep traces are emitted"
    if failure_category == "residual_lifecycle_state":
        return "release request-owned Browser tabs before terminal response"
    if failure_category == "kernel_idle_residue":
        return "reset request kernels and sweep idle Browser kernels"
    return ""


__all__ = [
    "BrowserProductScenario",
    "REQUIRED_TRACE_FIELDS",
    "default_scenarios",
    "evaluate_lifecycle_gate",
    "evaluate_reconnect_evidence",
    "validate_trace_contract",
]
