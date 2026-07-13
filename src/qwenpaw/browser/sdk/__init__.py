# -*- coding: utf-8 -*-
"""Unified browser automation SDK for QwenPaw agents."""

from .backends import (
    IsolatedBrowserBackend,
    register_isolated_backend_once,
)
from .backends.protocols import BrowserBackend, BrowserSession
from .backends.registry import (
    BrowserBackendRegistry,
    get_default_backend_registry,
)
from .canonical.contracts import (
    BrowserCondition,
    ResourceHandle,
    TabSummary,
    TargetRef,
)
from .canonical.facade import Browser
from .canonical.tabs import BrowserTabs, Tab, TabActions
from .docs.capabilities import (
    browser_capabilities,
    browser_sdk_help,
    capability_gap,
)
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
from .primitives.types import (
    BrowserActionRequest,
    BrowserActionResult,
    BrowserActionRisk,
    BrowserBackendCapabilities,
    BrowserBackendDiagnostic,
    BrowserBoundaryEvidence,
    BrowserBoundarySeverity,
    BrowserCapabilityClass,
    BrowserContext,
    BrowserContextRequest,
    BrowserDiagnosticCheck,
    BrowserDiagnosticStatus,
    BrowserDiagnostics,
    BrowserEvidenceSource,
    BrowserIntent,
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
    BrowserProductPolicy,
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

connect_browser = Browser.connect

__all__ = [
    "BrowserActionRequest",
    "BrowserActionResult",
    "BrowserActionRisk",
    "BrowserActionSignature",
    "Browser",
    "BrowserBackend",
    "BrowserBackendCapabilities",
    "BrowserBackendDiagnostic",
    "BrowserBackendRegistry",
    "BrowserBoundaryEvidence",
    "BrowserBoundarySeverity",
    "BrowserCapabilityClass",
    "BrowserContext",
    "BrowserContextConflict",
    "BrowserContextRequest",
    "BrowserContextResolver",
    "BrowserContextUnavailable",
    "BrowserCondition",
    "BrowserDiagnosticCheck",
    "BrowserDiagnosticStatus",
    "BrowserDiagnostics",
    "BrowserEvidenceSource",
    "BrowserIntent",
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
    "BrowserProductPolicy",
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
    "ResourceHandle",
    "Tab",
    "TabSummary",
    "TabActions",
    "TargetRef",
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
