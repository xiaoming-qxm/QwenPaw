# -*- coding: utf-8 -*-
"""Browser SDK policy hook contracts."""

from __future__ import annotations

from typing import Protocol

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
    ) -> BrowserPolicyDecision:
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
    ) -> BrowserPolicyDecision:
        _ = request
        return BrowserPolicyDecision(allowed=True, reason="allowed")


__all__ = ["BrowserPolicy", "DefaultBrowserPolicy"]
