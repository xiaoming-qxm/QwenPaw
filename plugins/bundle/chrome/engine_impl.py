# -*- coding: utf-8 -*-
"""Chrome action runtime implementation."""
# pylint: disable=protected-access

from __future__ import annotations

import json
from typing import Any

from agentscope.tool import ToolChunk

from qwenpaw.browser.governance.errors import BrowserSDKError
from qwenpaw.browser.runtime.responses import _tool_response
from .action_runtime import tab_manager as control_tab_manager
from .action_runtime import navigation as control_navigation
from .action_runtime.handlers import SUPPORTED_ACTIONS
from .action_runtime.handlers.dispatcher import dispatch
from .action_runtime.handlers.protocol import (
    is_trusted_command_envelope,
)
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
    _control_remove_dialog_auto_handlers,
    _control_request_context,
)
from .action_runtime.state import (
    control_state_from_mapping,
    sync_control_state_to_mapping,
)


class ControlEngineImpl:
    """Full Chrome action runtime backed by typed handlers."""

    def __init__(self, *, bridge_manager: Any | None = None) -> None:
        self._bridge_manager = bridge_manager

    async def dispatch(
        self,
        state: dict[str, Any],
        action: str,
        **kwargs: Any,
    ) -> ToolChunk:
        """Dispatch an action through Chrome handlers."""
        action_name = str(action or "").strip()
        state_obj = control_state_from_mapping(state)
        manager = self._bridge_manager
        bridge = manager.get_connection() if manager is not None else None
        request_context = _control_request_context()
        from qwenpaw.browser.runtime.kernel import (
            get_current_execution_context,
        )

        execution = get_current_execution_context()
        execution_mode = getattr(
            getattr(execution, "contract_mode", None),
            "value",
            getattr(execution, "contract_mode", None),
        )
        if execution is None or execution_mode != "CANONICAL":
            raise BrowserSDKError(
                "Control engine dispatch requires Canonical execution",
                code="canonical_dispatch_context_missing",
            )
        request_context = {
            **request_context,
            "contract_mode": "CANONICAL",
        }
        envelope = kwargs.get("trusted_envelope")
        if envelope is not None:
            if not is_trusted_command_envelope(envelope):
                raise BrowserSDKError(
                    "Control engine received an untrusted command envelope",
                    code="trusted_command_envelope_invalid",
                )
            if envelope.action != action_name:
                raise BrowserSDKError(
                    "Control engine action does not match its envelope",
                    code="trusted_command_envelope_mismatch",
                )
            request_context = {
                **request_context,
                "contract_mode": "CANONICAL",
                "canonical_dispatch_context": envelope.dispatch_context,
            }
        owner_id = _control_owner_id(state_obj)
        if not owner_id:
            return _ownership_context_missing_response()
        try:
            set_network_quiescence_wait(_network_quiescence_wait)
            control_navigation._CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS = (
                _CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS
            )
            control_navigation._CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS = (
                _CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS
            )
            if action_name not in SUPPORTED_ACTIONS:
                return unsupported_control_action_response(action_name)
            return await dispatch(
                state_obj,
                action_name,
                holder_id=owner_id,
                bridge=bridge,
                request_context=request_context,
                **kwargs,
            )
        finally:
            _control_remove_dialog_auto_handlers(state_obj, bridge)
            sync_control_state_to_mapping(state_obj, state)

    def supported_actions(self) -> frozenset[str]:
        """Return action names supported by this engine."""
        return SUPPORTED_ACTIONS

    def get_request_context(self) -> dict[str, Any]:
        """Return current request context for control mode detection."""
        return _control_request_context()

    def has_active_session(self, state: dict[str, Any]) -> bool:
        """Return whether the workspace state has active control tabs."""
        tabs = state.get("control_tabs")
        return isinstance(tabs, dict) and bool(tabs)

    async def cleanup_for_request(
        self,
        *,
        session_id: str,
        root_session_id: str = "",
        holder_id: str = "",
        workspace_id: str = "",
        cleanup_reason: str = "",
    ) -> dict[str, int]:
        """Release action runtime resources owned by one request."""
        return await control_tab_manager.cleanup_control_sessions_for_request(
            session_id=session_id,
            root_session_id=root_session_id,
            holder_id=holder_id,
            workspace_id=workspace_id,
            bridge_manager=self._bridge_manager,
            cleanup_reason=cleanup_reason,
        )

    async def release_for_request(
        self,
        *,
        session_id: str,
        root_session_id: str = "",
        workspace_id: str = "",
    ) -> dict[str, int]:
        """Release action runtime leases owned by one completed request."""
        return await control_tab_manager.release_control_sessions_for_request(
            session_id=session_id,
            root_session_id=root_session_id,
            workspace_id=workspace_id,
            bridge_manager=self._bridge_manager,
        )


def _control_owner_id(state: Any) -> str:
    context = state.get("ownership_context")
    if context is None:
        context = state.get("browser_ownership_context")
    if isinstance(context, dict):
        owner_id = str(context.get("owner_id") or context.get("ownerId") or "")
        if owner_id:
            return owner_id
    owner_id = str(getattr(context, "owner_id", "") or "")
    if owner_id:
        return owner_id
    return ""


def _ownership_context_missing_response() -> ToolChunk:
    return _tool_response(
        json.dumps(
            {
                "ok": False,
                "mode": "control",
                "code": "browser_ownership_context_missing",
                "error": "browser_ownership_context_missing",
                "message": "Browser ownership context is required.",
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
