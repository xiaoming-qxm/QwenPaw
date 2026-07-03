# -*- coding: utf-8 -*-
"""Browser Control Engine protocol: plugin implements, core consumes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agentscope.tool import ToolChunk


class BrowserControlEngine(ABC):
    """Core-facing interface implemented by the Browser Control plugin."""

    @abstractmethod
    async def dispatch(
        self,
        state: dict[str, Any],
        action: str,
        **kwargs: Any,
    ) -> ToolChunk:
        """Execute a control action, mutating state in-place."""

    @abstractmethod
    def supported_actions(self) -> frozenset[str]:
        """Return the set of action names this engine handles."""

    @abstractmethod
    def get_request_context(self) -> dict[str, Any]:
        """Return current request context for control mode detection."""

    @abstractmethod
    def has_active_session(self, state: dict[str, Any]) -> bool:
        """Return whether the given workspace state has a control session."""


_engine: BrowserControlEngine | None = None


def register_control_engine(engine: BrowserControlEngine | None) -> None:
    """Register the active Browser Control engine."""
    global _engine
    _engine = engine


def get_control_engine() -> BrowserControlEngine | None:
    """Return the registered Browser Control engine, if one is loaded."""
    return _engine


def clear_control_engine() -> None:
    """Clear the active Browser Control engine registration."""
    register_control_engine(None)
