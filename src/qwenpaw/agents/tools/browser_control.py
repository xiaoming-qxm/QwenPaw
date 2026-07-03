# -*- coding: utf-8 -*-
"""Backward-compatible shim for the browser tool package."""

from qwenpaw.browser.control_plugin import load_browser_control_submodule

from .browser import entry as _entry

browser_use = getattr(_entry, "browser_use")
legacy_browser_use_bypass = getattr(_entry, "legacy_browser_use_bypass")
stop_all_browsers = getattr(_entry, "stop_all_browsers")
stop_browsers_for_workspace_dirs = getattr(
    _entry,
    "stop_browsers_for_workspace_dirs",
)
_action_control = getattr(_entry, "_action_control")


def _control_tab_manager():
    return load_browser_control_submodule("engine.tab_manager")


async def cleanup_control_sessions_for_request(**kwargs):
    """Release and close browser-control resources for one request."""
    manager = _control_tab_manager()
    return await manager.cleanup_control_sessions_for_request(**kwargs)


async def release_control_sessions_for_request(**kwargs):
    """Release browser-control leases for one completed request."""
    manager = _control_tab_manager()
    return await manager.release_control_sessions_for_request(**kwargs)


__all__ = [
    "browser_use",
    "legacy_browser_use_bypass",
    "cleanup_control_sessions_for_request",
    "release_control_sessions_for_request",
    "stop_all_browsers",
    "stop_browsers_for_workspace_dirs",
]
