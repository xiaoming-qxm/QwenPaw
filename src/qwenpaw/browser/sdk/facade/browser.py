# -*- coding: utf-8 -*-
"""Top-level Browser facade for the unified Browser SDK."""

from __future__ import annotations

import inspect
from time import perf_counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..actions.tab_actions import BrowserActions
from ..backends.registry import get_default_backend_registry
from ..docs.capabilities import browser_capabilities
from ..governance.error_codes import classify_browser_error
from ..governance.errors import BrowserContextUnavailable
from ..governance.resolver import BrowserContextResolver
from ..primitives.tabs import BrowserTabs
from ..primitives.trace_metadata import coerce_action_result
from ..primitives.trace_metadata import with_boundary_decision
from ..primitives.trace_metadata import with_exception_metadata
from ..primitives.trace_metadata import with_route_metadata
from ..primitives.types import BrowserActionResult
from ..primitives.types import (
    BrowserBackendDiagnostic,
    BrowserContext,
    BrowserDiagnosticCheck,
    BrowserDiagnosticStatus,
    BrowserDiagnostics,
    BrowserRetention,
    ResolvedBrowserContext,
)
from ..runtime.kernel import get_current_execution_context
from ..telemetry.trace import record_browser_trace_event


@dataclass
class Browser:
    """Connected browser facade.

    T002 provides the connection shell used by browser(code=...). T003 fills
    in tabs, actions, and extraction on top of the backend session.
    """

    session: Any
    context: ResolvedBrowserContext
    session_id: str = ""
    retention: BrowserRetention = "clean"
    tabs: BrowserTabs = field(init=False)
    actions: BrowserActions = field(init=False)

    def __post_init__(self) -> None:
        self.tabs = BrowserTabs(self)
        self.actions = BrowserActions(self)

    @property
    def backend_id(self) -> str:
        """Return the selected backend id."""
        return self.context.backend_id

    async def close(self) -> None:
        """Release browser session resources through the selected backend."""
        started = perf_counter()
        if self.retention != "clean":
            self._trace(
                phase="close",
                status="ok",
                duration_ms=_duration_ms(started),
                metadata={
                    "retention": self.retention,
                    "cleanup_result": "preserved",
                },
            )
            return
        close_metadata: dict[str, Any] = {"retention": self.retention}
        try:
            cleanup = getattr(self.session, "cleanup_for_request", None)
            if callable(cleanup):
                result = cleanup(cleanup_reason="browser_close")
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, dict):
                    close_metadata["cleanup_summary"] = dict(result)
            else:
                close = getattr(self.session, "close", None)
                if not callable(close):
                    result = None
                else:
                    result = close()
                if inspect.isawaitable(result):
                    await result
                close_metadata["cleanup_result"] = "closed"
        except Exception as exc:
            self._trace(
                phase="close",
                status="error",
                duration_ms=_duration_ms(started),
                error_code=_error_code(exc),
                metadata={
                    **close_metadata,
                    "error_type": type(exc).__name__,
                },
            )
            raise
        self._trace(
            phase="close",
            status="ok",
            duration_ms=_duration_ms(started),
            metadata=close_metadata,
        )

    async def release(self) -> None:
        """Alias for close() that reads naturally for request cleanup."""
        await self.close()

    async def preserve(self) -> None:
        """Mark the browser session as intentionally retained."""
        started = perf_counter()
        self._trace(
            phase="close",
            status="ok",
            duration_ms=_duration_ms(started),
            metadata={
                "retention": self.retention,
                "cleanup_result": "preserved",
            },
        )

    async def stop(self) -> None:
        """Destroy the backend runtime for this browser session."""
        stop = getattr(self.session, "stop", None)
        if callable(stop):
            result = stop()
            if hasattr(result, "__await__"):
                await result
            return
        await self.close()

    @classmethod
    async def connect(
        cls,
        context: BrowserContext = "auto",
        *,
        requires_user_state: bool | None = None,
        session_id: str | None = None,
        retention: BrowserRetention = "clean",
    ) -> "Browser":
        """Connect to a browser backend using runtime context arbitration."""
        execution_context = get_current_execution_context()
        effective_context = _effective_context(context, execution_context)
        effective_requires_user_state = (
            requires_user_state
            if requires_user_state is not None
            else (
                execution_context.requires_user_state
                if execution_context is not None
                else None
            )
        )
        effective_browser_intent = (
            execution_context.browser_intent
            if execution_context is not None
            else None
        )
        effective_session_id = (
            session_id
            or (
                execution_context.session_id
                if execution_context is not None
                else ""
            )
            or "default"
        )

        started = perf_counter()
        try:
            resolved = BrowserContextResolver().resolve(
                session_id=effective_session_id,
                context=effective_context,
                requires_user_state=effective_requires_user_state,
                browser_intent=effective_browser_intent,
            )
            registry = get_default_backend_registry()
            backend = registry.get(resolved.backend_id)
            if backend is None:
                raise BrowserContextUnavailable(
                    f"Resolved browser backend is not registered: "
                    f"{resolved.backend_id}",
                    backend_id=resolved.backend_id,
                )
            session = await backend.connect(effective_session_id, resolved)
        except Exception as exc:
            record_browser_trace_event(
                session_id=effective_session_id,
                phase="connect",
                backend_id=str(getattr(exc, "backend_id", "") or ""),
                requested_context=str(effective_context or ""),
                status="error",
                duration_ms=_duration_ms(started),
                error_code=_error_code(exc),
                metadata={"error_type": type(exc).__name__},
            )
            raise
        browser = cls(
            session=session,
            context=resolved,
            session_id=effective_session_id,
            retention=_normalize_retention(retention),
        )
        browser._trace(
            phase="connect",
            status="ok",
            duration_ms=_duration_ms(started),
            metadata=_route_metadata(resolved),
        )
        return browser

    @classmethod
    async def diagnostics(
        cls,
        context: BrowserContext = "auto",
    ) -> BrowserDiagnostics:
        """Return backend availability diagnostics without connecting."""
        del cls
        requested = _normalize_context(context)
        registry = get_default_backend_registry()
        diagnostic_items: list[BrowserBackendDiagnostic] = []
        for backend in registry.all():
            diagnostic_items.append(await _backend_diagnostic(backend))
        diagnostics = tuple(diagnostic_items)
        route = _diagnostic_route_metadata(requested, diagnostics)
        return BrowserDiagnostics(
            requested_context=requested,
            selected_backend_id=route["selected_backend_id"],
            backends=diagnostics,
            preferred_backend_id=route["preferred_backend_id"],
            selected_backend_degraded=route["selected_backend_degraded"],
            fallback_allowed=route["fallback_allowed"],
            fallback_reason=route["fallback_reason"],
            auto_route_policy=route["auto_route_policy"],
        )

    @classmethod
    def capabilities(cls) -> dict[str, Any]:
        """Return public Browser SDK contexts, primitives, actions, limits."""
        del cls
        return browser_capabilities()

    async def _call_browser_action(
        self,
        name: str,
        **kwargs: Any,
    ) -> BrowserActionResult | Any:
        started = perf_counter()
        try:
            action = getattr(self.session, "action", None)
            if callable(action):
                result = await action("__browser__", name, **kwargs)
            else:
                browser_action = getattr(self.session, "browser_action", None)
                if callable(browser_action):
                    result = await browser_action(name, **kwargs)
                else:
                    result = {
                        "ok": False,
                        "message": (
                            "Backend does not support browser action: "
                            f"{name}"
                        ),
                    }
        except Exception as exc:
            self._trace(
                phase="action",
                action=name,
                status="error",
                duration_ms=_duration_ms(started),
                error_code=_error_code(exc),
                metadata=with_exception_metadata(
                    {
                        "kwargs": kwargs,
                        "error_type": type(exc).__name__,
                    },
                    exc,
                ),
            )
            raise
        action_result = coerce_action_result(result)
        self._trace(
            phase="action",
            action=name,
            status=_result_status(result),
            duration_ms=_duration_ms(started),
            metadata=with_boundary_decision(
                {"kwargs": kwargs},
                action_result.data.get("boundary_decision"),
            ),
        )
        return result

    def _trace(
        self,
        *,
        phase: str,
        status: str,
        duration_ms: float,
        action: str = "",
        tab_id: str = "",
        url: str = "",
        error_code: str = "",
        approval_state: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record_browser_trace_event(
            session_id=self.session_id,
            phase=phase,
            backend_id=self.context.backend_id,
            requested_context=self.context.requested,
            selected_context=self.context.selected,
            action=action,
            tab_id=tab_id,
            url=url,
            status=status,
            duration_ms=duration_ms,
            error_code=error_code,
            approval_state=approval_state,
            metadata=with_route_metadata(metadata, self.context),
        )


async def connect_browser(
    context: BrowserContext = "auto",
    *,
    requires_user_state: bool | None = None,
    session_id: str | None = None,
    retention: BrowserRetention = "clean",
) -> Browser:
    """Alias for Browser.connect()."""
    return await Browser.connect(
        context=context,
        requires_user_state=requires_user_state,
        session_id=session_id,
        retention=retention,
    )


def _effective_context(
    context: BrowserContext,
    execution_context: Any,
) -> BrowserContext:
    if context == "auto" and execution_context is not None:
        return execution_context.context
    return context


def _route_metadata(context: ResolvedBrowserContext) -> dict[str, Any]:
    return {
        "reason": context.reason,
        "route_reason": context.reason,
        "browser_intent": context.browser_intent,
        "preferred_backend_id": context.preferred_backend_id,
        "selected_backend_degraded": context.selected_backend_degraded,
        "fallback_allowed": context.fallback_allowed,
        "fallback_reason": context.fallback_reason,
        "auto_route_policy": context.auto_route_policy,
    }


def _normalize_context(context: str) -> BrowserContext:
    value = str(context or "auto").strip().lower()
    if value in {"auto", "user", "isolated"}:
        return value  # type: ignore[return-value]
    return "auto"


def _normalize_retention(retention: str) -> BrowserRetention:
    value = str(retention or "clean").strip().lower()
    if value in {"clean", "debug", "handoff"}:
        return value  # type: ignore[return-value]
    raise ValueError("Browser retention must be one of: clean, debug.")


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _error_code(exc: Exception) -> str:
    return classify_browser_error(exc).code.value


def _result_status(result: Any) -> str:
    ok = getattr(result, "ok", None)
    if ok is not None:
        return "ok" if bool(ok) else "error"
    if isinstance(result, dict) and result.get("ok") is False:
        return "error"
    return "ok"


async def _backend_diagnostic(backend: Any) -> BrowserBackendDiagnostic:
    diagnose = getattr(backend, "diagnose", None)
    if callable(diagnose):
        raw_diagnostic = diagnose()
        if inspect.isawaitable(raw_diagnostic):
            raw_diagnostic = await raw_diagnostic
        if isinstance(raw_diagnostic, BrowserBackendDiagnostic):
            return raw_diagnostic

    capabilities = backend.capabilities()
    metadata: dict[str, Any] = {}
    backend_diagnostics = getattr(backend, "diagnostics", None)
    if callable(backend_diagnostics):
        raw_metadata = backend_diagnostics()
        if isinstance(raw_metadata, dict):
            metadata.update(raw_metadata)
    try:
        available = bool(backend.is_available())
    except Exception as exc:  # pragma: no cover - defensive diagnostics
        message = str(exc)
        return BrowserBackendDiagnostic(
            backend_id=capabilities.backend_id,
            browser_context=capabilities.browser_context,
            available=False,
            code=type(exc).__name__,
            reason=message,
            status="unavailable",
            message=message,
            hint_key="browser_backend_unavailable",
            message_fallback=message,
            checks=(
                _diagnostic_check(
                    name="availability",
                    status="unavailable",
                    code=type(exc).__name__,
                    message=message,
                    hint_key="browser_backend_unavailable",
                    backend_id=capabilities.backend_id,
                ),
            ),
            observed_at=_observed_at(),
            features=capabilities.features,
            metadata=metadata,
        )
    code = ""
    reason = ""
    if not available:
        unavailable_error = getattr(backend, "unavailable_error", None)
        if callable(unavailable_error):
            error = unavailable_error()
            code = str(getattr(error, "code", "") or type(error).__name__)
            reason = str(error)
            metadata.update(dict(getattr(error, "metadata", {}) or {}))
    status: BrowserDiagnosticStatus = (
        "available" if available else "unavailable"
    )
    message = (
        reason if reason else ("Available" if available else "Unavailable")
    )
    hint_key = "" if available else "browser_backend_unavailable"
    return BrowserBackendDiagnostic(
        backend_id=capabilities.backend_id,
        browser_context=capabilities.browser_context,
        available=available,
        code=code,
        reason=reason,
        status=status,
        message=message,
        hint_key=hint_key,
        message_fallback=message,
        checks=(
            _diagnostic_check(
                name="availability",
                status=status,
                code=code,
                message=message,
                hint_key=hint_key,
                backend_id=capabilities.backend_id,
            ),
        ),
        observed_at=_observed_at(),
        features=capabilities.features,
        metadata=metadata,
    )


def _diagnostic_check(
    *,
    name: str,
    status: BrowserDiagnosticStatus,
    code: str,
    message: str,
    hint_key: str,
    backend_id: str,
) -> BrowserDiagnosticCheck:
    return BrowserDiagnosticCheck(
        name=name,
        status=status,
        code=code,
        message=message,
        hint_key=hint_key,
        metadata={"backend_id": backend_id},
    )


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()


def _diagnostic_route_metadata(
    context: BrowserContext,
    diagnostics: tuple[BrowserBackendDiagnostic, ...],
) -> dict[str, Any]:
    if context == "isolated":
        selected = _first_available_backend_id(diagnostics, "isolated")
        return _explicit_diagnostic_route(selected)
    if context == "user":
        selected = _first_available_backend_id(diagnostics, "user")
        return _explicit_diagnostic_route(selected)

    preferred = _first_backend_id(diagnostics, "user")
    available_user = _first_available_backend_id(diagnostics, "user")
    if available_user:
        return {
            "selected_backend_id": available_user,
            "preferred_backend_id": available_user,
            "selected_backend_degraded": False,
            "fallback_allowed": False,
            "fallback_reason": "",
            "auto_route_policy": "auto_user_chrome_first",
        }
    available_isolated = _first_available_backend_id(diagnostics, "isolated")
    if available_isolated:
        return {
            "selected_backend_id": available_isolated,
            "preferred_backend_id": preferred,
            "selected_backend_degraded": True,
            "fallback_allowed": True,
            "fallback_reason": "user_browser_unavailable",
            "auto_route_policy": "auto_user_chrome_first",
        }
    return {
        "selected_backend_id": "",
        "preferred_backend_id": preferred,
        "selected_backend_degraded": False,
        "fallback_allowed": True,
        "fallback_reason": "user_browser_unavailable",
        "auto_route_policy": "auto_user_chrome_first",
    }


def _explicit_diagnostic_route(selected: str) -> dict[str, Any]:
    return {
        "selected_backend_id": selected,
        "preferred_backend_id": selected,
        "selected_backend_degraded": False,
        "fallback_allowed": False,
        "fallback_reason": "",
        "auto_route_policy": "explicit_context",
    }


def _first_backend_id(
    diagnostics: tuple[BrowserBackendDiagnostic, ...],
    browser_context: str,
) -> str:
    for diagnostic in diagnostics:
        if diagnostic.browser_context == browser_context:
            return diagnostic.backend_id
    return ""


def _first_available_backend_id(
    diagnostics: tuple[BrowserBackendDiagnostic, ...],
    browser_context: str,
) -> str:
    for diagnostic in diagnostics:
        if (
            diagnostic.browser_context == browser_context
            and diagnostic.available
        ):
            return diagnostic.backend_id
    return ""


__all__ = ["Browser", "connect_browser"]
