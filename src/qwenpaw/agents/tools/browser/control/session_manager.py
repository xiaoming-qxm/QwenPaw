# -*- coding: utf-8 -*-
"""Browser Control session lifecycle helpers."""

from __future__ import annotations

from typing import Any

from ..runtime import logger
from .errors import RECOVERABLE_CONTROL_EXCEPTIONS


def _control_holder_id(
    state: dict,
    request_context: dict[str, Any] | None = None,
) -> str:
    workspace_id = state.get("workspace_id") or "default"
    request_context = request_context or {}
    session_scope = str(
        request_context.get("root_session_id")
        or request_context.get("session_id")
        or "",
    ).strip()
    if session_scope:
        return f"browser_use:{workspace_id}:{session_scope}"
    return f"browser_use:{workspace_id}"


def _control_sessions(state: dict) -> dict[str, Any]:
    sessions = state.get("control_sessions")
    if not isinstance(sessions, dict):
        sessions = {}
        state["control_sessions"] = sessions
    return sessions


async def _control_abandon_session(session: Any) -> None:
    abandon = getattr(session, "abandon", None)
    if callable(abandon):
        await abandon()
    else:
        setattr(session, "_closed", True)


def _control_validate_session_lease(
    bridge: Any,
    *,
    tab_id: int,
    holder_id: str,
    lease_version: int | None = None,
) -> None:
    validate_lease = getattr(bridge, "validate_lease", None)
    if not callable(validate_lease):
        return
    validate_lease(tab_id, holder_id, lease_version)


async def _control_ensure_tab_lease(
    bridge: Any,
    *,
    tab_id: int,
    holder_id: str,
) -> None:
    try:
        _control_validate_session_lease(
            bridge,
            tab_id=tab_id,
            holder_id=holder_id,
        )
        return
    except RECOVERABLE_CONTROL_EXCEPTIONS:
        claim_tab = getattr(bridge, "claim_tab", None)
        if not callable(claim_tab):
            raise

    await claim_tab(tab_id, holder_id)
    _control_validate_session_lease(
        bridge,
        tab_id=tab_id,
        holder_id=holder_id,
    )


def _control_request_context() -> dict[str, Any]:
    context: dict[str, Any] = {}

    try:
        from qwenpaw.tool_calls import get_call_context

        call_context = get_call_context()
    except RECOVERABLE_CONTROL_EXCEPTIONS:
        call_context = None

    if call_context is not None:
        context.update(
            {
                "tool_call_id": call_context.tool_call_id,
                "session_id": call_context.session_id,
                "root_session_id": call_context.root_session_id,
                "agent_id": call_context.agent_id,
            },
        )
        request_context = call_context.extra.get("request_context")
        if isinstance(request_context, dict):
            for key, value in request_context.items():
                if key not in context:
                    context[key] = value

    try:
        from qwenpaw.app.agent_context import (
            get_current_agent_id,
            get_current_root_session_id,
            get_current_session_id,
        )

        if "agent_id" not in context:
            context["agent_id"] = get_current_agent_id()
        session_id = get_current_session_id()
        if session_id and "session_id" not in context:
            context["session_id"] = session_id
        root_session_id = get_current_root_session_id()
        if root_session_id and "root_session_id" not in context:
            context["root_session_id"] = root_session_id
    except RECOVERABLE_CONTROL_EXCEPTIONS:
        pass

    try:
        from qwenpaw.config.context import (
            get_current_session_id as get_config_sid,
        )

        session_id = get_config_sid()
        if session_id and "session_id" not in context:
            context["session_id"] = session_id
        if session_id and "root_session_id" not in context:
            context["root_session_id"] = session_id
    except RECOVERABLE_CONTROL_EXCEPTIONS:
        pass

    if context.get("session_id") and "root_session_id" not in context:
        context["root_session_id"] = context["session_id"]
    return context


def _control_store_last_dialog(
    state: dict,
    *,
    dialog_type: str,
    message: str,
) -> None:
    payload = {
        "type": dialog_type,
        "message": message,
        "auto_accepted": True,
    }
    extra = getattr(state, "extra", None)
    if isinstance(extra, dict):
        extra["last_dialog"] = payload
        return
    state["last_dialog"] = payload


def _control_register_dialog_auto_handler(
    state: dict,
    *,
    session: Any,
    bridge: Any,
    tab_id: int,
) -> None:
    add_listener = getattr(bridge, "add_event_listener", None)
    if not callable(add_listener):
        return
    if getattr(session, "_control_dialog_auto_handler_registered", False):
        return

    async def _auto_handle_dialog(event: dict[str, Any]) -> None:
        try:
            if not isinstance(event, dict):
                return
            event_tab_id = event.get("tabId", event.get("tab_id"))
            if event_tab_id is None or int(event_tab_id) != int(tab_id):
                return
            if event.get("method") != "Page.javascriptDialogOpening":
                return
            params = event.get("params")
            if not isinstance(params, dict):
                params = {}
            dialog_type = str(params.get("type") or "")
            message = str(params.get("message") or "")
            _control_store_last_dialog(
                state,
                dialog_type=dialog_type,
                message=message,
            )
            await session.send(
                "Page.handleJavaScriptDialog",
                {"accept": True, "promptText": ""},
            )
            logger.info(
                "Auto-handled %s dialog: %s",
                dialog_type,
                message,
            )
        except Exception:
            logger.debug(
                "Failed to auto-handle browser-control dialog",
                exc_info=True,
            )

    add_listener("cdp.event", _auto_handle_dialog)
    setattr(session, "_control_dialog_auto_handler", _auto_handle_dialog)
    setattr(session, "_control_dialog_auto_handler_registered", True)


def _control_remove_dialog_auto_handlers(state: dict, bridge: Any) -> None:
    remove_listener = getattr(bridge, "remove_event_listener", None)
    if not callable(remove_listener):
        return
    sessions = state.get("control_sessions")
    if not isinstance(sessions, dict):
        return
    for session in sessions.values():
        handler = getattr(session, "_control_dialog_auto_handler", None)
        if not callable(handler):
            continue
        try:
            remove_listener("cdp.event", handler)
        except (RuntimeError, OSError, ValueError, TypeError):
            logger.debug(
                "Failed to remove browser-control dialog handler",
                exc_info=True,
            )
        setattr(session, "_control_dialog_auto_handler", None)
        setattr(session, "_control_dialog_auto_handler_registered", False)


async def _control_prepare_session_events(
    state: dict,
    *,
    session: Any,
    bridge: Any,
    tab_id: int,
) -> None:
    _control_register_dialog_auto_handler(
        state,
        session=session,
        bridge=bridge,
        tab_id=tab_id,
    )
    try:
        await session.send("Page.enable")
    except (RuntimeError, OSError, ValueError, TypeError):
        logger.debug(
            "Failed to enable Page events for browser-control tab %s",
            tab_id,
            exc_info=True,
        )


async def _control_get_session(
    state: dict,
    *,
    tab_id: int,
    holder_id: str,
    bridge: Any,
    request_context: dict[str, Any] | None = None,
) -> Any:
    from qwenpaw.agents.tools.cdp_relay import CDPRelaySession

    sessions = _control_sessions(state)
    key = str(tab_id)
    session = sessions.get(key)
    known_to_holder = _control_tab_known_to_holder(
        state,
        tab_id=tab_id,
        holder_id=holder_id,
    )
    if session is not None and not getattr(session, "_closed", False):
        if str(getattr(session, "holder_id", "") or "") == holder_id:
            try:
                _control_validate_session_lease(
                    bridge,
                    tab_id=tab_id,
                    holder_id=holder_id,
                    lease_version=getattr(session, "lease_version", None),
                )
            except RECOVERABLE_CONTROL_EXCEPTIONS:
                sessions.pop(key, None)
                await _control_abandon_session(session)
            else:
                from .navigation import _control_sync_session_navigation_scope

                _control_sync_session_navigation_scope(state, session)
                return session
        else:
            sessions.pop(key, None)
            await _control_abandon_session(session)

    if known_to_holder:
        await _control_ensure_tab_lease(
            bridge,
            tab_id=tab_id,
            holder_id=holder_id,
        )
    else:
        _control_validate_session_lease(
            bridge,
            tab_id=tab_id,
            holder_id=holder_id,
        )

    session = CDPRelaySession(
        tab_id=tab_id,
        holder_id=holder_id,
        bridge=bridge,
        request_context=request_context,
    )
    from .navigation import _control_sync_session_navigation_scope

    _control_sync_session_navigation_scope(state, session)
    await _control_prepare_session_events(
        state,
        session=session,
        bridge=bridge,
        tab_id=tab_id,
    )
    sessions[key] = session
    return session


async def _control_get_existing_session(
    state: dict,
    *,
    tab_id: int,
    holder_id: str,
    bridge: Any,
    request_context: dict[str, Any] | None = None,
) -> Any | None:
    if (
        _control_active_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
        )
        is None
    ):
        return None
    try:
        return await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
    except RECOVERABLE_CONTROL_EXCEPTIONS:
        logger.debug(
            "Discarded stale browser-control session tab=%s holder=%s",
            tab_id,
            holder_id,
            exc_info=True,
        )
        return None


def _control_active_session(
    state: dict,
    *,
    tab_id: int,
    holder_id: str,
) -> Any | None:
    sessions = state.get("control_sessions")
    if not isinstance(sessions, dict):
        return None
    session = sessions.get(str(tab_id))
    if session is None or getattr(session, "_closed", False):
        return None
    if str(getattr(session, "holder_id", "") or "") != holder_id:
        return None
    control_tabs = state.get("control_tabs") or {}
    tab = control_tabs.get(str(tab_id))
    if isinstance(tab, dict) and str(tab.get("holder_id") or "") != holder_id:
        return None
    return session


def _control_tab_known_to_holder(
    state: dict,
    *,
    tab_id: int,
    holder_id: str,
) -> bool:
    tab = (state.get("control_tabs") or {}).get(str(tab_id))
    if isinstance(tab, dict) and str(tab.get("holder_id") or "") == holder_id:
        return True

    session = (state.get("control_sessions") or {}).get(str(tab_id))
    return (
        session is not None
        and not getattr(session, "_closed", False)
        and str(getattr(session, "holder_id", "") or "") == holder_id
    )


async def _control_close_session(
    state: dict,
    *,
    tab_id: int,
    holder_id: str,
    bridge: Any,
) -> None:
    sessions = _control_sessions(state)
    session = sessions.pop(str(tab_id), None)
    if session is not None:
        await session.close()
    else:
        await bridge.release(tab_id, holder_id)

    if not sessions:
        state.pop("control_sessions", None)


__all__ = [
    "_control_abandon_session",
    "_control_active_session",
    "_control_close_session",
    "_control_ensure_tab_lease",
    "_control_get_existing_session",
    "_control_get_session",
    "_control_holder_id",
    "_control_remove_dialog_auto_handlers",
    "_control_request_context",
    "_control_sessions",
    "_control_tab_known_to_holder",
    "_control_validate_session_lease",
]
