# -*- coding: utf-8 -*-
"""No-progress detection for repeated Browser SDK action traces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterable

from .trace import BrowserTraceEvent


@dataclass(frozen=True)
class BrowserActionSignature:
    """Stable structural signature for one browser action attempt."""

    action: str
    tab_id: str
    url: str
    error_code: str
    kwargs_digest: str
    observation_digest: str
    intent_digest: str = ""
    target_digest: str = ""
    outcome_class: str = ""

    def to_dict(self) -> dict[str, str]:
        """Return JSON-safe signature metadata."""
        return {
            "action": self.action,
            "tab_id": self.tab_id,
            "url": self.url,
            "error_code": self.error_code,
            "kwargs_digest": self.kwargs_digest,
            "observation_digest": self.observation_digest,
            "intent_digest": self.intent_digest,
            "target_digest": self.target_digest,
            "outcome_class": self.outcome_class,
        }


@dataclass(frozen=True)
class BrowserProgressDecision:
    """Decision returned by no-progress trace analysis."""

    blocked: bool
    reason: str = ""
    retry_count: int = 0
    recovery_hint: str = ""
    signature: BrowserActionSignature | None = None
    threshold: int = 3
    recommended_next_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe decision metadata."""
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "retry_count": self.retry_count,
            "count": self.retry_count,
            "threshold": self.threshold,
            "recommended_next_action": self.recommended_next_action,
            "recovery_hint": self.recovery_hint,
            "signature": (
                self.signature.to_dict()
                if self.signature is not None
                else None
            ),
        }


def detect_no_progress(
    events: Iterable[BrowserTraceEvent],
    *,
    threshold: int = 3,
) -> BrowserProgressDecision:
    """Detect repeated failed actions with unchanged page state."""
    threshold = max(2, int(threshold))
    event_list = list(events)
    if not event_list or _action_signature(event_list[-1]) is None:
        return BrowserProgressDecision(blocked=False)
    signatures = [
        signature
        for event in event_list
        if (signature := _action_signature(event)) is not None
    ]
    if len(signatures) < threshold:
        return BrowserProgressDecision(blocked=False)

    latest = signatures[-1]
    retry_count = 0
    for signature in reversed(signatures):
        if signature != latest:
            break
        retry_count += 1

    if retry_count < threshold:
        return BrowserProgressDecision(blocked=False)

    return BrowserProgressDecision(
        blocked=True,
        reason="no_progress",
        retry_count=retry_count,
        recovery_hint=_recovery_hint(latest),
        signature=latest,
        threshold=threshold,
        recommended_next_action=_recommended_next_action(latest),
    )


def _action_signature(
    event: BrowserTraceEvent,
) -> BrowserActionSignature | None:
    if event.phase != "action" or not event.action:
        return None
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    outcome_class = _outcome_class(event, metadata)
    if not outcome_class:
        return None
    kwargs = metadata.get("kwargs", {})
    return BrowserActionSignature(
        action=str(event.action),
        tab_id=str(event.tab_id),
        url=str(event.url),
        error_code=str(event.error_code),
        kwargs_digest=_stable_digest(kwargs),
        observation_digest=_observation_digest(metadata),
        intent_digest=_stable_digest(
            metadata.get("intent")
            or metadata.get("action_intent")
            or str(event.action),
        ),
        target_digest=_stable_digest(_target_signature(kwargs)),
        outcome_class=outcome_class,
    )


def _outcome_class(
    event: BrowserTraceEvent,
    metadata: dict[str, Any],
) -> str:
    error_code = str(event.error_code or "")
    if event.status == "error":
        if error_code == "observation_stale":
            return "stale_observation"
        return "action_error"
    if event.status == "ok" and _is_mutation_without_state_change(metadata):
        return "mutation_no_change"
    return ""


def _is_mutation_without_state_change(metadata: dict[str, Any]) -> bool:
    mutation = bool(
        metadata.get("post_mutation_observation_required")
        or metadata.get("needs_observation"),
    )
    if not mutation:
        return False
    for key in (
        "state_changed",
        "snapshot_changed",
        "mutation_state_changed",
        "page_changed",
    ):
        if metadata.get(key) is False:
            return True
    return False


def _target_signature(kwargs: Any) -> dict[str, Any]:
    if not isinstance(kwargs, dict):
        return {"target": kwargs}
    return {
        key: kwargs.get(key)
        for key in ("target", "selector", "ref", "text", "x", "y")
        if kwargs.get(key) is not None
    }


def _recommended_next_action(signature: BrowserActionSignature) -> str:
    if signature.outcome_class == "stale_observation":
        return "observe"
    return "change_strategy"


def _recovery_hint(signature: BrowserActionSignature) -> str:
    if signature.outcome_class == "stale_observation":
        return (
            "No page progress detected after repeated stale-observation "
            f"{signature.action or 'browser'} actions. Call tab.snapshot() "
            "or tab.screenshot() before another mutation."
        )
    return (
        "No page progress detected after repeated same-intent "
        f"{signature.action or 'browser'} actions on the same page and "
        "target. Take a fresh observation, change strategy, or stop instead "
        "of retrying the same action."
    )


def _observation_digest(metadata: dict[str, Any]) -> str:
    for key in ("observation_digest", "snapshot_digest", "page_digest"):
        value = metadata.get(key)
        if value is not None:
            return str(value)
    return ""


def _stable_digest(value: Any) -> str:
    try:
        serialized = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError):
        serialized = str(type(value).__name__)
    return sha256(serialized.encode("utf-8")).hexdigest()


__all__ = [
    "BrowserActionSignature",
    "BrowserProgressDecision",
    "detect_no_progress",
]
