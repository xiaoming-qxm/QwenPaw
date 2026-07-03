# -*- coding: utf-8 -*-
"""Browser Control exception hierarchy."""

from __future__ import annotations


class BrowserControlError(Exception):
    """Root Browser Control error."""


class BrowserControlRecoverableError(BrowserControlError):
    """Expected Browser Control failure converted to tool output."""


class TargetResolutionFailed(BrowserControlRecoverableError):
    """Raised when a target ref, selector, text, or point cannot resolve."""


class CDPCommandFailed(BrowserControlRecoverableError):
    """Raised when a CDP command fails without disconnecting the bridge."""


class TabNotFoundError(BrowserControlRecoverableError):
    """Raised when the requested browser tab no longer exists."""


class SnapshotBuildFailed(BrowserControlRecoverableError):
    """Raised when snapshot construction fails and can be degraded."""


class NavigationFailed(BrowserControlRecoverableError):
    """Raised when a navigation operation fails in a recoverable way."""


class NetworkSettleTimeout(BrowserControlRecoverableError):
    """Raised when network quiescence does not settle before its deadline."""


class NMBridgeDisconnectedError(BrowserControlError):
    """Raised when Native Messaging bridge connectivity is lost."""


class SessionExpiredError(BrowserControlError):
    """Raised when a browser-control session is no longer valid."""


RECOVERABLE_CONTROL_EXCEPTIONS: tuple[type[BaseException], ...] = (
    BrowserControlRecoverableError,
)


__all__ = [
    "BrowserControlError",
    "BrowserControlRecoverableError",
    "CDPCommandFailed",
    "NMBridgeDisconnectedError",
    "NavigationFailed",
    "NetworkSettleTimeout",
    "RECOVERABLE_CONTROL_EXCEPTIONS",
    "SessionExpiredError",
    "SnapshotBuildFailed",
    "TabNotFoundError",
    "TargetResolutionFailed",
]
