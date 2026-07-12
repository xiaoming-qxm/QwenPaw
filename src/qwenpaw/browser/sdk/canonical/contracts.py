# -*- coding: utf-8 -*-
"""Canonical Browser public contract facts for S0."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CapabilityBlocked:
    """Machine-readable result for a not-yet-activated capability."""

    capability: str
    code: str = "browser_sdk_gap"


def canonical_api_catalog() -> dict[str, Any]:
    """Return the S0 canonical lifecycle-only API catalog."""
    return {
        "version": 1,
        "mode": "CANONICAL",
        "source": "canonical_browser_api",
        "apis": [
            _entry(
                "browser.close",
                "qwenpaw.browser.sdk.canonical.facade:Browser.close",
                "async close() -> None",
                mutates=True,
                summary="Release the current SDK lease only.",
            ),
            _entry(
                "browser.connect",
                "qwenpaw.browser.sdk.canonical.facade:Browser.connect",
                (
                    "async connect(context: Literal['auto', 'user', "
                    "'isolated'] = 'auto') -> Browser"
                ),
                mutates=False,
                summary="Connect with the trusted root-task binding.",
                parameters=[
                    {
                        "name": "context",
                        "kind": "POSITIONAL_OR_KEYWORD",
                        "required": False,
                        "default": "auto",
                        "annotation": "Literal['auto', 'user', 'isolated']",
                    },
                ],
            ),
        ],
    }


def _entry(
    api_id: str,
    callable_path: str,
    signature: str,
    *,
    mutates: bool,
    summary: str,
    parameters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "api_id": api_id,
        "public_name": api_id,
        "kind": "lifecycle",
        "visibility": "default",
        "mutates": mutates,
        "requires_observation": False,
        "satisfies_observation": False,
        "invalidates_observation": False,
        "callable_path": callable_path,
        "signature": signature,
        "parameters": parameters or [],
        "return_type": "None" if api_id == "browser.close" else "Browser",
        "summary": summary,
    }


__all__ = ["CapabilityBlocked", "canonical_api_catalog"]
