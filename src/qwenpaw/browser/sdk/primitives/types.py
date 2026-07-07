# -*- coding: utf-8 -*-
"""Public types for the unified Browser SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BrowserContext = Literal["auto", "user", "isolated"]
ConcreteBrowserContext = Literal["user", "isolated"]
BrowserIntent = Literal["ambiguous", "public", "user_state"]
BrowserCapabilityClass = Literal[
    "observation",
    "navigation",
    "input",
    "commerce",
    "credential",
    "file_transfer",
    "dialog",
    "script",
    "unknown_write",
]
BrowserEvidenceSource = Literal[
    "dom",
    "aria",
    "snapshot",
    "screenshot",
    "visual",
    "kwargs",
    "backend",
    "unknown",
]
BrowserBoundarySeverity = Literal[
    "operational",
    "sensitive",
    "critical_known",
    "critical_unknown",
]
ExtractionFormat = Literal["text", "json"]
BrowserDiagnosticStatus = Literal[
    "available",
    "unavailable",
    "degraded",
    "unknown",
]
BrowserRiskLevel = Literal["none", "low", "medium", "high"]
BrowserRiskKind = Literal[
    "read",
    "navigation",
    "destructive",
    "purchase",
    "payment",
    "submission",
    "upload",
    "download",
    "credential",
    "unknown_sensitive",
    "unknown_write",
]


@dataclass(frozen=True)
class ResolvedBrowserContext:
    """Concrete backend chosen for one browser SDK request."""

    requested: BrowserContext
    selected: ConcreteBrowserContext
    reason: str
    requires_user_state: bool
    backend_id: str
    browser_intent: BrowserIntent = "ambiguous"
    preferred_backend_id: str = ""
    selected_backend_degraded: bool = False
    fallback_allowed: bool = False
    fallback_reason: str = ""
    auto_route_policy: str = ""


@dataclass(frozen=True)
class BrowserBackendCapabilities:
    """Static capabilities advertised by a browser backend."""

    backend_id: str
    browser_context: ConcreteBrowserContext
    supports_primitives: bool = True
    supports_actions: bool = True
    supports_extraction: bool = True
    features: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class BrowserDiagnosticCheck:
    """One diagnostic check contributing to backend availability."""

    name: str
    status: BrowserDiagnosticStatus
    code: str = ""
    message: str = ""
    hint_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserBackendDiagnostic:
    """Availability diagnostic for one Browser SDK backend."""

    backend_id: str
    browser_context: ConcreteBrowserContext
    available: bool
    code: str = ""
    reason: str = ""
    status: BrowserDiagnosticStatus = "unknown"
    message: str = ""
    hint_key: str = ""
    message_fallback: str = ""
    checks: tuple[BrowserDiagnosticCheck, ...] = ()
    observed_at: str = ""
    features: frozenset[str] = field(default_factory=frozenset)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserDiagnostics:
    """Availability diagnostics for registered Browser SDK backends."""

    requested_context: BrowserContext
    selected_backend_id: str = ""
    backends: tuple[BrowserBackendDiagnostic, ...] = ()
    preferred_backend_id: str = ""
    selected_backend_degraded: bool = False
    fallback_allowed: bool = False
    fallback_reason: str = ""
    auto_route_policy: str = ""


@dataclass(frozen=True)
class BrowserBoundaryEvidence:
    """Evidence used to classify a Browser boundary decision."""

    source: BrowserEvidenceSource
    label: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserActionRisk:
    """Structured risk classification for one browser action."""

    sensitive: bool
    level: BrowserRiskLevel
    kind: BrowserRiskKind
    reason: str = ""
    matched: tuple[str, ...] = ()
    capability_class: BrowserCapabilityClass = "navigation"
    boundary_severity: BrowserBoundarySeverity = "operational"
    confidence: float = 0.0
    evidence: tuple[BrowserBoundaryEvidence, ...] = ()
    decision_reason: str = ""
    consequence_summary: str = ""
    error_code: str = ""


@dataclass(frozen=True)
class BrowserContextRequest:
    """Policy input for acquiring a browser context."""

    session_id: str
    requested_context: BrowserContext
    selected_context: ConcreteBrowserContext
    requires_user_state: bool
    backend_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserActionRequest:
    """Policy input for executing a browser action."""

    session_id: str
    action: str
    context: ResolvedBrowserContext
    sensitive: bool = False
    risk: BrowserActionRisk | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserPolicyDecision:
    """Allow/deny result returned by browser policy hooks."""

    allowed: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserObservation:
    """Textual browser observation for a tab."""

    tab_id: str
    text: str
    url: str = ""
    title: str = ""
    refs: dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserScreenshot:
    """Visual browser observation for a tab."""

    tab_id: str
    path: str = ""
    media_type: str = "image/png"
    url: str = ""
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserPageInfo:
    """Read-only browser page metadata for a tab."""

    tab_id: str
    url: str = ""
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserArtifact:
    """Browser SDK artifact emitted by a browser tool execution."""

    kind: str
    url: str
    media_type: str
    name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserActionResult:
    """Result of a primitive or structured browser action."""

    ok: bool
    message: str = ""
    needs_observation: bool = True
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserExtractionResult:
    """Result of lightweight text or JSON extraction."""

    ok: bool
    format: ExtractionFormat
    text: str = ""
    data: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "BrowserActionRequest",
    "BrowserActionResult",
    "BrowserActionRisk",
    "BrowserArtifact",
    "BrowserBackendCapabilities",
    "BrowserBackendDiagnostic",
    "BrowserBoundaryEvidence",
    "BrowserBoundarySeverity",
    "BrowserCapabilityClass",
    "BrowserContext",
    "BrowserContextRequest",
    "BrowserDiagnosticCheck",
    "BrowserDiagnosticStatus",
    "BrowserDiagnostics",
    "BrowserEvidenceSource",
    "BrowserIntent",
    "BrowserExtractionResult",
    "BrowserObservation",
    "BrowserPageInfo",
    "BrowserPolicyDecision",
    "BrowserRiskKind",
    "BrowserRiskLevel",
    "BrowserScreenshot",
    "ConcreteBrowserContext",
    "ExtractionFormat",
    "ResolvedBrowserContext",
]
