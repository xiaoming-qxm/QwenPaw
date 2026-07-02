# -*- coding: utf-8 -*-
"""Hover Browser Control action handler."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ..errors import BrowserControlRecoverableError
from ..navigation import _control_tab_id
from ..session_manager import _control_get_session
from ..state import ControlState
from ..tab_manager import _control_ensure_tab_available, _control_page_id
from ..targets import (
    _control_hover_at,
    _control_resolve_point,
    _control_selector_target,
    _control_snap_to_element,
    _control_text_target,
    _control_viewport_size,
)
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
            tab_id = _control_tab_id(
                _control_page_id(state, str(kwargs.get("page_id", ""))),
                kwargs.get("index", -1),
            )
            await _control_ensure_tab_available(bridge, tab_id)
            session = await _control_get_session(
                state,
                tab_id=tab_id,
                holder_id=holder_id,
                bridge=bridge,
                request_context=kwargs.get("request_context") or {},
            )
            x, y = await _hover_point(state, session, tab_id, kwargs)
            await _control_hover_at(session, x, y, "Hover")
            await asyncio.sleep(0.15)
            return _json_response(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "hovered": True,
                    "x": x,
                    "y": y,
                },
            )
        except (BrowserControlRecoverableError, ValueError, TypeError) as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


async def _hover_point(
    state: ControlState,
    session: Any,
    tab_id: int,
    kwargs: dict[str, Any],
) -> tuple[float, float]:
    ref = str(kwargs.get("ref") or "")
    selector = str(kwargs.get("selector") or "").strip()
    text = str(kwargs.get("text") or "").strip()
    target = state.refs.get(str(tab_id), {}).get(ref, {}) if ref else {}
    if not target and selector:
        target = await _control_selector_target(session, selector)
    if not target and text:
        target = await _control_text_target(session, text)
    x_param, y_param = kwargs.get("x"), kwargs.get("y")
    if (
        not target
        and not any([ref, selector, text])
        and x_param is not None
        and y_param is not None
    ):
        width, height = await _control_viewport_size(session)
        return await _control_snap_to_element(
            session,
            float(x_param),
            float(y_param),
            width,
            height,
        )
    return await _control_resolve_point(
        session,
        target,
        ref=ref or selector or text,
        fallback_x=x_param,
        fallback_y=y_param,
    )


HOVER_HANDLER = HoverHandler()
__all__ = ["HOVER_HANDLER", "HoverHandler"]
