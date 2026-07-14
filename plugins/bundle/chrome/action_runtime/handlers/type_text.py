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
class TypeHandler:
    action: str = "type"
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
            canonical_kwargs = dict(kwargs)
            canonical_kwargs["input_mode"] = (
                "REPLACE" if self.action == "fill" else "APPEND"
            )
            return await canonical_interaction_control(
                state,
                action=self.action,
                target_labels=("target",),
                kwargs=canonical_kwargs,
            )
        except ChromeRecoverableError as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


TYPE_HANDLER = TypeHandler()
FILL_HANDLER = TypeHandler("fill")
TYPE_TEXT_HANDLER = TypeHandler("type_text")
__all__ = [
    "FILL_HANDLER",
    "TYPE_HANDLER",
    "TYPE_TEXT_HANDLER",
    "TypeHandler",
]
