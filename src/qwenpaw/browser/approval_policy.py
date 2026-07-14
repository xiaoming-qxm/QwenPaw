# -*- coding: utf-8 -*-
"""QwenPaw approval-backed Browser SDK policy."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urlparse

from qwenpaw.app.approvals.models import ApprovalBrief, ApprovalRequestSummary
from qwenpaw.browser.sdk.action_runner import (
    ActionPreview,
    ApprovalGrant,
    issue_exact_grant,
)
from qwenpaw.browser.sdk.governance.policy import TrustedSurfacePolicy
from qwenpaw.browser.sdk.governance.error_codes import BrowserErrorCode
from qwenpaw.browser.sdk.telemetry.trace import record_browser_trace_event
from qwenpaw.browser.sdk.primitives.types import (
    BrowserActionRequest,
    BrowserActionRisk,
    BrowserContextRequest,
    BrowserPolicyDecision,
    ResolvedBrowserContext,
)
from qwenpaw.constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
from qwenpaw.security.tool_guard.approval import ApprovalDecision
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel

_DEFAULT_CACHE_TTL_SECONDS = 120.0
_REDACTED = "[REDACTED]"
_REDACT_KEY_TOKENS = {
    "credential",
    "otp",
    "password",
    "secret",
    "token",
    "value",
}
_REDACT_EXACT_KEYS = {
    "file_path",
    "file_paths",
    "files",
    "prompt_text",
    "text",
}


@dataclass(frozen=True)
class BrowserApprovalCacheKey:
    """Risk-domain key shared by Browser SDK and internal CDP relay."""

    root_session_id: str
    approval_level: str
    domain: str
    action_family: str
    risk_kind: str
    source_type: str = "legacy_browser"


@dataclass(frozen=True)
class BrowserApprovalCacheEntry:
    """Cached Browser approval outcome."""

    state: str
    expires_at: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BrowserApprovalResolution:
    """Approval decision returned by the shared Browser resolver."""

    allowed: bool
    reason: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BrowserExactApprovalResolution:
    """Decision and optional single-use grant for one Canonical action."""

    pending: Any
    decision: ApprovalDecision
    grant: ApprovalGrant | None


class BrowserApprovalCache:
    """TTL cache for Browser approval outcomes."""

    def __init__(
        self,
        *,
        now: Callable[[], float] | None = None,
        ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._now = now or time.time
        self._ttl_seconds = float(ttl_seconds)
        self._items: dict[
            BrowserApprovalCacheKey,
            BrowserApprovalCacheEntry,
        ] = {}

    def get(
        self,
        key: BrowserApprovalCacheKey,
    ) -> BrowserApprovalCacheEntry | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._now():
            self._items.pop(key, None)
            return None
        return entry

    def put(
        self,
        key: BrowserApprovalCacheKey,
        *,
        state: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._items[key] = BrowserApprovalCacheEntry(
            state=_approval_state_name(state),
            expires_at=self._now() + self._ttl_seconds,
            metadata=dict(metadata or {}),
        )

    def clear(self) -> None:
        self._items.clear()

    def items_for(
        self,
        source_type: str,
    ) -> tuple[BrowserApprovalCacheEntry, ...]:
        """Return cache entries for characterization by source."""
        source = str(source_type or "")
        return tuple(
            entry
            for key, entry in self._items.items()
            if key.source_type == source
        )


_DEFAULT_BROWSER_APPROVAL_CACHE = BrowserApprovalCache()


def get_default_browser_approval_cache() -> BrowserApprovalCache:
    """Return the process-local Browser approval cache."""
    return _DEFAULT_BROWSER_APPROVAL_CACHE


class QwenPawBrowserApprovalPolicy:
    """Route sensitive Browser SDK actions through QwenPaw approvals."""

    def __init__(
        self,
        *,
        approval_service: Any | None = None,
        approval_cache: BrowserApprovalCache | None = None,
        now: Callable[[], float] | None = None,
        grant_clock: Callable[[], float] | None = None,
        trusted_surface_policy: TrustedSurfacePolicy | None = None,
        cache_ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._approval_service = approval_service
        self._now = now or time.time
        self._grant_clock = grant_clock or monotonic
        self.trusted_surface_policy = trusted_surface_policy
        self._approval_cache = approval_cache or BrowserApprovalCache(
            now=self._now,
            ttl_seconds=cache_ttl_seconds,
        )

    def allow_context_acquisition(
        self,
        request: BrowserContextRequest,
    ) -> BrowserPolicyDecision:
        del request
        return BrowserPolicyDecision(allowed=True, reason="allowed")

    async def request_exact(
        self,
        preview: ActionPreview,
    ) -> BrowserExactApprovalResolution:
        """Request one uncached exact Canonical Browser approval."""
        if not isinstance(preview, ActionPreview):
            raise TypeError("preview must be an ActionPreview")
        if _current_approval_level_resolution().level == ToolExecutionLevel.OFF:
            return BrowserExactApprovalResolution(
                pending=None,
                decision=ApprovalDecision.APPROVED,
                grant=issue_exact_grant(preview, now=self._grant_clock()),
            )
        context = _canonical_approval_context(preview)
        payload = _canonical_preview_payload(preview)
        summary = ApprovalRequestSummary(
            source_type="browser_core_action",
            scope_policy="exact_only",
            name="browser",
            severity="medium",
            findings_count=1,
            result_summary=(
                f"Approve exact Browser operation {preview.api_id}"
            ),
            payload=payload,
        )
        service = self._service()
        timeout_seconds = _approval_timeout_seconds()
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
                    "input": payload,
                },
            },
        )
        decision = await service.wait_for_approval(
            pending.request_id,
            timeout_seconds,
        )
        grant = (
            issue_exact_grant(preview, now=self._grant_clock())
            if decision == ApprovalDecision.APPROVED
            else None
        )
        return BrowserExactApprovalResolution(
            pending=pending,
            decision=decision,
            grant=grant,
        )

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
        cache_key = _approval_cache_key(
            request,
            root_session_id=context["root_session_id"],
            approval_level=approval_level.level.name,
        )
        cache_entry = self._approval_cache.get(cache_key)
        if cache_entry is not None:
            resolution = _resolution_from_cache(cache_entry)
            return BrowserPolicyDecision(
                allowed=resolution.allowed,
                reason=resolution.reason,
                metadata={
                    **_boundary_decision_metadata(request, approval_level),
                    **resolution.metadata,
                },
            )

        summary = ApprovalRequestSummary(
            source_type="browser_sdk_action",
            name="browser",
            severity=_severity(request),
            findings_count=1,
            result_summary=_approval_summary(request),
            payload=_approval_payload(request),
            approval_brief=_approval_brief(request),
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
                error_code=BrowserErrorCode.APPROVAL_ERROR.value,
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
            approved_metadata = _approval_decision_metadata(
                "approved",
                request_id,
                request,
                approval_level,
            )
            self._approval_cache.put(
                cache_key,
                state="approved",
                metadata=approved_metadata,
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
                metadata=approved_metadata,
            )
        if decision == ApprovalDecision.TIMEOUT:
            timeout_metadata = _approval_decision_metadata(
                "timeout",
                request_id,
                request,
                approval_level,
            )
            self._approval_cache.put(
                cache_key,
                state="timeout",
                metadata=timeout_metadata,
            )
            _record_approval_trace(
                request,
                approval_state="timeout",
                approval_request_id=request_id,
                status="blocked",
                error_code=BrowserErrorCode.APPROVAL_TIMEOUT.value,
            )
            return BrowserPolicyDecision(
                allowed=False,
                reason="browser_action_approval_timeout",
                metadata=timeout_metadata,
            )
        denied_metadata = _approval_decision_metadata(
            "denied",
            request_id,
            request,
            approval_level,
        )
        self._approval_cache.put(
            cache_key,
            state="denied",
            metadata=denied_metadata,
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
            metadata=denied_metadata,
        )

    def _service(self) -> Any:
        if self._approval_service is not None:
            return self._approval_service
        from qwenpaw.app.approvals import get_approval_service

        return get_approval_service()


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


def _canonical_approval_context(preview: ActionPreview) -> dict[str, str]:
    call_context = _call_context()
    agent_id = (
        str(getattr(call_context, "agent_id", "") or "")
        or _agent_context_value("get_current_agent_id")
        or "unknown"
    )
    return {
        "session_id": preview.session_id,
        "root_session_id": preview.session_id,
        "owner_agent_id": agent_id,
        "user_id": _agent_context_value("get_current_user_id"),
        "channel": _agent_context_value("get_current_channel"),
        "agent_id": agent_id,
        "tool_call_id": str(
            getattr(call_context, "tool_call_id", "") or "",
        ),
    }


def _canonical_preview_payload(preview: ActionPreview) -> dict[str, Any]:
    return {
        "source_type": "browser_core_action",
        "scope_policy": "exact_only",
        "operation_id": preview.operation_id,
        "api_id": preview.api_id,
        "origin": preview.origin,
        "ordered_targets": [
            {"label": label, "ref": target_ref}
            for label, target_ref in preview.ordered_targets
        ],
        "safe_arguments": dict(preview.safe_arguments),
        "effects": [effect.value for effect in preview.effects],
        "expectation_bound": preview.expectation_digest != "none",
        "binding_hash": preview.binding_hash,
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


# Strategy matrices stay flatter and auditable with explicit exits.
# pylint: disable-next=too-many-return-statements
def _browser_boundary_matrix_decision(
    request: BrowserActionRequest,
    approval_level: BrowserApprovalLevelResolution,
) -> BrowserPolicyDecision | None:
    severity = _boundary_severity(request)
    metadata = _boundary_decision_metadata(request, approval_level)
    if severity == "critical_unknown":
        if not request.metadata.get("observation_attempted"):
            return BrowserPolicyDecision(
                allowed=False,
                reason="browser_boundary_observation_required",
                metadata={
                    **metadata,
                    "error_code": BrowserErrorCode.OBSERVATION_STALE.value,
                    "required_next_step": "tab.snapshot()",
                },
            )
        return BrowserPolicyDecision(
            allowed=False,
            reason="boundary_user_intervention_required",
            metadata={
                **metadata,
                "error_code": BrowserErrorCode.HANDOFF_REQUIRED.value,
                "required_next_step": "ask_user_to_take_over",
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
    if _is_reversible_low_risk(request) and level != ToolExecutionLevel.STRICT:
        return BrowserPolicyDecision(
            allowed=True,
            reason="browser_boundary_allowed",
            metadata=metadata,
        )
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


def _approval_brief(request: BrowserActionRequest) -> ApprovalBrief | None:
    risk = request.risk
    if risk is None or not risk.sensitive:
        return None
    payload = _approval_payload(request)
    evidence = {
        "action": request.action,
        "domain": payload["domain"],
        "url": payload["url"],
        "title": payload["title"],
        "risk": payload["risk"],
    }
    if payload["kwargs"]:
        evidence["kwargs"] = payload["kwargs"]
    return ApprovalBrief(
        subject="Browser action approval",
        target=str(payload["url"] or payload["domain"] or request.action),
        evidence=evidence,
        uncertainties=("Browser state may change after the action runs.",),
        possible_consequences=(
            risk.consequence_summary
            or "This Browser action may change page or account state.",
        ),
        risk_kind=str(risk.kind),
        risk_level=str(risk.level),
        confidence=float(risk.confidence),
        why_approval_required=(
            risk.decision_reason or "Browser action crosses a risk boundary."
        ),
        safe_alternative="Review or complete the action manually.",
    )


def _is_reversible_low_risk(request: BrowserActionRequest) -> bool:
    risk = request.risk
    if risk is None:
        return False
    if str(risk.level) != "low":
        return False
    return any(match == "account_state_reversible" for match in risk.matched)


def _approval_summary(request: BrowserActionRequest) -> str:
    payload = _approval_payload(request)
    risk = payload["risk"]
    domain = payload["domain"] or "unknown domain"
    return (
        "Browser SDK wants to run a sensitive Chrome action "
        f"`{request.action}` on {domain} ({risk['kind']})."
    )


def browser_approval_cache_key(
    request: BrowserActionRequest,
    *,
    root_session_id: str,
    approval_level: str,
) -> BrowserApprovalCacheKey:
    """Return the shared approval cache key for a Browser action."""
    return _approval_cache_key(
        request,
        root_session_id=root_session_id,
        approval_level=approval_level,
    )


def _approval_cache_key(
    request: BrowserActionRequest,
    *,
    root_session_id: str,
    approval_level: str,
) -> BrowserApprovalCacheKey:
    risk_kind = str(request.risk.kind) if request.risk else "unknown_sensitive"
    return BrowserApprovalCacheKey(
        root_session_id=str(root_session_id or "default"),
        approval_level=str(approval_level or "auto").strip().casefold(),
        domain=_approval_domain_scope(request.metadata),
        action_family=_browser_action_family(request.action),
        risk_kind=risk_kind,
    )


def _resolution_from_cache(
    entry: BrowserApprovalCacheEntry,
) -> BrowserApprovalResolution:
    state = _approval_state_name(entry.state)
    allowed = state == "approved"
    reason = (
        "browser_action_approval_cache"
        if allowed
        else f"browser_action_approval_cached_{state}"
    )
    return BrowserApprovalResolution(
        allowed=allowed,
        reason=reason,
        metadata={
            **entry.metadata,
            "approval_cache": "hit",
            "approval_state": state,
        },
    )


def _approval_state_name(state: str) -> str:
    normalized = str(state or "").strip().casefold()
    if normalized in {"approved", "denied", "timeout", "error"}:
        return normalized
    return "error"


def _browser_action_family(action: str) -> str:
    value = str(action or "").strip().casefold()
    if value in {"open", "navigate", "page.navigate", "new"}:
        return "navigation"
    if value in {"click", "type", "fill", "press", "press_key"}:
        return "input"
    if value in {"evaluate", "runtime.evaluate"}:
        return "script"
    if value.startswith("page."):
        return "navigation"
    return value or "unknown"


async def resolve_cdp_browser_approval(
    *,
    request_context: dict[str, Any],
    request: dict[str, Any],
    approval_service: Any | None = None,
    approval_cache: BrowserApprovalCache | None = None,
    now: Callable[[], float] | None = None,
) -> BrowserApprovalResolution:
    """Resolve internal CDP approval through the shared Browser cache."""
    del now
    approval_level = resolve_browser_approval_level(
        request_context=request_context,
        agent_id=str(
            request_context.get("agent_id")
            or request_context.get("root_agent_id")
            or "",
        ),
    )
    if approval_level.level == ToolExecutionLevel.OFF:
        return BrowserApprovalResolution(
            allowed=True,
            reason="browser_approval_level_off",
            metadata={
                "approval_level": approval_level.level.name,
                "approval_level_source": approval_level.source,
                "approval_state": "not_required",
            },
        )

    session_id = str(request_context.get("session_id") or "")
    root_session_id = str(
        request_context.get("root_session_id") or session_id or "default",
    )
    cache = approval_cache or get_default_browser_approval_cache()
    cache_key = _cdp_approval_cache_key(
        request,
        root_session_id=root_session_id,
        approval_level=approval_level.level.name,
    )
    cache_entry = cache.get(cache_key)
    if cache_entry is not None:
        return _resolution_from_cache(cache_entry)

    action_request = _cdp_browser_action_request(request_context, request)
    if not _cdp_request_requires_explicit_approval(request):
        matrix_decision = _browser_boundary_matrix_decision(
            action_request,
            approval_level,
        )
        if matrix_decision is not None:
            return BrowserApprovalResolution(
                allowed=matrix_decision.allowed,
                reason=matrix_decision.reason,
                metadata=matrix_decision.metadata,
            )

    if not session_id:
        return BrowserApprovalResolution(
            allowed=False,
            reason="browser_action_approval_error",
            metadata={
                "approval_state": "error",
                "error": "CDP approval requires request_context.session_id",
            },
        )

    service = approval_service
    if service is None:
        from qwenpaw.app.approvals import get_approval_service

        service = get_approval_service()

    request_id = ""
    timeout_seconds = _approval_timeout_seconds_from_context(request_context)
    try:
        pending = await service.create_pending_summary(
            session_id=session_id,
            root_session_id=root_session_id,
            owner_agent_id=str(request_context.get("root_agent_id") or ""),
            user_id=str(request_context.get("user_id") or ""),
            channel=str(request_context.get("channel") or ""),
            agent_id=str(request_context.get("agent_id") or "unknown"),
            summary=ApprovalRequestSummary(
                source_type="browser_sdk_cdp",
                name="browser",
                severity="medium",
                findings_count=1,
                result_summary=_cdp_approval_summary(request),
                payload=request,
            ),
            timeout_seconds=timeout_seconds,
            extra={
                "tool_call": {
                    "id": str(request_context.get("tool_call_id") or ""),
                    "name": "browser",
                    "input": request,
                },
            },
        )
        request_id = str(pending.request_id)
        decision = await service.wait_for_approval(
            pending.request_id,
            timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        metadata = {
            "approval_state": "error",
            "approval_request_id": request_id,
            "error": str(exc),
        }
        cache.put(cache_key, state="error", metadata=metadata)
        return BrowserApprovalResolution(
            allowed=False,
            reason="browser_action_approval_error",
            metadata=metadata,
        )

    state = _decision_state(decision)
    metadata = {
        "approval_state": state,
        "approval_request_id": request_id,
        "approval_level": approval_level.level.name,
        "approval_level_source": approval_level.source,
    }
    cache.put(cache_key, state=state, metadata=metadata)
    return BrowserApprovalResolution(
        allowed=state == "approved",
        reason=(
            "browser_action_approved"
            if state == "approved"
            else f"browser_action_approval_{state}"
        ),
        metadata=metadata,
    )


def _cdp_browser_action_request(
    request_context: dict[str, Any],
    request: dict[str, Any],
) -> BrowserActionRequest:
    risk_kind = _cdp_risk_kind(request)
    is_navigation = risk_kind == "navigation"
    return BrowserActionRequest(
        session_id=str(request_context.get("session_id") or ""),
        action=str(request.get("method") or request.get("action") or ""),
        context=ResolvedBrowserContext(
            requested="user",
            selected="user",
            reason="cdp_relay",
            requires_user_state=True,
            backend_id="user.chrome_extension",
        ),
        sensitive=not is_navigation,
        risk=BrowserActionRisk(
            sensitive=not is_navigation,
            level="low" if is_navigation else "high",
            kind=risk_kind,  # type: ignore[arg-type]
            reason=(
                "ordinary CDP navigation"
                if is_navigation
                else "unknown sensitive CDP command"
            ),
            capability_class=(
                "navigation" if is_navigation else "unknown_write"
            ),
            boundary_severity=(
                "operational" if is_navigation else "sensitive"
            ),
            confidence=1.0 if is_navigation else 0.0,
            decision_reason=(
                "CDP navigation is an operational browser boundary"
                if is_navigation
                else "CDP command lacks a safe operational classification"
            ),
        ),
        metadata={
            "method": str(request.get("method") or ""),
            "policy": str(request.get("policy") or ""),
            "url": str(request.get("url") or ""),
            "domain": _cdp_domain_scope(request),
            "tab_id": str(request.get("tab_id") or ""),
            "holder_id": str(request.get("holder_id") or ""),
        },
    )


def _cdp_request_requires_explicit_approval(
    request: dict[str, Any],
) -> bool:
    return str(request.get("policy") or "").strip().casefold() in {
        "ask",
        "ask_new_domain",
    }


def _cdp_approval_cache_key(
    request: dict[str, Any],
    *,
    root_session_id: str,
    approval_level: str,
) -> BrowserApprovalCacheKey:
    return BrowserApprovalCacheKey(
        root_session_id=str(root_session_id or "default"),
        approval_level=str(approval_level or "auto").strip().casefold(),
        domain=_cdp_domain_scope(request),
        action_family=_browser_action_family(str(request.get("method") or "")),
        risk_kind=_cdp_risk_kind(request),
    )


def _cdp_domain_scope(request: dict[str, Any]) -> str:
    domain = str(request.get("domain") or "").strip().lower()
    if domain:
        return domain
    url = str(request.get("url") or "")
    if url:
        try:
            domain = (urlparse(url).hostname or "").lower()
        except ValueError:
            return f"url:{url}"
        if domain:
            return domain
    tab_id = str(request.get("tab_id") or "").strip()
    return f"tab:{tab_id}" if tab_id else "unknown"


def _cdp_risk_kind(request: dict[str, Any]) -> str:
    method = str(request.get("method") or "").casefold()
    if method == "page.navigate":
        return "navigation"
    return "unknown_sensitive"


def _cdp_approval_summary(request: dict[str, Any]) -> str:
    method = str(request.get("method") or "unknown")
    domain = str(request.get("domain") or "").strip()
    url = str(request.get("url") or "").strip()
    if method == "Page.navigate":
        target = domain or url or "unknown domain"
        return (
            "Chrome browser control wants to navigate to new domain "
            f"{target}."
        )
    if domain:
        return (
            "Chrome browser control wants to run CDP command "
            f"{method} for domain {domain}."
        )
    return f"Chrome browser control wants to run CDP command {method}."


def _approval_timeout_seconds_from_context(
    request_context: dict[str, Any],
) -> float:
    try:
        value = float(request_context.get("approval_timeout_seconds") or 0)
    except (TypeError, ValueError):
        value = 0
    if value > 0:
        return min(value, float(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS))
    return float(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS)


def _decision_state(decision: ApprovalDecision) -> str:
    if decision == ApprovalDecision.APPROVED:
        return "approved"
    if decision == ApprovalDecision.TIMEOUT:
        return "timeout"
    return "denied"


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
    error_code = _approval_error_code(approval_state)
    if error_code:
        metadata["error_code"] = error_code
    metadata.update(dict(extra or {}))
    return metadata


def _approval_error_code(approval_state: str) -> str:
    if approval_state == "denied":
        return BrowserErrorCode.APPROVAL_DENIED.value
    if approval_state == "timeout":
        return BrowserErrorCode.APPROVAL_TIMEOUT.value
    if approval_state == "error":
        return BrowserErrorCode.APPROVAL_ERROR.value
    return ""


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
            if _redact_key(key_text):
                redacted[key_text] = _REDACTED
            else:
                redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def _redact_key(key: str) -> bool:
    lowered = key.strip().casefold()
    if lowered in _REDACT_EXACT_KEYS:
        return True
    return any(token in lowered for token in _REDACT_KEY_TOKENS)


__all__ = [
    "BrowserApprovalCache",
    "BrowserApprovalCacheEntry",
    "BrowserApprovalCacheKey",
    "BrowserApprovalLevelResolution",
    "BrowserApprovalResolution",
    "BrowserExactApprovalResolution",
    "QwenPawBrowserApprovalPolicy",
    "browser_approval_cache_key",
    "get_default_browser_approval_cache",
    "resolve_browser_approval_level",
    "resolve_cdp_browser_approval",
]
