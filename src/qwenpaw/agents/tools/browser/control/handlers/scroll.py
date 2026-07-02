# -*- coding: utf-8 -*-
"""Scroll Browser Control action handler."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ..errors import BrowserControlRecoverableError
from ..navigation import _control_tab_id
from ..session_manager import _control_get_session
from ..state import ControlState
from ..tab_manager import _control_ensure_tab_available, _control_page_id
from ..targets import _control_viewport_size
from .navigate import _json_response
from .protocol import ActionMeta


@dataclass(frozen=True)
class ScrollHandler:
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
            width, height = await _control_viewport_size(session)
            width = width if width > 0 else 800.0
            height = height if height > 0 else 600.0
            direction = str(kwargs.get("direction") or "down").strip().lower()
            amount = kwargs.get("amount") or "page"
            pixels = _scroll_pixels(amount, height)
            delta_x, delta_y = _scroll_delta(direction, pixels)
            fallback = None
            timed_out = False
            try:
                await _send_with_timeout(
                    session,
                    "Input.dispatchMouseEvent",
                    {
                        "type": "mouseWheel",
                        "x": width / 2,
                        "y": height / 2,
                        "deltaX": delta_x,
                        "deltaY": delta_y,
                    },
                )
            except asyncio.TimeoutError:
                timed_out = True
                fallback = await _send_scroll_key_fallback(
                    session,
                    direction,
                )
            await asyncio.sleep(0.3)
            payload = {
                "ok": True,
                "mode": "control",
                "tab_id": tab_id,
                "scrolled": True,
                "direction": direction,
                "amount": amount,
                "pixels": pixels,
            }
            if timed_out:
                payload["wheel_timed_out"] = True
            if fallback:
                payload["fallback"] = fallback
            return _json_response(payload)
        except (BrowserControlRecoverableError, asyncio.TimeoutError) as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


async def _send_with_timeout(
    session: Any,
    method: str,
    params: dict[str, Any],
    timeout: float = 3.0,
) -> dict[str, Any]:
    return await asyncio.wait_for(
        session.send(method, params),
        timeout=timeout,
    )


async def _send_scroll_key_fallback(
    session: Any,
    direction: str,
) -> str:
    key = {
        "up": "PageUp",
        "left": "ArrowLeft",
        "right": "ArrowRight",
    }.get(direction, "PageDown")
    params = _key_event_params(key)
    await _send_with_timeout(
        session,
        "Input.dispatchKeyEvent",
        {**params, "type": "rawKeyDown"},
    )
    await _send_with_timeout(
        session,
        "Input.dispatchKeyEvent",
        {**params, "type": "keyUp"},
    )
    return key


def _key_event_params(key: str) -> dict[str, Any]:
    virtual_key = {
        "PageUp": 33,
        "PageDown": 34,
        "ArrowLeft": 37,
        "ArrowRight": 39,
    }[key]
    return {
        "key": key,
        "code": key,
        "windowsVirtualKeyCode": virtual_key,
        "nativeVirtualKeyCode": virtual_key,
    }


def _scroll_pixels(amount: Any, viewport_height: float) -> int:
    if isinstance(amount, (int, float)):
        return max(int(abs(amount)), 1)
    raw = str(amount or "page").strip().lower()
    if raw.isdigit():
        return max(int(raw), 1)
    if raw in {"line", "small"}:
        return 120
    if raw in {"half", "half_page"}:
        return max(int(viewport_height / 2), 1)
    return max(int(viewport_height), 1)


def _scroll_delta(direction: str, pixels: int) -> tuple[int, int]:
    if direction == "up":
        return (0, -pixels)
    if direction == "left":
        return (-pixels, 0)
    if direction == "right":
        return (pixels, 0)
    return (0, pixels)


SCROLL_HANDLER = ScrollHandler()
__all__ = ["SCROLL_HANDLER", "ScrollHandler"]
