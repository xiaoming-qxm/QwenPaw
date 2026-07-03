# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser_sdk._runtime import _tool_response
from ..navigation import _control_tab_id
from ..observation import _control_clear_observation_required
from ..session_manager import _control_close_session
from ..state import ControlState
from ..tab_manager import _control_page_id
from .protocol import ActionMeta


@dataclass(frozen=True)
class ReleaseTabHandler:
    meta: ActionMeta = ActionMeta(True, False, False)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
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
        state.tabs.pop(str(tab_id), None)
        return _tool_response(
            json.dumps(
                {"ok": True, "mode": "control", "tab_id": tab_id},
                ensure_ascii=False,
                indent=2,
            ),
        )


RELEASE_TAB_HANDLER = ReleaseTabHandler()
__all__ = ["RELEASE_TAB_HANDLER", "ReleaseTabHandler"]
