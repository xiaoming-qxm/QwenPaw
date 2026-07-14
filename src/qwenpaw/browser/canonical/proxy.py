# -*- coding: utf-8 -*-
"""Runtime-safe proxy projection for the canonical Browser surface."""

from __future__ import annotations

from typing import Any

from ..governance.errors import BrowserPolicyDenied
from .contracts import canonical_api_catalog, canonical_value_namespace
from .facade import Browser


class _BrowserFactoryProxy:
    __slots__ = ()

    def __getattribute__(self, name: str) -> Any:
        if name == "connect":
            return Browser.connect
        if name in {"__repr__", "__str__"}:
            return object.__getattribute__(self, name)
        raise BrowserPolicyDenied(
            f"Canonical Browser attribute is not public: {name}",
            action="canonical_proxy",
        )

    def __repr__(self) -> str:
        return "<CanonicalBrowserProxyClass>"


BrowserProxyClass = _BrowserFactoryProxy()


def canonical_action_target_parameters() -> dict[str, tuple[str, ...]]:
    """Derive target-bearing action parameters from the sole catalog."""
    result: dict[str, tuple[str, ...]] = {}
    for entry in canonical_api_catalog()["apis"]:
        api_id = str(entry["api_id"])
        if not api_id.startswith("tab.actions."):
            continue
        parameters = tuple(
            str(parameter["name"])
            for parameter in entry["parameters"]
            if parameter.get("annotation") == "TargetRef"
        )
        if parameters:
            result[api_id.rsplit(".", 1)[-1]] = parameters
    return result


__all__ = [
    "BrowserProxyClass",
    "canonical_action_target_parameters",
    "canonical_value_namespace",
]
