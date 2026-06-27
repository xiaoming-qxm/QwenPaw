# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..claiming import claim_control_tab
from ..inference import _control_should_infer_user_initiated
from ..navigation import _control_page_id_is_tab_id
from ..state import ControlState
from .navigate import NAVIGATE_HANDLER, _json_response
from .protocol import ActionMeta


@dataclass(frozen=True)
class OpenHandler:
    meta: ActionMeta = ActionMeta(False, False, True)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        url = str(kwargs.get("url") or "").strip()
        if not url:
            return _json_response(
                {"ok": False, "mode": "control", "error": "url required for open"},
            )
        raw_page_id = str(kwargs.get("page_id") or "").strip()
        if _control_page_id_is_tab_id(raw_page_id) or kwargs.get("index", -1) >= 0:
            return await NAVIGATE_HANDLER.execute(
                state, holder_id=holder_id, bridge=bridge, **kwargs
            )
        request_context = kwargs.get("request_context") or {}
        user_initiated = _control_should_infer_user_initiated(
            state=state,
            action="open",
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
            raw_page_id=raw_page_id or "default",
            index=int(kwargs.get("index", -1)),
            user_initiated=user_initiated,
        )


OPEN_HANDLER = OpenHandler()
__all__ = ["OPEN_HANDLER", "OpenHandler"]
