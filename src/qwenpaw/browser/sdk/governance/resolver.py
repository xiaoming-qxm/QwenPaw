# -*- coding: utf-8 -*-
"""Runtime browser context arbitration."""

from __future__ import annotations

from typing import Any

from ..backends.registry import (
    BrowserBackendRegistry,
    get_default_backend_registry,
)
from ..backends.protocols import BrowserBackend
from ..primitives.types import (
    BrowserContext,
    BrowserContextRequest,
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
        metadata: dict[str, Any] | None = None,
    ) -> ResolvedBrowserContext:
        """Resolve a Browser SDK context request."""
        requested = _normalize_context(context)
        needs_user_state = bool(requires_user_state)
        self._reject_conflicts(requested, needs_user_state)

        selected, reason, backend = self._select_backend(
            requested,
            needs_user_state,
        )
        self._ensure_available(backend)

        request = BrowserContextRequest(
            session_id=session_id,
            requested_context=requested,
            selected_context=selected,
            requires_user_state=needs_user_state,
            backend_id=backend.backend_id,
            metadata=dict(metadata or {}),
        )
        decision = self._policy.allow_context_acquisition(request)
        if not decision.allowed:
            raise BrowserPolicyDenied(
                decision.reason or "Browser context acquisition denied",
                backend_id=backend.backend_id,
                metadata=decision.metadata,
            )

        return ResolvedBrowserContext(
            requested=requested,
            selected=selected,
            reason=reason,
            requires_user_state=needs_user_state,
            backend_id=backend.backend_id,
        )

    def _select_backend(
        self,
        requested: BrowserContext,
        requires_user_state: bool,
    ) -> tuple[ConcreteBrowserContext, str, BrowserBackend]:
        if requested == "user":
            return (
                "user",
                "explicit_user",
                self._require_backend("user"),
            )
        if requested == "isolated":
            return (
                "isolated",
                "explicit_isolated",
                self._require_backend("isolated"),
            )
        if requires_user_state:
            return (
                "user",
                "requires_user_state",
                self._require_backend("user"),
            )

        isolated = self._registry.first_for_context(
            "isolated",
            only_available=True,
        )
        if isolated is not None:
            return ("isolated", "public_web_isolated_available", isolated)

        user = self._registry.first_for_context("user", only_available=True)
        if user is not None:
            return ("user", "isolated_unavailable_user_available", user)

        fallback = self._registry.first_for_context(
            "isolated",
        ) or self._registry.first_for_context("user")
        if fallback is not None:
            caps = fallback.capabilities()
            return (
                caps.browser_context,
                "no_available_auto_backend",
                fallback,
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


__all__ = ["BrowserContextResolver"]
