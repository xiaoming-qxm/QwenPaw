# -*- coding: utf-8 -*-
"""Thin delegate to the registered BrowserControlEngine."""

from __future__ import annotations

import json
from typing import Any

from agentscope.tool import ToolChunk

from qwenpaw.browser.control_engine import get_control_engine

from ..runtime import _tool_response


async def _action_control(
    state: dict[str, Any],
    action: str,
    **kwargs: Any,
) -> ToolChunk:
    """Dispatch Browser Control actions through the registered engine."""
    engine = get_control_engine()
    if engine is None:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "Browser Control engine not loaded"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    return await engine.dispatch(state, action, **kwargs)


def _get_supported_actions() -> frozenset[str]:
    """Return actions supported by the registered engine."""
    engine = get_control_engine()
    return engine.supported_actions() if engine else frozenset()


_ACTION_HANDLERS: dict[str, Any] = {}


def _refresh_action_handlers() -> None:
    """Refresh the legacy action mapping from the registered engine."""
    global _ACTION_HANDLERS
    _ACTION_HANDLERS = {name: True for name in _get_supported_actions()}


class ControlBackend:
    """Compatibility backend that delegates all actions to the engine."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def _dispatch(self, action: str, **kwargs: Any) -> ToolChunk:
        return await _action_control(self.state, action, **kwargs)

    async def snapshot(self, **kwargs: Any) -> ToolChunk:
        return await self._dispatch("snapshot", **kwargs)

    async def click(self, **kwargs: Any) -> ToolChunk:
        return await self._dispatch("click", **kwargs)

    async def type_text(self, **kwargs: Any) -> ToolChunk:
        return await self._dispatch("type", **kwargs)

    async def press_key(self, **kwargs: Any) -> ToolChunk:
        return await self._dispatch("press_key", **kwargs)

    async def navigate(self, **kwargs: Any) -> ToolChunk:
        return await self._dispatch("navigate", **kwargs)

    async def list_tabs(self, **kwargs: Any) -> ToolChunk:
        return await self._dispatch("tabs", **kwargs)


__all__ = ["ControlBackend", "_ACTION_HANDLERS", "_action_control"]
