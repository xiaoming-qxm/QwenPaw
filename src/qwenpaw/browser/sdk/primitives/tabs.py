# -*- coding: utf-8 -*-
"""Tab collection facade for the unified Browser SDK."""

from __future__ import annotations

from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from ..governance.error_codes import classify_browser_error
from ..telemetry.trace import record_browser_trace_event
from .tab import Tab, tab_from_backend


class BrowserTabs:
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
        return self._remember(
            tab_from_backend(
                raw,
                session=self._session,
                context=self._context,
                session_id=self._browser.session_id,
            ),
        )

    async def open(self, url: str | None = None) -> Tab:
        """Reuse the request workspace tab and navigate it to *url*."""
        started = perf_counter()
        try:
            tab = await self.active()
            if url:
                await tab.actions.open(url)
                tab.url = str(url)
        except Exception as exc:
            self._trace(
                action="open",
                status="error",
                duration_ms=_duration_ms(started),
                url=str(url or ""),
                error_code=_error_code(exc),
                metadata={"error_type": type(exc).__name__},
            )
            raise
        self._trace(
            action="open",
            status="ok",
            duration_ms=_duration_ms(started),
            tab_id=tab.id,
            url=tab.url or str(url or ""),
            metadata={"workspace_reuse": True},
        )
        return self._remember(tab)

    async def new(self, url: str | None = None) -> Tab:
        """Explicitly create a new browser tab for the request workspace."""
        return await self._open_new_tab(url)

    async def _open_new_tab(self, url: str | None = None) -> Tab:
        """Open a new tab and mark it as needing observation before mutation."""
        started = perf_counter()
        try:
            raw = await self._session.open_tab(url)
            tab = tab_from_backend(
                raw,
                session=self._session,
                context=self._context,
                session_id=self._browser.session_id,
                observation_required=True,
            )
        except Exception as exc:
            self._trace(
                action="open",
                status="error",
                duration_ms=_duration_ms(started),
                url=str(url or ""),
                error_code=_error_code(exc),
                metadata={"error_type": type(exc).__name__},
            )
            raise
        self._trace(
            action="new",
            status="ok",
            duration_ms=_duration_ms(started),
            tab_id=tab.id,
            url=tab.url or str(url or ""),
            metadata={"workspace_reuse": False},
        )
        return self._remember(tab)

    async def list(self) -> list[Tab]:
        """List browser tabs."""
        started = perf_counter()
        try:
            raw_tabs = await self._session.list_tabs()
            tabs = [
                self._remember(
                    tab_from_backend(
                        raw,
                        session=self._session,
                        context=self._context,
                        session_id=self._browser.session_id,
                    ),
                )
                for raw in raw_tabs
            ]
        except Exception as exc:
            self._trace(
                action="list",
                status="error",
                duration_ms=_duration_ms(started),
                error_code=_error_code(exc),
                metadata={"error_type": type(exc).__name__},
            )
            raise
        self._trace(
            action="list",
            status="ok",
            duration_ms=_duration_ms(started),
            metadata={"tab_count": len(tabs)},
        )
        return tabs

    async def select(self, tab_id: str) -> Tab:
        """Select a tab by id."""
        started = perf_counter()
        normalized_tab_id = str(tab_id)
        try:
            raw = await self._session.select_tab(normalized_tab_id)
            tab = tab_from_backend(
                raw,
                session=self._session,
                context=self._context,
                session_id=self._browser.session_id,
            )
        except Exception as exc:
            self._trace(
                action="select",
                status="error",
                duration_ms=_duration_ms(started),
                tab_id=normalized_tab_id,
                error_code=_error_code(exc),
                metadata={"error_type": type(exc).__name__},
            )
            raise
        self._trace(
            action="select",
            status="ok",
            duration_ms=_duration_ms(started),
            tab_id=tab.id,
            url=tab.url,
        )
        return self._remember(tab)

    async def get(self, tab_id: str) -> Tab:
        """Return an existing tab by id using the backend select contract."""
        return await self.select(str(tab_id))

    def _remember(self, tab: Tab) -> Tab:
        existing = self._cache.get(tab.id)
        if existing is not None:
            existing.url = tab.url or existing.url
            existing.title = tab.title or existing.title
            return existing
        self._cache[tab.id] = tab
        return tab

    def _trace(
        self,
        *,
        action: str,
        status: str,
        duration_ms: float,
        tab_id: str = "",
        url: str = "",
        error_code: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record_browser_trace_event(
            session_id=self._browser.session_id,
            phase="tab_lifecycle",
            backend_id=self._context.backend_id,
            requested_context=self._context.requested,
            selected_context=self._context.selected,
            action=action,
            tab_id=tab_id,
            url=url,
            domain=_domain_from_url(url),
            status=status,
            duration_ms=duration_ms,
            error_code=error_code,
            metadata=metadata,
        )


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _error_code(exc: Exception) -> str:
    return classify_browser_error(exc).code.value


def _domain_from_url(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


__all__ = ["BrowserTabs"]
