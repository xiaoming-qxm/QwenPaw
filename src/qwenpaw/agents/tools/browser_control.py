# -*- coding: utf-8 -*-
"""Backward-compatible shim for the browser tool package."""

from .browser import entry as _entry

browser_use = getattr(_entry, "browser_use")
stop_all_browsers = getattr(_entry, "stop_all_browsers")
stop_browsers_for_workspace_dirs = getattr(
    _entry,
    "stop_browsers_for_workspace_dirs",
)
cleanup_control_sessions_for_request = getattr(
    _entry,
    "cleanup_control_sessions_for_request",
)
release_control_sessions_for_request = getattr(
    _entry,
    "release_control_sessions_for_request",
)
_action_control = getattr(_entry, "_action_control")

__all__ = [
    "browser_use",
    "cleanup_control_sessions_for_request",
    "release_control_sessions_for_request",
    "stop_all_browsers",
    "stop_browsers_for_workspace_dirs",
]
