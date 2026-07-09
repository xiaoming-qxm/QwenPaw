# -*- coding: utf-8 -*-
"""Capability guard for browser(code=...) snippets."""

from __future__ import annotations

import ast
from dataclasses import dataclass

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


@dataclass(frozen=True)
class CapabilityGuard:
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
    def __init__(self, guard: CapabilityGuard) -> None:
        self._guard = guard
        self._imported_sleep_names: set[str] = set()

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
            self._validate_sdk_call(call_name)
        self.generic_visit(node)

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
                "Use Browser.capabilities(...) and documented primitives or "
                "actions instead of public JavaScript evaluation.",
            )
        if "cdp" in parts or any("cdp" in part for part in parts):
            self._guard.deny_invalid_sdk_usage(
                "cdp",
                "Raw CDP is not a public Browser SDK escape hatch.",
            )
        if parts[-1:] == ["action"]:
            self._guard.deny_invalid_sdk_usage(
                "session.action",
                "Use canonical tab.actions.* methods instead of public string "
                "dispatch.",
            )
        if len(parts) >= 3 and parts[-2] == "actions":
            old_name = parts[-1]
            if old_name in OLD_PUBLIC_ACTIONS:
                self._guard.deny_invalid_sdk_usage(
                    f"{'.'.join(parts[-3:])}",
                    "Use the canonical generated Browser SDK action name from "
                    "Browser.capabilities(...) or Browser.help(...).",
                )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    return ""


def _literal_string(node: ast.AST | None) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


__all__ = [
    "CapabilityGuard",
    "DISALLOWED_CALLS",
    "DISALLOWED_IMPORT_ROOTS",
    "OLD_PUBLIC_ACTIONS",
]
