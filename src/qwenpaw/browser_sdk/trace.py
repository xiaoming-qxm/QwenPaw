# -*- coding: utf-8 -*-
"""In-memory Browser SDK execution trace store."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
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
            events = events[-limit:] if limit else []
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
    metadata: dict[str, Any] | None = None,
) -> BrowserTraceEvent:
    """Record one Browser SDK trace event in the default store."""
    event = BrowserTraceEvent(
        event_id=uuid4().hex,
        session_id=str(session_id or "default"),
        tool_call_id=_current_tool_call_id(),
        backend_id=str(backend_id or ""),
        requested_context=str(requested_context or ""),
        selected_context=str(selected_context or ""),
        phase=str(phase or ""),
        action=str(action or ""),
        tab_id=str(tab_id or ""),
        url=str(url or ""),
        domain=str(domain or _domain_from_url(url)),
        status=str(status or ""),
        duration_ms=float(duration_ms or 0.0),
        error_code=str(error_code or ""),
        approval_state=str(approval_state or ""),
        metadata=dict(metadata or {}),
    )
    return get_browser_trace_store().record(event)


def _current_tool_call_id() -> str:
    try:
        from qwenpaw.tool_calls import get_call_context

        context = get_call_context()
        return str(getattr(context, "tool_call_id", "") or "")
    except Exception:  # pragma: no cover - defensive runtime fallback
        return ""


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
            if any(token in key_text.casefold() for token in _SENSITIVE_KEY_TOKENS):
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
]
