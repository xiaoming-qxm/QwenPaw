# -*- coding: utf-8 -*-
"""Public types for the unified Browser SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BrowserContext = Literal["auto", "user", "isolated"]
ConcreteBrowserContext = Literal["user", "isolated"]
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
]


@dataclass(frozen=True)
class ResolvedBrowserContext:
    """Concrete backend chosen for one browser SDK request."""

    requested: BrowserContext
    selected: ConcreteBrowserContext
    reason: str
    requires_user_state: bool
    backend_id: str


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


@dataclass(frozen=True)
class BrowserActionRisk:
    """Structured risk classification for one browser action."""

    sensitive: bool
    level: BrowserRiskLevel
    kind: BrowserRiskKind
    reason: str = ""
    matched: tuple[str, ...] = ()


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
    "BrowserContext",
    "BrowserContextRequest",
    "BrowserDiagnosticCheck",
    "BrowserDiagnosticStatus",
    "BrowserDiagnostics",
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
