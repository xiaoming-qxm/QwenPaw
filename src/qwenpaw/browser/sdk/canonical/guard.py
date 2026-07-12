# -*- coding: utf-8 -*-
"""Canonical browser(code=...) capability guard."""

from __future__ import annotations

import ast

from ..runtime.guard import CapabilityGuard
from .proxy import canonical_action_target_parameters


class CanonicalCapabilityGuard(CapabilityGuard):
    """Mode-specific guard type for canonical namespaces."""

    def parse(self, code: str) -> ast.Module:
        """Reject inline legacy target shapes using the catalog contract."""
        tree = super().parse(code)
        _CanonicalTargetVisitor(self).visit(tree)
        return tree


class _CanonicalTargetVisitor(ast.NodeVisitor):
    def __init__(self, guard: CanonicalCapabilityGuard) -> None:
        self._guard = guard
        self._targets = canonical_action_target_parameters()

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
                    "Pass a Runtime-issued TargetRef from canonical snapshot "
                    "evidence.",
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


__all__ = ["CanonicalCapabilityGuard"]
