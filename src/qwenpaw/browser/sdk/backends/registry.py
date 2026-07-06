# -*- coding: utf-8 -*-
"""Deterministic Browser SDK backend registry."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

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


async def cleanup_browser_backend_request_resources(
    *,
    session_id: str = "",
    root_session_id: str = "",
    holder_id: str = "",
    workspace_id: str = "",
    cleanup_reason: str = "finally",
    registry: BrowserBackendRegistry | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run request cleanup hooks exposed by registered browser backends."""
    cleanup_registry = registry or get_default_backend_registry()
    merged: dict[str, Any] = {
        "backend_cleanups": 0,
        "cleanup_errors": 0,
        "cleanup_reason": cleanup_reason,
    }
    backend_results: list[dict[str, Any]] = []
    for backend in cleanup_registry.all():
        cleanup = getattr(backend, "cleanup_for_request", None)
        if not callable(cleanup):
            continue
        try:
            raw_result = cleanup(
                session_id=session_id,
                root_session_id=root_session_id,
                holder_id=holder_id,
                workspace_id=workspace_id,
                cleanup_reason=cleanup_reason,
                **kwargs,
            )
            if hasattr(raw_result, "__await__"):
                raw_result = await raw_result
            result = (
                dict(raw_result or {}) if isinstance(raw_result, dict) else {}
            )
            backend_results.append(
                {
                    "backend_id": _backend_id(backend),
                    **result,
                },
            )
            _merge_cleanup_counters(merged, result)
            merged["backend_cleanups"] += 1
        except Exception:
            merged["cleanup_errors"] += 1
    if backend_results:
        merged["backend_results"] = backend_results
    return merged


async def shutdown_registered_browser_backends(
    registry: BrowserBackendRegistry | None = None,
) -> None:
    """Run shutdown hooks exposed by registered browser backends."""
    shutdown_registry = registry or get_default_backend_registry()
    for backend in shutdown_registry.all():
        shutdown = getattr(backend, "shutdown", None)
        if not callable(shutdown):
            continue
        result = shutdown()
        if hasattr(result, "__await__"):
            await result


def _backend_id(backend: BrowserBackend) -> str:
    backend_id = str(getattr(backend, "backend_id", "") or "")
    if not backend_id:
        capabilities = backend.capabilities()
        backend_id = capabilities.backend_id
    if not backend_id:
        raise ValueError("browser backend id is required")
    return backend_id


def _merge_cleanup_counters(
    merged: dict[str, Any],
    result: dict[str, Any],
) -> None:
    for key in (
        "matched_sessions",
        "user_backend_sessions",
        "matched_tabs",
        "closed_tabs",
        "released_tabs",
        "closed_owned_tabs",
        "released_borrowed_tabs",
        "skipped_protected_tabs",
        "remaining_orphaned_tabs",
        "cleanup_errors",
    ):
        merged[key] = int(merged.get(key) or 0) + int(result.get(key) or 0)
    cleanup_reason = str(result.get("cleanup_reason") or "")
    if cleanup_reason:
        merged["cleanup_reason"] = cleanup_reason


__all__ = [
    "BrowserBackendRegistry",
    "cleanup_browser_backend_request_resources",
    "get_default_backend_registry",
    "shutdown_registered_browser_backends",
]
