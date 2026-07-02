# -*- coding: utf-8 -*-
"""Top-level Browser facade for the Browser Control SDK."""

from __future__ import annotations

import uuid
from typing import Any

from .errors import BridgeDisconnected, BrowserSDKError
from .remote_bridge import RemoteBridge
from .tab import Tab
from .types import TabInfo


class Tabs:
    """Tab collection facade backed by the native messaging bridge."""

    def __init__(self, bridge: Any, holder_id: str, state: Any) -> None:
        self._bridge = bridge
        self._holder_id = holder_id
        self._state = state
        self._current: Tab | None = None

    async def list(self) -> list[TabInfo]:
        """List available browser tabs."""
        raw_tabs = await self._bridge.discover_tabs()
        return [
            TabInfo(
                id=int(tab["id"]),
                url=str(tab.get("url") or ""),
                title=str(tab.get("title") or ""),
            )
            for tab in raw_tabs
            if isinstance(tab, dict) and "id" in tab
        ]

    async def get(self, tab_id: int | Tab) -> Tab:
        """Claim a tab and return its SDK object."""
        if isinstance(tab_id, Tab):
            self._current = tab_id
            return tab_id
        tab_id = int(tab_id)
        await self._attach_tab(tab_id, created_by_control=False)
        tab = Tab(tab_id, self._bridge, self._holder_id, self._state)
        self._current = tab
        return tab

    async def open(self, url: str = "about:blank") -> Tab:
        """Open a new background tab, claim it, and return its SDK object."""
        url = str(url or "about:blank").strip() or "about:blank"
        _remember_approved_navigation(self._state, url)
        response = await self._bridge.request(
            "tab.create",
            {"url": url, "active": False},
        )
        tab_id = _created_tab_id(response)
        await self._attach_tab(tab_id, url=url, created_by_control=True)
        tab = Tab(tab_id, self._bridge, self._holder_id, self._state)
        self._current = tab
        return tab

    async def new_tab(self, url: str = "about:blank") -> Tab:
        """Compatibility alias for open(url)."""
        return await self.open(url)

    async def new(self, url: str = "about:blank") -> Tab:
        """Compatibility alias for open(url)."""
        return await self.open(url)

    async def claim(
        self,
        tab_id: int | None = None,
        url: str = "about:blank",
        allow_new_context: bool = True,
        **_kwargs: Any,
    ) -> Tab:
        """Compatibility alias for opening or getting a controlled tab."""
        if tab_id is None:
            if not allow_new_context:
                tabs = await self.list()
                if tabs:
                    return await self.get(tabs[0].id)
                raise BrowserSDKError(
                    "No existing browser tab is available to claim",
                )
            return await self.open(url)
        return await self.get(tab_id)

    async def claim_tab(
        self,
        tab_id: int | Tab | None = None,
        url: str = "about:blank",
        allow_new_context: bool = True,
        **kwargs: Any,
    ) -> Tab:
        """Compatibility alias for claim(tab_id, url)."""
        if isinstance(tab_id, Tab):
            return await self.get(tab_id)
        return await self.claim(
            tab_id=tab_id,
            url=url,
            allow_new_context=allow_new_context,
            **kwargs,
        )

    async def current(self) -> Tab | None:
        """Return the most recently claimed tab, if any."""
        return self._current

    async def _attach_tab(
        self,
        tab_id: int,
        *,
        url: str = "",
        created_by_control: bool,
    ) -> None:
        await self._bridge.claim_tab(tab_id, self._holder_id)
        response = await self._bridge.request(
            "tab.attach",
            {"tabId": tab_id, "holderId": self._holder_id},
        )
        error = _jsonrpc_error(response)
        if error:
            raise BrowserSDKError(f"Failed to attach tab {tab_id}: {error}")
        info = await self._tab_info(tab_id)
        self._remember_tab(
            tab_id,
            url=url or str(info.get("url") or ""),
            title=str(info.get("title") or ""),
            created_by_control=created_by_control,
        )

    async def _tab_info(self, tab_id: int) -> dict[str, str]:
        for tab in await self._bridge.discover_tabs():
            try:
                if int(tab.get("id") or tab.get("tabId") or -1) == tab_id:
                    return {
                        "url": str(tab.get("url") or tab.get("pendingUrl") or ""),
                        "title": str(tab.get("title") or ""),
                    }
            except (TypeError, ValueError):
                continue
        return {"url": "", "title": ""}

    def _remember_tab(
        self,
        tab_id: int,
        *,
        url: str,
        title: str,
        created_by_control: bool,
    ) -> None:
        tabs = self._state.setdefault("control_tabs", {})
        tabs[str(tab_id)] = {
            "tab_id": tab_id,
            "holder_id": self._holder_id,
            "url": url,
            "title": title,
            "url_key": _url_key(url),
            "created_by_control": bool(created_by_control),
        }
        self._state["current_page_id"] = str(tab_id)


class Browser:
    """Entry point for the Browser Control SDK."""

    def __init__(self, bridge: Any, holder_id: str, state: Any) -> None:
        self.tabs = Tabs(bridge, holder_id, state)
        self._bridge = bridge
        self._holder_id = holder_id
        self._state = state

    @classmethod
    async def connect(cls, ws_url: str = "", token: str = "") -> "Browser":
        """Create a Browser SDK entry point for REPL-generated code."""
        bridge = _current_bridge()
        if bridge is None and ws_url:
            bridge = await RemoteBridge.connect(ws_url, token)
        if bridge is None:
            bridge = _DisconnectedBridge(ws_url, token)
        holder_id = f"python_repl:{uuid.uuid4().hex}"
        state = {"workspace_id": "python_repl"}
        return cls(bridge, holder_id, state)

    async def documentation(self) -> str:
        """Return the SDK API reference."""
        from .documentation import generate_api_reference

        return generate_api_reference()

    async def close(self) -> None:
        """Release all tabs held by this browser instance."""
        await self._bridge.release_all(self._holder_id)
        close = getattr(self._bridge, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result


def _current_bridge() -> Any | None:
    try:
        from qwenpaw.browser.connection_manager import (
            get_bridge_connection_manager,
        )
    except (ImportError, RuntimeError):
        return None
    manager = get_bridge_connection_manager()
    if manager is None or not manager.is_connected():
        return None
    return manager.get_connection()


class _DisconnectedBridge:
    def __init__(self, ws_url: str, token: str) -> None:
        self.ws_url = ws_url
        self.token = token
        self.connected = False

    async def discover_tabs(self) -> list[dict[str, Any]]:
        raise BridgeDisconnected(_disconnect_message(self.ws_url))

    async def claim_tab(self, tab_id: int, holder_id: str) -> bool:
        raise BridgeDisconnected(
            _disconnect_message(
                self.ws_url,
                detail=f"tab={tab_id} holder={holder_id}",
            ),
        )

    async def release_all(self, holder_id: str | None = None) -> None:
        if holder_id is not None:
            return None
        return None

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        raise BridgeDisconnected(_disconnect_message(self.ws_url))


def _disconnect_message(ws_url: str, *, detail: str = "") -> str:
    target = ws_url or "the Browser Control bridge"
    suffix = f" ({detail})" if detail else ""
    return f"Browser Control bridge is not connected: {target}{suffix}"


def _jsonrpc_error(response: dict[str, Any]) -> str:
    error = response.get("error") if isinstance(response, dict) else None
    if not error:
        return ""
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def _jsonrpc_result(response: dict[str, Any]) -> Any:
    if not isinstance(response, dict):
        return None
    return response.get("result")


def _created_tab_id(response: dict[str, Any]) -> int:
    error = _jsonrpc_error(response)
    if error:
        raise BrowserSDKError(error)
    result = _jsonrpc_result(response)
    value = result.get("id") if isinstance(result, dict) else None
    if value is None and isinstance(result, dict):
        value = result.get("tabId")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise BrowserSDKError("tab.create did not return a tab id")


def _remember_approved_navigation(state: dict[str, Any], url: str) -> None:
    try:
        from qwenpaw.agents.tools.browser.control.navigation import (
            _control_remember_approved_navigation,
        )
    except (ImportError, RuntimeError):
        return
    _control_remember_approved_navigation(state, url)


def _url_key(url: str) -> str:
    try:
        from qwenpaw.agents.tools.browser.control.navigation import (
            _control_url_key,
        )
    except (ImportError, RuntimeError):
        return ""
    return _control_url_key(url) if url else ""


__all__ = ["Browser", "Tabs"]
