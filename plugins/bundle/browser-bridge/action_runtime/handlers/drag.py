# -*- coding: utf-8 -*-
"""Trusted Canonical drag handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..interactions import canonical_native_interaction_control
from ..state import ControlState
from .protocol import ActionMeta


@dataclass(frozen=True)
class DragHandler:
    meta: ActionMeta = ActionMeta(True, True, True)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        return await canonical_native_interaction_control(
            state,
            holder_id=holder_id,
            bridge=bridge,
            action="drag",
            target_labels=("source", "destination"),
            kwargs=kwargs,
        )


DRAG_HANDLER = DragHandler()
__all__ = ["DRAG_HANDLER", "DragHandler"]
