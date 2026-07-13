# -*- coding: utf-8 -*-
"""Trusted Canonical checked-state ensure handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..interactions import (
    _canonical_set_checked_decision,
    _json_response,
    canonical_interaction_control,
)
from ..state import ControlState
from .protocol import ActionMeta


@dataclass(frozen=True)
class SetCheckedHandler:
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
        requested = kwargs.get("checked")
        current = kwargs.get("_canonical_checked_state")
        if isinstance(current, bool) and isinstance(requested, bool):
            decision = await _canonical_set_checked_decision(
                current=current,
                requested=requested,
            )
            if decision == "ALREADY_SATISFIED":
                return _json_response(
                    {
                        "ok": True,
                        "action": "set_checked",
                        "already_satisfied": True,
                        "condition_truth": "NOT_EVALUATED",
                    },
                )
        return await canonical_interaction_control(
            state,
            action="set_checked",
            target_labels=("target",),
            kwargs=kwargs,
        )


SET_CHECKED_HANDLER = SetCheckedHandler()
__all__ = ["SET_CHECKED_HANDLER", "SetCheckedHandler"]
