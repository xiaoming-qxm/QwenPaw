# -*- coding: utf-8 -*-
"""Chrome exception hierarchy."""

from __future__ import annotations

from qwenpaw.browser.governance.error_codes import BrowserErrorCode


class ChromeError(Exception):
    """Root Chrome error."""


class ChromeRecoverableError(ChromeError):
    """Expected Chrome failure converted to tool output."""


class ChromeTimeout(ChromeRecoverableError):
    """Expected timeout from a bounded Chrome protocol wait."""

    code = BrowserErrorCode.NETWORK_TIMEOUT.value

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.browser_error_code = code or self.code


class TargetResolutionFailed(ChromeRecoverableError):
    """Raised when a target ref, selector, text, or point cannot resolve."""


class CDPCommandFailed(ChromeRecoverableError):
    """Raised when a CDP command fails without disconnecting the bridge."""


class CDPCommandTimeout(CDPCommandFailed, ChromeTimeout):
    """Raised when a bounded CDP command wait expires."""

    code = BrowserErrorCode.CDP_COMMAND_TIMEOUT.value


class TabNotFoundError(ChromeRecoverableError):
    """Raised when the requested browser tab no longer exists."""


class SnapshotBuildFailed(ChromeRecoverableError):
    """Raised when snapshot construction fails and can be degraded."""


class DOMSettleTimeout(SnapshotBuildFailed, ChromeTimeout):
    """Raised when a bounded DOM observation wait expires."""

    code = BrowserErrorCode.DOM_SETTLE_TIMEOUT.value


class NavigationFailed(ChromeRecoverableError):
    """Raised when a navigation operation fails in a recoverable way."""


class NetworkSettleTimeout(ChromeRecoverableError):
    """Raised when network quiescence does not settle before its deadline."""

    browser_error_code = BrowserErrorCode.NETWORK_SETTLE_TIMEOUT.value


class DownloadTimeout(ChromeTimeout):
    """Raised when download completion does not arrive before its deadline."""

    code = BrowserErrorCode.DOWNLOAD_TIMEOUT.value


class NMBridgeDisconnectedError(ChromeError):
    """Raised when Native Messaging bridge connectivity is lost."""


class SessionExpiredError(ChromeError):
    """Raised when a chrome session is no longer valid."""


RECOVERABLE_CONTROL_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ChromeRecoverableError,
)


__all__ = [
    "ChromeError",
    "ChromeRecoverableError",
    "ChromeTimeout",
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
