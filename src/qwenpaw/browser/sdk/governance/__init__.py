# -*- coding: utf-8 -*-
"""Browser SDK governance, policy, and error contracts."""

from .error_codes import (
    BrowserErrorCode,
    BrowserErrorInfo,
    BrowserOutcome,
    classify_browser_error,
)
from .errors import (
    BrowserContextConflict,
    BrowserContextUnavailable,
    BrowserObservationRequired,
    BrowserPolicyDenied,
    BrowserSDKError,
    BrowserSDKGap,
)
from .policy import BrowserPolicy, DefaultBrowserPolicy
from .risk import classify_browser_action

__all__ = [
    "BrowserContextConflict",
    "BrowserContextUnavailable",
    "BrowserErrorCode",
    "BrowserErrorInfo",
    "BrowserObservationRequired",
    "BrowserOutcome",
    "BrowserPolicy",
    "BrowserPolicyDenied",
    "BrowserSDKError",
    "BrowserSDKGap",
    "DefaultBrowserPolicy",
    "classify_browser_action",
    "classify_browser_error",
]
