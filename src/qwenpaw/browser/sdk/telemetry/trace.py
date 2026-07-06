# -*- coding: utf-8 -*-
"""In-memory Browser SDK execution trace store."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
import subprocess
from threading import RLock
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

_DEFAULT_MAX_EVENTS_PER_SESSION = 200
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_TOKENS = (
    "authorization",
    "cookie",
    "credential",
    "otp",
    "password",
    "secret",
    "token",
    "value",
)
V9_REQUIRED_TRACE_FIELDS = (
    "event_id",
    "session_id",
    "tool_call_id",
    "backend_id",
    "requested_context",
    "selected_context",
    "phase",
    "action",
    "tab_id",
    "domain",
    "status",
    "approval_state",
    "freshness_marker",
)
TAB_OWNERSHIP_STATES = (
    "owned",
    "borrowed",
    "protected",
    "orphaned",
    "released",
)


@dataclass(frozen=True)
class BrowserTraceEvent:
    """Structured evidence for one Browser SDK operation."""

    event_id: str
    session_id: str
    tool_call_id: str = ""
    backend_id: str = ""
    requested_context: str = ""
    selected_context: str = ""
    phase: str = ""
    action: str = ""
    tab_id: str = ""
    url: str = ""
    domain: str = ""
    status: str = ""
    duration_ms: float = 0.0
    error_code: str = ""
    approval_state: str = ""
    freshness_marker: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe redacted representation."""
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "backend_id": self.backend_id,
            "requested_context": self.requested_context,
            "selected_context": self.selected_context,
            "phase": self.phase,
            "action": self.action,
            "tab_id": self.tab_id,
            "url": self.url,
            "domain": self.domain,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "approval_state": self.approval_state,
            "freshness_marker": self.freshness_marker,
            "metadata": _redact(self.metadata),
        }


class BrowserTraceStore:
    """Bounded per-session in-memory trace event store."""

    def __init__(
        self,
        *,
        max_events_per_session: int = _DEFAULT_MAX_EVENTS_PER_SESSION,
    ) -> None:
        self._max_events_per_session = max(1, int(max_events_per_session))
        self._events: dict[str, deque[BrowserTraceEvent]] = defaultdict(
            lambda: deque(maxlen=self._max_events_per_session),
        )
        self._lock = RLock()

    def record(self, event: BrowserTraceEvent) -> BrowserTraceEvent:
        """Record an event after redacting sensitive metadata."""
        redacted = replace(event, metadata=_redact(event.metadata))
        with self._lock:
            self._events[redacted.session_id].append(redacted)
        return redacted

    def list(
        self,
        session_id: str | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[BrowserTraceEvent, ...]:
        """Return trace events, optionally scoped to one session."""
        with self._lock:
            if session_id:
                events = list(self._events.get(session_id, ()))
            else:
                events = [
                    event
                    for session_events in self._events.values()
                    for event in session_events
                ]
        if limit is not None and limit >= 0:
            limit_value = int(limit)
            events = events[-limit_value:] if limit_value else []
        return tuple(events)

    def clear(self) -> None:
        """Clear all recorded trace events."""
        with self._lock:
            self._events.clear()


_default_trace_store = BrowserTraceStore()


def get_browser_trace_store() -> BrowserTraceStore:
    """Return the process-local Browser SDK trace store."""
    return _default_trace_store


def reset_browser_trace_store_for_tests() -> None:
    """Reset the process-local trace store for deterministic tests."""
    _default_trace_store.clear()


def record_browser_trace_event(
    *,
    session_id: str,
    phase: str,
    backend_id: str = "",
    requested_context: str = "",
    selected_context: str = "",
    action: str = "",
    tab_id: str = "",
    url: str = "",
    domain: str = "",
    status: str = "",
    duration_ms: float = 0.0,
    error_code: str = "",
    approval_state: str = "",
    freshness_marker: str = "",
    metadata: dict[str, Any] | None = None,
) -> BrowserTraceEvent:
    """Record one Browser SDK trace event in the default store."""
    safe_metadata = dict(metadata or {})
    current_tool_call_id = _current_tool_call_id()
    effective_url = str(url or "")
    event = BrowserTraceEvent(
        event_id=uuid4().hex,
        session_id=str(session_id or "default"),
        tool_call_id=str(
            current_tool_call_id
            or safe_metadata.get("tool_call_id")
            or "current_browser_tool",
        ),
        backend_id=str(backend_id or ""),
        requested_context=str(requested_context or ""),
        selected_context=str(selected_context or ""),
        phase=str(phase or ""),
        action=str(action or phase or "browser"),
        tab_id=str(tab_id or "__browser__"),
        url=effective_url,
        domain=str(
            domain or _domain_from_url(effective_url) or "local_runtime",
        ),
        status=str(status or "ok"),
        duration_ms=float(duration_ms or 0.0),
        error_code=str(error_code or ""),
        approval_state=str(
            approval_state
            or safe_metadata.get("approval_state")
            or "not_required",
        ),
        freshness_marker=str(freshness_marker or _runtime_freshness_marker()),
        metadata=safe_metadata,
    )
    return get_browser_trace_store().record(event)


def validate_browser_trace_event(
    event: BrowserTraceEvent | dict[str, Any],
) -> dict[str, Any]:
    """Return V9 trace completeness evidence for one event."""
    payload = (
        event.to_dict() if isinstance(event, BrowserTraceEvent) else event
    )
    missing = [
        field
        for field in V9_REQUIRED_TRACE_FIELDS
        if not _trace_field_present(payload, field)
    ]
    return {
        "ok": not missing,
        "event_id": str(payload.get("event_id") or ""),
        "missing_fields": missing,
    }


def validate_browser_trace_events(
    events: list[dict[str, Any]] | tuple[BrowserTraceEvent, ...],
) -> dict[str, Any]:
    """Return aggregate V9 trace completeness evidence."""
    results = [validate_browser_trace_event(event) for event in events]
    missing = {
        str(result.get("event_id") or f"event_{index}"): list(
            result.get("missing_fields") or [],
        )
        for index, result in enumerate(results)
        if result.get("missing_fields")
    }
    return {
        "ok": not missing,
        "event_count": len(results),
        "missing_fields": missing,
    }


def summarize_browser_tab_ownership(
    events: list[dict[str, Any]] | tuple[BrowserTraceEvent, ...],
) -> dict[str, Any]:
    """Summarize tab ownership evidence carried by trace metadata."""
    counts = {state: 0 for state in TAB_OWNERSHIP_STATES}
    transition_count = 0
    latest_by_tab: dict[str, str] = {}

    for event in events:
        payload = (
            event.to_dict() if isinstance(event, BrowserTraceEvent) else event
        )
        metadata = payload.get("metadata") or {}
        if not isinstance(metadata, dict):
            continue
        ownership_state = _trace_ownership_state(metadata)
        if not ownership_state:
            continue
        counts[ownership_state] = counts.get(ownership_state, 0) + 1
        tab_id = str(payload.get("tab_id") or "")
        if tab_id:
            latest_by_tab[tab_id] = ownership_state
        if (
            metadata.get("ownership_state_before") is not None
            or metadata.get("ownership_state_after") is not None
        ):
            transition_count += 1

    return {
        "counts": counts,
        "transition_count": transition_count,
        "latest_by_tab": latest_by_tab,
    }


def _trace_ownership_state(metadata: dict[str, Any]) -> str:
    for key in ("ownership_state_after", "ownership_state", "ownership"):
        value = str(metadata.get(key) or "").strip().lower()
        if value in TAB_OWNERSHIP_STATES:
            return value
    return ""


def _current_tool_call_id() -> str:
    try:
        from qwenpaw.tool_calls import get_call_context

        context = get_call_context()
        return str(getattr(context, "tool_call_id", "") or "")
    except Exception:  # pragma: no cover - defensive runtime fallback
        return ""


def _trace_field_present(payload: dict[str, Any], field_name: str) -> bool:
    if field_name == "error_code":
        return field_name in payload
    value = payload.get(field_name)
    if isinstance(value, str):
        return bool(value.strip())
    if field_name == "duration_ms":
        return value is not None
    return bool(value)


@lru_cache(maxsize=1)
def _runtime_freshness_marker() -> str:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "--short", "HEAD"),
            cwd=Path(__file__).resolve().parents[3],
            check=False,
            capture_output=True,
            text=True,
            timeout=0.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "commit:unknown"
    commit = result.stdout.strip() if result.returncode == 0 else ""
    return f"commit:{commit or 'unknown'}"


def _domain_from_url(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(
                token in key_text.casefold() for token in _SENSITIVE_KEY_TOKENS
            ):
                redacted[key_text] = _REDACTED
            else:
                redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


__all__ = [
    "BrowserTraceEvent",
    "BrowserTraceStore",
    "get_browser_trace_store",
    "record_browser_trace_event",
    "reset_browser_trace_store_for_tests",
    "summarize_browser_tab_ownership",
    "validate_browser_trace_event",
    "validate_browser_trace_events",
]
