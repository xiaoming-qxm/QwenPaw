# -*- coding: utf-8 -*-
"""Executor boundary for browser(code=...) runtimes."""

from __future__ import annotations

import ast
import builtins
import inspect
from types import CodeType
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..governance.errors import BrowserPolicyDenied
from .session_owner import ContractMode
from .guard import CapabilityGuard

if TYPE_CHECKING:
    from .kernel import BrowserExecutionContext

_RETURN_NAME = "__qwenpaw_browser_return__"
_MAX_PREBOUND_REF_INDEX = 10000
_ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "collections",
        "datetime",
        "decimal",
        "functools",
        "itertools",
        "json",
        "math",
        "re",
        "statistics",
        "time",
        "typing",
    },
)


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

    def __init__(self, *, guard: CapabilityGuard | None = None) -> None:
        self._guard = guard or CapabilityGuard()
        self._namespaces: dict[
            tuple[str, str, ContractMode],
            dict[str, Any],
        ] = {}
        self._session_keys: dict[
            str,
            set[tuple[str, str, ContractMode]],
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
            execution_context.contract_mode,
        )
        guard = _guard_for_mode(execution_context.contract_mode, self._guard)
        namespace = self._namespaces.setdefault(
            namespace_key,
            _new_namespace(guard, execution_context.contract_mode),
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


def _compile_code(code: str, guard: CapabilityGuard) -> CodeType:
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


def _guard_for_mode(
    mode: ContractMode,
    legacy_guard: CapabilityGuard,
) -> CapabilityGuard:
    if mode is ContractMode.LEGACY:
        return legacy_guard
    from ..canonical.guard import CanonicalCapabilityGuard

    return CanonicalCapabilityGuard()


def _new_namespace(
    guard: CapabilityGuard,
    mode: ContractMode,
) -> dict[str, Any]:
    from ..governance.errors import (
        BrowserContextConflict,
        BrowserContextUnavailable,
        BrowserObservationRequired,
        BrowserSDKError,
        BrowserSDKGap,
    )

    if mode is ContractMode.CANONICAL:
        from ..canonical.proxy import (
            BrowserProxyClass as canonical_browser_proxy,
        )
        from ..canonical.proxy import canonical_value_namespace

        browser_proxy: Any = canonical_browser_proxy
        connect_browser = canonical_browser_proxy.connect
    else:
        from .proxy import BrowserProxyClass as legacy_browser_proxy
        from .proxy import connect_browser

        browser_proxy = legacy_browser_proxy

    namespace: dict[str, Any] = {"__builtins__": _safe_builtins(guard)}
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
    if mode is ContractMode.CANONICAL:
        namespace.update(canonical_value_namespace())
    if mode is ContractMode.LEGACY:
        namespace.update(
            {
                f"e{index}": f"e{index}"
                for index in range(1, _MAX_PREBOUND_REF_INDEX + 1)
            },
        )
    return namespace


def _safe_builtins(guard: CapabilityGuard) -> dict[str, Any]:
    return {
        "__build_class__": builtins.__build_class__,
        "__import__": _safe_import_factory(guard),
        "ArithmeticError": ArithmeticError,
        "AssertionError": AssertionError,
        "AttributeError": AttributeError,
        "BaseException": BaseException,
        "Exception": Exception,
        "IndexError": IndexError,
        "KeyError": KeyError,
        "LookupError": LookupError,
        "NameError": NameError,
        "RuntimeError": RuntimeError,
        "StopIteration": StopIteration,
        "TypeError": TypeError,
        "ValueError": ValueError,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "object": object,
        "print": print,
        "property": property,
        "range": range,
        "repr": repr,
        "round": round,
        "set": set,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "super": super,
        "tuple": tuple,
        "type": type,
        "zip": zip,
    }


def _safe_import_factory(guard: CapabilityGuard):
    def _safe_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        del globals_, locals_
        root = str(name or "").split(".", 1)[0]
        guard.validate_import(root)
        if level or root not in _ALLOWED_IMPORT_ROOTS:
            raise BrowserPolicyDenied(
                f"Import is not allowed in browser(code=...): {name}",
                action="browser_kernel_guard",
                metadata={"import": name, "level": level},
            )
        return builtins.__import__(name, {}, {}, fromlist, level)

    return _safe_import


__all__ = [
    "BrowserCodeExecutor",
    "InProcessBrowserCodeExecutor",
]
