# -*- coding: utf-8 -*-
"""Hover Chrome action handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ChromeRecoverableError
from ..interactions import canonical_native_interaction_control
from ..state import ControlState
from .navigate import _json_response
from .protocol import ActionMeta


@dataclass(frozen=True)
class HoverHandler:
    meta: ActionMeta = ActionMeta(True, False, True)

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
                action="hover",
                target_labels=("target",),
                kwargs=kwargs,
            )
        except (ChromeRecoverableError, ValueError, TypeError) as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


HOVER_HANDLER = HoverHandler()
__all__ = ["HOVER_HANDLER", "HoverHandler"]
