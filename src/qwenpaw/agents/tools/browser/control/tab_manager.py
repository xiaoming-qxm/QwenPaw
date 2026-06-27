# -*- coding: utf-8 -*-
"""Browser Control tab lease helpers."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from ..runtime import _get_workspace_state, _workspace_states, logger
from .errors import RECOVERABLE_CONTROL_EXCEPTIONS
from .navigation import (
    _control_page_id_is_tab_id,
    _control_same_site,
    _control_url_key,
)
from .session_manager import _control_close_session, _control_holder_id


def _control_tab_record(
    *,
    tab_id: int,
    holder_id: str,
    url: str,
    created_by_control: bool,
    request_context: dict[str, Any],
    previous_tab: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_tab = previous_tab or {}
    record: dict[str, Any] = {
        "tab_id": tab_id,
        "holder_id": holder_id,
        "url": url,
        "url_key": _control_url_key(url) if url else "",
        "created_by_control": created_by_control,
    }
    for key in (
        "session_id",
        "root_session_id",
        "agent_id",
        "root_agent_id",
        "tool_call_id",
    ):
        value = str(request_context.get(key) or previous_tab.get(key) or "")
        if value:
            record[key] = value
    return record


def _control_int_tab_id(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _control_tab_url(tab: dict[str, Any]) -> str:
    return str(tab.get("url") or tab.get("pendingUrl") or "")


def _control_is_http_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def _control_live_tab_map(
    tabs: list[dict[str, Any]] | None,
) -> dict[int, dict[str, Any]] | None:
    if tabs is None:
        return None
    live_tabs: dict[int, dict[str, Any]] = {}
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        tab_id = _control_int_tab_id(tab.get("id") or tab.get("tabId"))
        if tab_id is not None:
            live_tabs[tab_id] = tab
    return live_tabs


def _control_claimed_tab_candidates(state: dict, url: str) -> list[int]:
    if not url:
        return []
    target_key = _control_url_key(url)
    current = str(state.get("current_page_id") or "")
    control_tabs = state.get("control_tabs") or {}
    candidate_tabs = []
    if current:
        candidate_tabs.append(control_tabs.get(current))
    candidate_tabs.extend(control_tabs.values())
    tab_ids: list[int] = []
    for tab in candidate_tabs:
        if not isinstance(tab, dict):
            continue
        if tab.get("url_key") == target_key:
            tab_id = _control_int_tab_id(tab.get("tab_id"))
            if tab_id is not None and tab_id not in tab_ids:
                tab_ids.append(tab_id)
    return tab_ids


def _control_current_same_site_candidate(
    state: dict,
    url: str,
    holder_id: str,
) -> int | None:
    if not url:
        return None
    current = str(state.get("current_page_id") or "")
    tab = (state.get("control_tabs") or {}).get(current)
    if not isinstance(tab, dict):
        return None
    if str(tab.get("holder_id") or "") != holder_id:
        return None
    tab_url = str(tab.get("url") or "")
    if not tab_url or not _control_same_site(tab_url, url):
        return None
    return _control_int_tab_id(tab.get("tab_id"))


def _control_refresh_tab_url(
    state: dict,
    tab_id: int,
    url: str,
) -> None:
    if not url:
        return
    control_tabs = state.get("control_tabs") or {}
    tab = control_tabs.get(str(tab_id))
    if not isinstance(tab, dict):
        return
    tab["url"] = url
    tab["url_key"] = _control_url_key(url)


async def _control_forget_tab_state(state: dict, tab_id: int) -> None:
    from .observation import _control_clear_observation_required

    key = str(tab_id)
    _control_clear_observation_required(state, tab_id)
    control_tabs = state.get("control_tabs")
    if isinstance(control_tabs, dict):
        control_tabs.pop(key, None)
    sessions = state.get("control_sessions")
    session = None
    if isinstance(sessions, dict):
        session = sessions.pop(key, None)
        if not sessions:
            state.pop("control_sessions", None)
    if state.get("current_page_id") == key:
        remaining = list((state.get("control_tabs") or {}).keys())
        state["current_page_id"] = remaining[-1] if remaining else None
    if session is not None:
        try:
            await session.close()
        except RECOVERABLE_CONTROL_EXCEPTIONS:
            logger.debug(
                "Failed to close stale control session for tab %s",
                tab_id,
                exc_info=True,
            )


async def _control_ensure_tab_available(bridge: Any, tab_id: int) -> None:
    """Verify the tab exists without foregrounding Chrome or switching tabs."""
    try:
        await bridge.request("tab.ensure", {"tabId": tab_id})
    except RECOVERABLE_CONTROL_EXCEPTIONS:
        logger.debug(
            "Failed to ensure control tab %s",
            tab_id,
            exc_info=True,
        )


async def _control_close_owned_tab(
    state: dict,
    *,
    bridge: Any,
    tab_id: int,
    holder_id: str,
) -> None:
    tab = (state.get("control_tabs") or {}).get(str(tab_id)) or {}
    if not isinstance(tab, dict) or not tab.get("created_by_control"):
        return

    with contextlib.suppress(*RECOVERABLE_CONTROL_EXCEPTIONS):
        await bridge.request("banner.hide", {"tabId": tab_id})
    with contextlib.suppress(*RECOVERABLE_CONTROL_EXCEPTIONS):
        await bridge.request(
            "tab.detach",
            {"tabId": tab_id, "holderId": holder_id},
        )
    with contextlib.suppress(*RECOVERABLE_CONTROL_EXCEPTIONS):
        await bridge.request("tab.close", {"tabId": tab_id})
    await _control_forget_tab_state(state, tab_id)


def _control_tab_matches_request(
    tab: dict[str, Any],
    *,
    session_id: str,
    root_session_id: str,
) -> bool:
    candidates = {value for value in (session_id, root_session_id) if value}
    if not candidates:
        return False
    if str(tab.get("session_id") or "") in candidates:
        return True
    if str(tab.get("root_session_id") or "") in candidates:
        return True
    holder_id = str(tab.get("holder_id") or "")
    return any(holder_id.endswith(f":{candidate}") for candidate in candidates)


async def _control_cleanup_tab_record(
    state: dict,
    *,
    bridge: Any,
    tab: dict[str, Any],
) -> dict[str, int]:
    tab_id = _control_int_tab_id(tab.get("tab_id"))
    if tab_id is None:
        return {"closed_tabs": 0, "released_tabs": 0}
    holder_id = str(tab.get("holder_id") or _control_holder_id(state))

    with contextlib.suppress(*RECOVERABLE_CONTROL_EXCEPTIONS):
        await _control_close_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
        )
    with contextlib.suppress(*RECOVERABLE_CONTROL_EXCEPTIONS):
        await bridge.request("banner.hide", {"tabId": tab_id})
    with contextlib.suppress(*RECOVERABLE_CONTROL_EXCEPTIONS):
        await bridge.request(
            "tab.detach",
            {"tabId": tab_id, "holderId": holder_id},
        )

    if bool(tab.get("created_by_control")):
        try:
            await bridge.request("tab.close", {"tabId": tab_id})
        except RECOVERABLE_CONTROL_EXCEPTIONS:
            logger.debug(
                "control cleanup: failed to close created tab %s",
                tab_id,
                exc_info=True,
            )
            return {"closed_tabs": 0, "released_tabs": 0}
        await _control_forget_tab_state(state, tab_id)
        return {"closed_tabs": 1, "released_tabs": 0}

    await _control_forget_tab_state(state, tab_id)
    return {"closed_tabs": 0, "released_tabs": 1}


async def _control_release_tab_record(
    state: dict,
    *,
    bridge: Any,
    tab: dict[str, Any],
) -> dict[str, int]:
    tab_id = _control_int_tab_id(tab.get("tab_id"))
    if tab_id is None:
        return {"closed_tabs": 0, "released_tabs": 0}
    holder_id = str(tab.get("holder_id") or _control_holder_id(state))

    with contextlib.suppress(*RECOVERABLE_CONTROL_EXCEPTIONS):
        await _control_close_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
        )
    with contextlib.suppress(*RECOVERABLE_CONTROL_EXCEPTIONS):
        await bridge.request("banner.hide", {"tabId": tab_id})
    with contextlib.suppress(*RECOVERABLE_CONTROL_EXCEPTIONS):
        await bridge.request(
            "tab.detach",
            {"tabId": tab_id, "holderId": holder_id},
        )

    await _control_forget_tab_state(state, tab_id)
    return {"closed_tabs": 0, "released_tabs": 1}


async def _control_cleanup_matching_tabs(
    state: dict,
    *,
    bridge: Any,
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, int]:
    result = {"matched_tabs": 0, "closed_tabs": 0, "released_tabs": 0}
    control_tabs = state.get("control_tabs")
    if not isinstance(control_tabs, dict):
        return result

    for tab in list(control_tabs.values()):
        if not isinstance(tab, dict) or not predicate(tab):
            continue
        result["matched_tabs"] += 1
        cleanup_result = await _control_cleanup_tab_record(
            state,
            bridge=bridge,
            tab=tab,
        )
        result["closed_tabs"] += cleanup_result["closed_tabs"]
        result["released_tabs"] += cleanup_result["released_tabs"]

    if not state.get("control_tabs"):
        state.pop("control_tabs", None)
    return result


async def _control_release_matching_tabs(
    state: dict,
    *,
    bridge: Any,
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, int]:
    result = {"matched_tabs": 0, "closed_tabs": 0, "released_tabs": 0}
    control_tabs = state.get("control_tabs")
    if not isinstance(control_tabs, dict):
        return result

    for tab in list(control_tabs.values()):
        if not isinstance(tab, dict) or not predicate(tab):
            continue
        result["matched_tabs"] += 1
        release_result = await _control_release_tab_record(
            state,
            bridge=bridge,
            tab=tab,
        )
        result["closed_tabs"] += release_result["closed_tabs"]
        result["released_tabs"] += release_result["released_tabs"]

    if not state.get("control_tabs"):
        state.pop("control_tabs", None)
    return result


def _control_states_have_tabs(
    states: list[dict],
    *,
    workspace_id: str = "",
) -> bool:
    for state in states:
        if workspace_id and str(state.get("workspace_id") or "") != workspace_id:
            continue
        control_tabs = state.get("control_tabs")
        if isinstance(control_tabs, dict) and control_tabs:
            return True
    return False


def _control_tab_created_by_extension(tab: dict[str, Any]) -> bool:
    return bool(
        tab.get("createdByQwenPaw")
        or tab.get("created_by_qwenpaw")
        or tab.get("qwenpawCreated"),
    )


async def _control_cleanup_extension_created_tabs(
    state: dict,
    *,
    bridge: Any,
    request_context: dict[str, Any],
    holder_id: str | None = None,
    seen_tab_ids: set[int] | None = None,
) -> dict[str, int]:
    result = {"matched_tabs": 0, "closed_tabs": 0, "released_tabs": 0}
    seen_tab_ids = seen_tab_ids if seen_tab_ids is not None else set()
    tabs = await _control_discover_tabs_safe(bridge)
    if tabs is None:
        return result

    for live_tab in tabs:
        if not isinstance(live_tab, dict):
            continue
        if not _control_tab_created_by_extension(live_tab):
            continue
        tab_id = _control_int_tab_id(
            live_tab.get("id", live_tab.get("tab_id")),
        )
        if tab_id is None or tab_id in seen_tab_ids:
            continue

        seen_tab_ids.add(tab_id)
        result["matched_tabs"] += 1
        record = _control_tab_record(
            tab_id=tab_id,
            holder_id=holder_id or _control_holder_id(state, request_context),
            url=str(live_tab.get("url") or ""),
            created_by_control=True,
            request_context=request_context,
        )
        control_tabs = state.get("control_tabs")
        if not isinstance(control_tabs, dict):
            control_tabs = {}
            state["control_tabs"] = control_tabs
        control_tabs[str(tab_id)] = record
        cleanup_result = await _control_cleanup_tab_record(
            state,
            bridge=bridge,
            tab=record,
        )
        result["closed_tabs"] += cleanup_result["closed_tabs"]
        result["released_tabs"] += cleanup_result["released_tabs"]

    if not state.get("control_tabs"):
        state.pop("control_tabs", None)
    return result


async def _control_cleanup_stopped_session(
    state: dict,
    bridge: Any,
    session: Any,
    _params: dict[str, Any],
) -> None:
    request_context = getattr(session, "request_context", {}) or {}
    session_id = str(request_context.get("session_id") or "")
    root_session_id = str(request_context.get("root_session_id") or session_id)
    tab_id = _control_int_tab_id(getattr(session, "tab_id", None))

    if session_id or root_session_id:
        await _control_cleanup_matching_tabs(
            state,
            bridge=bridge,
            predicate=lambda tab: _control_tab_matches_request(
                tab,
                session_id=session_id,
                root_session_id=root_session_id,
            ),
        )
        return

    if tab_id is None:
        return
    await _control_cleanup_matching_tabs(
        state,
        bridge=bridge,
        predicate=lambda tab: _control_int_tab_id(tab.get("tab_id")) == tab_id,
    )


async def cleanup_control_sessions_for_request(
    *,
    session_id: str,
    root_session_id: str = "",
    workspace_id: str = "",
) -> dict[str, int]:
    """Release browser control resources owned by one request session."""
    from qwenpaw.browser.connection_manager import (
        get_bridge_connection_manager,
    )

    result = {"matched_tabs": 0, "closed_tabs": 0, "released_tabs": 0}
    session_id = str(session_id or "")
    root_session_id = str(root_session_id or session_id or "")
    if not session_id and not root_session_id:
        return result

    manager = get_bridge_connection_manager()
    if manager is None or not manager.is_connected():
        return result
    bridge = manager.get_connection()

    states = list(_workspace_states.values())
    if not states:
        states = [_get_workspace_state(workspace_id or "default")]
    request_context = {
        "session_id": session_id,
        "root_session_id": root_session_id,
    }
    had_local_control_state = _control_states_have_tabs(
        states,
        workspace_id=workspace_id,
    )

    for state in states:
        if workspace_id and str(state.get("workspace_id") or "") != workspace_id:
            continue
        cleanup_result = await _control_cleanup_matching_tabs(
            state,
            bridge=bridge,
            predicate=lambda tab: _control_tab_matches_request(
                tab,
                session_id=session_id,
                root_session_id=root_session_id,
            ),
        )
        result["matched_tabs"] += cleanup_result["matched_tabs"]
        result["closed_tabs"] += cleanup_result["closed_tabs"]
        result["released_tabs"] += cleanup_result["released_tabs"]

    if result["matched_tabs"] == 0 and not had_local_control_state:
        seen_tab_ids: set[int] = set()
        for state in states:
            if workspace_id and str(state.get("workspace_id") or "") != workspace_id:
                continue
            cleanup_result = await _control_cleanup_extension_created_tabs(
                state,
                bridge=bridge,
                request_context=request_context,
                seen_tab_ids=seen_tab_ids,
            )
            result["matched_tabs"] += cleanup_result["matched_tabs"]
            result["closed_tabs"] += cleanup_result["closed_tabs"]
            result["released_tabs"] += cleanup_result["released_tabs"]

    return result


async def release_control_sessions_for_request(
    *,
    session_id: str,
    root_session_id: str = "",
    workspace_id: str = "",
) -> dict[str, int]:
    """Release browser control leases for one completed request.

    Normal completion should leave the user's visible tabs open, but the
    debugger/lease must be released so the next request can claim the tab.
    """
    from qwenpaw.browser.connection_manager import (
        get_bridge_connection_manager,
    )

    result = {"matched_tabs": 0, "closed_tabs": 0, "released_tabs": 0}
    session_id = str(session_id or "")
    root_session_id = str(root_session_id or session_id or "")
    if not session_id and not root_session_id:
        return result

    manager = get_bridge_connection_manager()
    if manager is None or not manager.is_connected():
        return result
    bridge = manager.get_connection()

    for state in list(_workspace_states.values()):
        if workspace_id and str(state.get("workspace_id") or "") != workspace_id:
            continue
        release_result = await _control_release_matching_tabs(
            state,
            bridge=bridge,
            predicate=lambda tab: _control_tab_matches_request(
                tab,
                session_id=session_id,
                root_session_id=root_session_id,
            ),
        )
        result["matched_tabs"] += release_result["matched_tabs"]
        result["closed_tabs"] += release_result["closed_tabs"]
        result["released_tabs"] += release_result["released_tabs"]

    return result


async def _control_close_other_owned_tabs(
    state: dict,
    *,
    bridge: Any,
    keep_tab_id: int,
    holder_id: str,
) -> None:
    control_tabs = state.get("control_tabs") or {}
    for raw_tab_id, tab in list(control_tabs.items()):
        tab_id = _control_int_tab_id(raw_tab_id)
        if tab_id is None or tab_id == keep_tab_id:
            continue
        if not isinstance(tab, dict):
            continue
        if str(tab.get("holder_id") or "") != holder_id:
            continue
        await _control_close_owned_tab(
            state,
            bridge=bridge,
            tab_id=tab_id,
            holder_id=holder_id,
        )


def _control_matching_browser_tab_from_tabs(
    tabs: list[dict[str, Any]],
    url: str,
    *,
    allow_same_site: bool = False,
    managed_first: bool = False,
    same_site_requires_active_or_managed: bool = False,
) -> tuple[int, str] | None:
    if not url:
        return None
    target_key = _control_url_key(url)
    matches: list[tuple[int, int, int, int, int, str]] = []
    for index, tab in enumerate(tabs):
        if not isinstance(tab, dict):
            continue
        tab_url = _control_tab_url(tab)
        if not tab_url:
            continue
        exact_match = _control_url_key(tab_url) == target_key
        same_site_match = allow_same_site and _control_same_site(tab_url, url)
        if not exact_match and not same_site_match:
            continue
        if (
            same_site_match
            and not exact_match
            and same_site_requires_active_or_managed
            and not tab.get("active")
            and not tab.get("managed")
        ):
            continue
        tab_id = _control_int_tab_id(tab.get("id") or tab.get("tabId"))
        if tab_id is not None:
            matches.append(
                (
                    0 if exact_match else 1,
                    0 if managed_first and tab.get("managed") else 1,
                    0 if tab.get("active") else 1,
                    index,
                    tab_id,
                    tab_url,
                ),
            )
    if not matches:
        return None
    _match_type, _managed_rank, _active_rank, _index, tab_id, tab_url = sorted(
        matches,
    )[0]
    return tab_id, tab_url


async def _control_discover_tabs_safe(
    bridge: Any,
) -> list[dict[str, Any]] | None:
    if not hasattr(bridge, "discover_tabs"):
        return None
    try:
        return await bridge.discover_tabs()
    except RECOVERABLE_CONTROL_EXCEPTIONS:
        logger.debug("Failed to discover existing control tabs", exc_info=True)
        return None


async def _control_matching_control_or_browser_tab(
    state: dict,
    bridge: Any,
    url: str,
    holder_id: str,
) -> tuple[int, str] | None:
    tabs = await _control_discover_tabs_safe(bridge)
    live_tabs = _control_live_tab_map(tabs)
    target_key = _control_url_key(url) if url else ""

    for tab_id in _control_claimed_tab_candidates(state, url):
        if live_tabs is None:
            return tab_id, ""
        live_tab = live_tabs.get(tab_id)
        if live_tab is None:
            await _control_forget_tab_state(state, tab_id)
            continue
        live_url = _control_tab_url(live_tab)
        if live_url and _control_url_key(live_url) != target_key:
            _control_refresh_tab_url(state, tab_id, live_url)
            continue
        return tab_id, live_url

    current_same_site = _control_current_same_site_candidate(
        state,
        url,
        holder_id,
    )
    if current_same_site is not None:
        if live_tabs is None:
            return current_same_site, ""
        live_tab = live_tabs.get(current_same_site)
        if live_tab is None:
            await _control_forget_tab_state(state, current_same_site)
        else:
            live_url = _control_tab_url(live_tab)
            if live_url and _control_same_site(live_url, url):
                _control_refresh_tab_url(state, current_same_site, live_url)
                return current_same_site, live_url

    if tabs is None:
        return None
    return _control_matching_browser_tab_from_tabs(
        tabs,
        url,
        allow_same_site=True,
        managed_first=True,
        same_site_requires_active_or_managed=True,
    )


async def _control_matching_browser_tab(
    bridge: Any,
    url: str,
) -> tuple[int, str] | None:
    if not url:
        return None
    tabs = await _control_discover_tabs_safe(bridge)
    if tabs is None:
        return None
    return _control_matching_browser_tab_from_tabs(tabs, url)


def _control_missing_tab_error(error: str) -> bool:
    lower = error.lower()
    return (
        "no tab with given id" in lower
        or "target_closed" in lower
        or "target closed" in lower
        or "cannot access a closed" in lower
    )


def _control_page_id(state: dict, page_id: str) -> str:
    raw = (page_id or "").strip() or "default"
    if raw != "default":
        aliases = state.get("control_page_aliases") or {}
        alias = aliases.get(raw) if isinstance(aliases, dict) else None
        if alias:
            return str(alias)
        if not _control_page_id_is_tab_id(raw):
            current = state.get("current_page_id")
            control_tabs = state.get("control_tabs") or {}
            if current and str(current) in control_tabs:
                return str(current)
        return raw
    current = state.get("current_page_id")
    control_tabs = state.get("control_tabs") or {}
    if current and str(current) in control_tabs:
        return str(current)
    return raw


def _control_remember_page_alias(
    state: dict,
    page_id: str,
    tab_id: int,
) -> None:
    raw = (page_id or "").strip()
    if not raw or raw == "default" or _control_page_id_is_tab_id(raw):
        return
    aliases = state.get("control_page_aliases")
    if not isinstance(aliases, dict):
        aliases = {}
        state["control_page_aliases"] = aliases
    aliases[raw] = str(tab_id)


_CONTROL_IMPLICIT_MODE_ACTIONS = {
    "claim_tab",
    "open",
    "navigate",
    "navigate_back",
    "reload",
    "tabs",
    "snapshot",
    "screenshot",
    "click",
    "hover",
    "scroll",
    "select_option",
    "type",
    "press_key",
    "wait_for",
    "release_tab",
    "stop",
}

_CONTROL_CLICK_TAB_TRANSITION_MAX_POLLS = 4
_CONTROL_CLICK_TAB_TRANSITION_POLL_SECONDS = 0.1
_CONTROL_PENDING_ACTION_TRANSITION_TTL_SECONDS = 10.0
_CONTROL_OBSERVATION_ACTIONS = {"snapshot", "screenshot"}
_CONTROL_MUTATING_ACTIONS = {"click", "type", "press_key", "select_option"}


__all__ = [
    "_CONTROL_CLICK_TAB_TRANSITION_MAX_POLLS",
    "_CONTROL_CLICK_TAB_TRANSITION_POLL_SECONDS",
    "_CONTROL_IMPLICIT_MODE_ACTIONS",
    "_CONTROL_MUTATING_ACTIONS",
    "_CONTROL_OBSERVATION_ACTIONS",
    "_CONTROL_PENDING_ACTION_TRANSITION_TTL_SECONDS",
    "_control_ensure_tab_available",
    "_control_claimed_tab_candidates",
    "_control_cleanup_extension_created_tabs",
    "_control_cleanup_matching_tabs",
    "_control_cleanup_stopped_session",
    "_control_cleanup_tab_record",
    "_control_close_other_owned_tabs",
    "_control_close_owned_tab",
    "_control_current_same_site_candidate",
    "_control_discover_tabs_safe",
    "_control_forget_tab_state",
    "_control_int_tab_id",
    "_control_is_http_url",
    "_control_live_tab_map",
    "_control_matching_browser_tab",
    "_control_matching_browser_tab_from_tabs",
    "_control_matching_control_or_browser_tab",
    "_control_missing_tab_error",
    "_control_page_id",
    "_control_refresh_tab_url",
    "_control_release_matching_tabs",
    "_control_release_tab_record",
    "_control_remember_page_alias",
    "_control_states_have_tabs",
    "_control_tab_created_by_extension",
    "_control_tab_matches_request",
    "_control_tab_record",
    "_control_tab_url",
    "cleanup_control_sessions_for_request",
    "release_control_sessions_for_request",
]
