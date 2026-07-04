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
from .error_codes import (
    BrowserErrorCode,
    BrowserErrorInfo,
    BrowserOutcome,
    classify_browser_error,
)
from .policy import BrowserPolicy, DefaultBrowserPolicy
from .progress import (
    BrowserActionSignature,
    BrowserProgressDecision,
    detect_no_progress,
)
from .resolver import BrowserContextResolver
from .risk import classify_browser_action
from .trace import (
    BrowserTraceEvent,
    BrowserTraceStore,
    get_browser_trace_store,
    record_browser_trace_event,
    reset_browser_trace_store_for_tests,
)
from .types import (
    BrowserActionRequest,
    BrowserActionResult,
    BrowserActionRisk,
    BrowserBackendCapabilities,
    BrowserBackendDiagnostic,
    BrowserContext,
    BrowserContextRequest,
    BrowserDiagnosticCheck,
    BrowserDiagnosticStatus,
    BrowserDiagnostics,
    BrowserExtractionResult,
    BrowserObservation,
    BrowserPageInfo,
    BrowserPolicyDecision,
    BrowserRiskKind,
    BrowserRiskLevel,
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
    "BrowserActionRisk",
    "BrowserActionSignature",
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
    "BrowserDiagnosticCheck",
    "BrowserDiagnosticStatus",
    "BrowserDiagnostics",
    "BrowserErrorCode",
    "BrowserErrorInfo",
    "BrowserExtractionResult",
    "BrowserObservation",
    "BrowserObservationRequired",
    "BrowserPageInfo",
    "BrowserPolicy",
    "BrowserPolicyDecision",
    "BrowserPolicyDenied",
    "BrowserProgressDecision",
    "BrowserOutcome",
    "BrowserRiskKind",
    "BrowserRiskLevel",
    "BrowserSDKError",
    "BrowserSDKGap",
    "BrowserScreenshot",
    "BrowserSession",
    "BrowserTraceEvent",
    "BrowserTraceStore",
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
    "classify_browser_action",
    "classify_browser_error",
    "detect_no_progress",
    "get_browser_trace_store",
    "get_default_backend_registry",
    "record_browser_trace_event",
    "register_isolated_backend_once",
    "register_user_backend_once",
    "reset_browser_trace_store_for_tests",
]
