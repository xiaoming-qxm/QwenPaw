# -*- coding: utf-8 -*-
"""Session-scoped runtime for the browser(code=...) tool."""

from __future__ import annotations

import asyncio
import contextlib
import io
import traceback
from contextvars import ContextVar, Token
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from ..primitives.types import BrowserArtifact, BrowserContext
from .executor import BrowserCodeExecutor, InProcessBrowserCodeExecutor

_DEFAULT_IDLE_TTL_SECONDS = 300.0


@dataclass(frozen=True)
class BrowserExecutionContext:
    """Context inherited by SDK calls during one browser tool execution."""

    session_id: str
    context: BrowserContext
    requires_user_state: bool | None = None


@dataclass(frozen=True)
class BrowserKernelResult:
    """Execution result returned by the browser kernel runtime."""

    output: str
    return_value: str | None
    error: dict[str, Any] | None
    artifacts: tuple[BrowserArtifact, ...] = ()


_CURRENT_EXECUTION_CONTEXT: ContextVar[
    BrowserExecutionContext | None
] = ContextVar("qwenpaw_browser_execution_context", default=None)
_CURRENT_ARTIFACTS: ContextVar[list[BrowserArtifact] | None] = ContextVar(
    "qwenpaw_browser_artifacts",
    default=None,
)


def get_current_execution_context() -> BrowserExecutionContext | None:
    """Return the current browser tool execution context, if any."""
    return _CURRENT_EXECUTION_CONTEXT.get()


def set_current_execution_context(
    context: BrowserExecutionContext,
) -> Token[BrowserExecutionContext | None]:
    """Install the current browser execution context."""
    return _CURRENT_EXECUTION_CONTEXT.set(context)


def reset_current_execution_context(
    token: Token[BrowserExecutionContext | None],
) -> None:
    """Restore the previous browser execution context."""
    _CURRENT_EXECUTION_CONTEXT.reset(token)


def record_browser_artifact(artifact: BrowserArtifact) -> None:
    """Record one artifact for the current browser tool execution."""
    artifacts = _CURRENT_ARTIFACTS.get()
    if artifacts is not None:
        artifacts.append(artifact)


def drain_browser_artifacts() -> tuple[BrowserArtifact, ...]:
    """Return and clear artifacts for the current browser tool execution."""
    artifacts = _CURRENT_ARTIFACTS.get()
    if artifacts is None:
        return ()
    drained = tuple(artifacts)
    artifacts.clear()
    return drained


class BrowserKernelRuntime:
    """Coordinate browser code execution around an injected executor."""

    def __init__(
        self,
        *,
        executor: BrowserCodeExecutor | None = None,
        idle_ttl_seconds: float = _DEFAULT_IDLE_TTL_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._executor = executor or InProcessBrowserCodeExecutor()
        self._idle_ttl_seconds = float(idle_ttl_seconds)
        self._clock = clock
        self._last_used: dict[str, float] = {}

    async def execute(
        self,
        *,
        session_id: str,
        code: str,
        context: BrowserContext,
        requires_user_state: bool | None = None,
    ) -> BrowserKernelResult:
        """Execute code in a session-scoped browser kernel."""
        execution_context = BrowserExecutionContext(
            session_id=session_id,
            context=context,
            requires_user_state=requires_user_state,
        )
        stdout_capture = io.StringIO()
        token = set_current_execution_context(execution_context)
        artifacts_token = _CURRENT_ARTIFACTS.set([])
        try:
            with contextlib.redirect_stdout(stdout_capture):
                result = await self._executor.execute(
                    code,
                    execution_context=execution_context,
                )
            return BrowserKernelResult(
                output=stdout_capture.getvalue(),
                return_value=repr(result) if result is not None else None,
                error=None,
                artifacts=drain_browser_artifacts(),
            )
        except asyncio.CancelledError:
            _record_kernel_cancelled(execution_context)
            raise
        except Exception as exc:  # noqa: BLE001
            return BrowserKernelResult(
                output=stdout_capture.getvalue(),
                return_value=None,
                error=_error_payload(exc),
                artifacts=drain_browser_artifacts(),
            )
        finally:
            self._last_used[session_id] = self._clock()
            _CURRENT_ARTIFACTS.reset(artifacts_token)
            reset_current_execution_context(token)

    async def reset(self, session_id: str) -> None:
        """Reset one session kernel."""
        self._last_used.pop(session_id, None)
        await self._executor.reset(session_id)

    async def reset_all(self) -> None:
        """Reset all session kernels."""
        self._last_used.clear()
        await self._executor.reset_all()

    async def sweep_idle(
        self,
        *,
        now: float | None = None,
    ) -> tuple[str, ...]:
        """Reset kernels idle for more than the configured TTL."""
        current = self._clock() if now is None else float(now)
        expired = tuple(
            session_id
            for session_id, last_used in list(self._last_used.items())
            if current - last_used > self._idle_ttl_seconds
        )
        for session_id in expired:
            await self.reset(session_id)
        return expired

    def diagnostics(self) -> dict[str, Any]:
        """Return JSON-safe runtime diagnostics."""
        return {
            "runtime": "browser_kernel",
            "idle_ttl_seconds": self._idle_ttl_seconds,
            "tracked_sessions": len(self._last_used),
            "executor": self._executor.diagnostics(),
        }


class BrowserKernel:
    """Compatibility wrapper for one in-process session kernel."""

    def __init__(
        self,
        *,
        executor: BrowserCodeExecutor | None = None,
    ) -> None:
        self._runtime = BrowserKernelRuntime(executor=executor)

    async def execute(
        self,
        code: str,
        *,
        execution_context: BrowserExecutionContext,
    ) -> BrowserKernelResult:
        """Execute code using the wrapped runtime."""
        return await self._runtime.execute(
            session_id=execution_context.session_id,
            code=code,
            context=execution_context.context,
            requires_user_state=execution_context.requires_user_state,
        )


class BrowserKernelManager(BrowserKernelRuntime):
    """Manage durable browser kernels keyed by session id."""


_DEFAULT_KERNEL_MANAGER = BrowserKernelManager()


def get_default_kernel_manager() -> BrowserKernelManager:
    """Return the process-global browser kernel manager."""
    return _DEFAULT_KERNEL_MANAGER


def _record_kernel_cancelled(
    execution_context: BrowserExecutionContext,
) -> None:
    from ..governance.error_codes import BrowserErrorCode, classify_browser_error
    from ..telemetry.trace import record_browser_trace_event

    error_info = classify_browser_error(BrowserErrorCode.CANCELLED)
    record_browser_trace_event(
        session_id=execution_context.session_id,
        phase="tool",
        backend_id="browser.kernel",
        requested_context=execution_context.context,
        selected_context=execution_context.context,
        action="browser_kernel_cancelled",
        status="cancelled",
        error_code=error_info.code.value,
        metadata={
            "outcome": error_info.outcome.value,
            "recovery_hint": error_info.recovery_hint,
        },
    )


def _error_payload(exc: Exception) -> dict[str, Any]:
    from ..governance.error_codes import classify_browser_error
    from ..governance.errors import BrowserSDKError

    error_info = classify_browser_error(exc)
    payload: dict[str, Any] = {
        "type": type(exc).__name__,
        "code": error_info.code.value,
        "outcome": error_info.outcome.value,
        "recovery_hint": error_info.recovery_hint,
        "message": str(exc),
        "traceback": traceback.format_exc(),
    }
    if isinstance(exc, BrowserSDKError):
        payload["recovery_hint"] = exc.recovery_hint
        if exc.backend_id:
            payload["backend_id"] = exc.backend_id
        if exc.action:
            payload["action"] = exc.action
        metadata = dict(exc.metadata)
        if metadata:
            payload["metadata"] = metadata
    return payload


__all__ = [
    "BrowserCodeExecutor",
    "BrowserExecutionContext",
    "BrowserKernel",
    "BrowserKernelManager",
    "BrowserKernelResult",
    "BrowserKernelRuntime",
    "InProcessBrowserCodeExecutor",
    "drain_browser_artifacts",
    "get_current_execution_context",
    "get_default_kernel_manager",
    "record_browser_artifact",
    "reset_current_execution_context",
    "set_current_execution_context",
]
