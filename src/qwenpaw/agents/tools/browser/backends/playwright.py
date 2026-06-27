# -*- coding: utf-8 -*-
"""Playwright backend class for the browser tool."""

from __future__ import annotations

from typing import Any

from agentscope.tool import ToolChunk

from .playwright_basic import (
    _action_click,
    _action_navigate,
    _action_snapshot,
    _action_type,
)
from .playwright_interactions import _action_press_key, _action_tabs


class PlaywrightBackend:
    """Protocol implementation backed by Playwright action functions."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def snapshot(self, **kwargs: Any) -> ToolChunk:
        """Return structured page evidence."""
        return await _action_snapshot(
            self.state,
            kwargs.get("page_id", ""),
            kwargs.get("filename", ""),
            kwargs.get("frame_selector", ""),
        )

    async def click(self, **kwargs: Any) -> ToolChunk:
        """Click a target on the active page."""
        return await _action_click(
            self.state,
            kwargs.get("page_id", ""),
            kwargs.get("selector", ""),
            kwargs.get("ref", ""),
            kwargs.get("element", ""),
            int(kwargs.get("wait", 0)),
            bool(kwargs.get("double_click", False)),
            kwargs.get("button", "left"),
            kwargs.get("modifiers_json", ""),
            kwargs.get("frame_selector", ""),
        )

    async def type_text(self, **kwargs: Any) -> ToolChunk:
        """Type text into the active page."""
        return await _action_type(
            self.state,
            kwargs.get("page_id", ""),
            kwargs.get("selector", ""),
            kwargs.get("ref", ""),
            kwargs.get("element", ""),
            kwargs.get("text", ""),
            bool(kwargs.get("submit", False)),
            bool(kwargs.get("slowly", False)),
            kwargs.get("frame_selector", ""),
        )

    async def press_key(self, **kwargs: Any) -> ToolChunk:
        """Press a keyboard key on the active page."""
        return await _action_press_key(
            self.state,
            kwargs.get("page_id", ""),
            kwargs.get("key", ""),
        )

    async def navigate(self, **kwargs: Any) -> ToolChunk:
        """Navigate the active page to a URL."""
        return await _action_navigate(
            self.state,
            kwargs.get("url", ""),
            kwargs.get("page_id", ""),
        )

    async def list_tabs(self, **_kwargs: Any) -> ToolChunk:
        """List available Playwright pages."""
        return await _action_tabs(self.state, "", "list", -1)


__all__ = ["PlaywrightBackend"]
