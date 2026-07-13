# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import BrowserBridgeRecoverableError
from ..interactions import (
    _canonical_runner_request,
    _json_response,
    canonical_native_interaction_control,
    click_control,
)
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
            request_context = kwargs.get("request_context") or {}
            if _canonical_runner_request(request_context):
                return await canonical_native_interaction_control(
                    state,
                    holder_id=holder_id,
                    bridge=bridge,
                    action="click",
                    target_labels=("target",),
                    kwargs=kwargs,
                )
            return await click_control(
                state,
                holder_id=holder_id,
                bridge=bridge,
                request_context=kwargs.get("request_context") or {},
                kwargs=kwargs,
            )
        except (BrowserBridgeRecoverableError, ValueError, TypeError) as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


CLICK_HANDLER = ClickHandler()
__all__ = ["CLICK_HANDLER", "ClickHandler"]
