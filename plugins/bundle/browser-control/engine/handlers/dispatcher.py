# -*- coding: utf-8 -*-
"""Dispatcher for typed Browser Control action handlers."""

from __future__ import annotations

import json
from typing import Any

from agentscope.tool import ToolChunk

from qwenpaw.browser_sdk._runtime import _tool_response
from ..navigation import _control_tab_id
from ..observation import (
    _control_mark_observation_required,
    _control_require_observation_before_action,
)
from ..state import ControlState
from ..tab_manager import _control_int_tab_id, _control_page_id
from ..transitions import _control_consume_pending_action_transition
from .misc import unsupported_control_action_response
from .protocol import ActionHandler

_REGISTRY: dict[str, ActionHandler] = {}

_LEGACY_FALLBACK_ACTIONS = {
    "start",
    "tabs",
    "discover_tabs",
    "open",
    "claim_tab",
    "navigate",
    "release_tab",
    "click",
    "type",
    "press_key",
    "screenshot",
    "wait_for",
    "stop",
}

_TRANSITION_OBSERVATION_ACTIONS = {
    "snapshot",
    "screenshot",
    "click",
    "type",
    "press_key",
    "wait_for",
}


def register_handler(name: str, handler: ActionHandler) -> None:
    """Register a typed action handler by action name."""
    _REGISTRY[str(name or "").strip().lower()] = handler


def _bridge_unavailable_response() -> ToolChunk:
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


def _tab_id_from_kwargs(kwargs: dict[str, Any]) -> int | None:
    value = kwargs.get("tab_id", kwargs.get("page_id"))
    tab_id = _control_int_tab_id(value)
    if tab_id is not None:
        return tab_id
    page_id = str(kwargs.get("page_id") or "")
    if page_id.startswith("tab_"):
        return _control_int_tab_id(page_id[4:])
    index = kwargs.get("index")
    return _control_int_tab_id(index)


def _resolved_tab_id(
    state: ControlState,
    kwargs: dict[str, Any],
) -> int | None:
    try:
        return _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
    except (RuntimeError, ValueError, TypeError):
        return _tab_id_from_kwargs(kwargs)


def _response_ok(response: ToolChunk) -> bool:
    try:
        text = getattr(response.content[0], "text", "")
        return json.loads(text).get("ok") is True
    except (
        AttributeError,
        IndexError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ):
        return False


async def dispatch(
    state: ControlState,
    action: str,
    *,
    holder_id: str,
    bridge: Any,
    **kwargs: Any,
) -> ToolChunk:
    """Dispatch a Browser Control action through typed handlers."""
    action_name = str(action or "").strip().lower()
    handler = _REGISTRY.get(action_name)
    if handler is None:
        return unsupported_control_action_response(action_name)

    if handler.meta.requires_tab_claimed and (
        bridge is None or not bool(getattr(bridge, "connected", False))
    ):
        return _bridge_unavailable_response()

    if action_name in _TRANSITION_OBSERVATION_ACTIONS:
        pending_payload = await _control_consume_pending_action_transition(
            state,
            bridge=bridge,
            holder_id=holder_id,
            request_context=kwargs.get("request_context") or {},
        )
        if pending_payload is not None:
            return _tool_response(
                json.dumps(pending_payload, ensure_ascii=False, indent=2),
            )

    tab_id = _resolved_tab_id(state, kwargs)
    if handler.meta.requires_observation and tab_id is not None:
        pending_response = _control_require_observation_before_action(
            state,
            action=action_name,
            tab_id=tab_id,
        )
        if pending_response is not None:
            return pending_response

    response = await handler.execute(
        state,
        holder_id=holder_id,
        bridge=bridge,
        **kwargs,
    )
    if (
        handler.meta.invalidates_snapshot
        and tab_id is not None
        and _response_ok(response)
    ):
        _control_mark_observation_required(state, tab_id, action=action_name)
    return response


__all__ = ["_REGISTRY", "dispatch", "register_handler"]
