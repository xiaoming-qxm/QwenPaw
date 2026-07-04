# -*- coding: utf-8 -*-
"""Unified browser automation SDK for QwenPaw agents."""

from .backend_registry import (
    BrowserBackendRegistry,
    get_default_backend_registry,
)
from .backend_protocols import BrowserBackend, BrowserSession
from .browser import Browser, connect_browser
from .actions import BrowserActions, TabActions
from .backends.isolated import (
    IsolatedBrowserBackend,
    register_isolated_backend_once,
)
from .backends.user import (
    ChromeExtensionBrowserBackend,
    register_user_backend_once,
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
from .resolver import BrowserContextResolver
from .types import (
    BrowserActionRequest,
    BrowserActionResult,
    BrowserBackendCapabilities,
    BrowserBackendDiagnostic,
    BrowserContext,
    BrowserContextRequest,
    BrowserDiagnostics,
    BrowserExtractionResult,
    BrowserObservation,
    BrowserPageInfo,
    BrowserPolicyDecision,
    BrowserScreenshot,
    ConcreteBrowserContext,
    ExtractionFormat,
    ResolvedBrowserContext,
)
from .tab import Tab
from .tabs import Tabs

__all__ = [
    "BrowserActionRequest",
    "BrowserActionResult",
    "Browser",
    "BrowserActions",
    "BrowserBackend",
    "BrowserBackendCapabilities",
    "BrowserBackendDiagnostic",
    "BrowserBackendRegistry",
    "BrowserContext",
    "BrowserContextConflict",
    "BrowserContextRequest",
    "BrowserContextResolver",
    "BrowserContextUnavailable",
    "BrowserDiagnostics",
    "BrowserExtractionResult",
    "BrowserObservation",
    "BrowserObservationRequired",
    "BrowserPageInfo",
    "BrowserPolicy",
    "BrowserPolicyDecision",
    "BrowserPolicyDenied",
    "BrowserSDKError",
    "BrowserSDKGap",
    "BrowserScreenshot",
    "BrowserSession",
    "ChromeExtensionBrowserBackend",
    "ConcreteBrowserContext",
    "DefaultBrowserPolicy",
    "ExtractionFormat",
    "IsolatedBrowserBackend",
    "ResolvedBrowserContext",
    "Tab",
    "TabActions",
    "Tabs",
    "connect_browser",
    "get_default_backend_registry",
    "register_isolated_backend_once",
    "register_user_backend_once",
]
