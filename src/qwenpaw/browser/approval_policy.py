# -*- coding: utf-8 -*-
"""QwenPaw approval-backed Browser SDK policy."""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass
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
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel

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
        approval_level = _current_approval_level_resolution()
        matrix_decision = _browser_boundary_matrix_decision(
            request,
            approval_level,
        )
        if matrix_decision is not None:
            return matrix_decision

        context = _approval_context(request)
        cache_key = _approval_cache_key(request, context["root_session_id"])
        if self._cache_hit(cache_key):
            return BrowserPolicyDecision(
                allowed=True,
                reason="browser_action_approval_cache",
                metadata={
                    **_boundary_decision_metadata(
                        request,
                        approval_level,
                    ),
                    "approval_cache": "hit",
                },
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
                    request,
                    approval_level,
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
                    request,
                    approval_level,
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
                    request,
                    approval_level,
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
            metadata=_approval_decision_metadata(
                "denied",
                request_id,
                request,
                approval_level,
            ),
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


@dataclass(frozen=True)
class BrowserApprovalLevelResolution:
    """Resolved Browser approval level and source."""

    level: ToolExecutionLevel
    source: str


def resolve_browser_approval_level(
    *,
    request_context: dict[str, Any] | None = None,
    agent_profile: Any | None = None,
    agent_id: str = "",
) -> BrowserApprovalLevelResolution:
    """Resolve Browser approval level from session, profile, then AUTO."""
    request_ctx = request_context if isinstance(request_context, dict) else {}
    session_raw = request_ctx.get("approval_level") if request_ctx else None
    if session_raw:
        return BrowserApprovalLevelResolution(
            level=ToolExecutionLevel.from_config(str(session_raw)),
            source="session",
        )

    profile = agent_profile
    if profile is None and agent_id:
        try:
            from qwenpaw.config.config import load_agent_config

            profile = load_agent_config(agent_id)
        except Exception:
            profile = None
    profile_raw = getattr(profile, "approval_level", None)
    if profile_raw:
        return BrowserApprovalLevelResolution(
            level=ToolExecutionLevel.from_config(str(profile_raw)),
            source="agent_profile",
        )

    return BrowserApprovalLevelResolution(
        level=ToolExecutionLevel.AUTO,
        source="default",
    )


def _current_approval_level_resolution() -> BrowserApprovalLevelResolution:
    call_context = _call_context()
    request_context = getattr(call_context, "request_context", {}) or {}
    if not isinstance(request_context, dict):
        request_context = {}
    return resolve_browser_approval_level(
        request_context=request_context,
        agent_id=str(getattr(call_context, "agent_id", "") or ""),
    )


def _browser_boundary_matrix_decision(
    request: BrowserActionRequest,
    approval_level: BrowserApprovalLevelResolution,
) -> BrowserPolicyDecision | None:
    severity = _boundary_severity(request)
    metadata = _boundary_decision_metadata(request, approval_level)
    if severity == "critical_unknown":
        return BrowserPolicyDecision(
            allowed=False,
            reason="boundary_user_intervention_required",
            metadata={
                **metadata,
                "error_code": (
                    BrowserErrorCode.BOUNDARY_USER_INTERVENTION_REQUIRED.value
                ),
            },
        )
    if severity == "operational":
        return BrowserPolicyDecision(
            allowed=True,
            reason="browser_boundary_allowed",
            metadata=metadata,
        )
    if severity == "critical_known":
        return None

    level = approval_level.level
    if level == ToolExecutionLevel.OFF:
        return BrowserPolicyDecision(
            allowed=True,
            reason="browser_boundary_allowed",
            metadata=metadata,
        )
    if (
        level == ToolExecutionLevel.SMART
        and _boundary_confidence(request) >= 0.8
    ):
        return BrowserPolicyDecision(
            allowed=True,
            reason="browser_boundary_allowed",
            metadata=metadata,
        )
    return None


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


def _boundary_decision_metadata(
    request: BrowserActionRequest,
    approval_level: BrowserApprovalLevelResolution,
) -> dict[str, Any]:
    risk = request.risk
    return {
        "approval_level": approval_level.level.name,
        "approval_level_source": approval_level.source,
        "capability_class": (
            str(risk.capability_class) if risk else "unknown"
        ),
        "boundary_severity": _boundary_severity(request),
        "risk_kind": str(risk.kind) if risk else "unknown_sensitive",
        "decision_reason": str(
            risk.decision_reason if risk else "missing risk metadata",
        ),
        "evidence": _evidence_payload(request),
        "consequence_summary": str(
            risk.consequence_summary if risk else "",
        ),
    }


def _boundary_severity(request: BrowserActionRequest) -> str:
    risk = request.risk
    if risk is None:
        return "sensitive" if request.sensitive else "operational"
    return str(risk.boundary_severity or "operational")


def _boundary_confidence(request: BrowserActionRequest) -> float:
    risk = request.risk
    if risk is None:
        return 0.0
    return float(risk.confidence)


def _evidence_payload(request: BrowserActionRequest) -> list[dict[str, Any]]:
    risk = request.risk
    if risk is None:
        return []
    return [
        {
            "source": evidence.source,
            "label": evidence.label,
            "confidence": evidence.confidence,
            "metadata": dict(evidence.metadata),
        }
        for evidence in risk.evidence
    ]


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
            "capability_class": (
                str(risk.capability_class) if risk else "unknown"
            ),
            "boundary_severity": _boundary_severity(request),
            "confidence": _boundary_confidence(request),
            "decision_reason": str(
                risk.decision_reason if risk else "",
            ),
            "consequence_summary": str(
                risk.consequence_summary if risk else "",
            ),
            "evidence": _evidence_payload(request),
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
    approval_level = _current_approval_level_resolution()
    trace_metadata = {
        **_boundary_decision_metadata(request, approval_level),
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
    request: BrowserActionRequest,
    approval_level: BrowserApprovalLevelResolution,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        **_boundary_decision_metadata(request, approval_level),
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


__all__ = [
    "BrowserApprovalLevelResolution",
    "QwenPawBrowserApprovalPolicy",
    "resolve_browser_approval_level",
]
