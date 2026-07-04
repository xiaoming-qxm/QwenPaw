# -*- coding: utf-8 -*-
"""Browser SDK policy hook contracts."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable
from typing import Protocol, cast

from .types import (
    BrowserActionRequest,
    BrowserContextRequest,
    BrowserPolicyDecision,
)


class BrowserPolicy(Protocol):
    """Policy hook layer for browser context acquisition and actions."""

    def allow_context_acquisition(
        self,
        request: BrowserContextRequest,
    ) -> BrowserPolicyDecision:
        """Return whether a browser context may be acquired."""

    def allow_action(
        self,
        request: BrowserActionRequest,
    ) -> BrowserPolicyDecision | Awaitable[BrowserPolicyDecision]:
        """Return whether a browser action may execute."""


class DefaultBrowserPolicy:
    """Default allow-all policy used when governance is not wired."""

    def allow_context_acquisition(
        self,
        request: BrowserContextRequest,
    ) -> BrowserPolicyDecision:
        _ = request
        return BrowserPolicyDecision(allowed=True, reason="allowed")

    def allow_action(
        self,
        request: BrowserActionRequest,
    ) -> BrowserPolicyDecision | Awaitable[BrowserPolicyDecision]:
        _ = request
        return BrowserPolicyDecision(allowed=True, reason="allowed")


async def maybe_await_policy_decision(
    value: BrowserPolicyDecision | Awaitable[BrowserPolicyDecision],
) -> BrowserPolicyDecision:
    """Return a browser policy decision from sync or async policies."""
    if inspect.isawaitable(value):
        return await value
    return cast(BrowserPolicyDecision, value)


__all__ = [
    "BrowserPolicy",
    "DefaultBrowserPolicy",
    "maybe_await_policy_decision",
]
