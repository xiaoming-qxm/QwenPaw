# -*- coding: utf-8 -*-
"""Browser Bridge exception hierarchy."""

from __future__ import annotations

from qwenpaw.browser.governance.error_codes import BrowserErrorCode


class BrowserBridgeError(Exception):
    """Root Browser Bridge error."""


class BrowserBridgeRecoverableError(BrowserBridgeError):
    """Expected Browser Bridge failure converted to tool output."""


class BrowserBridgeTimeout(BrowserBridgeRecoverableError):
    """Expected timeout from a bounded Browser Bridge protocol wait."""

    code = BrowserErrorCode.NETWORK_TIMEOUT.value

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.browser_error_code = code or self.code


class TargetResolutionFailed(BrowserBridgeRecoverableError):
    """Raised when a target ref, selector, text, or point cannot resolve."""


class CDPCommandFailed(BrowserBridgeRecoverableError):
    """Raised when a CDP command fails without disconnecting the bridge."""


class CDPCommandTimeout(CDPCommandFailed, BrowserBridgeTimeout):
    """Raised when a bounded CDP command wait expires."""

    code = BrowserErrorCode.CDP_COMMAND_TIMEOUT.value


class TabNotFoundError(BrowserBridgeRecoverableError):
    """Raised when the requested browser tab no longer exists."""


class SnapshotBuildFailed(BrowserBridgeRecoverableError):
    """Raised when snapshot construction fails and can be degraded."""


class DOMSettleTimeout(SnapshotBuildFailed, BrowserBridgeTimeout):
    """Raised when a bounded DOM observation wait expires."""

    code = BrowserErrorCode.DOM_SETTLE_TIMEOUT.value


class NavigationFailed(BrowserBridgeRecoverableError):
    """Raised when a navigation operation fails in a recoverable way."""


class NetworkSettleTimeout(BrowserBridgeRecoverableError):
    """Raised when network quiescence does not settle before its deadline."""

    browser_error_code = BrowserErrorCode.NETWORK_SETTLE_TIMEOUT.value


class DownloadTimeout(BrowserBridgeTimeout):
    """Raised when download completion does not arrive before its deadline."""

    code = BrowserErrorCode.DOWNLOAD_TIMEOUT.value


class NMBridgeDisconnectedError(BrowserBridgeError):
    """Raised when Native Messaging bridge connectivity is lost."""


class SessionExpiredError(BrowserBridgeError):
    """Raised when a browser-bridge session is no longer valid."""


RECOVERABLE_CONTROL_EXCEPTIONS: tuple[type[BaseException], ...] = (
    BrowserBridgeRecoverableError,
)


__all__ = [
    "BrowserBridgeError",
    "BrowserBridgeRecoverableError",
    "BrowserBridgeTimeout",
    "CDPCommandFailed",
    "CDPCommandTimeout",
    "DOMSettleTimeout",
    "DownloadTimeout",
    "NMBridgeDisconnectedError",
    "NavigationFailed",
    "NetworkSettleTimeout",
    "RECOVERABLE_CONTROL_EXCEPTIONS",
    "SessionExpiredError",
    "SnapshotBuildFailed",
    "TabNotFoundError",
    "TargetResolutionFailed",
]
