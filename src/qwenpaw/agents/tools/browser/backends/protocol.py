# -*- coding: utf-8 -*-
"""Backend protocol for browser tool implementations."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agentscope.tool import ToolChunk


@runtime_checkable
class BrowserBackend(Protocol):
    """Common async action surface implemented by browser backends."""

    async def snapshot(self, **kwargs: Any) -> ToolChunk:
        """Return structured page evidence."""

    async def click(self, **kwargs: Any) -> ToolChunk:
        """Click a target on the active page."""

    async def type_text(self, **kwargs: Any) -> ToolChunk:
        """Type text into the active page."""

    async def press_key(self, **kwargs: Any) -> ToolChunk:
        """Press a keyboard key on the active page."""

    async def navigate(self, **kwargs: Any) -> ToolChunk:
        """Navigate the active page to a URL."""

    async def list_tabs(self, **kwargs: Any) -> ToolChunk:
        """List available browser tabs."""
