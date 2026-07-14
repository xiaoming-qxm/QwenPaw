# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ChromeRecoverableError
from ..interactions import (
    _json_response,
    canonical_interaction_control,
)
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
        del holder_id, bridge
        try:
            return await canonical_interaction_control(
                state,
                action="press_key",
                target_labels=("target",),
                kwargs=kwargs,
            )
        except ChromeRecoverableError as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


PRESS_KEY_HANDLER = PressKeyHandler()
__all__ = ["PRESS_KEY_HANDLER", "PressKeyHandler"]
