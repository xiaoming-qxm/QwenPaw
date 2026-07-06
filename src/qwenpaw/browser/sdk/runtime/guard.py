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


class _GuardVisitor(ast.NodeVisitor):
    def __init__(self, guard: CapabilityGuard) -> None:
        self._guard = guard

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._guard.validate_import(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self._guard.validate_import(node.module or "")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        call_name = _call_name(node.func)
        if call_name:
            self._guard.validate_call(call_name)
        self.generic_visit(node)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return ""


__all__ = [
    "CapabilityGuard",
    "DISALLOWED_CALLS",
    "DISALLOWED_IMPORT_ROOTS",
]
