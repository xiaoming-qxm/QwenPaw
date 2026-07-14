# -*- coding: utf-8 -*-
"""Executor boundary for browser(code=...) runtimes."""

from __future__ import annotations

import ast
import inspect
from types import CodeType
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..canonical.guard import CanonicalCapabilityGuard
from .session_owner import ContractMode

if TYPE_CHECKING:
    from .kernel import BrowserExecutionContext

_RETURN_NAME = "__qwenpaw_browser_return__"


@runtime_checkable
class BrowserCodeExecutor(Protocol):
    """Protocol shared by V10 in-process and future V11 executors."""

    async def execute(
        self,
        code: str,
        *,
        execution_context: "BrowserExecutionContext",
    ) -> Any:
        """Execute code for one browser kernel session."""

    async def reset(self, session_id: str) -> None:
        """Reset one session namespace."""

    async def reset_all(self) -> None:
        """Reset all session namespaces."""

    async def sweep_idle(
        self,
        *,
        now: float | None = None,
    ) -> tuple[str, ...]:
        """Sweep executor-owned idle resources, if any."""

    def diagnostics(self) -> dict[str, Any]:
        """Return JSON-safe executor diagnostics."""


class InProcessBrowserCodeExecutor:
    """AST-guarded in-process executor used by V10."""

    def __init__(
        self,
        *,
        guard: CanonicalCapabilityGuard | None = None,
    ) -> None:
        self._guard = guard or CanonicalCapabilityGuard()
        self._namespaces: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}
        self._session_keys: dict[
            str,
            set[tuple[str, str]],
        ] = {}

    async def execute(
        self,
        code: str,
        *,
        execution_context: "BrowserExecutionContext",
    ) -> Any:
        """Execute code in the durable namespace for one session."""
        namespace_key = (
            execution_context.root_task_id,
            execution_context.browser_owner_id,
        )
        if execution_context.contract_mode is not ContractMode.CANONICAL:
            raise RuntimeError("canonical_contract_required")
        guard = self._guard
        namespace = self._namespaces.setdefault(
            namespace_key,
            _new_namespace(guard),
        )
        self._session_keys.setdefault(execution_context.session_id, set()).add(
            namespace_key,
        )
        namespace.pop(_RETURN_NAME, None)
        compiled = _compile_code(code, guard)
        maybe_awaitable = eval(compiled, namespace)  # noqa: S307
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
        return namespace.pop(_RETURN_NAME, None)

    async def reset(self, session_id: str) -> None:
        """Reset one session namespace."""
        for namespace_key in self._session_keys.pop(session_id, set()):
            self._namespaces.pop(namespace_key, None)

    async def reset_all(self) -> None:
        """Reset all session namespaces."""
        self._namespaces.clear()
        self._session_keys.clear()

    async def sweep_idle(
        self,
        *,
        now: float | None = None,
    ) -> tuple[str, ...]:
        """Return no-op sweep result; runtime owns V10 TTL policy."""
        del now
        return ()

    def diagnostics(self) -> dict[str, Any]:
        """Return JSON-safe executor diagnostics."""
        return {
            "executor": "in_process",
            "session_count": len(self._namespaces),
            "guard": {
                "disallowed_import_roots": sorted(
                    self._guard.disallowed_import_roots,
                ),
                "disallowed_calls": sorted(self._guard.disallowed_calls),
            },
        }


def _compile_code(code: str, guard: CanonicalCapabilityGuard) -> CodeType:
    tree = guard.parse(code)
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


def _new_namespace(
    guard: CanonicalCapabilityGuard,
) -> dict[str, Any]:
    from ..governance.errors import (
        BrowserContextConflict,
        BrowserContextUnavailable,
        BrowserObservationRequired,
        BrowserPolicyDenied,
        BrowserSDKError,
        BrowserSDKGap,
    )

    from ..canonical.proxy import BrowserProxyClass as browser_proxy
    from ..canonical.proxy import canonical_value_namespace

    connect_browser = browser_proxy.connect
    namespace: dict[str, Any] = {"__builtins__": guard.safe_builtins()}
    namespace.update(
        {
            "Browser": browser_proxy,
            "BrowserSDKError": BrowserSDKError,
            "BrowserContextUnavailable": BrowserContextUnavailable,
            "BrowserContextConflict": BrowserContextConflict,
            "BrowserPolicyDenied": BrowserPolicyDenied,
            "BrowserSDKGap": BrowserSDKGap,
            "BrowserObservationRequired": BrowserObservationRequired,
            "connect_browser": connect_browser,
        },
    )
    namespace.update(canonical_value_namespace())
    return namespace


__all__ = [
    "BrowserCodeExecutor",
    "InProcessBrowserCodeExecutor",
]
