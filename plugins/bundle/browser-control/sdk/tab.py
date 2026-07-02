# -*- coding: utf-8 -*-
"""Tab facade for the Browser Control SDK."""

from __future__ import annotations

import json
from typing import Any, cast

from qwenpaw.agents.tools.browser.control import (
    navigation as control_navigation,
)
from qwenpaw.agents.tools.browser.control.handlers import ACTION_HANDLERS
from qwenpaw.agents.tools.browser.control.handlers.dispatcher import dispatch
from qwenpaw.agents.tools.browser.control.handlers.misc import (
    unsupported_control_action_response,
)
from qwenpaw.agents.tools.browser.control.interactions import (
    click_control,
    press_key_control,
    set_network_quiescence_wait,
    type_control,
)
from qwenpaw.agents.tools.browser.control.navigation import (
    _CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS,
    _CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS,
    _control_remember_approved_navigation,
    _control_url_key,
)
from qwenpaw.agents.tools.browser.control.network_settle import (
    _network_quiescence_wait,
)
from qwenpaw.agents.tools.browser.control.session_manager import (
    _control_get_session,
)
from qwenpaw.agents.tools.browser.control.snapshot_builder import (
    build_control_snapshot,
)
from qwenpaw.agents.tools.browser.control.state import ControlState

from .errors import BrowserSDKError
from .guard import ObserveActGuard
from .types import (
    ActionResult,
    ClickResult,
    RefInfo,
    ScreenshotResult,
    Snapshot,
    TypeResult,
)


class Tab:
    """OOP wrapper around Browser Control actions for one tab."""

    def __init__(
        self,
        tab_id: int,
        bridge: Any,
        holder_id: str,
        state: Any,
    ) -> None:
        self.id = int(tab_id)
        self._bridge = bridge
        self._holder_id = holder_id
        self._state = state
        self._guard = ObserveActGuard()

    @property
    def tab_id(self) -> int:
        """Compatibility alias for code that names the tab id explicitly."""
        return self.id

    @property
    def url(self) -> str:
        """Return the last known URL for this tab."""
        return _known_tab_field(self._state, self.id, "url")

    @property
    def title(self) -> str:
        """Return the last known title for this tab."""
        return _known_tab_field(self._state, self.id, "title")

    def __getitem__(self, key: str) -> Any:
        """Return common tab fields using dict-style access."""
        if key in {"id", "tab_id", "tabId"}:
            return self.id
        if key == "url":
            return self.url
        if key == "title":
            return self.title
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Return common tab fields using dict-style access."""
        try:
            return self[key]
        except KeyError:
            return default

    async def snapshot(self) -> Snapshot:
        """Observe the current tab and return a structured snapshot."""
        session = await _control_get_session(
            self._state,
            tab_id=self.id,
            holder_id=self._holder_id,
            bridge=self._bridge,
            request_context={},
        )
        text, refs_raw, degraded = await build_control_snapshot(session)
        self._store_refs(refs_raw)
        refs = {
            key: _ref_info(value)
            for key, value in refs_raw.items()
            if isinstance(value, dict)
        }
        self._guard.mark_observed()
        return Snapshot(text=text, refs=refs, degraded=degraded)

    async def screenshot(
        self,
        *,
        path: str = "",
        full_page: bool = False,
        screenshot_type: str = "png",
    ) -> ScreenshotResult:
        """Observe the current tab visually and save a screenshot."""
        payload = _chunk_payload(
            await _action_with_bridge(
                self._state,
                "screenshot",
                holder_id=self._holder_id,
                bridge=self._bridge,
                kwargs={
                    "page_id": str(self.id),
                    "path": path,
                    "full_page": full_page,
                    "screenshot_type": screenshot_type,
                },
            ),
        )
        self._guard.mark_observed()
        return ScreenshotResult(
            ok=bool(payload.get("ok")),
            needs_observation=bool(payload.get("needs_observation", False)),
            message=_result_message(payload),
            path=str(payload.get("path") or ""),
        )

    async def click(
        self,
        *,
        ref: str | None = None,
        selector: str | None = None,
        text: str | None = None,
        x: float | str | None = None,
        y: float | str | None = None,
    ) -> ClickResult:
        """Click a target in the tab."""
        self._guard.check_before_action("click")
        payload = await _call_control(
            click_control,
            self._state,
            holder_id=self._holder_id,
            bridge=self._bridge,
            kwargs={
                "page_id": str(self.id),
                "ref": ref or "",
                "selector": selector or "",
                "text": text or "",
                "x": x,
                "y": y,
            },
        )
        _sync_known_tab_url(
            self._state,
            self.id,
            str(payload.get("url") or ""),
        )
        return ClickResult(
            ok=bool(payload.get("ok")),
            navigation_occurred=bool(payload.get("navigation_occurred")),
            url=str(payload.get("url") or ""),
            needs_observation=bool(payload.get("needs_observation", True)),
            message=_result_message(payload),
        )

    async def type(
        self,
        text: str,
        *,
        ref: str | None = None,
        selector: str | None = None,
        submit: bool = False,
    ) -> TypeResult:
        """Type text into the active or targeted element."""
        self._guard.check_before_action("type")
        payload = await _call_control(
            type_control,
            self._state,
            holder_id=self._holder_id,
            bridge=self._bridge,
            kwargs={
                "page_id": str(self.id),
                "text": text,
                "ref": ref or "",
                "selector": selector or "",
                "submit": submit,
            },
        )
        return TypeResult(
            ok=bool(payload.get("ok")),
            needs_observation=bool(payload.get("needs_observation", True)),
            message=_result_message(payload),
        )

    async def press_key(self, key: str) -> ActionResult:
        """Press a keyboard key in the tab."""
        self._guard.check_before_action("press_key")
        payload = await _call_control(
            press_key_control,
            self._state,
            holder_id=self._holder_id,
            bridge=self._bridge,
            kwargs={"page_id": str(self.id), "key": key},
        )
        return _action_result(payload)

    async def action(self, name: str, **kwargs: Any) -> ActionResult:
        """Run a generic Browser Control action."""
        self._guard.check_before_action(name)
        payload = _chunk_payload(
            await _action_with_bridge(
                self._state,
                str(name or "").strip().lower(),
                holder_id=self._holder_id,
                bridge=self._bridge,
                kwargs={"page_id": str(self.id), **kwargs},
            ),
        )
        _sync_known_tab_url(
            self._state,
            self.id,
            str(payload.get("url") or ""),
        )
        return _action_result(payload)

    async def hover(self, **kwargs: Any) -> ActionResult:
        return await self.action("hover", **kwargs)

    async def scroll(self, **kwargs: Any) -> ActionResult:
        return await self.action("scroll", **kwargs)

    async def select_option(self, **kwargs: Any) -> ActionResult:
        return await self.action("select_option", **kwargs)

    async def navigate(self, url: str) -> ActionResult:
        _control_remember_approved_navigation(self._state, url)
        return await self.action("navigate", url=url)

    async def wait_for(self, *args: Any, **kwargs: Any) -> ActionResult:
        """Wait for page settling or text state without requiring a new snapshot."""
        if len(args) > 1:
            raise TypeError("wait_for accepts at most one positional argument")
        if args:
            value = args[0]
            if isinstance(value, (int, float)):
                wait_time = float(value)
                if wait_time > 100:
                    wait_time /= 1000
                kwargs.setdefault("wait_time", wait_time)
            elif isinstance(value, str):
                kwargs.setdefault("text", value)
            else:
                raise TypeError(
                    "wait_for positional argument must be text or seconds",
                )
        try:
            payload = _chunk_payload(
                await _action_with_bridge(
                    self._state,
                    "wait_for",
                    holder_id=self._holder_id,
                    bridge=self._bridge,
                    kwargs={"page_id": str(self.id), **kwargs},
                ),
            )
            _sync_known_tab_url(
                self._state,
                self.id,
                str(payload.get("url") or ""),
            )
            return _action_result(payload)
        finally:
            self._guard.consume_observation()

    async def close(self, *, force: bool = False) -> ActionResult:
        """Close SDK-created tabs, or release existing tabs by default."""
        created_by_control = _known_tab_bool(
            self._state,
            self.id,
            "created_by_control",
        )
        await _bridge_request_checked(
            self._bridge,
            "banner.hide",
            {"tabId": self.id},
        )
        await _bridge_request_checked(
            self._bridge,
            "tab.detach",
            {"tabId": self.id, "holderId": self._holder_id},
        )
        release = getattr(self._bridge, "release", None)
        if callable(release):
            result = release(self.id, self._holder_id)
            if hasattr(result, "__await__"):
                await result

        closed = False
        if created_by_control or force:
            await _bridge_request_checked(
                self._bridge,
                "tab.close",
                {"tabId": self.id},
            )
            closed = True

        _forget_known_tab(self._state, self.id)
        return ActionResult(
            ok=True,
            needs_observation=False,
            message="Tab closed" if closed else "Tab released",
        )

    def _store_refs(self, refs_raw: dict[str, dict]) -> None:
        refs_by_tab = getattr(self._state, "refs", None)
        if not isinstance(refs_by_tab, dict):
            refs_by_tab = self._state.setdefault("refs", {})
        refs_by_tab[str(self.id)] = refs_raw
        if hasattr(self._state, "refs"):
            self._state.refs = refs_by_tab
        refresh_mapping = getattr(self._state, "_refresh_mapping", None)
        if callable(refresh_mapping):
            refresh_mapping()


async def _call_control(
    control_func: Any,
    state: Any,
    *,
    holder_id: str,
    bridge: Any,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return _chunk_payload(
        await control_func(
            state,
            holder_id=holder_id,
            bridge=bridge,
            request_context={},
            kwargs=kwargs,
        ),
    )


async def _action_with_bridge(
    state: dict[str, Any] | ControlState,
    action: str,
    *,
    holder_id: str,
    bridge: Any,
    kwargs: dict[str, Any],
):
    action_name = str(action or "").strip()
    state_obj = ControlState.from_dict(state)
    try:
        set_network_quiescence_wait(_network_quiescence_wait)
        # pylint: disable=protected-access
        control_navigation._CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS = (
            _CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS
        )
        control_navigation._CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS = (
            _CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS
        )
        # pylint: enable=protected-access
        if action_name not in ACTION_HANDLERS:
            return unsupported_control_action_response(action_name)
        return await dispatch(
            state_obj,
            action_name,
            holder_id=holder_id,
            bridge=bridge,
            request_context={},
            **kwargs,
        )
    finally:
        if isinstance(state, dict):
            state_obj.sync_to(state)


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        return chunk
    try:
        content = getattr(chunk, "content", [])
        first = content[0] if content else None
        text = getattr(first, "text", "")
    except (AttributeError, IndexError, TypeError):
        text = str(chunk)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {"ok": False, "message": str(text or "")}
    return parsed if isinstance(parsed, dict) else {"ok": False}


def _known_tab_field(state: Any, tab_id: int, field: str) -> str:
    try:
        tabs = state.get("control_tabs", {})
    except AttributeError:
        tabs = getattr(state, "control_tabs", {})
    if not isinstance(tabs, dict):
        return ""
    entry = tabs.get(str(tab_id)) or tabs.get(tab_id)
    return str(entry.get(field) or "") if isinstance(entry, dict) else ""


def _known_tab_bool(state: Any, tab_id: int, field: str) -> bool:
    try:
        tabs = state.get("control_tabs", {})
    except AttributeError:
        tabs = getattr(state, "control_tabs", {})
    if not isinstance(tabs, dict):
        return False
    entry = tabs.get(str(tab_id)) or tabs.get(tab_id)
    return bool(entry.get(field)) if isinstance(entry, dict) else False


def _sync_known_tab_url(state: Any, tab_id: int, url: str) -> None:
    if not url:
        return
    try:
        tabs = state.setdefault("control_tabs", {})
    except AttributeError:
        tabs = getattr(state, "control_tabs", {})
        if not isinstance(tabs, dict):
            return
    if not isinstance(tabs, dict):
        return
    entry = tabs.get(str(tab_id))
    if not isinstance(entry, dict):
        entry = {"tab_id": tab_id}
        tabs[str(tab_id)] = entry
    entry["url"] = url
    entry["url_key"] = _control_url_key(url)


async def _bridge_request_checked(
    bridge: Any,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    response = await bridge.request(method, params)
    if not isinstance(response, dict):
        return {}
    error = response.get("error")
    if error:
        if isinstance(error, dict):
            message = str(error.get("message") or error)
        else:
            message = str(error)
        raise BrowserSDKError(message)
    return response


def _forget_known_tab(state: Any, tab_id: int) -> None:
    tab_keys = {str(tab_id), tab_id}
    try:
        tabs = state.get("control_tabs", {})
    except AttributeError:
        tabs = getattr(state, "control_tabs", {})
    if isinstance(tabs, dict):
        for key in tab_keys:
            tabs.pop(key, None)
        if not tabs and isinstance(state, dict):
            state.pop("control_tabs", None)

    try:
        current_page_id = state.get("current_page_id")
    except AttributeError:
        current_page_id = getattr(state, "current_page_id", None)
    if str(current_page_id or "") == str(tab_id):
        if isinstance(state, dict):
            state.pop("current_page_id", None)
        elif hasattr(state, "current_page_id"):
            setattr(state, "current_page_id", "")

    try:
        refs = state.get("refs", {})
    except AttributeError:
        refs = getattr(state, "refs", {})
    if isinstance(refs, dict):
        for key in tab_keys:
            refs.pop(key, None)


def _ref_info(value: dict[str, Any]) -> RefInfo:
    bounds = value.get("bounds")
    if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
        parsed_bounds = cast(
            tuple[float, float, float, float],
            tuple(float(item) for item in bounds),
        )
    else:
        parsed_bounds = None
    return RefInfo(
        role=str(value.get("role") or ""),
        name=str(value.get("name") or ""),
        x=float(value.get("x") or 0),
        y=float(value.get("y") or 0),
        bounds=parsed_bounds,
    )


def _result_message(payload: dict[str, Any]) -> str:
    return str(
        payload.get("message")
        or payload.get("next_instruction")
        or payload.get("error")
        or "",
    )


def _action_result(payload: dict[str, Any]) -> ActionResult:
    return ActionResult(
        ok=bool(payload.get("ok")),
        needs_observation=bool(payload.get("needs_observation", True)),
        message=_result_message(payload),
    )


__all__ = ["Tab"]
