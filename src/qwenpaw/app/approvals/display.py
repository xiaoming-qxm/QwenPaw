# -*- coding: utf-8 -*-
"""Presentation helpers for approval records."""

from __future__ import annotations

from typing import Any

from .models import ApprovalBrief

REDACTED = "[REDACTED]"
SENSITIVE_KEY_TOKENS = (
    "authorization",
    "cookie",
    "credential",
    "otp",
    "password",
    "secret",
    "token",
)


def approval_display_fields(pending: Any) -> dict[str, Any]:
    """Return UI-facing tool display metadata for one pending approval.

    ``is_generalized`` lets the console render the Approve Pattern /
    Approve Exact choice only when the generalized target actually
    differs from the literal one; ``exact_target`` / ``similar_target``
    are the two values the user is choosing between.
    """
    display = pending.extra.get("display", {})
    if not isinstance(display, dict):
        display = {}
    return {
        "tool_display_name": str(
            display.get("tool_name") or pending.tool_name,
        ),
        "tool_source": str(display.get("tool_source") or "No rule hit"),
        "exact_target": str(display.get("exact_target") or ""),
        "similar_target": str(display.get("similar_target") or ""),
        "is_generalized": bool(display.get("is_generalized")),
    }


def approval_brief_to_payload(
    brief: ApprovalBrief | dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a redacted JSON-safe approval brief payload."""
    if brief is None:
        return None
    if isinstance(brief, ApprovalBrief):
        payload = {
            "subject": brief.subject,
            "target": brief.target,
            "evidence": brief.evidence,
            "uncertainties": list(brief.uncertainties),
            "possible_consequences": list(brief.possible_consequences),
            "risk_kind": brief.risk_kind,
            "risk_level": brief.risk_level,
            "confidence": brief.confidence,
            "why_approval_required": brief.why_approval_required,
            "safe_alternative": brief.safe_alternative,
        }
    elif isinstance(brief, dict):
        payload = dict(brief)
    else:
        return None
    return _redact_sensitive(payload)


def approval_brief_payload(pending: Any) -> dict[str, Any] | None:
    """Return the UI-facing redacted brief stored on a pending approval."""
    return approval_brief_to_payload(pending.extra.get("approval_brief"))


def approval_brief_notice(brief: dict[str, Any]) -> str:
    """Build a concise user-facing pre-approval notice."""
    subject = str(brief.get("subject") or "Approval request")
    target = str(brief.get("target") or "")
    risk_kind = str(brief.get("risk_kind") or "unknown")
    risk_level = str(brief.get("risk_level") or "unknown")
    why = str(brief.get("why_approval_required") or "")
    lines = [
        "Approval decision brief",
        f"Subject: {subject}",
    ]
    if target:
        lines.append(f"Target: {target}")
    lines.append(f"Risk: {risk_kind} / {risk_level}")
    if why:
        lines.append(f"Why approval is required: {why}")
    return "\n".join(lines)


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if _is_sensitive_key(str(key))
                else _redact_sensitive(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_sensitive(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(token in normalized for token in SENSITIVE_KEY_TOKENS)
