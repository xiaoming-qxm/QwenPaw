# -*- coding: utf-8 -*-
"""Scroll Browser Bridge action handler."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ..errors import BrowserBridgeRecoverableError
from ..navigation import _control_tab_id
from ..observation import (
    _click_effect_last_snapshot_hash,
    _click_effect_record_click,
    _control_scroll_action_loop_guard,
)
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
            tracking_ref = _scroll_tracking_ref(direction, amount)
            blocked = _control_scroll_action_loop_guard(
                state,
                tab_id,
                tracking_ref,
            )
            if blocked is not None:
                return blocked

            fallback = None
            timed_out = False
            absolute_position = _absolute_scroll_position(direction, amount)
            if absolute_position:
                try:
                    await _scroll_to_absolute(session, absolute_position)
                except Exception:  # noqa: BLE001
                    timed_out = True
                    fallback = await _send_scroll_key_fallback(
                        session,
                        absolute_position,
                    )
                pixels = 0
            else:
                pixels = _scroll_pixels(amount, height)
                delta_x, delta_y = _scroll_delta(direction, pixels)
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
            metrics = await _read_scroll_metrics(session)
            _click_effect_record_click(
                state,
                tab_id,
                tracking_ref,
                _click_effect_last_snapshot_hash(state, tab_id),
            )
            payload = {
                "ok": True,
                "mode": "control",
                "tab_id": tab_id,
                "scrolled": True,
                "direction": direction,
                "amount": amount,
                "pixels": pixels,
                "needs_observation": True,
                "ready_for_observation": True,
                "next_action": "snapshot",
                "next_instruction": (
                    "Observe the page with snapshot before another action. "
                    "If the next snapshot is unchanged, do not repeat the "
                    "same scroll; use a visible ref/text target, an absolute "
                    "top/bottom jump, direct navigation, or report a blocker."
                ),
                **metrics,
            }
            if timed_out:
                payload["wheel_timed_out"] = True
            if fallback:
                payload["fallback"] = fallback
            return _json_response(payload)
        except (BrowserBridgeRecoverableError, asyncio.TimeoutError) as exc:
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
        "top": "Home",
        "bottom": "End",
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
        "Home": 36,
        "End": 35,
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


def _absolute_scroll_position(direction: str, amount: Any) -> str | None:
    raw_amount = str(amount or "").strip().lower()
    raw_direction = str(direction or "").strip().lower()
    if raw_amount in {"top", "start", "home"} or raw_direction == "top":
        return "top"
    if raw_amount in {"bottom", "end"} or raw_direction == "bottom":
        return "bottom"
    return None


def _scroll_delta(direction: str, pixels: int) -> tuple[int, int]:
    if direction == "up":
        return (0, -pixels)
    if direction == "left":
        return (-pixels, 0)
    if direction == "right":
        return (pixels, 0)
    return (0, pixels)


def _scroll_tracking_ref(direction: str, amount: Any) -> str:
    raw_direction = str(direction or "down").strip().lower() or "down"
    if isinstance(amount, (int, float)):
        raw_amount = (
            f"{int(amount)}"
            if float(amount).is_integer()
            else str(
                amount,
            )
        )
    else:
        raw_amount = str(amount or "page").strip().lower() or "page"
    return f"scroll:{raw_direction}:{raw_amount}"


async def _scroll_to_absolute(session: Any, position: str) -> None:
    await _send_with_timeout(
        session,
        "Runtime.evaluate",
        {
            "expression": _absolute_scroll_script(position),
            "returnByValue": True,
            "awaitPromise": False,
            "timeout": 1000,
        },
    )


async def _read_scroll_metrics(session: Any) -> dict[str, Any]:
    try:
        result = await _send_with_timeout(
            session,
            "Runtime.evaluate",
            {
                "expression": _SCROLL_METRICS_SCRIPT,
                "returnByValue": True,
                "awaitPromise": False,
                "timeout": 1000,
            },
            timeout=1.5,
        )
    except Exception:  # noqa: BLE001
        return {}
    value = _runtime_value(result)
    if not isinstance(value, dict):
        return {}
    return {
        "scroll_y": _rounded_number(value.get("scrollY")),
        "max_scroll_y": _rounded_number(value.get("maxScrollY")),
        "scroll_percent": _rounded_number(value.get("scrollPercent")),
        "at_top": bool(value.get("atTop")),
        "at_bottom": bool(value.get("atBottom")),
    }


def _runtime_value(result: dict[str, Any]) -> Any:
    remote_object = result.get("result") if isinstance(result, dict) else None
    if isinstance(remote_object, dict) and "result" in remote_object:
        remote_object = remote_object.get("result")
    if isinstance(remote_object, dict):
        return remote_object.get("value")
    return None


def _rounded_number(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    try:
        return int(round(float(str(value))))
    except (TypeError, ValueError):
        return 0


def _absolute_scroll_script(position: str) -> str:
    target = "maxScrollY" if position == "bottom" else "0"
    return f"""
(() => {{
  const doc = document.scrollingElement
    || document.documentElement
    || document.body;
  const viewportHeight = window.innerHeight || doc.clientHeight || 0;
  const scrollHeight = Math.max(
    doc.scrollHeight || 0,
    document.documentElement ? document.documentElement.scrollHeight || 0 : 0,
    document.body ? document.body.scrollHeight || 0 : 0
  );
  const maxScrollY = Math.max(0, scrollHeight - viewportHeight);
  const y = {target};
  if (doc && typeof doc.scrollTo === "function") {{
    doc.scrollTo({{
      top: y,
      left: doc.scrollLeft || 0,
      behavior: "instant"
    }});
  }}
  window.scrollTo({{
    top: y,
    left: window.scrollX || 0,
    behavior: "instant"
  }});
  return true;
}})()
""".strip()


_SCROLL_METRICS_SCRIPT = """
(() => {
  const doc = document.scrollingElement
    || document.documentElement
    || document.body;
  const viewportHeight = window.innerHeight || doc.clientHeight || 0;
  const scrollHeight = Math.max(
    doc.scrollHeight || 0,
    document.documentElement ? document.documentElement.scrollHeight || 0 : 0,
    document.body ? document.body.scrollHeight || 0 : 0
  );
  const scrollY = window.scrollY || doc.scrollTop || 0;
  const maxScrollY = Math.max(0, scrollHeight - viewportHeight);
  const scrollPercent = maxScrollY > 0
    ? Math.round((scrollY / maxScrollY) * 100)
    : 0;
  return {
    scrollY: Math.round(scrollY),
    maxScrollY: Math.round(maxScrollY),
    scrollPercent,
    atTop: scrollY <= 2,
    atBottom: maxScrollY <= 2 || scrollY >= maxScrollY - 2,
  };
})()
""".strip()


SCROLL_HANDLER = ScrollHandler()
__all__ = ["SCROLL_HANDLER", "ScrollHandler"]
