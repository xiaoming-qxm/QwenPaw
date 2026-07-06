# -*- coding: utf-8 -*-
"""Deterministic Browser SDK backend registry."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable

from ..primitives.types import ConcreteBrowserContext
from .protocols import BrowserBackend


class BrowserBackendRegistry:
    """Register and resolve browser backends by stable backend id."""

    def __init__(
        self,
        backends: Iterable[BrowserBackend] | None = None,
    ) -> None:
        self._backends: OrderedDict[str, BrowserBackend] = OrderedDict()
        for backend in backends or ():
            self.register(backend)

    def register(self, backend: BrowserBackend) -> None:
        """Register a backend, preserving insertion order."""
        backend_id = _backend_id(backend)
        if backend_id in self._backends:
            raise ValueError(f"browser backend {backend_id!r} registered")
        self._backends[backend_id] = backend

    def get(self, backend_id: str) -> BrowserBackend | None:
        """Return a backend by id."""
        return self._backends.get(str(backend_id or ""))

    def ids(self) -> list[str]:
        """Return backend ids in deterministic registration order."""
        return list(self._backends.keys())

    def all(self) -> list[BrowserBackend]:
        """Return all backends in registration order."""
        return list(self._backends.values())

    def clear(self) -> None:
        """Remove all registered backends."""
        self._backends.clear()

    def first_for_context(
        self,
        browser_context: ConcreteBrowserContext,
        *,
        only_available: bool = False,
    ) -> BrowserBackend | None:
        """Return the first backend advertising *browser_context*."""
        for backend in self._backends.values():
            capabilities = backend.capabilities()
            if capabilities.browser_context != browser_context:
                continue
            if only_available and not backend.is_available():
                continue
            return backend
        return None


_DEFAULT_BACKEND_REGISTRY = BrowserBackendRegistry()


def get_default_backend_registry() -> BrowserBackendRegistry:
    """Return the process-global Browser SDK backend registry."""
    return _DEFAULT_BACKEND_REGISTRY


def _backend_id(backend: BrowserBackend) -> str:
    backend_id = str(getattr(backend, "backend_id", "") or "")
    if not backend_id:
        capabilities = backend.capabilities()
        backend_id = capabilities.backend_id
    if not backend_id:
        raise ValueError("browser backend id is required")
    return backend_id


__all__ = ["BrowserBackendRegistry", "get_default_backend_registry"]
