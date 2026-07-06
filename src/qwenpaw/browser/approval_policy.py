# -*- coding: utf-8 -*-
"""QwenPaw approval-backed Browser SDK policy."""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from typing import Any
from urllib.parse import urlparse

from qwenpaw.app.approvals.models import ApprovalRequestSummary
from qwenpaw.browser.sdk.governance.error_codes import BrowserErrorCode
from qwenpaw.browser.sdk.telemetry.trace import record_browser_trace_event
from qwenpaw.browser.sdk.primitives.types import (
    BrowserActionRequest,
    BrowserContextRequest,
    BrowserPolicyDecision,
)
from qwenpaw.constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
from qwenpaw.security.tool_guard.approval import ApprovalDecision

_DEFAULT_CACHE_TTL_SECONDS = 120.0
_REDACTED = "[REDACTED]"
_REDACT_KEYS = {
    "credential",
    "otp",
    "password",
    "secret",
    "token",
    "value",
}


class QwenPawBrowserApprovalPolicy:
    """Route sensitive Browser SDK actions through QwenPaw approvals."""

    def __init__(
        self,
        *,
        approval_service: Any | None = None,
        now: Callable[[], float] | None = None,
        cache_ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._approval_service = approval_service
        self._now = now or time.time
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self._approved_cache: dict[tuple[Hashable, ...], float] = {}

    def allow_context_acquisition(
        self,
        request: BrowserContextRequest,
    ) -> BrowserPolicyDecision:
        del request
        return BrowserPolicyDecision(allowed=True, reason="allowed")

    async def allow_action(
        self,
        request: BrowserActionRequest,
    ) -> BrowserPolicyDecision:
        preapproved = _preapproved_decision(request)
        if preapproved is not None:
            return preapproved

        context = _approval_context(request)
        cache_key = _approval_cache_key(request, context["root_session_id"])
        if self._cache_hit(cache_key):
            return BrowserPolicyDecision(
                allowed=True,
                reason="browser_action_approval_cache",
                metadata={"approval_cache": "hit"},
            )

        summary = ApprovalRequestSummary(
            source_type="browser_sdk_action",
            name="browser",
            severity=_severity(request),
            findings_count=1,
            result_summary=_approval_summary(request),
            payload=_approval_payload(request),
        )
        request_id = ""
        timeout_seconds = _approval_timeout_seconds()
        try:
            service = self._service()
            pending = await service.create_pending_summary(
                session_id=context["session_id"],
                root_session_id=context["root_session_id"],
                owner_agent_id=context["owner_agent_id"],
                user_id=context["user_id"],
                channel=context["channel"],
                agent_id=context["agent_id"],
                summary=summary,
                timeout_seconds=timeout_seconds,
                extra={
                    "tool_call": {
                        "id": context["tool_call_id"],
                        "name": "browser",
                        "input": summary.payload,
                    },
                },
            )
            request_id = str(pending.request_id)
            _record_approval_trace(
                request,
                approval_state="pending",
                approval_request_id=request_id,
                status="pending",
            )
            decision = await service.wait_for_approval(
                pending.request_id,
                timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            _record_approval_trace(
                request,
                approval_state="error",
                approval_request_id=request_id,
                status="error",
                error_code=BrowserErrorCode.APPROVAL_DENIED.value,
                metadata={"error": str(exc)},
            )
            return BrowserPolicyDecision(
                allowed=False,
                reason="browser_action_approval_error",
                metadata=_approval_decision_metadata(
                    "error",
                    request_id,
                    {"error": str(exc)},
                ),
            )

        if decision == ApprovalDecision.APPROVED:
            self._approved_cache[cache_key] = (
                self._now() + self._cache_ttl_seconds
            )
            _record_approval_trace(
                request,
                approval_state="approved",
                approval_request_id=request_id,
                status="ok",
            )
            return BrowserPolicyDecision(
                allowed=True,
                reason="browser_action_approved",
                metadata=_approval_decision_metadata(
                    "approved",
                    request_id,
                ),
            )
        if decision == ApprovalDecision.TIMEOUT:
            _record_approval_trace(
                request,
                approval_state="timeout",
                approval_request_id=request_id,
                status="blocked",
                error_code=BrowserErrorCode.APPROVAL_DENIED.value,
            )
            return BrowserPolicyDecision(
                allowed=False,
                reason="browser_action_approval_timeout",
                metadata=_approval_decision_metadata(
                    "timeout",
                    request_id,
                ),
            )
        _record_approval_trace(
            request,
            approval_state="denied",
            approval_request_id=request_id,
            status="blocked",
            error_code=BrowserErrorCode.APPROVAL_DENIED.value,
        )
        return BrowserPolicyDecision(
            allowed=False,
            reason="browser_action_denied",
            metadata=_approval_decision_metadata("denied", request_id),
        )

    def _service(self) -> Any:
        if self._approval_service is not None:
            return self._approval_service
        from qwenpaw.app.approvals import get_approval_service

        return get_approval_service()

    def _cache_hit(self, key: tuple[Hashable, ...]) -> bool:
        expires_at = self._approved_cache.get(key)
        if expires_at is None:
            return False
        if expires_at <= self._now():
            self._approved_cache.pop(key, None)
            return False
        return True


def _approval_context(request: BrowserActionRequest) -> dict[str, str]:
    call_context = _call_context()
    session_id = (
        str(getattr(call_context, "session_id", "") or "")
        or request.session_id
        or "default"
    )
    root_session_id = (
        str(getattr(call_context, "root_session_id", "") or "")
        or _agent_context_value("get_current_root_session_id")
        or session_id
    )
    agent_id = (
        str(getattr(call_context, "agent_id", "") or "")
        or _agent_context_value("get_current_agent_id")
        or "unknown"
    )
    return {
        "session_id": session_id,
        "root_session_id": root_session_id,
        "owner_agent_id": agent_id,
        "user_id": _agent_context_value("get_current_user_id"),
        "channel": _agent_context_value("get_current_channel"),
        "agent_id": agent_id,
        "tool_call_id": str(getattr(call_context, "tool_call_id", "") or ""),
    }


def _call_context() -> Any | None:
    try:
        from qwenpaw.tool_calls import get_call_context

        return get_call_context()
    except Exception:  # pragma: no cover - defensive runtime fallback
        return None


def _preapproved_decision(
    request: BrowserActionRequest,
) -> BrowserPolicyDecision | None:
    if not request.sensitive:
        return BrowserPolicyDecision(allowed=True, reason="allowed")
    if _request_approval_level() == "off":
        return BrowserPolicyDecision(
            allowed=True,
            reason="browser_action_approval_level_off",
            metadata={"approval_level": "OFF"},
        )
    return None


def _request_approval_level() -> str:
    call_context = _call_context()
    request_context = getattr(call_context, "request_context", {}) or {}
    if not isinstance(request_context, dict):
        return ""
    return str(request_context.get("approval_level") or "").strip().casefold()


def _approval_timeout_seconds() -> float:
    call_context = _call_context()
    request_context = getattr(call_context, "request_context", {}) or {}
    if isinstance(request_context, dict):
        try:
            value = float(request_context.get("approval_timeout_seconds") or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return min(value, float(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS))
    return float(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS)


def _agent_context_value(function_name: str) -> str:
    try:
        from qwenpaw.app import agent_context

        value = getattr(agent_context, function_name)()
        return str(value or "")
    except Exception:  # pragma: no cover - defensive runtime fallback
        return ""


def _approval_payload(request: BrowserActionRequest) -> dict[str, Any]:
    metadata = dict(request.metadata)
    risk = request.risk
    return {
        "tab_id": str(metadata.get("tab_id") or ""),
        "url": str(metadata.get("url") or ""),
        "domain": _domain(metadata),
        "title": str(metadata.get("title") or ""),
        "action": request.action,
        "risk": {
            "sensitive": bool(risk.sensitive) if risk else request.sensitive,
            "level": str(risk.level) if risk else "unknown",
            "kind": str(risk.kind) if risk else "unknown_sensitive",
            "reason": str(risk.reason) if risk else "",
            "matched": list(risk.matched) if risk else [],
        },
        "kwargs": _redact(metadata),
    }


def _approval_summary(request: BrowserActionRequest) -> str:
    payload = _approval_payload(request)
    risk = payload["risk"]
    domain = payload["domain"] or "unknown domain"
    return (
        "Browser SDK wants to run a sensitive Chrome action "
        f"`{request.action}` on {domain} ({risk['kind']})."
    )


def _approval_cache_key(
    request: BrowserActionRequest,
    root_session_id: str,
) -> tuple[Hashable, ...]:
    risk_kind = str(request.risk.kind) if request.risk else "unknown_sensitive"
    return (
        root_session_id,
        _approval_domain_scope(request.metadata),
        risk_kind,
        str(request.action or "").strip().casefold(),
    )


def _record_approval_trace(
    request: BrowserActionRequest,
    *,
    approval_state: str,
    approval_request_id: str,
    status: str,
    error_code: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    payload = _approval_payload(request)
    trace_metadata = {
        "approval_request_id": approval_request_id,
        "approval_state": approval_state,
        "risk_kind": payload["risk"]["kind"],
        "risk_level": payload["risk"]["level"],
        **dict(metadata or {}),
    }
    record_browser_trace_event(
        session_id=request.session_id,
        phase="approval",
        backend_id=request.context.backend_id,
        requested_context=request.context.requested,
        selected_context=request.context.selected,
        action=request.action,
        tab_id=str(payload.get("tab_id") or ""),
        url=str(payload.get("url") or ""),
        domain=str(payload.get("domain") or ""),
        status=status,
        error_code=error_code,
        approval_state=approval_state,
        metadata=trace_metadata,
    )


def _approval_decision_metadata(
    approval_state: str,
    approval_request_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "approval_state": approval_state,
        "approval_request_id": approval_request_id,
    }
    metadata.update(dict(extra or {}))
    return metadata


def _severity(request: BrowserActionRequest) -> str:
    risk = request.risk
    if risk is None:
        return "medium"
    if risk.level == "high":
        return "high"
    if risk.level == "medium":
        return "medium"
    return "low"


def _domain(metadata: dict[str, Any]) -> str:
    domain = str(metadata.get("domain") or "").strip().lower()
    if domain:
        return domain
    url = str(metadata.get("url") or "")
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _approval_domain_scope(metadata: dict[str, Any]) -> str:
    domain = _domain(metadata)
    if domain:
        return domain
    tab_id = str(metadata.get("tab_id") or "").strip()
    if tab_id:
        return f"tab:{tab_id}"
    url = str(metadata.get("url") or "").strip()
    if url:
        return f"url:{url}"
    return "unknown"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(token in key_text.casefold() for token in _REDACT_KEYS):
                redacted[key_text] = _REDACTED
            else:
                redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


__all__ = ["QwenPawBrowserApprovalPolicy"]
