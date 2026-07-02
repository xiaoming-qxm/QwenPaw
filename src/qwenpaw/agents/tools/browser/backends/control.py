# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any
from agentscope.tool import ToolChunk
from ..control import navigation as control_navigation
from ..control.handlers import ACTION_HANDLERS
from ..control.handlers.dispatcher import dispatch
from ..control.handlers.misc import unsupported_control_action_response
from ..control.interactions import (
    _control_click_feedback_payload,
    _control_click_navigation_status,
    set_network_quiescence_wait,
)
from ..control.navigation import (
    _CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS,
    _CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS,
)
from ..control.network_settle import _network_quiescence_wait
from ..control.session_manager import (
    _control_holder_id,
    _control_remove_dialog_auto_handlers,
    _control_request_context,
)
from ..control.state import ControlState

_ACTION_HANDLERS = ACTION_HANDLERS


async def _action_control(
    state: dict[str, Any] | ControlState,
    action: str,
    **kwargs: Any,
) -> ToolChunk:
    """Dispatch Browser Control actions through action handlers."""
    action_name = str(action or "").strip()
    state_obj = ControlState.from_dict(state)
    from qwenpaw.browser.connection_manager import (
        get_bridge_connection_manager,
    )

    manager = get_bridge_connection_manager()
    bridge = manager.get_connection() if manager is not None else None
    request_context = _control_request_context()
    holder_id = _control_holder_id(state_obj, request_context)
    try:
        set_network_quiescence_wait(_network_quiescence_wait)
        control_navigation._CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS = (
            _CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS
        )
        control_navigation._CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS = (
            _CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS
        )
        if action_name not in _ACTION_HANDLERS:
            return unsupported_control_action_response(action_name)
        return await dispatch(
            state_obj,
            action_name,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
            **kwargs,
        )
    finally:
        _control_remove_dialog_auto_handlers(state_obj, bridge)
        if isinstance(state, dict):
            state_obj.sync_to(state)


def _backend_handler(action: str):
    async def run(self: "ControlBackend", **kwargs: Any) -> ToolChunk:
        return await _action_control(self.state, action, **kwargs)

    return run


class ControlBackend:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    snapshot = _backend_handler("snapshot")
    click = _backend_handler("click")
    type_text = _backend_handler("type")
    press_key = _backend_handler("press_key")
    navigate = _backend_handler("navigate")
    list_tabs = _backend_handler("tabs")


__all__ = ["ControlBackend", "_ACTION_HANDLERS", "_action_control"]
