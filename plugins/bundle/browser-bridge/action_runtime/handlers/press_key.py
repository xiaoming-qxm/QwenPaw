# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import BrowserBridgeRecoverableError
from ..interactions import _json_response, press_key_control
from ..state import ControlState
from .protocol import ActionMeta


@dataclass(frozen=True)
class PressKeyHandler:
    meta: ActionMeta = ActionMeta(True, True, True)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        try:
            return await press_key_control(
                state,
                holder_id=holder_id,
                bridge=bridge,
                request_context=kwargs.get("request_context") or {},
                kwargs=kwargs,
            )
        except BrowserBridgeRecoverableError as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


PRESS_KEY_HANDLER = PressKeyHandler()
__all__ = ["PRESS_KEY_HANDLER", "PressKeyHandler"]
