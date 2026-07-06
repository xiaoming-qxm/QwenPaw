# -*- coding: utf-8 -*-
"""Browser SDK public capability docs and gap helpers."""

from __future__ import annotations

from typing import Any

from ..governance.errors import BrowserSDKGap


def browser_capabilities() -> dict[str, Any]:
    """Return the compact public Browser SDK capability contract."""
    actions = {
        "navigate": {
            "kind": "mutation",
            "kwargs": ("url",),
        },
        "back": {"kind": "mutation", "kwargs": ()},
        "forward": {"kind": "mutation", "kwargs": ()},
        "reload": {"kind": "mutation", "kwargs": ()},
        "click": {
            "kind": "mutation",
            "kwargs": (
                "target",
                "selector",
                "ref",
                "text",
                "x",
                "y",
                "allow_new_context",
            ),
        },
        "type": {
            "kind": "mutation",
            "kwargs": ("target", "selector", "ref", "text"),
        },
        "press": {"kind": "mutation", "kwargs": ("key",)},
        "scroll": {"kind": "mutation", "kwargs": ("direction", "amount")},
        "select": {
            "kind": "mutation",
            "kwargs": ("target", "selector", "ref", "value"),
        },
        "upload": {
            "kind": "mutation",
            "kwargs": ("target", "selector", "ref", "file_path"),
        },
        "download": {
            "kind": "transition",
            "kwargs": ("target", "selector", "ref", "max_wait_ms"),
        },
        "dialog": {
            "kind": "transition",
            "kwargs": ("accept", "prompt_text"),
        },
        "hover": {
            "kind": "mutation",
            "kwargs": ("target", "selector", "ref", "text"),
        },
        "wait_for": {
            "kind": "read_transition",
            "kwargs": ("instruction", "max_wait_ms"),
        },
    }
    return {
        "contexts": ("auto", "user", "isolated"),
        "primitives": (
            "tabs.open",
            "tabs.active",
            "tabs.list",
            "tabs.select",
            "snapshot",
            "screenshot",
            "page_info",
            "evaluate",
            "extract",
            "close",
        ),
        "actions": actions,
        "limits": {
            "requires_fresh_observe_after_mutation": True,
            "mutation_observations": ("snapshot", "screenshot"),
            "download_max_wait_ms_default": 30000,
            "raw_cdp_public_hot_path": False,
        },
    }


def browser_sdk_help() -> str:
    """Return concise model-facing Browser SDK usage help."""
    capabilities = browser_capabilities()
    actions = ", ".join(sorted(capabilities["actions"]))
    return "\n".join(
        (
            'Browser.connect(context="auto") selects isolated or user Chrome.',
            "Use tab.snapshot() before every mutating action.",
            "Use tab.screenshot() for visual fallback evidence.",
            f"Available actions: {actions}.",
            "Examples: tab.actions.upload(target, file_path), "
            "tab.actions.download(target), tab.actions.dialog(accept=True), "
            "tab.actions.click(target, allow_new_context=True).",
        ),
    )


def capability_gap(action: str, message: str) -> dict[str, Any]:
    """Return a typed generic capability-missing payload."""
    return BrowserSDKGap(
        message,
        action=str(action or "browser"),
    ).to_dict()


__all__ = [
    "browser_capabilities",
    "browser_sdk_help",
    "capability_gap",
]
