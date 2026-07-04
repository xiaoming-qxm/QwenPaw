# -*- coding: utf-8 -*-
"""No-progress detection for repeated Browser SDK action traces."""

from __future__ import annotations

import json
from dataclasses import dataclass
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

    def to_dict(self) -> dict[str, str]:
        """Return JSON-safe signature metadata."""
        return {
            "action": self.action,
            "tab_id": self.tab_id,
            "url": self.url,
            "error_code": self.error_code,
            "kwargs_digest": self.kwargs_digest,
            "observation_digest": self.observation_digest,
        }


@dataclass(frozen=True)
class BrowserProgressDecision:
    """Decision returned by no-progress trace analysis."""

    blocked: bool
    reason: str = ""
    retry_count: int = 0
    recovery_hint: str = ""
    signature: BrowserActionSignature | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe decision metadata."""
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "retry_count": self.retry_count,
            "recovery_hint": self.recovery_hint,
            "signature": (
                self.signature.to_dict() if self.signature is not None else None
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
        recovery_hint=(
            "No page progress detected after repeated identical failed "
            f"{latest.action or 'browser'} actions. Take a fresh observation, "
            "change strategy, or stop instead of retrying the same action."
        ),
        signature=latest,
    )


def _action_signature(
    event: BrowserTraceEvent,
) -> BrowserActionSignature | None:
    if event.phase != "action" or event.status != "error":
        return None
    if not event.action:
        return None
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    return BrowserActionSignature(
        action=str(event.action),
        tab_id=str(event.tab_id),
        url=str(event.url),
        error_code=str(event.error_code),
        kwargs_digest=_stable_digest(metadata.get("kwargs", {})),
        observation_digest=_observation_digest(metadata),
    )


def _observation_digest(metadata: dict[str, Any]) -> str:
    for key in ("observation_digest", "snapshot_digest", "page_digest"):
        value = metadata.get(key)
        if value is not None:
            return str(value)
    return ""


def _stable_digest(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError):
        return str(value)


__all__ = [
    "BrowserActionSignature",
    "BrowserProgressDecision",
    "detect_no_progress",
]
