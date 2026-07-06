# -*- coding: utf-8 -*-
"""Browser SDK action risk classification."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from ..primitives.types import BrowserActionRisk, BrowserRiskKind

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
RISK_ACTIONS_BY_KIND: dict[BrowserRiskKind, frozenset[str]] = {
    "destructive": frozenset({"clear", "delete", "remove"}),
    "purchase": frozenset({"buy", "checkout", "purchase"}),
    "payment": frozenset({"pay", "payment"}),
    "submission": frozenset({"submit"}),
    "upload": frozenset({"upload"}),
    "download": frozenset({"download"}),
}

RISK_KEYWORDS_BY_KIND: dict[BrowserRiskKind, frozenset[str]] = {
    "credential": frozenset(
        {"credential", "login", "otp", "password", "secret", "token"},
    ),
    "destructive": frozenset({"clear", "delete", "remove"}),
    "purchase": frozenset({"buy", "cart", "checkout", "purchase"}),
    "payment": frozenset({"pay", "payment"}),
    "submission": frozenset({"submit"}),
    "upload": frozenset({"upload"}),
    "download": frozenset({"download"}),
    "unknown_sensitive": frozenset({"reveal"}),
}

_STRUCTURED_SENSITIVE_ACTIONS: dict[str, BrowserRiskKind] = {
    action: kind
    for kind, actions in RISK_ACTIONS_BY_KIND.items()
    for action in actions
}
_CREDENTIAL_KEYWORDS = set(RISK_KEYWORDS_BY_KIND["credential"])
_SENSITIVE_KEYWORDS = set().union(
    *(
        set(keywords)
        for kind, keywords in RISK_KEYWORDS_BY_KIND.items()
        if kind != "credential"
    ),
)


# pylint: disable-next=too-many-return-statements
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

    if normalized == "dialog":
        if _bool_arg(kwargs.get("accept", True)):
            return BrowserActionRisk(
                sensitive=True,
                level="high",
                kind="submission",
                reason="accepting a browser dialog may submit state",
                matched=("dialog.accept",),
            )
        return BrowserActionRisk(
            sensitive=False,
            level="low",
            kind="navigation",
            reason="dismissing a browser dialog is non-sensitive",
            matched=("dialog.dismiss",),
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
    keywords: Collection[str],
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


def _bool_arg(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


__all__ = [
    "RISK_ACTIONS_BY_KIND",
    "RISK_KEYWORDS_BY_KIND",
    "classify_browser_action",
]
