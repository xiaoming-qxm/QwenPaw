# -*- coding: utf-8 -*-
"""Browser Control SDK public interface."""

from __future__ import annotations

from .errors import (
    BridgeDisconnected,
    BrowserSDKError,
    ObservationRequired,
    StaleLease,
    TabOccupied,
)
from .browser import Browser, Tabs
from .guard import ObserveActGuard
from .remote_bridge import RemoteBridge, resolve_sdk_ws_url
from .tab import Tab
from .types import (
    ActionResult,
    ClickResult,
    RefInfo,
    Snapshot,
    TabInfo,
    TypeResult,
)

__all__ = [
    "ActionResult",
    "BridgeDisconnected",
    "Browser",
    "BrowserSDKError",
    "ClickResult",
    "ObservationRequired",
    "ObserveActGuard",
    "RefInfo",
    "RemoteBridge",
    "Snapshot",
    "StaleLease",
    "Tab",
    "TabInfo",
    "TabOccupied",
    "Tabs",
    "TypeResult",
    "resolve_sdk_ws_url",
]
