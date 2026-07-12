# -*- coding: utf-8 -*-
"""Shared Browser boundary policy evaluation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..primitives.types import (
    BrowserActionRequest,
    BrowserActionResult,
    BrowserActionRisk,
    BrowserPolicyDecision,
    ResolvedBrowserContext,
)
from .errors import BrowserPolicyDenied
from .effects import (
    COMMUNICATION,
    DELETE,
    FINANCIAL,
    PERMISSION_OR_SECURITY,
    REMOTE_WRITE,
    UNKNOWN,
    EffectClassification,
    minimum_effects,
)
from .errors import BrowserSDKError
from .policy import BrowserPolicy, maybe_await_policy_decision
from .risk import classify_browser_action


@dataclass(frozen=True)
class BrowserBoundaryEvaluation:
    """Policy decision and trace metadata for one Browser action."""

    risk: BrowserActionRisk
    decision: BrowserPolicyDecision
    boundary_decision: dict[str, Any]


async def evaluate_browser_boundary(
    *,
    policy: BrowserPolicy,
    session_id: str,
    context: ResolvedBrowserContext,
    action: str,
    metadata: dict[str, Any],
) -> BrowserBoundaryEvaluation:
    """Classify a Browser action and run it through the policy hook."""
    risk = classify_browser_action(action, metadata)
    decision = await maybe_await_policy_decision(
        policy.allow_action(
            BrowserActionRequest(
                session_id=session_id,
                action=action,
                context=context,
                sensitive=risk.sensitive,
                risk=risk,
                metadata=metadata,
            ),
        ),
    )
    return BrowserBoundaryEvaluation(
        risk=risk,
        decision=decision,
        boundary_decision=boundary_decision_metadata(decision, risk),
    )


def raise_if_boundary_denied(
    evaluation: BrowserBoundaryEvaluation,
    *,
    action: str,
    tab_id: str,
    action_metadata: dict[str, Any],
    context: ResolvedBrowserContext,
    backend_id: str,
) -> None:
    """Raise BrowserPolicyDenied with boundary metadata when denied."""
    if evaluation.decision.allowed:
        return
    metadata = policy_denial_metadata(
        decision=evaluation.decision,
        action=action,
        tab_id=tab_id,
        action_metadata=action_metadata,
        context=context,
        backend_id=backend_id,
    )
    error_code = str(metadata.get("error_code") or "")
    raise BrowserPolicyDenied(
        evaluation.decision.reason or "Browser action denied by policy",
        code=error_code or None,
        action=action,
        backend_id=backend_id,
        metadata=metadata,
    )


def action_result_with_boundary_decision(
    payload: Any,
    name: str,
    *,
    boundary_decision: dict[str, Any] | None = None,
) -> BrowserActionResult:
    """Coerce action payloads and attach boundary decision metadata."""
    if isinstance(payload, BrowserActionResult):
        if boundary_decision:
            return BrowserActionResult(
                ok=payload.ok,
                message=payload.message,
                needs_observation=payload.needs_observation,
                data={
                    **dict(payload.data),
                    "boundary_decision": dict(boundary_decision),
                },
            )
        return payload
    if isinstance(payload, dict):
        data = dict(payload.get("data") or {})
        if boundary_decision:
            data["boundary_decision"] = dict(boundary_decision)
        return BrowserActionResult(
            ok=bool(payload.get("ok", True)),
            message=str(payload.get("message") or name),
            needs_observation=bool(payload.get("needs_observation", True)),
            data=data,
        )
    data = (
        {"boundary_decision": dict(boundary_decision)}
        if boundary_decision
        else {}
    )
    return BrowserActionResult(
        ok=True,
        message=str(payload or name),
        data=data,
    )


def policy_metadata_kwargs(
    name: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Return kwargs enriched with state-changing intent for policy."""
    metadata = dict(kwargs)
    if state_changing_action(name, metadata):
        metadata.setdefault("can_write", True)
    return metadata


def state_changing_action(name: str, kwargs: dict[str, Any]) -> bool:
    """Return whether a Browser action should be treated as a write."""
    normalized = str(name or "").strip().casefold().replace("-", "_")
    if normalized == "dialog":
        return bool_arg(kwargs.get("accept", True))
    return normalized in {
        "click",
        "type",
        "select",
        "upload",
    }


def require_canonical_effect_floor(
    api_id: str,
    arguments: Mapping[str, object],
    classification: EffectClassification,
) -> EffectClassification:
    """Reject a Canonical classification that lowers its operation floor."""
    if not isinstance(classification, EffectClassification):
        raise BrowserSDKError(
            "Canonical effect classification is invalid",
            code="effect_floor_lowered",
        )
    floor = minimum_effects(api_id, arguments)
    received = set(classification.categories)
    if any(
        category not in received
        for category in floor
        if category is not UNKNOWN
    ):
        raise BrowserSDKError(
            "Canonical effect classification lowered its minimum floor",
            code="effect_floor_lowered",
        )
    if (
        UNKNOWN in floor
        and UNKNOWN not in received
        and not str(classification.proof_ref or "").strip()
    ):
        raise BrowserSDKError(
            "Canonical UNKNOWN effect lacks independent closure proof",
            code="effect_floor_lowered",
        )
    return classification


def canonical_preflight_handoff_reason(
    classification: EffectClassification,
    arguments: Mapping[str, object],
) -> str:
    """Return the fixed material-risk handoff reason, if any."""
    material = {
        REMOTE_WRITE,
        DELETE,
        COMMUNICATION,
        FINANCIAL,
        PERMISSION_OR_SECURITY,
    }
    if material.intersection(classification.categories):
        return "material_effect_requires_handoff"
    if any(
        bool(arguments.get(signal))
        for signal in (
            "financial_signal",
            "communication_signal",
            "delete_signal",
            "security_signal",
            "credential_signal",
            "irreversible_signal",
        )
    ):
        return "material_effect_requires_handoff"
    return ""


def bool_arg(value: Any) -> bool:
    """Coerce common Browser action boolean inputs."""
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


def boundary_decision_metadata(
    decision: BrowserPolicyDecision,
    risk: BrowserActionRisk,
) -> dict[str, Any]:
    """Return flattened boundary decision metadata for results and traces."""
    metadata = dict(decision.metadata)
    metadata.setdefault("capability_class", risk.capability_class)
    metadata.setdefault("boundary_severity", risk.boundary_severity)
    metadata.setdefault("risk_kind", risk.kind)
    metadata.setdefault("decision_reason", risk.decision_reason)
    metadata.setdefault("consequence_summary", risk.consequence_summary)
    metadata.setdefault("evidence", risk_evidence(risk))
    return metadata


def policy_denial_metadata(
    *,
    decision: BrowserPolicyDecision,
    action: str,
    tab_id: str,
    action_metadata: dict[str, Any],
    context: ResolvedBrowserContext,
    backend_id: str,
) -> dict[str, Any]:
    """Return denial metadata for BrowserPolicyDenied."""
    metadata = dict(decision.metadata)
    approval_state = approval_state_from_reason(decision.reason)
    if approval_state:
        metadata.setdefault("approval_state", approval_state)
    metadata.update(
        {
            "action": action,
            "tab_id": str(tab_id),
            "requested_context": context.requested,
            "selected_context": context.selected,
            "backend_id": backend_id,
        },
    )
    for key in ("url", "domain", "title"):
        value = action_metadata.get(key)
        if value:
            metadata[key] = str(value)
    return metadata


def risk_evidence(risk: BrowserActionRisk) -> list[dict[str, Any]]:
    """Return JSON-safe risk evidence."""
    return [
        {
            "source": evidence.source,
            "label": evidence.label,
            "confidence": evidence.confidence,
            "metadata": dict(evidence.metadata),
        }
        for evidence in risk.evidence
    ]


def approval_state_from_reason(reason: str) -> str:
    """Map policy reason strings to trace approval states."""
    normalized = str(reason or "").strip().casefold()
    if normalized == "browser_action_denied":
        return "denied"
    if normalized == "browser_action_approval_timeout":
        return "timeout"
    if normalized == "browser_action_approval_error":
        return "error"
    return ""


__all__ = [
    "BrowserBoundaryEvaluation",
    "action_result_with_boundary_decision",
    "approval_state_from_reason",
    "bool_arg",
    "boundary_decision_metadata",
    "canonical_preflight_handoff_reason",
    "evaluate_browser_boundary",
    "policy_denial_metadata",
    "policy_metadata_kwargs",
    "raise_if_boundary_denied",
    "require_canonical_effect_floor",
    "risk_evidence",
    "state_changing_action",
]
