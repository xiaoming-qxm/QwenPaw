# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ChromeRecoverableError
from ..interactions import (
    _json_response,
    canonical_native_interaction_control,
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
            return await canonical_native_interaction_control(
                state,
                holder_id=holder_id,
                bridge=bridge,
                action="click",
                target_labels=("target",),
                kwargs=kwargs,
            )
        except (ChromeRecoverableError, ValueError, TypeError) as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


CLICK_HANDLER = ClickHandler()
__all__ = ["CLICK_HANDLER", "ClickHandler"]
