# -*- coding: utf-8 -*-
"""Backend protocols for the unified Browser SDK."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..primitives.types import (
    BrowserBackendCapabilities,
    BrowserOwnershipContext,
    BrowserRetention,
    ResolvedBrowserContext,
)


@runtime_checkable
class BrowserSession(Protocol):
    """Runtime session returned by a browser backend."""

    backend_id: str

    async def close(self) -> None:
        """Release backend-owned resources for the session."""


@runtime_checkable
class BrowserBackend(Protocol):
    """Protocol implemented by concrete browser execution backends."""

    backend_id: str

    async def connect(
        self,
        session_id: str,
        context: ResolvedBrowserContext,
        *,
        request_scope_key: str = "",
        retention: BrowserRetention = "clean",
        ownership_context: BrowserOwnershipContext | None = None,
    ) -> BrowserSession | Any:
        """Create or attach a browser session."""

    def is_available(self) -> bool:
        """Return whether this backend can be selected now."""

    def capabilities(self) -> BrowserBackendCapabilities:
        """Return static backend capabilities."""


__all__ = ["BrowserBackend", "BrowserSession"]
