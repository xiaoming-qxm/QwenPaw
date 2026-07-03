# -*- coding: utf-8 -*-
"""Top-level Browser facade for the Browser Control SDK."""
# pylint: disable=protected-access,redefined-builtin

from __future__ import annotations

import contextlib
import uuid
from typing import Any

from qwenpaw.browser_sdk import Browser as CoreBrowser
from qwenpaw.browser_sdk import Tabs as CoreTabs

from .errors import BridgeDisconnected, BrowserSDKError
from .remote_bridge import RemoteBridge
from .tab import Tab
from .types import TabInfo

_REQUEST_CONTEXT: dict[str, Any] = {}
_SESSION_STATES: dict[str, dict[str, Any]] = {}
_SESSION_HOLDER_IDS: dict[str, str] = {}


class Tabs:
    """Tab collection facade backed by the native messaging bridge."""

    def __init__(self, bridge: Any, holder_id: str, state: Any) -> None:
        self._bridge = bridge
        self._holder_id = holder_id
        self._state = state
        self._current: Tab | None = None

    async def list(self, *, all: bool = False) -> list[TabInfo]:
        """List SDK-controlled tabs, or all visible tabs when requested."""
        raw_tabs = await self._bridge.discover_tabs()
        visible_tabs = [
            TabInfo(
                id=int(tab["id"]),
                url=str(tab.get("url") or ""),
                title=str(tab.get("title") or ""),
            )
            for tab in raw_tabs
            if isinstance(tab, dict) and "id" in tab
        ]
        if all:
            return visible_tabs
        return self._controlled_tab_infos(visible_tabs)

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
                tabs = await self.list(all=True)
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
        if self._current is not None:
            return self._current
        tab_id = _current_state_tab_id(self._state)
        if tab_id is None:
            return None
        tab = Tab(tab_id, self._bridge, self._holder_id, self._state)
        self._current = tab
        return tab

    async def close(
        self,
        tab_id: int | Tab | None = None,
        *,
        force: bool = False,
    ):
        """Close or release a tab without changing its creation metadata."""
        if isinstance(tab_id, Tab):
            tab = tab_id
        elif tab_id is None:
            tab = await self.current()
            if tab is None:
                raise BrowserSDKError("No current browser tab is available")
        else:
            tab = Tab(int(tab_id), self._bridge, self._holder_id, self._state)
        result = await tab.close(force=force)
        if self._current is not None and self._current.id == tab.id:
            self._current = None
        return result

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
                        "url": str(
                            tab.get("url") or tab.get("pendingUrl") or "",
                        ),
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
        _apply_request_context_to_tab_record(
            tabs[str(tab_id)],
            _state_request_context(self._state),
        )
        self._state["current_page_id"] = str(tab_id)

    def _controlled_tab_infos(
        self,
        visible_tabs: list[TabInfo],
    ) -> list[TabInfo]:
        try:
            tabs = self._state.get("control_tabs", {})
        except AttributeError:
            tabs = getattr(self._state, "control_tabs", {})
        if not isinstance(tabs, dict):
            return []

        visible_by_id = {tab.id: tab for tab in visible_tabs}
        result: list[TabInfo] = []
        for key, record in tabs.items():
            if not isinstance(record, dict):
                continue
            holder_id = str(record.get("holder_id") or "")
            if holder_id and holder_id != self._holder_id:
                continue
            tab_id = _record_tab_id(key, record)
            if tab_id is None:
                continue
            live = visible_by_id.get(tab_id)
            if live is None:
                continue
            record_url = str(record.get("url") or "")
            live_url = str(live.url or "")
            url = (
                record_url
                if record_url and record_url != "about:blank"
                else live_url
            )
            title = str(live.title or record.get("title") or "")
            record["url"] = url
            record["title"] = title
            result.append(TabInfo(id=tab_id, url=url, title=title))
        return result


class _BrowserConnect:
    """Descriptor that supports class and instance Browser.connect calls."""

    def __get__(self, instance: Any, owner: type) -> Any:
        async def connect(ws_url: str = "", token: str = "") -> Browser:
            if instance is None:
                return await owner._connect_new(ws_url, token)
            replacement = await owner._connect_new(
                ws_url or _bridge_value(instance._bridge, "ws_url"),
                token or _bridge_value(instance._bridge, "token"),
            )
            await instance._replace_connection(replacement)
            return instance

        return connect


class Browser:
    """Entry point for the Browser Control SDK."""

    connect = _BrowserConnect()

    def __init__(self, bridge: Any, holder_id: str, state: Any) -> None:
        self.tabs = Tabs(bridge, holder_id, state)
        self._bridge = bridge
        self._holder_id = holder_id
        self._state = state

    @classmethod
    async def _connect_new(
        cls,
        ws_url: str = "",
        token: str = "",
    ) -> "Browser":
        """Create a Browser SDK entry point for REPL-generated code."""
        bridge = _current_bridge()
        if bridge is None and ws_url:
            bridge = await RemoteBridge.connect(ws_url, token)
        if bridge is None:
            bridge = _DisconnectedBridge(ws_url, token)
        request_context = get_request_context()
        holder_id = _session_holder_id(request_context)
        state = _session_state(request_context)
        return cls(bridge, holder_id, state)

    async def documentation(self) -> str:
        """Return the SDK API reference."""
        from .documentation import generate_api_reference

        return generate_api_reference()

    async def close(self) -> None:
        """Release all tabs held by this browser instance."""
        with contextlib.suppress(BridgeDisconnected):
            await self._bridge.release_all(self._holder_id)
        close = getattr(self._bridge, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result
        _forget_session(self._state, self._holder_id)

    async def _replace_connection(self, replacement: "Browser") -> None:
        await _close_bridge_transport(self._bridge)
        self._bridge = replacement._bridge
        if self._state is not replacement._state:
            _merge_session_state(self._state, replacement._state)
            _adopt_session_cache(
                replacement._state,
                self._state,
                self._holder_id,
            )
        self.tabs = Tabs(self._bridge, self._holder_id, self._state)

    def _set_request_context(
        self,
        request_context: dict[str, Any] | None,
    ) -> None:
        _set_state_request_context(self._state, request_context)


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


def set_request_context(request_context: dict[str, Any] | None) -> None:
    """Refresh the Browser SDK request context for the current tool call."""

    global _REQUEST_CONTEXT  # pylint: disable=global-statement
    _REQUEST_CONTEXT = dict(request_context or {})


def get_request_context() -> dict[str, Any]:
    """Return the Browser SDK request context for the current tool call."""

    return dict(_REQUEST_CONTEXT)


def _request_context_key(request_context: dict[str, Any]) -> str:
    for key in ("root_session_id", "session_id"):
        value = str(request_context.get(key) or "").strip()
        if value:
            return value
    return "default"


def _session_holder_id(request_context: dict[str, Any]) -> str:
    key = _request_context_key(request_context)
    holder_id = _SESSION_HOLDER_IDS.get(key)
    if holder_id:
        return holder_id
    suffix = key if key != "default" else uuid.uuid4().hex
    holder_id = f"browser_sdk:{suffix}"
    _SESSION_HOLDER_IDS[key] = holder_id
    return holder_id


def _session_state(request_context: dict[str, Any]) -> dict[str, Any]:
    key = _request_context_key(request_context)
    state = _SESSION_STATES.get(key)
    if state is None:
        state = {"workspace_id": "browser_sdk"}
        _SESSION_STATES[key] = state
    _set_state_request_context(state, request_context)
    return state


def _forget_session(state: dict[str, Any], holder_id: str) -> None:
    for key, cached_state in list(_SESSION_STATES.items()):
        if cached_state is state:
            _SESSION_STATES.pop(key, None)
            if _SESSION_HOLDER_IDS.get(key) == holder_id:
                _SESSION_HOLDER_IDS.pop(key, None)


def _merge_session_state(
    current: dict[str, Any],
    replacement: dict[str, Any],
) -> None:
    request_context = replacement.get("request_context")
    if isinstance(request_context, dict) and request_context:
        _set_state_request_context(current, request_context)


def _adopt_session_cache(
    old_state: dict[str, Any],
    new_state: dict[str, Any],
    holder_id: str,
) -> None:
    for key, cached_state in list(_SESSION_STATES.items()):
        if cached_state is old_state:
            _SESSION_STATES[key] = new_state
            _SESSION_HOLDER_IDS[key] = holder_id


async def _close_bridge_transport(bridge: Any) -> None:
    close = getattr(bridge, "close", None)
    if not callable(close):
        return
    with contextlib.suppress(Exception):
        result = close()
        if hasattr(result, "__await__"):
            await result


def _current_state_tab_id(state: Any) -> int | None:
    try:
        current = state.get("current_page_id")
    except AttributeError:
        current = getattr(state, "current_page_id", None)
    if isinstance(current, int):
        return current
    if isinstance(current, str) and current.isdigit():
        return int(current)
    return None


def _record_tab_id(key: Any, record: dict[str, Any]) -> int | None:
    value = record.get("tab_id", key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _set_state_request_context(
    state: dict[str, Any],
    request_context: dict[str, Any] | None,
) -> None:
    context = dict(request_context or {})
    if context:
        state["request_context"] = context
        return
    state.pop("request_context", None)


def _state_request_context(state: dict[str, Any]) -> dict[str, Any]:
    request_context = state.get("request_context")
    return dict(request_context) if isinstance(request_context, dict) else {}


def _apply_request_context_to_tab_record(
    record: dict[str, Any],
    request_context: dict[str, Any],
) -> None:
    for key in (
        "session_id",
        "root_session_id",
        "agent_id",
        "root_agent_id",
        "tool_call_id",
        "user_id",
        "channel",
    ):
        value = str(request_context.get(key) or "")
        if value:
            record[key] = value


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


def _bridge_value(bridge: Any, name: str) -> str:
    return str(getattr(bridge, name, "") or "")


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
        from ..engine.navigation import (
            _control_remember_approved_navigation,
        )
    except (ImportError, RuntimeError):
        return
    _control_remember_approved_navigation(state, url)


def _url_key(url: str) -> str:
    try:
        from ..engine.navigation import (
            _control_url_key,
        )
    except (ImportError, RuntimeError):
        return ""
    return _control_url_key(url) if url else ""


__all__ = [
    "Browser",
    "CoreBrowser",
    "CoreTabs",
    "Tabs",
    "get_request_context",
    "set_request_context",
]
