# -*- coding: utf-8 -*-
"""Tab collection facade for the unified Browser SDK."""

from __future__ import annotations

from typing import Any

from .tab import Tab, tab_from_backend


class Tabs:
    """Collection of tabs for a connected browser session."""

    def __init__(self, browser: Any) -> None:
        self._browser = browser
        self._session = browser.session
        self._context = browser.context
        self._cache: dict[str, Tab] = {}

    async def active(self) -> Tab:
        """Return the active tab."""
        active_tab = getattr(self._session, "active_tab", None)
        if callable(active_tab):
            raw = await active_tab()
        else:
            tabs = await self.list()
            raw = tabs[0] if tabs else {"id": "default"}
        return self._remember(tab_from_backend(
            raw,
            session=self._session,
            context=self._context,
        ))

    async def open(self, url: str | None = None) -> Tab:
        """Open a tab and mark it as needing observation before mutation."""
        raw = await self._session.open_tab(url)
        return self._remember(tab_from_backend(
            raw,
            session=self._session,
            context=self._context,
            observation_required=True,
        ))

    async def list(self) -> list[Tab]:
        """List browser tabs."""
        raw_tabs = await self._session.list_tabs()
        return [
            self._remember(tab_from_backend(
                raw,
                session=self._session,
                context=self._context,
            ))
            for raw in raw_tabs
        ]

    async def select(self, tab_id: str) -> Tab:
        """Select a tab by id."""
        raw = await self._session.select_tab(str(tab_id))
        return self._remember(tab_from_backend(
            raw,
            session=self._session,
            context=self._context,
        ))

    def _remember(self, tab: Tab) -> Tab:
        existing = self._cache.get(tab.id)
        if existing is not None:
            existing.url = tab.url or existing.url
            existing.title = tab.title or existing.title
            return existing
        self._cache[tab.id] = tab
        return tab


__all__ = ["Tabs"]
