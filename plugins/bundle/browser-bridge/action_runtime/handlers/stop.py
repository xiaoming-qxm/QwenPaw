# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.runtime.responses import _tool_response
from ..state import ControlState
from ..tab_manager import (
    _control_cleanup_extension_created_tabs,
    _control_cleanup_matching_tabs,
    _control_tab_matches_request,
)
from .protocol import ActionMeta
from .tabs import _bridge_error, _connected


@dataclass(frozen=True)
class StopHandler:
    meta: ActionMeta = ActionMeta(False, False, False)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        if not _connected(bridge):
            return _bridge_error()
        request_context = kwargs.get("request_context") or {}
        had_state = bool(state.tabs)
        session_id = str(request_context.get("session_id") or "")
        root_session_id = str(
            request_context.get("root_session_id") or session_id,
        )
        if session_id or root_session_id:
            result = await _control_cleanup_matching_tabs(
                state,
                bridge=bridge,
                predicate=lambda tab: _control_tab_matches_request(
                    tab,
                    session_id=session_id,
                    root_session_id=root_session_id,
                ),
            )
        else:
            result = await _control_cleanup_matching_tabs(
                state,
                bridge=bridge,
                predicate=lambda tab: str(tab.get("holder_id") or "")
                == holder_id,
            )
        if result["matched_tabs"] == 0 and request_context.get(
            "browser_bridge_invocation",
        ):
            prefix = f"browser_sdk:{state.workspace_id or 'default'}"
            result = await _control_cleanup_matching_tabs(
                state,
                bridge=bridge,
                predicate=lambda tab: str(
                    tab.get("holder_id") or "",
                ).startswith(prefix),
            )
        if result["matched_tabs"] == 0 and not had_state:
            result = await _control_cleanup_extension_created_tabs(
                state,
                bridge=bridge,
                request_context=request_context,
                holder_id=holder_id,
            )
        await bridge.release_all(holder_id)
        return _tool_response(
            json.dumps(
                {"ok": True, "mode": "control", **result},
                ensure_ascii=False,
                indent=2,
            ),
        )


STOP_HANDLER = StopHandler()

__all__ = ["STOP_HANDLER", "StopHandler"]
