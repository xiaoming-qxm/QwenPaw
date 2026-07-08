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
        "ownership_protocol_version": 2,
        "contexts": ("auto", "user", "isolated"),
        "routing": {
            "contract": "V12 Browser Routing And Permission Contract",
            "auto_route_policy": "auto_user_chrome_first",
            "auto_preferred_backend": "user.chrome_extension",
            "degraded_fallback_backend": "isolated.playwright",
            "degraded_fallback_for": ("public", "ambiguous"),
            "user_state_fail_closed": True,
            "requires_user_state_flag": "requires_user_state=True",
        },
        "primitives": (
            "tabs.open",
            "tabs.new",
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
        "tab_semantics": {
            "open": "reuse_request_workspace_tab_with_target_url",
            "new": "explicit_new_tab_requires_target_url",
            "active": "return_existing_request_tab_without_creation",
        },
        "diagnostics": {
            "user_backend": (
                "connected_routable_actionable_cleanup_verified"
            ),
        },
        "actions": actions,
        "limits": {
            "requires_fresh_observe_after_mutation": True,
            "mutation_observations": ("snapshot", "screenshot"),
            "download_max_wait_ms_default": 30000,
            "raw_cdp_public_hot_path": False,
            "raw_cdp_public_entrypoint": False,
            "normal_task_blank_tab_creation": False,
        },
    }


def browser_sdk_help() -> str:
    """Return concise model-facing Browser SDK usage help."""
    capabilities = browser_capabilities()
    actions = ", ".join(sorted(capabilities["actions"]))
    return "\n".join(
        (
            'Browser.connect(context="auto") auto prefers user Chrome.',
            "Protocol v2: start normal page work with "
            "tabs.open(target_url), which reuses the request workspace tab.",
            "Use tabs.new(target_url) only for an explicit additional tab; "
            "tabs.active() never creates a tab.",
            "Browser.diagnostics() checks connected, routable, actionable, "
            "and cleanup_verified health.",
            "Use requires_user_state=True for logged-in or existing-tab work.",
            "Degraded isolated fallback is only for public or ambiguous work "
            "when user Chrome is unavailable.",
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
