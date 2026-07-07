# -*- coding: utf-8 -*-
"""Runtime browser context arbitration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..backends.registry import (
    BrowserBackendRegistry,
    get_default_backend_registry,
)
from ..backends.protocols import BrowserBackend
from ..primitives.types import (
    BrowserContext,
    BrowserContextRequest,
    BrowserIntent,
    ConcreteBrowserContext,
    ResolvedBrowserContext,
)
from .errors import (
    BrowserContextConflict,
    BrowserContextUnavailable,
    BrowserPolicyDenied,
)
from .policy import BrowserPolicy, DefaultBrowserPolicy


class BrowserContextResolver:
    """Resolve requested browser context to one concrete backend."""

    def __init__(
        self,
        *,
        registry: BrowserBackendRegistry | None = None,
        policy: BrowserPolicy | None = None,
    ) -> None:
        self._registry = registry or get_default_backend_registry()
        self._policy = policy or DefaultBrowserPolicy()

    def resolve(
        self,
        *,
        session_id: str,
        context: BrowserContext = "auto",
        requires_user_state: bool | None = None,
        browser_intent: BrowserIntent | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResolvedBrowserContext:
        """Resolve a Browser SDK context request."""
        requested = _normalize_context(context)
        needs_user_state = bool(requires_user_state)
        intent = _normalize_browser_intent(
            browser_intent
            if browser_intent is not None
            else (metadata or {}).get("browser_intent"),
            requires_user_state=needs_user_state,
        )
        self._reject_conflicts(requested, needs_user_state)

        route = self._select_backend(
            requested,
            needs_user_state,
            intent,
        )
        self._ensure_available(route.backend)

        request = BrowserContextRequest(
            session_id=session_id,
            requested_context=requested,
            selected_context=route.selected,
            requires_user_state=needs_user_state,
            backend_id=route.backend.backend_id,
            metadata={
                **dict(metadata or {}),
                **route.metadata,
            },
        )
        decision = self._policy.allow_context_acquisition(request)
        if not decision.allowed:
            raise BrowserPolicyDenied(
                decision.reason or "Browser context acquisition denied",
                backend_id=route.backend.backend_id,
                metadata=decision.metadata,
            )

        return ResolvedBrowserContext(
            requested=requested,
            selected=route.selected,
            reason=route.reason,
            requires_user_state=needs_user_state,
            backend_id=route.backend.backend_id,
            browser_intent=intent,
            preferred_backend_id=route.preferred_backend_id,
            selected_backend_degraded=route.selected_backend_degraded,
            fallback_allowed=route.fallback_allowed,
            fallback_reason=route.fallback_reason,
            auto_route_policy=route.auto_route_policy,
        )

    def _select_backend(
        self,
        requested: BrowserContext,
        requires_user_state: bool,
        browser_intent: BrowserIntent,
    ) -> "_RouteSelection":
        if requested == "user":
            backend = self._require_backend("user")
            return _RouteSelection(
                selected="user",
                reason="explicit_user",
                backend=backend,
                preferred_backend_id=backend.backend_id,
                auto_route_policy="explicit_context",
            )
        if requested == "isolated":
            backend = self._require_backend("isolated")
            return _RouteSelection(
                selected="isolated",
                reason="explicit_isolated",
                backend=backend,
                preferred_backend_id=backend.backend_id,
                auto_route_policy="explicit_context",
            )

        user = self._registry.first_for_context("user")
        if user is not None and user.is_available():
            return _RouteSelection(
                selected="user",
                reason=(
                    "requires_user_state"
                    if requires_user_state
                    else "auto_user_chrome_available"
                ),
                backend=user,
                preferred_backend_id=user.backend_id,
                auto_route_policy="auto_user_chrome_first",
            )

        if requires_user_state or browser_intent == "user_state":
            raise _user_browser_unavailable_error(user)

        isolated = self._registry.first_for_context("isolated")
        if isolated is not None and isolated.is_available():
            return _RouteSelection(
                selected="isolated",
                reason="user_chrome_unavailable_degraded_isolated",
                backend=isolated,
                preferred_backend_id=(
                    user.backend_id if user is not None else ""
                ),
                selected_backend_degraded=True,
                fallback_allowed=True,
                fallback_reason="user_browser_unavailable",
                auto_route_policy="auto_user_chrome_first",
            )

        fallback = isolated or user
        if fallback is not None:
            caps = fallback.capabilities()
            return _RouteSelection(
                selected=caps.browser_context,
                reason="no_available_auto_backend",
                backend=fallback,
                preferred_backend_id=(
                    user.backend_id if user is not None else ""
                ),
                fallback_allowed=True,
                fallback_reason="user_browser_unavailable",
                auto_route_policy="auto_user_chrome_first",
            )
        fallback = self._registry.first_for_context(
            "isolated",
        ) or self._registry.first_for_context("user")
        if fallback is not None:
            caps = fallback.capabilities()
            return _RouteSelection(
                selected=caps.browser_context,
                reason="no_available_auto_backend",
                backend=fallback,
                auto_route_policy="auto_user_chrome_first",
            )
        raise BrowserContextUnavailable(
            'No browser backend is registered for context="auto"',
        )

    def _require_backend(
        self,
        browser_context: ConcreteBrowserContext,
    ) -> BrowserBackend:
        backend = self._registry.first_for_context(browser_context)
        if backend is None:
            message = (
                "No browser backend is registered for "
                f'context="{browser_context}"'
            )
            raise BrowserContextUnavailable(
                message,
            )
        return backend

    @staticmethod
    def _reject_conflicts(
        requested: BrowserContext,
        requires_user_state: bool,
    ) -> None:
        if requested == "isolated" and requires_user_state:
            raise BrowserContextConflict(
                'User browser state requires context="user" or '
                'context="auto" with requires_user_state=True.',
            )

    @staticmethod
    def _ensure_available(backend: BrowserBackend) -> None:
        if backend.is_available():
            return
        unavailable_error = getattr(backend, "unavailable_error", None)
        if callable(unavailable_error):
            raise unavailable_error()
        capabilities = backend.capabilities()
        raise BrowserContextUnavailable(
            (
                "Browser backend is unavailable for "
                f'context="{capabilities.browser_context}"'
            ),
            backend_id=backend.backend_id,
        )


def _normalize_context(context: str) -> BrowserContext:
    value = str(context or "auto").strip().lower()
    if value in {"auto", "user", "isolated"}:
        return value  # type: ignore[return-value]
    raise BrowserContextConflict(
        "Browser context must be one of: auto, user, isolated.",
    )


def _normalize_browser_intent(
    value: object,
    *,
    requires_user_state: bool,
) -> BrowserIntent:
    if requires_user_state:
        return "user_state"
    normalized = str(value or "ambiguous").strip().lower().replace("-", "_")
    if normalized in {"public", "public_web"}:
        return "public"
    if normalized in {"user_state", "requires_user_state", "authenticated"}:
        return "user_state"
    return "ambiguous"


def _user_browser_unavailable_error(
    backend: BrowserBackend | None,
) -> BrowserContextUnavailable:
    backend_id = backend.backend_id if backend is not None else ""
    return BrowserContextUnavailable(
        "User Chrome is unavailable for a browser request that requires user "
        "state.",
        code="user_browser_unavailable",
        backend_id=backend_id,
        metadata={
            "hint": "Install, reload, or reconnect the Chrome Extension.",
            "recommended_action": "reconnect_chrome_extension",
        },
    )


@dataclass(frozen=True)
class _RouteSelection:
    selected: ConcreteBrowserContext
    reason: str
    backend: BrowserBackend
    preferred_backend_id: str = ""
    selected_backend_degraded: bool = False
    fallback_allowed: bool = False
    fallback_reason: str = ""
    auto_route_policy: str = ""

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "route_reason": self.reason,
            "preferred_backend_id": self.preferred_backend_id,
            "selected_backend_degraded": self.selected_backend_degraded,
            "fallback_allowed": self.fallback_allowed,
            "fallback_reason": self.fallback_reason,
            "auto_route_policy": self.auto_route_policy,
        }


__all__ = ["BrowserContextResolver"]
