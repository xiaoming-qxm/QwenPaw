# -*- coding: utf-8 -*-
"""Browser Bridge session lifecycle helpers."""
# pylint: disable=too-many-branches

from __future__ import annotations

from typing import Any

from qwenpaw.browser.sdk.runtime.responses import logger
from .errors import RECOVERABLE_CONTROL_EXCEPTIONS
from .state import StateMapping


def _control_holder_id(
    state: StateMapping,
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
        return f"browser_sdk:{workspace_id}:{session_scope}"
    return f"browser_sdk:{workspace_id}"


def _control_sessions(state: StateMapping) -> dict[str, Any]:
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
) -> Any | None:
    validate_or_renew = getattr(bridge, "validate_or_renew", None)
    if callable(validate_or_renew):
        return validate_or_renew(tab_id, holder_id, lease_version)
    validate_lease = getattr(bridge, "validate_lease", None)
    if not callable(validate_lease):
        return None
    return validate_lease(tab_id, holder_id, lease_version)


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


def _control_refresh_session_request_context(
    session: Any,
    request_context: dict[str, Any] | None,
) -> None:
    """Keep cached CDP sessions aligned with the current tool call context."""

    if not request_context:
        return

    current = getattr(session, "request_context", None)
    if not isinstance(current, dict):
        current = {}
    else:
        current = dict(current)

    for key, value in request_context.items():
        if value is None:
            continue
        if isinstance(value, str) and not value:
            continue
        current[key] = value

    setattr(session, "request_context", current)


def _control_store_last_dialog(
    state: StateMapping,
    *,
    dialog_type: str,
    message: str,
    accepted: bool = True,
) -> None:
    payload = {
        "type": dialog_type,
        "message": message,
        "auto_accepted": accepted,
        "accepted": accepted,
    }
    extra = getattr(state, "extra", None)
    if isinstance(extra, dict):
        extra["last_dialog"] = payload
        return
    state["last_dialog"] = payload


def _control_pop_next_dialog_decision(
    state: StateMapping,
    *,
    tab_id: int,
) -> dict[str, Any]:
    default = {"accept": True, "prompt_text": ""}
    extra = getattr(state, "extra", None)
    if isinstance(extra, dict):
        decision = extra.pop("next_dialog_decision", None)
    else:
        decision = state.pop("next_dialog_decision", None)
    if not isinstance(decision, dict):
        return default
    decision_tab_id = decision.get("tab_id")
    if decision_tab_id is not None and int(decision_tab_id) != int(tab_id):
        if isinstance(extra, dict):
            extra["next_dialog_decision"] = decision
        else:
            state["next_dialog_decision"] = decision
        return default
    return {
        "accept": bool(decision.get("accept", True)),
        "prompt_text": str(decision.get("prompt_text") or ""),
    }


def _control_register_dialog_auto_handler(
    state: StateMapping,
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
            decision = _control_pop_next_dialog_decision(state, tab_id=tab_id)
            accept = bool(decision.get("accept", True))
            prompt_text = str(decision.get("prompt_text") or "")
            _control_store_last_dialog(
                state,
                dialog_type=dialog_type,
                message=message,
                accepted=accept,
            )
            await session.send(
                "Page.handleJavaScriptDialog",
                {"accept": accept, "promptText": prompt_text},
            )
            logger.info(
                "Auto-handled %s dialog: %s",
                dialog_type,
                message,
            )
        except Exception:
            logger.debug(
                "Failed to auto-handle browser-bridge dialog",
                exc_info=True,
            )

    add_listener("cdp.event", _auto_handle_dialog)
    setattr(session, "_control_dialog_auto_handler", _auto_handle_dialog)
    setattr(session, "_control_dialog_auto_handler_registered", True)


def _control_remove_dialog_auto_handlers(
    state: StateMapping,
    bridge: Any,
) -> None:
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
                "Failed to remove browser-bridge dialog handler",
                exc_info=True,
            )
        setattr(session, "_control_dialog_auto_handler", None)
        setattr(session, "_control_dialog_auto_handler_registered", False)


async def _control_prepare_session_events(
    state: StateMapping,
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
            "Failed to enable Page events for browser-bridge tab %s",
            tab_id,
            exc_info=True,
        )


async def _control_get_session(
    state: StateMapping,
    *,
    tab_id: int,
    holder_id: str,
    bridge: Any,
    request_context: dict[str, Any] | None = None,
) -> Any:
    from .cdp_relay import CDPRelaySession

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

                _control_refresh_session_request_context(
                    session,
                    request_context,
                )
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
    state: StateMapping,
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
            "Discarded stale browser-bridge session tab=%s holder=%s",
            tab_id,
            holder_id,
            exc_info=True,
        )
        return None


def _control_active_session(
    state: StateMapping,
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
    state: StateMapping,
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
    state: StateMapping,
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
