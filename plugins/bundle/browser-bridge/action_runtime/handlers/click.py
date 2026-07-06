# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import BrowserBridgeRecoverableError
from ..interactions import _json_response, click_control
from ..state import ControlState
from .protocol import ActionMeta


@dataclass(frozen=True)
class ClickHandler:
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
            return await click_control(
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


CLICK_HANDLER = ClickHandler()
__all__ = ["CLICK_HANDLER", "ClickHandler"]
