# -*- coding: utf-8 -*-
"""Runtime-safe proxy projection for the canonical Browser surface."""

from __future__ import annotations

from typing import Any

from ..governance.errors import BrowserPolicyDenied
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

__all__ = ["BrowserProxyClass"]
