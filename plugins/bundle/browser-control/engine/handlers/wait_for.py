# -*- coding: utf-8 -*-
"""Wait Browser Control action handler."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.sdk.runtime.responses import _tool_response
from ..state import ControlState
from .protocol import ActionMeta


@dataclass(frozen=True)
class WaitForHandler:
    meta: ActionMeta = ActionMeta(
        requires_tab_claimed=True,
        requires_observation=False,
        invalidates_snapshot=True,
    )

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        del state, holder_id, bridge
        waited = float(kwargs.get("wait_time") or 0)
        if waited <= 0:
            waited = 1.0
        await asyncio.sleep(waited)
        return _tool_response(
            json.dumps(
                {"ok": True, "mode": "control", "waited": waited},
                ensure_ascii=False,
                indent=2,
            ),
        )


WAIT_FOR_HANDLER = WaitForHandler()

__all__ = ["WAIT_FOR_HANDLER", "WaitForHandler"]
