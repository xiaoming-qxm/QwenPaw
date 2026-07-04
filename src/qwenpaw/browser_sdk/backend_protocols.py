# -*- coding: utf-8 -*-
"""Backend protocols for the unified Browser SDK."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .types import BrowserBackendCapabilities, ResolvedBrowserContext


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
    ) -> BrowserSession | Any:
        """Create or attach a browser session."""

    def is_available(self) -> bool:
        """Return whether this backend can be selected now."""

    def capabilities(self) -> BrowserBackendCapabilities:
        """Return static backend capabilities."""


__all__ = ["BrowserBackend", "BrowserSession"]
