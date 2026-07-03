# -*- coding: utf-8 -*-
"""Browser Control action transition helpers."""
# pylint: disable=consider-using-in,too-many-return-statements

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from typing import Any

from qwenpaw.browser_sdk._runtime import (
    _CONTROL_BANNER_TIMEOUT_SECONDS,
    logger,
)
from .errors import RECOVERABLE_CONTROL_EXCEPTIONS
from .inference import _control_jsonrpc_error
from .navigation import (
    _control_sync_session_navigation_scope,
    _control_url_key,
)
from .session_manager import _control_get_session
from .tab_manager import (
    _CONTROL_CLICK_TAB_TRANSITION_MAX_POLLS,
    _CONTROL_CLICK_TAB_TRANSITION_POLL_SECONDS,
    _CONTROL_PENDING_ACTION_TRANSITION_TTL_SECONDS,
    _control_ensure_tab_available,
    _control_cleanup_tab_record,
    _control_discover_tabs_safe,
    _control_int_tab_id,
    _control_is_http_url,
    _control_live_tab_map,
    _control_refresh_tab_url,
    _control_tab_record,
    _control_tab_url,
)


def _control_tab_ids(tabs: list[dict[str, Any]] | None) -> set[int]:
    if not tabs:
        return set()
    tab_ids: set[int] = set()
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        tab_id = _control_int_tab_id(tab.get("id") or tab.get("tabId"))
        if tab_id is not None:
            tab_ids.add(tab_id)
    return tab_ids


def _control_new_tab_opened_from_action(
    before_tabs: list[dict[str, Any]],
    after_tabs: list[dict[str, Any]],
    source_tab_id: int,
) -> dict[str, Any] | None:
    before_ids = _control_tab_ids(before_tabs)
    candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    for index, tab in enumerate(after_tabs):
        if not isinstance(tab, dict):
            continue
        tab_id = _control_int_tab_id(tab.get("id") or tab.get("tabId"))
        if tab_id is None or tab_id in before_ids:
            continue
        opener_tab_id = _control_int_tab_id(tab.get("openerTabId"))
        candidates.append(
            (
                0 if opener_tab_id == source_tab_id else 1,
                0 if tab.get("active") else 1,
                index,
                tab,
            ),
        )
    if not candidates:
        return None
    return sorted(candidates)[0][3]


def _control_event_tab(params: dict[str, Any]) -> dict[str, Any]:
    tab = params.get("tab")
    if isinstance(tab, dict):
        merged = dict(tab)
        for key in ("tabId", "sourceTabId", "openerTabId"):
            if key in params and key not in merged:
                merged[key] = params[key]
    else:
        merged = dict(params)

    tab_id = _control_int_tab_id(merged.get("id") or merged.get("tabId"))
    if tab_id is not None:
        if "id" not in merged:
            merged["id"] = tab_id
        if "tabId" not in merged:
            merged["tabId"] = tab_id

    change_info = params.get("changeInfo")
    if isinstance(change_info, dict):
        for key in ("url", "pendingUrl", "status"):
            value = change_info.get(key)
            if value and not merged.get(key):
                merged[key] = value
    return merged


def _control_transition_from_tab_event(
    params: dict[str, Any],
    *,
    before_tabs: list[dict[str, Any]],
    source_tab_id: int,
    source_url: str,
) -> dict[str, Any] | None:
    tab = _control_event_tab(params)
    tab_id = _control_int_tab_id(tab.get("id") or tab.get("tabId"))
    if tab_id is None:
        return None

    url = _control_tab_url(tab)
    before_ids = _control_tab_ids(before_tabs)
    source_event_id = _control_int_tab_id(tab.get("sourceTabId"))
    opener_tab_id = _control_int_tab_id(tab.get("openerTabId"))

    if tab_id not in before_ids:
        source_matches = (
            source_event_id == source_tab_id or opener_tab_id == source_tab_id
        )
        if not source_matches and not tab.get("active"):
            return None
        if not _control_is_http_url(url):
            return None
        return {"kind": "new_tab", "tab": tab}

    if tab_id != source_tab_id or not _control_is_http_url(url):
        return None
    if source_url and _control_url_key(url) == _control_url_key(source_url):
        return None
    return {"kind": "current_tab_navigation", "tab": tab}


def _control_transition_from_cdp_event(
    params: dict[str, Any],
    *,
    source_tab_id: int,
    source_url: str,
) -> dict[str, Any] | None:
    tab_id = _control_int_tab_id(params.get("tabId"))
    if tab_id != source_tab_id:
        return None

    method = str(params.get("method") or "")
    event_params = params.get("params")
    if not isinstance(event_params, dict):
        event_params = {}

    url = ""
    frame = event_params.get("frame")
    if isinstance(frame, dict):
        url = str(frame.get("url") or "")
    if not url:
        url = str(event_params.get("url") or "")

    if method not in {
        "Page.frameNavigated",
        "Page.navigatedWithinDocument",
        "Page.loadEventFired",
    }:
        return None
    if not _control_is_http_url(url):
        return None
    if source_url and _control_url_key(url) == _control_url_key(source_url):
        return None
    return {
        "kind": "current_tab_navigation",
        "tab": {"id": source_tab_id, "tabId": source_tab_id, "url": url},
    }


def _control_create_action_transition_waiter(
    bridge: Any,
    *,
    before_tabs: list[dict[str, Any]] | None,
    source_tab_id: int,
) -> Callable[..., Any] | None:
    if before_tabs is None or not hasattr(bridge, "add_event_listener"):
        return None

    source_tab = (_control_live_tab_map(before_tabs) or {}).get(
        source_tab_id,
    ) or {}
    source_url = _control_tab_url(source_tab)
    loop = asyncio.get_running_loop()
    future: asyncio.Future[dict[str, Any]] = loop.create_future()
    handlers: list[tuple[str, Callable[[dict[str, Any]], None]]] = []

    def accept(transition: dict[str, Any] | None) -> None:
        if transition is not None and not future.done():
            future.set_result(transition)

    def on_tab_event(params: dict[str, Any]) -> None:
        accept(
            _control_transition_from_tab_event(
                params,
                before_tabs=before_tabs,
                source_tab_id=source_tab_id,
                source_url=source_url,
            ),
        )

    def on_cdp_event(params: dict[str, Any]) -> None:
        accept(
            _control_transition_from_cdp_event(
                params,
                source_tab_id=source_tab_id,
                source_url=source_url,
            ),
        )

    for event_name, handler in (
        ("webNavigation.createdNavigationTarget", on_tab_event),
        ("tabs.created", on_tab_event),
        ("tabs.updated", on_tab_event),
        ("cdp.event", on_cdp_event),
    ):
        bridge.add_event_listener(event_name, handler)
        handlers.append((event_name, handler))

    async def wait(timeout: float = 0.0) -> dict[str, Any] | None:
        try:
            if future.done():
                return future.result()
            if timeout <= 0:
                return None
            return await asyncio.wait_for(
                future,
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return None
        finally:
            if hasattr(bridge, "remove_event_listener"):
                for event_name, handler in handlers:
                    with contextlib.suppress(ValueError):
                        bridge.remove_event_listener(event_name, handler)

    return wait


def _control_store_pending_action_transition(
    state: dict,
    *,
    before_tabs: list[dict[str, Any]] | None,
    source_tab_id: int,
    holder_id: str,
) -> None:
    if before_tabs is None:
        return
    state["control_pending_action_transition"] = {
        "before_tabs": before_tabs,
        "source_tab_id": source_tab_id,
        "holder_id": holder_id,
        "created_at": time.monotonic(),
    }


async def _control_consume_pending_action_transition(
    state: dict,
    *,
    bridge: Any,
    holder_id: str,
    request_context: dict[str, Any],
) -> dict[str, Any] | None:
    pending = state.get("control_pending_action_transition")
    if not isinstance(pending, dict):
        return None
    if str(pending.get("holder_id") or "") != holder_id:
        return None

    created_at = pending.get("created_at")
    if not isinstance(created_at, (int, float)):
        state.pop("control_pending_action_transition", None)
        return None
    if (
        time.monotonic() - created_at
        > _CONTROL_PENDING_ACTION_TRANSITION_TTL_SECONDS
    ):
        state.pop("control_pending_action_transition", None)
        return None

    source_tab_id = _control_int_tab_id(pending.get("source_tab_id"))
    before_tabs = pending.get("before_tabs")
    if source_tab_id is None or not isinstance(before_tabs, list):
        state.pop("control_pending_action_transition", None)
        return None

    payload = await _control_claim_tab_opened_by_action(
        state,
        bridge=bridge,
        before_tabs=before_tabs,
        source_tab_id=source_tab_id,
        holder_id=holder_id,
        request_context=request_context,
    )
    if payload is not None:
        state.pop("control_pending_action_transition", None)
        payload["claimed_delayed_transition"] = True
        return payload
    return None


def _control_refresh_current_tab_from_live_tabs(
    state: dict,
    tab_id: int,
    tabs: list[dict[str, Any]] | None,
) -> None:
    live_tabs = _control_live_tab_map(tabs)
    if not live_tabs:
        return
    live_tab = live_tabs.get(tab_id)
    if not isinstance(live_tab, dict):
        return
    live_url = _control_tab_url(live_tab)
    if live_url:
        _control_refresh_tab_url(state, tab_id, live_url)


async def _control_attach_new_current_tab(
    state: dict,
    *,
    bridge: Any,
    tab: dict[str, Any],
    previous_tab_id: int,
    holder_id: str,
    request_context: dict[str, Any],
    close_previous_owned_tab: bool = True,
) -> dict[str, Any] | None:
    tab_id = _control_int_tab_id(tab.get("id") or tab.get("tabId"))
    if tab_id is None or tab_id == previous_tab_id:
        return None

    try:
        await bridge.claim_tab(tab_id, holder_id)
        attach_response = await bridge.request(
            "tab.attach",
            {"tabId": tab_id, "holderId": holder_id},
        )
        attach_error = _control_jsonrpc_error(attach_response)
        if attach_error:
            raise RuntimeError(attach_error)
    except RECOVERABLE_CONTROL_EXCEPTIONS:
        logger.debug(
            "Failed to attach newly opened control tab %s",
            tab_id,
            exc_info=True,
        )
        return None

    await _control_ensure_tab_available(bridge, tab_id)
    session = await _control_get_session(
        state,
        tab_id=tab_id,
        holder_id=holder_id,
        bridge=bridge,
        request_context=request_context,
    )
    try:
        await asyncio.wait_for(
            bridge.request(
                "banner.show",
                {
                    "tabId": tab_id,
                    "status_text": "QwenPaw control active",
                },
            ),
            timeout=_CONTROL_BANNER_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.debug("control banner.show timed out for new tab")
    except RECOVERABLE_CONTROL_EXCEPTIONS:
        logger.debug("control banner.show failed for new tab", exc_info=True)

    tab_url = _control_tab_url(tab)
    control_tabs = state.get("control_tabs")
    if not isinstance(control_tabs, dict):
        control_tabs = {}
        state["control_tabs"] = control_tabs
    control_tabs[str(tab_id)] = _control_tab_record(
        tab_id=tab_id,
        holder_id=holder_id,
        url=tab_url,
        created_by_control=True,
        request_context=request_context,
    )
    state["current_page_id"] = str(tab_id)
    _control_sync_session_navigation_scope(state, session)

    closed_tabs = 0
    released_tabs = 0
    previous_tab = (state.get("control_tabs") or {}).get(str(previous_tab_id))
    if close_previous_owned_tab and isinstance(previous_tab, dict):
        cleanup_result = await _control_cleanup_tab_record(
            state,
            bridge=bridge,
            tab=previous_tab,
        )
        closed_tabs = cleanup_result["closed_tabs"]
        released_tabs = cleanup_result["released_tabs"]

    payload: dict[str, Any] = {
        "ok": True,
        "mode": "control",
        "tab_id": tab_id,
        "opened_new_tab": True,
        "ready_for_observation": True,
        "next_action": "snapshot",
        "next_instruction": (
            "The action opened a new tab and it is now the current controlled "
            "tab. Do not repeat the same action; observe it with snapshot."
        ),
    }
    if tab_url:
        payload["url"] = tab_url
    if closed_tabs:
        payload["closed_previous_tabs"] = closed_tabs
    if released_tabs:
        payload["released_previous_tabs"] = released_tabs
    return payload


async def _control_apply_action_transition(
    state: dict,
    *,
    bridge: Any,
    transition: dict[str, Any],
    source_tab_id: int,
    holder_id: str,
    request_context: dict[str, Any],
    close_previous_owned_tab: bool = True,
) -> dict[str, Any] | None:
    kind = transition.get("kind")
    tab = transition.get("tab")
    if not isinstance(tab, dict):
        return None

    if kind == "new_tab":
        return await _control_attach_new_current_tab(
            state,
            bridge=bridge,
            tab=tab,
            previous_tab_id=source_tab_id,
            holder_id=holder_id,
            request_context=request_context,
            close_previous_owned_tab=close_previous_owned_tab,
        )

    if kind != "current_tab_navigation":
        return None

    url = _control_tab_url(tab)
    if url:
        _control_refresh_tab_url(state, source_tab_id, url)
    state["current_page_id"] = str(source_tab_id)
    payload: dict[str, Any] = {
        "ok": True,
        "mode": "control",
        "tab_id": source_tab_id,
        "navigated": True,
        "ready_for_observation": True,
        "next_action": "snapshot",
        "next_instruction": (
            "The action changed the current tab. Do not repeat the same "
            "action; observe it with snapshot."
        ),
    }
    if url:
        payload["url"] = url
    return payload


async def _control_claim_tab_opened_by_action(
    state: dict,
    *,
    bridge: Any,
    before_tabs: list[dict[str, Any]] | None,
    source_tab_id: int,
    holder_id: str,
    request_context: dict[str, Any],
    close_previous_owned_tab: bool = True,
) -> dict[str, Any] | None:
    if before_tabs is None:
        return None

    last_tabs: list[dict[str, Any]] | None = None
    for attempt in range(_CONTROL_CLICK_TAB_TRANSITION_MAX_POLLS):
        after_tabs = await _control_discover_tabs_safe(bridge)
        if after_tabs is None:
            return None
        last_tabs = after_tabs
        new_tab = _control_new_tab_opened_from_action(
            before_tabs,
            after_tabs,
            source_tab_id,
        )
        if new_tab is not None:
            return await _control_attach_new_current_tab(
                state,
                bridge=bridge,
                tab=new_tab,
                previous_tab_id=source_tab_id,
                holder_id=holder_id,
                request_context=request_context,
                close_previous_owned_tab=close_previous_owned_tab,
            )
        if attempt < _CONTROL_CLICK_TAB_TRANSITION_MAX_POLLS - 1:
            await asyncio.sleep(_CONTROL_CLICK_TAB_TRANSITION_POLL_SECONDS)

    _control_refresh_current_tab_from_live_tabs(
        state,
        source_tab_id,
        last_tabs,
    )
    return None


async def _control_resolve_action_transition(
    state: dict,
    *,
    bridge: Any,
    before_tabs: list[dict[str, Any]] | None,
    transition_waiter: Callable[..., Any] | None,
    source_tab_id: int,
    holder_id: str,
    request_context: dict[str, Any],
    close_previous_owned_tab: bool = True,
) -> dict[str, Any] | None:
    event_transition = (
        await transition_waiter() if transition_waiter is not None else None
    )
    if event_transition is not None:
        transition_payload = await _control_apply_action_transition(
            state,
            bridge=bridge,
            transition=event_transition,
            source_tab_id=source_tab_id,
            holder_id=holder_id,
            request_context=request_context,
            close_previous_owned_tab=close_previous_owned_tab,
        )
        if transition_payload is not None:
            return transition_payload

    transition_payload = await _control_claim_tab_opened_by_action(
        state,
        bridge=bridge,
        before_tabs=before_tabs,
        source_tab_id=source_tab_id,
        holder_id=holder_id,
        request_context=request_context,
        close_previous_owned_tab=close_previous_owned_tab,
    )
    if transition_payload is not None:
        return transition_payload

    _control_store_pending_action_transition(
        state,
        before_tabs=before_tabs,
        source_tab_id=source_tab_id,
        holder_id=holder_id,
    )
    return None


__all__ = [
    "_control_apply_action_transition",
    "_control_attach_new_current_tab",
    "_control_claim_tab_opened_by_action",
    "_control_consume_pending_action_transition",
    "_control_create_action_transition_waiter",
    "_control_event_tab",
    "_control_new_tab_opened_from_action",
    "_control_refresh_current_tab_from_live_tabs",
    "_control_resolve_action_transition",
    "_control_store_pending_action_transition",
    "_control_tab_ids",
    "_control_transition_from_cdp_event",
    "_control_transition_from_tab_event",
]
