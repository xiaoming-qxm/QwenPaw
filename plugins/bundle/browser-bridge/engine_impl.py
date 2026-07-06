# -*- coding: utf-8 -*-
"""Browser Bridge action runtime implementation."""
# pylint: disable=protected-access

from __future__ import annotations

from typing import Any

from agentscope.tool import ToolChunk

from .action_runtime import tab_manager as control_tab_manager
from .action_runtime import navigation as control_navigation
from .action_runtime.handlers import ACTION_HANDLERS
from .action_runtime.handlers.dispatcher import dispatch
from .action_runtime.handlers.misc import (
    unsupported_control_action_response,
)
from .action_runtime.interactions import (
    set_network_quiescence_wait,
)
from .action_runtime.navigation import (
    _CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS,
    _CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS,
)
from .action_runtime.network_settle import (
    _network_quiescence_wait,
)
from .action_runtime.session_manager import (
    _control_holder_id,
    _control_remove_dialog_auto_handlers,
    _control_request_context,
)
from .action_runtime.state import (
    control_state_from_mapping,
    sync_control_state_to_mapping,
)


class ControlEngineImpl:
    """Full Browser Bridge action runtime backed by typed handlers."""

    def __init__(self, *, bridge_manager: Any | None = None) -> None:
        self._bridge_manager = bridge_manager

    async def dispatch(
        self,
        state: dict[str, Any],
        action: str,
        **kwargs: Any,
    ) -> ToolChunk:
        """Dispatch an action through Browser Bridge handlers."""
        action_name = str(action or "").strip()
        state_obj = control_state_from_mapping(state)
        manager = self._bridge_manager
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

    async def cleanup_for_request(self, **kwargs: Any) -> dict[str, int]:
        """Release action runtime resources owned by one request."""
        return await control_tab_manager.cleanup_control_sessions_for_request(
            bridge_manager=self._bridge_manager,
            **kwargs,
        )

    async def release_for_request(self, **kwargs: Any) -> dict[str, int]:
        """Release action runtime leases owned by one completed request."""
        return await control_tab_manager.release_control_sessions_for_request(
            bridge_manager=self._bridge_manager,
            **kwargs,
        )
