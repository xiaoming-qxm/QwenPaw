# -*- coding: utf-8 -*-
"""BrowserControlEngine implementation for the browser-control plugin."""
# pylint: disable=protected-access

from __future__ import annotations

from typing import Any

from agentscope.tool import ToolChunk

from qwenpaw.browser.connection_manager import get_bridge_connection_manager
from qwenpaw.browser.control_engine import BrowserControlEngine

from .engine import navigation as control_navigation
from .engine.handlers import ACTION_HANDLERS
from .engine.handlers.dispatcher import dispatch
from .engine.handlers.misc import (
    unsupported_control_action_response,
)
from .engine.interactions import (
    set_network_quiescence_wait,
)
from .engine.navigation import (
    _CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS,
    _CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS,
)
from .engine.network_settle import (
    _network_quiescence_wait,
)
from .engine.session_manager import (
    _control_holder_id,
    _control_remove_dialog_auto_handlers,
    _control_request_context,
)
from .engine.state import (
    control_state_from_mapping,
    sync_control_state_to_mapping,
)


class ControlEngineImpl(BrowserControlEngine):
    """Full Browser Control engine backed by typed action handlers."""

    async def dispatch(
        self,
        state: dict[str, Any],
        action: str,
        **kwargs: Any,
    ) -> ToolChunk:
        """Dispatch an action through Browser Control handlers."""
        action_name = str(action or "").strip()
        state_obj = control_state_from_mapping(state)
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
            if action_name not in ACTION_HANDLERS:
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
            sync_control_state_to_mapping(state_obj, state)

    def supported_actions(self) -> frozenset[str]:
        """Return action names supported by this engine."""
        return frozenset(ACTION_HANDLERS.keys())

    def get_request_context(self) -> dict[str, Any]:
        """Return current request context for control mode detection."""
        return _control_request_context()

    def has_active_session(self, state: dict[str, Any]) -> bool:
        """Return whether the workspace state has active control tabs."""
        tabs = state.get("control_tabs")
        return isinstance(tabs, dict) and bool(tabs)
