# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Browser Control backend action dispatcher."""

from ..runtime import *
from ..control.session_manager import *
from ..control.navigation import *
from ..control.tab_manager import *
from ..control.observation import *
from ..control.inference import *
from ..control.transitions import *
from ..control.targets import *


def _control_tab_url_from_tabs(
    tabs: list[dict[str, Any]] | None,
    tab_id: int,
) -> str:
    """Return the live URL for a tab from a discovered tab list."""
    live_tabs = _control_live_tab_map(tabs)
    if not live_tabs:
        return ""
    tab = live_tabs.get(tab_id)
    if not isinstance(tab, dict):
        return ""
    return _control_tab_url(tab)


def _control_cached_tab_url(state: dict, tab_id: int) -> str:
    """Return the cached URL for a controlled tab."""
    control_tabs = state.get("control_tabs") or {}
    if not isinstance(control_tabs, dict):
        return ""
    tab = control_tabs.get(str(tab_id))
    if not isinstance(tab, dict):
        return ""
    return str(tab.get("url") or "")


def _control_click_navigation_status(
    state: dict,
    *,
    tab_id: int,
    before_tabs: list[dict[str, Any]] | None,
    after_tabs: list[dict[str, Any]] | None,
    before_url: str = "",
) -> tuple[bool, str]:
    """Detect whether a click changed the current tab URL."""
    before_url = (
        before_url
        or _control_cached_tab_url(state, tab_id)
        or _control_tab_url_from_tabs(before_tabs, tab_id)
    )

    after_url = _control_tab_url_from_tabs(after_tabs, tab_id)
    if after_url:
        _control_refresh_tab_url(state, tab_id, after_url)

    if not before_url or not after_url:
        return False, after_url or before_url
    return (
        _control_url_key(before_url) != _control_url_key(after_url),
        after_url,
    )


def _control_click_feedback_payload(
    *,
    tab_id: int,
    navigation_occurred: bool,
    url: str,
) -> dict[str, Any]:
    """Build the post-click response used when no transition payload exists."""
    if navigation_occurred:
        message = "Click completed and navigation was detected."
        next_instruction = (
            "The click changed the current tab. Observe it with snapshot "
            "before taking another action."
        )
    else:
        message = (
            "Click completed, but no navigation was detected. If the target "
            'destination is known, use browser_use(action="navigate", '
            f'mode="control", page_id="{tab_id}", url="...") instead '
            "of repeating the same click."
        )
        next_instruction = (
            "Observe the page before another action. If this action should "
            "have opened a known URL, navigate directly with that URL; if it "
            "opened a tab asynchronously, the next observation will claim it "
            "instead of repeating the opener action."
        )

    payload: dict[str, Any] = {
        "ok": True,
        "mode": "control",
        "tab_id": tab_id,
        "message": message,
        "navigation_occurred": navigation_occurred,
        "needs_observation": True,
        "ready_for_observation": True,
        "next_action": "snapshot",
        "next_instruction": next_instruction,
    }
    if url:
        payload["url"] = url
    return payload


async def _action_control(  # pylint: disable=too-many-return-statements
    state: dict,
    action: str,
    **kwargs,
) -> ToolChunk:
    """Dispatch browser_use control actions through NMBridge."""
    from qwenpaw.browser.connection_manager import (
        get_bridge_connection_manager,
    )

    manager = get_bridge_connection_manager()
    if manager is not None:
        bridge = manager.get_connection()
    else:
        bridge = None
    request_context = _control_request_context()
    holder_id = _control_holder_id(state, request_context)
    action = (action or "").strip().lower()
    url = str(kwargs.get("url") or "").strip()
    user_initiated = bool(kwargs.get("user_initiated", False))

    if action == "start" and url:
        action = "claim_tab"
    user_initiated = _control_should_infer_user_initiated(
        state=state,
        action=action,
        url=url,
        holder_id=holder_id,
        request_context=request_context,
        user_initiated=user_initiated,
    )

    if action == "start":
        return _tool_response(
            json.dumps(
                {
                    "ok": bridge is not None and bridge.connected,
                    "mode": "control",
                    "message": (
                        "Chrome extension bridge connected"
                        if bridge is not None and bridge.connected
                        else "Chrome extension bridge is not connected"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    if bridge is None:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "mode": "control",
                    "error": "Chrome extension bridge is not connected",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action in {"discover_tabs", "tabs"}:
        tab_action = str(kwargs.get("tab_action") or "list").strip().lower()
        if action == "tabs" and tab_action not in {"", "list"}:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "mode": "control",
                        "error": (
                            "control tabs only supports tab_action=list"
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        tabs = await bridge.discover_tabs()
        return _tool_response(
            json.dumps(
                {"ok": True, "mode": "control", "tabs": tabs},
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action in {
        "snapshot",
        "screenshot",
        "click",
        "type",
        "press_key",
        "wait_for",
    }:
        pending_payload = await _control_consume_pending_action_transition(
            state,
            bridge=bridge,
            holder_id=holder_id,
            request_context=request_context,
        )
        if pending_payload is not None:
            return _tool_response(
                json.dumps(
                    pending_payload,
                    ensure_ascii=False,
                    indent=2,
                ),
            )

    if action == "open":
        if not url:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "mode": "control",
                        "error": "url required for open",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        raw_page_id = str(kwargs.get("page_id") or "").strip()
        has_explicit_target = (
            _control_page_id_is_tab_id(
                raw_page_id,
            )
            or kwargs.get("index", -1) >= 0
        )
        action = "navigate" if has_explicit_target else "claim_tab"

    if action == "claim_tab":
        raw_page_id = str(kwargs.get("page_id", "")).strip() or "default"
        discovered_tab_url = ""
        selected_by_url = (
            bool(url)
            and not _control_page_id_is_tab_id(raw_page_id)
            and kwargs.get("index", -1) < 0
        )
        tab_created_by_control = False
        if selected_by_url:
            (
                tab_id,
                discovered_tab_url,
                selection_error,
                tab_created_by_control,
            ) = await _control_select_or_create_url_tab(
                state,
                bridge,
                url,
                request_context,
                holder_id,
                user_initiated=user_initiated,
            )
            if selection_error or tab_id is None:
                return _tool_response(
                    json.dumps(
                        {
                            "ok": False,
                            "mode": "control",
                            "error": selection_error or "No tab selected",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        else:
            page_id = _control_page_id(state, raw_page_id)
            tab_id = _control_tab_id(page_id, kwargs.get("index", -1))
        existing_session = await _control_get_existing_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        if existing_session is not None:
            await _control_activate_tab(bridge, tab_id)
            control_tabs = state.setdefault("control_tabs", {})
            previous_tab = control_tabs.get(str(tab_id)) or {}
            current_tab_url = (
                discovered_tab_url or previous_tab.get("url") or ""
            )
            tab_url = await _control_align_tab_to_requested_url(
                existing_session,
                url,
                current_tab_url,
            )
            if not tab_url:
                tab_url = current_tab_url or url
            control_tabs[str(tab_id)] = _control_tab_record(
                tab_id=tab_id,
                holder_id=holder_id,
                url=tab_url,
                created_by_control=bool(
                    previous_tab.get("created_by_control"),
                ),
                request_context=request_context,
                previous_tab=previous_tab,
            )
            state["current_page_id"] = str(tab_id)
            _control_remember_page_alias(state, raw_page_id, tab_id)
            return _tool_response(
                json.dumps(
                    _control_claim_success_payload(tab_id, tab_url),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        attach_attempt = 0
        while True:
            try:
                await bridge.claim_tab(tab_id, holder_id)
                attach_response = await bridge.request(
                    "tab.attach",
                    {"tabId": tab_id, "holderId": holder_id},
                )
                attach_error = _control_jsonrpc_error(attach_response)
                if attach_error:
                    raise RuntimeError(attach_error)
                break
            except Exception as exc:
                try:
                    await bridge.release(tab_id, holder_id)
                except Exception:
                    logger.debug(
                        "Failed to release control lease after attach failure",
                        exc_info=True,
                    )
                if (
                    not selected_by_url
                    or attach_attempt > 0
                    or not _control_missing_tab_error(str(exc))
                ):
                    return _tool_response(
                        json.dumps(
                            {
                                "ok": False,
                                "mode": "control",
                                "error": (
                                    f"Failed to attach tab {tab_id}: {exc!s}"
                                ),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                await _control_forget_tab_state(state, tab_id)
                attach_attempt += 1
                (
                    tab_id,
                    discovered_tab_url,
                    selection_error,
                    tab_created_by_control,
                ) = await _control_select_or_create_url_tab(
                    state,
                    bridge,
                    url,
                    request_context,
                    holder_id,
                    user_initiated=user_initiated,
                )
                if selection_error or tab_id is None:
                    return _tool_response(
                        json.dumps(
                            {
                                "ok": False,
                                "mode": "control",
                                "error": selection_error or "No tab selected",
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
        await _control_activate_tab(bridge, tab_id)
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
            logger.debug("control banner.show timed out")
        except Exception:
            logger.debug("control banner.show failed", exc_info=True)
        control_tabs = state.setdefault("control_tabs", {})
        previous_tab = control_tabs.get(str(tab_id)) or {}
        current_tab_url = discovered_tab_url or previous_tab.get("url") or ""
        tab_url = await _control_align_tab_to_requested_url(
            session,
            url,
            current_tab_url,
        )
        if not tab_url:
            tab_url = current_tab_url or url
        control_tabs[str(tab_id)] = _control_tab_record(
            tab_id=tab_id,
            holder_id=holder_id,
            url=tab_url,
            created_by_control=bool(
                tab_created_by_control
                or previous_tab.get("created_by_control"),
            ),
            request_context=request_context,
            previous_tab=previous_tab,
        )
        state["current_page_id"] = str(tab_id)
        _control_remember_page_alias(state, raw_page_id, tab_id)
        return _tool_response(
            json.dumps(
                _control_claim_success_payload(tab_id, tab_url),
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action == "navigate":
        if not url:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "mode": "control",
                        "error": "url required for navigate",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        await _control_activate_tab(bridge, tab_id)
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        await session.send_after_banner(
            "Page.navigate",
            {"url": url},
            {"status_text": "Navigate"},
        )
        state["current_page_id"] = str(tab_id)
        control_tabs = state.setdefault("control_tabs", {})
        previous_tab = control_tabs.get(str(tab_id)) or {}
        control_tabs[str(tab_id)] = _control_tab_record(
            tab_id=tab_id,
            holder_id=str(previous_tab.get("holder_id") or holder_id),
            url=url,
            created_by_control=bool(
                previous_tab.get("created_by_control"),
            ),
            request_context=request_context,
            previous_tab=previous_tab,
        )
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "url": url,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action == "release_tab":
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        await bridge.request("banner.hide", {"tabId": tab_id})
        await bridge.request(
            "tab.detach",
            {"tabId": tab_id, "holderId": holder_id},
        )
        await _control_close_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
        )
        _control_clear_observation_required(state, tab_id)
        state.setdefault("control_tabs", {}).pop(str(tab_id), None)
        return _tool_response(
            json.dumps(
                {"ok": True, "mode": "control", "tab_id": tab_id},
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action == "snapshot":
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        await _control_activate_tab(bridge, tab_id)
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        ax_tree = await session.send("Accessibility.getFullAXTree")
        from qwenpaw.agents.tools.browser_snapshot import from_cdp_ax_tree

        snapshot, refs = from_cdp_ax_tree(ax_tree)
        snapshot_text = snapshot.strip()
        if not refs and (
            len(snapshot_text) < 50
            or snapshot_text.startswith("- RootWebArea")
        ):
            try:
                dom_snapshot = await session.send(
                    "DOMSnapshot.captureSnapshot",
                    {
                        "computedStyles": [],
                        "includeDOMRects": True,
                        "includePaintOrder": True,
                    },
                )
                from qwenpaw.agents.tools.browser_snapshot import (
                    from_cdp_dom_snapshot,
                )

                fallback_snapshot, fallback_refs = from_cdp_dom_snapshot(
                    dom_snapshot,
                )
                if fallback_snapshot != "(empty)":
                    snapshot = fallback_snapshot
                    refs = fallback_refs
            except Exception:
                logger.debug(
                    "Failed to build control DOMSnapshot fallback",
                    exc_info=True,
                )
        state.setdefault("refs", {})[str(tab_id)] = refs
        _control_clear_observation_required(state, tab_id)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "snapshot": snapshot,
                    "refs": refs,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action == "click":
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        pending_response = _control_require_observation_before_action(
            state,
            action=action,
            tab_id=tab_id,
        )
        if pending_response is not None:
            return pending_response
        await _control_activate_tab(bridge, tab_id)
        ref = kwargs.get("ref") or ""
        selector = str(kwargs.get("selector") or "").strip()
        text = str(kwargs.get("text") or "").strip()
        refs = state.get("refs", {}).get(str(tab_id), {})
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        target = refs.get(ref, {}) if ref else {}
        if not target and selector:
            target = await _control_selector_target(session, selector)
        if not target and text:
            target = await _control_text_target(session, text)
        x, y = await _control_resolve_point(
            session,
            target,
            ref=ref or selector or text,
            fallback_x=kwargs.get("x"),
            fallback_y=kwargs.get("y"),
        )
        before_url = _control_cached_tab_url(state, tab_id)
        before_tabs = await _control_discover_tabs_safe(bridge)
        if not before_url:
            before_url = _control_tab_url_from_tabs(before_tabs, tab_id)
        transition_waiter = _control_create_action_transition_waiter(
            bridge,
            before_tabs=before_tabs,
            source_tab_id=tab_id,
        )
        await _control_click_at(session, x, y, "Click")
        transition_payload = await _control_resolve_action_transition(
            state,
            bridge=bridge,
            before_tabs=before_tabs,
            transition_waiter=transition_waiter,
            source_tab_id=tab_id,
            holder_id=holder_id,
            request_context=request_context,
        )
        if transition_payload is not None:
            transition_tab_id = _control_int_tab_id(
                transition_payload.get("tab_id"),
            )
            _control_mark_observation_required(
                state,
                transition_tab_id if transition_tab_id is not None else tab_id,
                action=action,
            )
            transition_payload.setdefault("navigation_occurred", True)
            transition_payload.setdefault("needs_observation", True)
            return _tool_response(
                json.dumps(
                    transition_payload,
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        after_tabs = (
            await _control_discover_tabs_safe(bridge) if before_url else None
        )
        navigation_occurred, current_url = _control_click_navigation_status(
            state,
            tab_id=tab_id,
            before_tabs=before_tabs,
            after_tabs=after_tabs,
            before_url=before_url,
        )
        _control_mark_observation_required(state, tab_id, action=action)
        return _tool_response(
            json.dumps(
                _control_click_feedback_payload(
                    tab_id=tab_id,
                    navigation_occurred=navigation_occurred,
                    url=current_url,
                ),
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action == "type":
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        pending_response = _control_require_observation_before_action(
            state,
            action=action,
            tab_id=tab_id,
        )
        if pending_response is not None:
            return pending_response
        await _control_activate_tab(bridge, tab_id)
        ref = kwargs.get("ref") or ""
        selector = str(kwargs.get("selector") or "").strip()
        refs = state.get("refs", {}).get(str(tab_id), {})
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        before_tabs = await _control_discover_tabs_safe(bridge)
        transition_waiter = _control_create_action_transition_waiter(
            bridge,
            before_tabs=before_tabs,
            source_tab_id=tab_id,
        )
        target = refs.get(ref, {}) if ref else {}
        if not target and selector:
            target = await _control_selector_target(session, selector)
        if target:
            x, y = await _control_resolve_point(
                session,
                target,
                ref=ref or selector,
            )
            await _control_click_at(session, x, y, "Focus")
        text_to_type = str(kwargs.get("text", ""))
        await _control_show_keyboard(
            session,
            text=text_to_type,
            status_text="Type",
        )
        await session.send(
            "Input.insertText",
            {"text": text_to_type},
        )
        if bool(kwargs.get("submit", False)):
            await _control_press_key(session, "Enter")
        transition_payload = await _control_resolve_action_transition(
            state,
            bridge=bridge,
            before_tabs=before_tabs,
            transition_waiter=transition_waiter,
            source_tab_id=tab_id,
            holder_id=holder_id,
            request_context=request_context,
        )
        if transition_payload is not None:
            transition_tab_id = _control_int_tab_id(
                transition_payload.get("tab_id"),
            )
            _control_mark_observation_required(
                state,
                transition_tab_id if transition_tab_id is not None else tab_id,
                action=action,
            )
            return _tool_response(
                json.dumps(
                    transition_payload,
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        _control_mark_observation_required(state, tab_id, action=action)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "ready_for_observation": True,
                    "next_action": "snapshot",
                    "next_instruction": (
                        "Text was entered. Observe the page before deciding "
                        "whether to press Enter, click a submit button, or "
                        "take another action."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action == "press_key":
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        pending_response = _control_require_observation_before_action(
            state,
            action=action,
            tab_id=tab_id,
        )
        if pending_response is not None:
            return pending_response
        await _control_activate_tab(bridge, tab_id)
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        before_tabs = await _control_discover_tabs_safe(bridge)
        transition_waiter = _control_create_action_transition_waiter(
            bridge,
            before_tabs=before_tabs,
            source_tab_id=tab_id,
        )
        try:
            await _control_press_key(session, str(kwargs.get("key") or ""))
        except ValueError as exc:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "mode": "control",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        transition_payload = await _control_resolve_action_transition(
            state,
            bridge=bridge,
            before_tabs=before_tabs,
            transition_waiter=transition_waiter,
            source_tab_id=tab_id,
            holder_id=holder_id,
            request_context=request_context,
        )
        if transition_payload is not None:
            transition_tab_id = _control_int_tab_id(
                transition_payload.get("tab_id"),
            )
            _control_mark_observation_required(
                state,
                transition_tab_id if transition_tab_id is not None else tab_id,
                action=action,
            )
            return _tool_response(
                json.dumps(
                    transition_payload,
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        _control_mark_observation_required(state, tab_id, action=action)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "ready_for_observation": True,
                    "next_action": "snapshot",
                    "next_instruction": (
                        "The key press completed. Observe the page before "
                        "taking another action."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action == "screenshot":
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        await _control_activate_tab(bridge, tab_id)
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        screenshot_type = kwargs.get("screenshot_type", "png")
        path = str(kwargs.get("path") or "").strip()
        if not path:
            ext = "jpeg" if screenshot_type == "jpeg" else "png"
            path = f"page-{int(time.time())}.{ext}"
        path = _resolve_output_path(path)
        result = await session.send(
            "Page.captureScreenshot",
            {
                "format": screenshot_type,
                "captureBeyondViewport": bool(kwargs.get("full_page", False)),
            },
        )
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, str) or not data:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "mode": "control",
                        "error": "Screenshot failed: CDP returned no image data",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        _control_clear_observation_required(state, tab_id)
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(data))
        media_type = "image/jpeg" if screenshot_type == "jpeg" else "image/png"
        return _tool_response_with_blocks(
            json.dumps(
                {
                    "ok": True,
                    "mode": "control",
                    "message": f"Screenshot saved to {path}",
                    "path": path,
                },
                ensure_ascii=False,
                indent=2,
            ),
            [
                DataBlock(
                    source=URLSource(
                        url=output_path.resolve().as_uri(),
                        media_type=media_type,
                    ),
                    name=output_path.name,
                ),
            ],
        )

    if action == "wait_for":
        waited = float(kwargs.get("wait_time") or 0)
        if waited <= 0:
            waited = 1.0
        await asyncio.sleep(waited)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "mode": "control",
                    "waited": waited,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    if action == "stop":
        had_local_control_state = bool(state.get("control_tabs"))
        session_id = str(request_context.get("session_id") or "")
        root_session_id = str(
            request_context.get("root_session_id") or session_id,
        )
        if session_id or root_session_id:
            cleanup_result = await _control_cleanup_matching_tabs(
                state,
                bridge=bridge,
                predicate=lambda tab: _control_tab_matches_request(
                    tab,
                    session_id=session_id,
                    root_session_id=root_session_id,
                ),
            )
        else:
            cleanup_result = await _control_cleanup_matching_tabs(
                state,
                bridge=bridge,
                predicate=lambda tab: str(tab.get("holder_id") or "")
                == holder_id,
            )
        if cleanup_result["matched_tabs"] == 0 and request_context.get(
            "browser_control_invocation",
        ):
            workspace_holder_prefix = (
                f"browser_use:{state.get('workspace_id') or 'default'}"
            )
            cleanup_result = await _control_cleanup_matching_tabs(
                state,
                bridge=bridge,
                predicate=lambda tab: str(
                    tab.get("holder_id") or "",
                ).startswith(workspace_holder_prefix),
            )
        if cleanup_result["matched_tabs"] == 0 and not had_local_control_state:
            cleanup_result = await _control_cleanup_extension_created_tabs(
                state,
                bridge=bridge,
                request_context=request_context,
                holder_id=holder_id,
            )
        await bridge.release_all(holder_id)
        return _tool_response(
            json.dumps(
                {"ok": True, "mode": "control", **cleanup_result},
                ensure_ascii=False,
                indent=2,
            ),
        )

    unsupported_guidance = (
        "JavaScript evaluation is not available in control mode. "
        'Use browser_use(action="tabs", mode="control") to inspect '
        "current tab URLs, and use snapshot or screenshot to observe page "
        "state before choosing the next browser action."
    )
    unsupported_actions = {
        "eval",
        "evaluate",
        "run_code",
        "runtime.evaluate",
    }
    return _tool_response(
        json.dumps(
            {
                "ok": False,
                "mode": "control",
                "error": (
                    f"Unsupported control action: {action}"
                    if action in unsupported_actions
                    else f"Unknown action: {action}"
                ),
                "use_instead": ["tabs", "snapshot", "screenshot"],
                "guidance": unsupported_guidance,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


class ControlBackend:
    """Protocol implementation backed by Browser Control action dispatch."""

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def snapshot(self, **kwargs: Any) -> ToolChunk:
        """Return structured page evidence from the controlled tab."""
        return await _action_control(self.state, "snapshot", **kwargs)

    async def click(self, **kwargs: Any) -> ToolChunk:
        """Click a target in the controlled tab."""
        return await _action_control(self.state, "click", **kwargs)

    async def type_text(self, **kwargs: Any) -> ToolChunk:
        """Type text in the controlled tab."""
        return await _action_control(self.state, "type", **kwargs)

    async def press_key(self, **kwargs: Any) -> ToolChunk:
        """Press a keyboard key in the controlled tab."""
        return await _action_control(self.state, "press_key", **kwargs)

    async def navigate(self, **kwargs: Any) -> ToolChunk:
        """Navigate the controlled tab."""
        return await _action_control(self.state, "navigate", **kwargs)

    async def list_tabs(self, **kwargs: Any) -> ToolChunk:
        """List Browser Control tabs."""
        return await _action_control(self.state, "tabs", **kwargs)


__all__ = [name for name in globals() if not name.startswith("__")]
