# -*- coding: utf-8 -*-
"""Browser SDK action risk classification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .types import BrowserActionRisk, BrowserRiskKind

_READ_ACTIONS = {
    "active_tab",
    "extract",
    "evaluate",
    "list_tabs",
    "page_info",
    "screenshot",
    "snapshot",
}
_NAVIGATION_ACTIONS = {
    "back",
    "forward",
    "hover",
    "navigate",
    "open",
    "press",
    "reload",
    "scroll",
    "select",
    "type",
    "wait_for",
}
_STRUCTURED_SENSITIVE_ACTIONS: dict[str, BrowserRiskKind] = {
    "clear": "destructive",
    "delete": "destructive",
    "remove": "destructive",
    "buy": "purchase",
    "checkout": "purchase",
    "purchase": "purchase",
    "pay": "payment",
    "payment": "payment",
    "submit": "submission",
    "upload": "upload",
    "download": "download",
}
_CREDENTIAL_KEYWORDS = {
    "credential",
    "login",
    "otp",
    "password",
    "secret",
    "token",
}
_SENSITIVE_KEYWORDS = {
    "buy",
    "cart",
    "checkout",
    "clear",
    "delete",
    "download",
    "pay",
    "payment",
    "purchase",
    "remove",
    "reveal",
    "submit",
    "upload",
}


def classify_browser_action(
    action: str,
    kwargs: Mapping[str, Any],
) -> BrowserActionRisk:
    """Classify browser action risk using action structure first."""
    normalized = _normalize(action)
    if normalized in _READ_ACTIONS:
        return BrowserActionRisk(
            sensitive=False,
            level="none",
            kind="read",
            reason="read-only browser action",
        )

    if normalized in _STRUCTURED_SENSITIVE_ACTIONS:
        kind = _STRUCTURED_SENSITIVE_ACTIONS[normalized]
        return BrowserActionRisk(
            sensitive=True,
            level="high",
            kind=kind,
            reason=f"structured sensitive browser action: {normalized}",
            matched=(normalized,),
        )

    credential_matches = _matches(_CREDENTIAL_KEYWORDS, action, kwargs)
    if credential_matches:
        return BrowserActionRisk(
            sensitive=True,
            level="high",
            kind="credential",
            reason="credential-like browser action arguments",
            matched=credential_matches,
        )

    if normalized in _NAVIGATION_ACTIONS:
        return BrowserActionRisk(
            sensitive=False,
            level="low",
            kind="navigation",
            reason="non-sensitive browser interaction",
        )

    sensitive_matches = _matches(_SENSITIVE_KEYWORDS, action, kwargs)
    if sensitive_matches:
        return BrowserActionRisk(
            sensitive=True,
            level="high",
            kind="unknown_sensitive",
            reason="sensitive keyword fallback",
            matched=sensitive_matches,
        )

    return BrowserActionRisk(
        sensitive=False,
        level="low",
        kind="navigation",
        reason="no sensitive browser risk matched",
    )


def _normalize(value: Any) -> str:
    return str(value or "").strip().casefold().replace("-", "_")


def _matches(
    keywords: set[str],
    action: str,
    kwargs: Mapping[str, Any],
) -> tuple[str, ...]:
    haystack = " ".join([str(action), *_flatten_values(kwargs)]).casefold()
    return tuple(
        sorted(keyword for keyword in keywords if keyword in haystack),
    )


def _flatten_values(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        out: list[str] = []
        for key, item in value.items():
            out.append(str(key))
            out.extend(_flatten_values(item))
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        out = []
        for item in value:
            out.extend(_flatten_values(item))
        return out
    return [str(value)]


__all__ = ["classify_browser_action"]
