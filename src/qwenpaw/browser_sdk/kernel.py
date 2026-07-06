# -*- coding: utf-8 -*-
"""Session-scoped Python kernel for the browser(code=...) tool."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import io
import traceback
from contextvars import ContextVar, Token
from dataclasses import dataclass
from types import CodeType
from typing import Any

from .types import BrowserArtifact, BrowserContext

_RETURN_NAME = "__qwenpaw_browser_return__"
_MAX_PREBOUND_REF_INDEX = 10000


@dataclass(frozen=True)
class BrowserExecutionContext:
    """Context inherited by SDK calls during one browser tool execution."""

    session_id: str
    context: BrowserContext
    requires_user_state: bool | None = None


@dataclass(frozen=True)
class BrowserKernelResult:
    """Execution result returned by the in-process browser kernel."""

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


class BrowserKernel:
    """Execute snippets in a durable per-session namespace."""

    def __init__(self) -> None:
        self._namespace = _new_namespace()

    async def execute(
        self,
        code: str,
        *,
        execution_context: BrowserExecutionContext,
    ) -> BrowserKernelResult:
        """Execute Python code with top-level await support."""
        stdout_capture = io.StringIO()
        token = set_current_execution_context(execution_context)
        artifacts_token = _CURRENT_ARTIFACTS.set([])
        try:
            with contextlib.redirect_stdout(stdout_capture):
                result = await self._execute_code(code)
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
            _CURRENT_ARTIFACTS.reset(artifacts_token)
            reset_current_execution_context(token)

    async def _execute_code(self, code: str) -> Any:
        namespace = self._namespace
        namespace.pop(_RETURN_NAME, None)
        compiled = _compile_code(code)
        maybe_awaitable = eval(compiled, namespace)  # noqa: S307
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
        return namespace.pop(_RETURN_NAME, None)


class BrowserKernelManager:
    """Manage durable browser kernels keyed by session id."""

    def __init__(self) -> None:
        self._kernels: dict[str, BrowserKernel] = {}

    async def execute(
        self,
        *,
        session_id: str,
        code: str,
        timeout_ms: int,
        context: BrowserContext,
        requires_user_state: bool | None = None,
    ) -> BrowserKernelResult:
        """Execute code in the session-scoped browser kernel."""
        _record_timeout_ms_compat_warning(
            session_id=session_id,
            context=context,
            timeout_ms=timeout_ms,
        )
        kernel = self._kernels.setdefault(session_id, BrowserKernel())
        return await kernel.execute(
            code,
            execution_context=BrowserExecutionContext(
                session_id=session_id,
                context=context,
                requires_user_state=requires_user_state,
            ),
        )

    async def reset(self, session_id: str) -> None:
        """Reset one session kernel."""
        self._kernels.pop(session_id, None)

    async def reset_all(self) -> None:
        """Reset all session kernels."""
        self._kernels.clear()


_DEFAULT_KERNEL_MANAGER = BrowserKernelManager()


def get_default_kernel_manager() -> BrowserKernelManager:
    """Return the process-global browser kernel manager."""
    return _DEFAULT_KERNEL_MANAGER


def _record_timeout_ms_compat_warning(
    *,
    session_id: str,
    context: BrowserContext,
    timeout_ms: int,
) -> None:
    if int(timeout_ms) == 30000:
        return

    from .trace import record_browser_trace_event

    record_browser_trace_event(
        session_id=session_id,
        phase="tool",
        backend_id="browser.kernel",
        requested_context=context,
        selected_context=context,
        action="timeout_ms_ignored",
        status="warning",
        metadata={
            "warning": "timeout_ms_deprecated_compatibility",
            "timeout_ms": int(timeout_ms),
            "contract": (
                "timeout_ms is accepted for compatibility but does not "
                "limit total Browser SDK execution; cancel the task to stop "
                "long-running code."
            ),
        },
    )


def _record_kernel_cancelled(
    execution_context: BrowserExecutionContext,
) -> None:
    from .error_codes import BrowserErrorCode, classify_browser_error
    from .trace import record_browser_trace_event

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


def _compile_code(code: str) -> CodeType:
    tree = ast.parse(str(code or ""), mode="exec")
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last_expr = tree.body[-1]
        tree.body[-1] = ast.Assign(
            targets=[ast.Name(id=_RETURN_NAME, ctx=ast.Store())],
            value=last_expr.value,
        )
        ast.fix_missing_locations(tree)
    return compile(
        tree,
        "<browser>",
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )


def _new_namespace() -> dict[str, Any]:
    from .browser import Browser, connect_browser
    from .errors import (
        BrowserContextConflict,
        BrowserContextUnavailable,
        BrowserObservationRequired,
        BrowserPolicyDenied,
        BrowserSDKError,
        BrowserSDKGap,
    )

    namespace: dict[str, Any] = {"__builtins__": __builtins__}
    namespace.update(
        {
            "Browser": Browser,
            "BrowserSDKError": BrowserSDKError,
            "BrowserContextUnavailable": BrowserContextUnavailable,
            "BrowserContextConflict": BrowserContextConflict,
            "BrowserPolicyDenied": BrowserPolicyDenied,
            "BrowserSDKGap": BrowserSDKGap,
            "BrowserObservationRequired": BrowserObservationRequired,
            "connect_browser": connect_browser,
        },
    )
    namespace.update(
        {
            f"e{index}": f"e{index}"
            for index in range(1, _MAX_PREBOUND_REF_INDEX + 1)
        },
    )
    return namespace


def _error_payload(exc: Exception) -> dict[str, Any]:
    from .errors import BrowserSDKError
    from .error_codes import classify_browser_error

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
    "BrowserExecutionContext",
    "BrowserKernel",
    "BrowserKernelManager",
    "BrowserKernelResult",
    "get_current_execution_context",
    "get_default_kernel_manager",
    "reset_current_execution_context",
    "set_current_execution_context",
]
