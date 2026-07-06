# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import BrowserBridgeRecoverableError
from ..interactions import _json_response, type_control
from ..state import ControlState
from .protocol import ActionMeta


@dataclass(frozen=True)
class TypeHandler:
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
            return await type_control(
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


TYPE_HANDLER = TypeHandler()
__all__ = ["TYPE_HANDLER", "TypeHandler"]
