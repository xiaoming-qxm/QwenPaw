# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..claiming import claim_control_tab
from ..inference import _control_should_infer_user_initiated
from ..state import ControlState
from .protocol import ActionMeta


@dataclass(frozen=True)
class ClaimTabHandler:
    meta: ActionMeta = ActionMeta(False, False, False)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        request_context = kwargs.get("request_context") or {}
        url = str(kwargs.get("url") or "").strip()
        user_initiated = _control_should_infer_user_initiated(
            state=state,
            action="claim_tab",
            url=url,
            holder_id=holder_id,
            request_context=request_context,
            user_initiated=bool(kwargs.get("user_initiated", False)),
        )
        return await claim_control_tab(
            state,
            bridge=bridge,
            holder_id=holder_id,
            request_context=request_context,
            url=url,
            raw_page_id=str(kwargs.get("page_id", "")).strip() or "default",
            index=int(kwargs.get("index", -1)),
            user_initiated=user_initiated,
        )


CLAIM_TAB_HANDLER = ClaimTabHandler()
__all__ = ["CLAIM_TAB_HANDLER", "ClaimTabHandler"]
