# -*- coding: utf-8 -*-
"""Permissive compatibility hooks for retired Browser approvals.

The public symbols in this module remain available for extensions that still
construct Browser approval policies. Browser actions no longer use approval
services, caches, risk classification, or approval presentation.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from .action_runner import (
    ActionPreview,
    ApprovalGrant,
    issue_exact_grant,
)
from .governance.policy import TrustedSurfacePolicy
from .primitives.types import (
    BrowserActionRequest,
    BrowserContextRequest,
    BrowserPolicyDecision,
)
from qwenpaw.security.tool_guard.approval import ApprovalDecision
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel

_DEFAULT_CACHE_TTL_SECONDS = 120.0
_COMPATIBILITY_REASON = "browser_policy_compatibility_allow"


@dataclass(frozen=True)
class BrowserApprovalCacheKey:
    """Legacy cache-key value retained for import compatibility."""

    root_session_id: str
    approval_level: str
    domain: str
    action_family: str
    risk_kind: str
    source_type: str = "legacy_browser"


@dataclass(frozen=True)
class BrowserApprovalCacheEntry:
    """Legacy cache-entry value retained for import compatibility."""

    state: str
    expires_at: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BrowserApprovalResolution:
    """Compatibility result for former CDP approval callers."""

    allowed: bool
    reason: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BrowserExactApprovalResolution:
    """Compatibility result that immediately issues the existing grant."""

    pending: Any
    decision: ApprovalDecision
    grant: ApprovalGrant | None


class BrowserApprovalCache:
    """Inert legacy cache container; Browser execution never consults it."""

    def __init__(
        self,
        *,
        now: Callable[[], float] | None = None,
        ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._now = now or time.time
        self._ttl_seconds = float(ttl_seconds)
        self._items: dict[
            BrowserApprovalCacheKey,
            BrowserApprovalCacheEntry,
        ] = {}

    def get(
        self,
        key: BrowserApprovalCacheKey,
    ) -> BrowserApprovalCacheEntry | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._now():
            self._items.pop(key, None)
            return None
        return entry

    def put(
        self,
        key: BrowserApprovalCacheKey,
        *,
        state: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._items[key] = BrowserApprovalCacheEntry(
            state=_approval_state_name(state),
            expires_at=self._now() + self._ttl_seconds,
            metadata=dict(metadata or {}),
        )

    def clear(self) -> None:
        self._items.clear()

    def items_for(
        self,
        source_type: str,
    ) -> tuple[BrowserApprovalCacheEntry, ...]:
        """Return legacy entries for callers that still inspect the cache."""
        source = str(source_type or "")
        return tuple(
            entry
            for key, entry in self._items.items()
            if key.source_type == source
        )


_DEFAULT_BROWSER_APPROVAL_CACHE = BrowserApprovalCache()


def get_default_browser_approval_cache() -> BrowserApprovalCache:
    """Return the legacy cache object without wiring it into Browser actions."""
    return _DEFAULT_BROWSER_APPROVAL_CACHE


class QwenPawBrowserApprovalPolicy:
    """Allow-all compatibility policy for retired Browser approval plumbing."""

    def __init__(
        self,
        *,
        approval_service: Any | None = None,
        approval_cache: BrowserApprovalCache | None = None,
        now: Callable[[], float] | None = None,
        grant_clock: Callable[[], float] | None = None,
        trusted_surface_policy: TrustedSurfacePolicy | None = None,
        cache_ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        # Keep legacy construction and attribute access stable. These values
        # are deliberately never consulted by Browser policy methods.
        self._approval_service = approval_service
        self._approval_cache = approval_cache
        self._now = now
        self._grant_clock = grant_clock or monotonic
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self.trusted_surface_policy = trusted_surface_policy

    def allow_context_acquisition(
        self,
        request: BrowserContextRequest,
    ) -> BrowserPolicyDecision:
        del request
        return BrowserPolicyDecision(
            allowed=True,
            reason=_COMPATIBILITY_REASON,
        )

    async def request_exact(
        self,
        preview: ActionPreview,
    ) -> BrowserExactApprovalResolution:
        """Issue the existing exact grant without opening an approval flow."""
        if not isinstance(preview, ActionPreview):
            raise TypeError("preview must be an ActionPreview")
        return BrowserExactApprovalResolution(
            pending=None,
            decision=ApprovalDecision.APPROVED,
            grant=issue_exact_grant(preview, now=self._grant_clock()),
        )

    async def allow_action(
        self,
        request: BrowserActionRequest,
    ) -> BrowserPolicyDecision:
        del request
        return BrowserPolicyDecision(
            allowed=True,
            reason=_COMPATIBILITY_REASON,
        )


@dataclass(frozen=True)
class BrowserApprovalLevelResolution:
    """Legacy approval-level result fixed to the non-blocking mode."""

    level: ToolExecutionLevel
    source: str


def resolve_browser_approval_level(
    *,
    request_context: dict[str, Any] | None = None,
    agent_profile: Any | None = None,
    agent_id: str = "",
) -> BrowserApprovalLevelResolution:
    """Return a non-blocking compatibility level without reading config."""
    del request_context, agent_profile, agent_id
    return BrowserApprovalLevelResolution(
        level=ToolExecutionLevel.OFF,
        source="browser_policy_compatibility",
    )


def browser_approval_cache_key(
    request: BrowserActionRequest,
    *,
    root_session_id: str,
    approval_level: str,
) -> BrowserApprovalCacheKey:
    """Build a passive legacy cache key without risk classification."""
    del approval_level
    metadata = dict(request.metadata)
    return BrowserApprovalCacheKey(
        root_session_id=str(root_session_id or "default"),
        approval_level="compatibility",
        domain=str(metadata.get("domain") or "compatibility"),
        action_family=str(request.action or "compatibility"),
        risk_kind="compatibility",
    )


async def resolve_cdp_browser_approval(
    *,
    request_context: dict[str, Any],
    request: dict[str, Any],
    approval_service: Any | None = None,
    approval_cache: BrowserApprovalCache | None = None,
    now: Callable[[], float] | None = None,
) -> BrowserApprovalResolution:
    """Allow legacy CDP ``ask`` callers without invoking approval plumbing."""
    del request_context, request, approval_service, approval_cache, now
    return BrowserApprovalResolution(
        allowed=True,
        reason=_COMPATIBILITY_REASON,
        metadata={"compatibility": "allow"},
    )


def _approval_state_name(state: str) -> str:
    normalized = str(state or "").strip().casefold()
    if normalized in {"approved", "denied", "timeout", "error"}:
        return normalized
    return "error"


__all__ = [
    "BrowserApprovalCache",
    "BrowserApprovalCacheEntry",
    "BrowserApprovalCacheKey",
    "BrowserApprovalLevelResolution",
    "BrowserApprovalResolution",
    "BrowserExactApprovalResolution",
    "QwenPawBrowserApprovalPolicy",
    "browser_approval_cache_key",
    "get_default_browser_approval_cache",
    "resolve_browser_approval_level",
    "resolve_cdp_browser_approval",
]
