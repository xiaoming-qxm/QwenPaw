# -*- coding: utf-8 -*-
"""Canonical capability guard for browser(code=...) snippets."""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
from typing import Any

from ..governance.errors import BrowserPolicyDenied

DISALLOWED_IMPORT_ROOTS = frozenset(
    {
        "os",
        "subprocess",
        "socket",
        "shutil",
        "pathlib",
    },
)
DISALLOWED_CALLS = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "input",
    },
)
ALLOWED_IMPORT_ROOTS = frozenset(
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
OLD_PUBLIC_ACTIONS = frozenset(
    {
        "dialog",
        "download",
        "open",
        "press",
        "search",
        "select",
        "type",
        "upload",
    },
)
PRIVATE_SDK_ATTRIBUTES = frozenset(
    {
        "_backend",
        "_call_action",
        "_call_browser_action",
        "_executor",
        "_runtime",
        "_session",
    },
)
META_INTROSPECTION_ATTRIBUTES = frozenset(
    {
        "__bases__",
        "__base__",
        "__call__",
        "__class__",
        "__closure__",
        "__code__",
        "__dict__",
        "__func__",
        "__getattr__",
        "__getattribute__",
        "__globals__",
        "__mro__",
        "__self__",
        "__subclasses__",
    },
)
META_INTROSPECTION_CALLS = frozenset(
    {
        "object.__getattribute__",
        "type.__getattribute__",
    },
)
_INITIAL_SDK_OBJECT_NAMES = frozenset({"browser", "tab"})
_BROWSER_FACTORY_CALLS = frozenset({"Browser.connect", "connect_browser"})
_TAB_FACTORY_SUFFIXES = (
    ".tabs.active",
    ".tabs.new",
    ".tabs.open",
    ".tabs.select",
)
_CANONICAL_SDK_HINT = (
    "Use only the documented Browser SDK. Observe, act, and verify. If unsure "
    "of an API or its arguments, call Browser.help(...)."
)
_META_INTROSPECTION_HINT = (
    "Do not use Python object introspection. Use only the documented Browser "
    "SDK; if unsure of an API or its arguments, call Browser.help(...)."
)


@dataclass(frozen=True)
class _BaseCapabilityGuard:
    """Validate browser snippets before Python evaluation."""

    disallowed_import_roots: frozenset[str] = DISALLOWED_IMPORT_ROOTS
    disallowed_calls: frozenset[str] = DISALLOWED_CALLS

    def parse(self, code: str) -> ast.Module:
        """Return a validated AST for *code*."""
        tree = ast.parse(str(code or ""), mode="exec")
        _GuardVisitor(self).visit(tree)
        return tree

    def validate_import(self, module_name: str) -> None:
        """Reject imports outside the browser kernel capability budget."""
        root = str(module_name or "").split(".", 1)[0]
        if root in self.disallowed_import_roots:
            raise BrowserPolicyDenied(
                f"Import is not allowed in browser(code=...): {root}",
                action="browser_kernel_guard",
                metadata={"import": module_name},
            )

    def validate_call(self, call_name: str) -> None:
        """Reject direct calls to blocked Python capabilities."""
        if call_name in self.disallowed_calls:
            raise BrowserPolicyDenied(
                f"Call is not allowed in browser(code=...): {call_name}",
                action="browser_kernel_guard",
                metadata={"call": call_name},
            )

    def safe_import(
        self,
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        """Import only reviewed pure-Python library roots."""
        del globals_, locals_
        root = str(name or "").split(".", 1)[0]
        self.validate_import(root)
        if level or root not in ALLOWED_IMPORT_ROOTS:
            raise BrowserPolicyDenied(
                f"Import is not allowed in browser(code=...): {name}",
                action="browser_kernel_guard",
                metadata={"import": name, "level": level},
            )
        return builtins.__import__(name, {}, {}, fromlist, level)

    def safe_builtins(self) -> dict[str, object]:
        """Return the complete reviewed browser-kernel builtin namespace."""
        return {
            "__build_class__": builtins.__build_class__,
            "__import__": self.safe_import,
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

    def deny_invalid_sdk_usage(self, pattern: str, hint: str) -> None:
        """Reject Browser SDK anti-patterns with recovery guidance."""
        raise BrowserPolicyDenied(
            "Browser SDK usage is not allowed in browser(code=...): "
            f"{pattern}. "
            f"{hint}",
            code="invalid_sdk_usage",
            action="browser_kernel_guard",
            metadata={
                "pattern": pattern,
                "recovery_hint": hint,
            },
        )


class _GuardVisitor(ast.NodeVisitor):
    def __init__(self, guard: _BaseCapabilityGuard) -> None:
        self._guard = guard
        self._imported_sleep_names: set[str] = set()
        self._sdk_object_names: set[str] = set(_INITIAL_SDK_OBJECT_NAMES)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._guard.validate_import(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self._guard.validate_import(node.module or "")
        if node.module == "time":
            for alias in node.names:
                if alias.name == "sleep":
                    self._imported_sleep_names.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        call_name = _call_name(node.func)
        if call_name:
            self._guard.validate_call(call_name)
            if call_name in META_INTROSPECTION_CALLS:
                self._guard.deny_invalid_sdk_usage(
                    "python_meta_introspection",
                    _META_INTROSPECTION_HINT,
                )
            self._validate_sdk_call(call_name)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        chain = _attribute_chain(node)
        if node.attr in META_INTROSPECTION_ATTRIBUTES:
            self._guard.deny_invalid_sdk_usage(
                "python_meta_introspection",
                _META_INTROSPECTION_HINT,
            )
        if _has_session_action(chain):
            self._guard.deny_invalid_sdk_usage(
                "session.action",
                _CANONICAL_SDK_HINT,
            )
        if self._is_sdk_object_chain(chain):
            for part in chain[1:]:
                if part.startswith("_") or part in PRIVATE_SDK_ATTRIBUTES:
                    self._guard.deny_invalid_sdk_usage(
                        "private_sdk_attribute",
                        _CANONICAL_SDK_HINT,
                    )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        self.generic_visit(node)
        self._track_sdk_assignment(node.value, node.targets)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        self.generic_visit(node)
        if node.value is not None:
            self._track_sdk_assignment(node.value, [node.target])

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # noqa: N802
        self.generic_visit(node)
        self._track_sdk_assignment(node.value, [node.target])

    def visit_Dict(self, node: ast.Dict) -> None:  # noqa: N802
        for key in node.keys:
            if _literal_string(key) == "selector":
                self._guard.deny_invalid_sdk_usage(
                    "selector",
                    "Use observation refs, role/name, exact text, or coords "
                    "instead of CSS selectors.",
                )
        self.generic_visit(node)

    def _validate_sdk_call(self, call_name: str) -> None:
        normalized = call_name.lower()
        parts = normalized.split(".")
        if normalized in {"time.sleep", "asyncio.sleep"}:
            self._guard.deny_invalid_sdk_usage(
                "sleep",
                "Use tab.wait_for(...) or an observation-driven condition "
                "instead of fixed sleeps.",
            )
        if call_name in self._imported_sleep_names:
            self._guard.deny_invalid_sdk_usage(
                "sleep",
                "Use tab.wait_for(...) or an observation-driven condition "
                "instead of fixed sleeps.",
            )
        if parts[-1:] == ["evaluate"]:
            self._guard.deny_invalid_sdk_usage(
                "evaluate",
                "Use documented primitives or actions and inspect them with "
                "Browser.help(...) instead of public JavaScript evaluation.",
            )
        if "cdp" in parts or any("cdp" in part for part in parts):
            self._guard.deny_invalid_sdk_usage(
                "cdp",
                "Raw CDP is not a public Browser SDK escape hatch.",
            )
        if parts[-1:] == ["action"]:
            self._guard.deny_invalid_sdk_usage(
                "session.action",
                "Use documented Browser SDK actions instead of public string "
                "dispatch. If unsure of an API, call Browser.help(...).",
            )
        if len(parts) >= 3 and parts[-2] == "actions":
            old_name = parts[-1]
            if old_name in OLD_PUBLIC_ACTIONS:
                self._guard.deny_invalid_sdk_usage(
                    f"{'.'.join(parts[-3:])}",
                    "Use the documented Browser SDK action name from "
                    "Browser.help(...).",
                )

    def _is_sdk_object_chain(self, chain: list[str]) -> bool:
        return bool(chain) and chain[0] in self._sdk_object_names

    def _track_sdk_assignment(
        self,
        value: ast.AST,
        targets: list[ast.expr],
    ) -> None:
        call_name = _value_call_name(value)
        if not call_name:
            return
        if _is_sdk_factory_call(call_name):
            for name in _target_names(targets):
                self._sdk_object_names.add(name)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    return ""


def _value_call_name(node: ast.AST) -> str:
    value = node.value if isinstance(node, ast.Await) else node
    if isinstance(value, ast.Call):
        return _call_name(value.func)
    return ""


def _is_sdk_factory_call(call_name: str) -> bool:
    if call_name in _BROWSER_FACTORY_CALLS:
        return True
    return call_name.endswith(_TAB_FACTORY_SUFFIXES)


def _target_names(targets: list[ast.expr]) -> tuple[str, ...]:
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
    return tuple(names)


def _attribute_chain(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        parent = _attribute_chain(node.value)
        if parent:
            return [*parent, node.attr]
    if isinstance(node, ast.Call):
        return _attribute_chain(node.func)
    return []


def _has_session_action(chain: list[str]) -> bool:
    return any(
        left in {"session", "_session"} and right == "action"
        for left, right in zip(chain, chain[1:])
    )


def _literal_string(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


class CapabilityGuard(_BaseCapabilityGuard):
    """Mode-specific guard type for canonical namespaces."""

    def parse(self, code: str) -> ast.Module:
        """Reject inline legacy target shapes using the catalog contract."""
        tree = super().parse(code)
        _TargetVisitor(self).visit(tree)
        return tree


class _TargetVisitor(ast.NodeVisitor):
    def __init__(self, guard: CapabilityGuard) -> None:
        from .proxy import action_target_parameters

        self._guard = guard
        self._targets = action_target_parameters()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        action = _action_name(node.func)
        target_names = self._targets.get(action)
        if target_names is not None:
            values = {
                name: node.args[index]
                for index, name in enumerate(target_names)
                if index < len(node.args)
            }
            values.update(
                {
                    keyword.arg: keyword.value
                    for keyword in node.keywords
                    if keyword.arg in target_names
                },
            )
            if any(
                _is_inline_legacy_target(value) for value in values.values()
            ):
                self._guard.deny_invalid_sdk_usage(
                    f"tab.actions.{action}.legacy_target_shape",
                    "Use an observed target supplied by the documented API. "
                    "If unsure of an API or its arguments, call "
                    "Browser.help(...).",
                )
        self.generic_visit(node)


def _action_name(node: ast.expr) -> str:
    if not isinstance(node, ast.Attribute):
        return ""
    owner = node.value
    if not isinstance(owner, ast.Attribute) or owner.attr != "actions":
        return ""
    return node.attr


def _is_inline_legacy_target(node: ast.expr) -> bool:
    return isinstance(
        node,
        (ast.Constant, ast.Dict, ast.List, ast.Set, ast.Tuple),
    )


__all__ = ["CapabilityGuard"]
