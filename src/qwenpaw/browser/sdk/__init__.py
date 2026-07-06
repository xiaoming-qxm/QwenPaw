# -*- coding: utf-8 -*-
"""Unified browser automation SDK for QwenPaw agents."""

from .actions.tab_actions import BrowserActions, TabActions
from .backends import (
    IsolatedBrowserBackend,
    register_isolated_backend_once,
)
from .backends.protocols import BrowserBackend, BrowserSession
from .backends.registry import (
    BrowserBackendRegistry,
    get_default_backend_registry,
)
from .docs.capabilities import (
    browser_capabilities,
    browser_sdk_help,
    capability_gap,
)
from .facade.browser import Browser, connect_browser
from .governance.error_codes import (
    BrowserErrorCode,
    BrowserErrorInfo,
    BrowserOutcome,
    classify_browser_error,
)
from .governance.errors import (
    BrowserContextConflict,
    BrowserContextUnavailable,
    BrowserObservationRequired,
    BrowserPolicyDenied,
    BrowserSDKError,
    BrowserSDKGap,
)
from .governance.loop_gate import (
    BrowserGate,
    BrowserLoopGateProvider,
    register_browser_loop_gate_provider_once,
)
from .governance.policy import BrowserPolicy, DefaultBrowserPolicy
from .governance.resolver import BrowserContextResolver
from .governance.risk import classify_browser_action
from .primitives.tab import Tab
from .primitives.tabs import BrowserTabs
from .primitives.types import (
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
from .recovery import (
    BrowserRecoveryAction,
    BrowserRecoveryDecision,
    BrowserRecoveryPolicy,
    BrowserRequestEvidence,
    collect_browser_request_evidence,
)
from .telemetry.progress import (
    BrowserActionSignature,
    BrowserProgressDecision,
    detect_no_progress,
)
from .telemetry.trace import (
    BrowserTraceEvent,
    BrowserTraceStore,
    get_browser_trace_store,
    record_browser_trace_event,
    reset_browser_trace_store_for_tests,
)

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
    "BrowserGate",
    "BrowserLoopGateProvider",
    "BrowserObservation",
    "BrowserObservationRequired",
    "BrowserOutcome",
    "BrowserPageInfo",
    "BrowserPolicy",
    "BrowserPolicyDecision",
    "BrowserPolicyDenied",
    "BrowserProgressDecision",
    "BrowserRecoveryAction",
    "BrowserRecoveryDecision",
    "BrowserRecoveryPolicy",
    "BrowserRequestEvidence",
    "BrowserRiskKind",
    "BrowserRiskLevel",
    "BrowserSDKError",
    "BrowserSDKGap",
    "BrowserScreenshot",
    "BrowserSession",
    "BrowserTabs",
    "BrowserTraceEvent",
    "BrowserTraceStore",
    "ConcreteBrowserContext",
    "DefaultBrowserPolicy",
    "ExtractionFormat",
    "IsolatedBrowserBackend",
    "ResolvedBrowserContext",
    "Tab",
    "TabActions",
    "browser_capabilities",
    "browser_sdk_help",
    "capability_gap",
    "classify_browser_action",
    "classify_browser_error",
    "collect_browser_request_evidence",
    "connect_browser",
    "detect_no_progress",
    "get_browser_trace_store",
    "get_default_backend_registry",
    "record_browser_trace_event",
    "register_browser_loop_gate_provider_once",
    "register_isolated_backend_once",
    "reset_browser_trace_store_for_tests",
]
