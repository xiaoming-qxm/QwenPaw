# -*- coding: utf-8 -*-
"""Browser tool implementation package."""

from . import entry as _entry
from .models import ActionResult, ElementTarget, SessionContext, SnapshotResult
from .observe_act import ObservationRequired, ObserveActGuard
from .state import BrowserState, ControlSessionState, TabState

browser_use = getattr(_entry, "browser_use")
legacy_browser_use_bypass = getattr(_entry, "legacy_browser_use_bypass")
stop_all_browsers = getattr(_entry, "stop_all_browsers")

__all__ = [
    "ActionResult",
    "BrowserState",
    "ControlSessionState",
    "ElementTarget",
    "ObservationRequired",
    "ObserveActGuard",
    "SessionContext",
    "SnapshotResult",
    "TabState",
    "browser_use",
    "legacy_browser_use_bypass",
    "stop_all_browsers",
]
