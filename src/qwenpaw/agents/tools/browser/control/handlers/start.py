# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ...runtime import _tool_response
from ..state import ControlState
from .protocol import ActionMeta


@dataclass(frozen=True)
class StartHandler:
    meta: ActionMeta = ActionMeta(False, False, False)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        del state, holder_id, kwargs
        ok = bridge is not None and bool(getattr(bridge, "connected", False))
        return _tool_response(
            json.dumps(
                {
                    "ok": ok,
                    "mode": "control",
                    "message": (
                        "Chrome extension bridge connected"
                        if ok
                        else "Chrome extension bridge is not connected"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )


START_HANDLER = StartHandler()

__all__ = ["START_HANDLER", "StartHandler"]
