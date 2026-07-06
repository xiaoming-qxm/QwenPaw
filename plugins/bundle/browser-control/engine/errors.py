# -*- coding: utf-8 -*-
"""Browser Control exception hierarchy."""

from __future__ import annotations

from qwenpaw.browser.sdk.governance.error_codes import BrowserErrorCode


class BrowserControlError(Exception):
    """Root Browser Control error."""


class BrowserControlRecoverableError(BrowserControlError):
    """Expected Browser Control failure converted to tool output."""


class BrowserControlTimeout(BrowserControlRecoverableError):
    """Expected timeout from a bounded Browser Control protocol wait."""

    code = BrowserErrorCode.NETWORK_TIMEOUT.value

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.browser_error_code = code or self.code


class TargetResolutionFailed(BrowserControlRecoverableError):
    """Raised when a target ref, selector, text, or point cannot resolve."""


class CDPCommandFailed(BrowserControlRecoverableError):
    """Raised when a CDP command fails without disconnecting the bridge."""


class CDPCommandTimeout(CDPCommandFailed, BrowserControlTimeout):
    """Raised when a bounded CDP command wait expires."""

    code = BrowserErrorCode.CDP_COMMAND_TIMEOUT.value


class TabNotFoundError(BrowserControlRecoverableError):
    """Raised when the requested browser tab no longer exists."""


class SnapshotBuildFailed(BrowserControlRecoverableError):
    """Raised when snapshot construction fails and can be degraded."""


class DOMSettleTimeout(SnapshotBuildFailed, BrowserControlTimeout):
    """Raised when a bounded DOM observation wait expires."""

    code = BrowserErrorCode.DOM_SETTLE_TIMEOUT.value


class NavigationFailed(BrowserControlRecoverableError):
    """Raised when a navigation operation fails in a recoverable way."""


class NetworkSettleTimeout(BrowserControlRecoverableError):
    """Raised when network quiescence does not settle before its deadline."""

    browser_error_code = BrowserErrorCode.NETWORK_SETTLE_TIMEOUT.value


class DownloadTimeout(BrowserControlTimeout):
    """Raised when download completion does not arrive before its deadline."""

    code = BrowserErrorCode.DOWNLOAD_TIMEOUT.value


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
    "BrowserControlTimeout",
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
