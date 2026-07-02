# -*- coding: utf-8 -*-
"""Browser Control SDK error hierarchy."""

from __future__ import annotations


class BrowserSDKError(RuntimeError):
    """Base SDK error."""


class ObservationRequired(BrowserSDKError):
    """Raised when mutating action lacks fresh observation."""


class TabOccupied(BrowserSDKError):
    """Raised when tab is held by another holder."""


class StaleLease(BrowserSDKError):
    """Raised when lease version is outdated."""


class BridgeDisconnected(BrowserSDKError):
    """Raised when WS connection to bridge is lost."""
