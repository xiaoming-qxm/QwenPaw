# -*- coding: utf-8 -*-
"""Browser SDK generated capability docs and gap helpers."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from ..governance.errors import BrowserSDKGap


def browser_capabilities(scope: str = "all") -> dict[str, Any]:
    """Return generated public Browser SDK capabilities."""
    capabilities = _generated_capabilities()
    normalized_scope = _normalize_scope(scope)
    if normalized_scope == "all":
        return dict(capabilities)
    scopes = capabilities["scopes"]
    if normalized_scope not in scopes:
        raise BrowserSDKGap(
            f"Unknown Browser capabilities scope: {scope}",
            action="browser.capabilities",
            metadata={"available_scopes": tuple(sorted(scopes))},
        )
    api_ids = scopes[normalized_scope]
    return {
        "version": capabilities["version"],
        "source": capabilities["source"],
        "scope": normalized_scope,
        "apis": {api_id: capabilities["apis"][api_id] for api_id in api_ids},
    }


def browser_sdk_help(
    scope: str | None = None,
    api_id: str | None = None,
) -> str:
    """Return generated model-facing Browser SDK usage help."""
    help_payload = _generated_capabilities().get("help") or {}
    if api_id:
        api_help = help_payload.get("apis") or {}
        normalized_api_id = str(api_id).strip()
        if normalized_api_id in api_help:
            return str(api_help[normalized_api_id])
        raise BrowserSDKGap(
            f"Unknown Browser help API id: {api_id}",
            action="browser.help",
            metadata={"available_api_ids": tuple(sorted(api_help))},
        )
    if scope:
        scope_help = help_payload.get("scopes") or {}
        normalized_scope = _normalize_scope(scope)
        if normalized_scope in scope_help:
            return str(scope_help[normalized_scope])
        raise BrowserSDKGap(
            f"Unknown Browser help scope: {scope}",
            action="browser.help",
            metadata={"available_scopes": tuple(sorted(scope_help))},
        )
    return str(help_payload.get("index") or "")


def capability_gap(action: str, message: str) -> dict[str, Any]:
    """Return a typed generic capability-missing payload."""
    return BrowserSDKGap(
        message,
        action=str(action or "browser"),
    ).to_dict()


@lru_cache(maxsize=1)
def _generated_capabilities() -> dict[str, Any]:
    artifact = (
        resources.files("qwenpaw.browser.sdk")
        / "generated"
        / "capabilities.json"
    )
    return json.loads(artifact.read_text(encoding="utf-8"))


def _normalize_scope(scope: str | None) -> str:
    normalized = str(scope or "all").strip().casefold()
    return normalized or "all"


__all__ = [
    "browser_capabilities",
    "browser_sdk_help",
    "capability_gap",
]
