# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentscope.message import DataBlock

from qwenpaw.browser.sdk.runtime.responses import (
    _resolve_output_path,
    _tool_response,
)
from qwenpaw.browser.sdk.runtime.responses import _tool_response_with_blocks
from ..navigation import _control_tab_id
from ..coordinates import (
    _control_coordinate_space_payload,
    _control_image_size,
)
from ..observation import (
    _click_effect_check,
    _click_effect_record_snapshot,
    _control_clear_observation_required,
    _control_mark_visual_observation,
)
from ..session_manager import _control_get_session
from ..snapshot_builder import (
    _control_escalation_payload,
    _control_snapshot_hash,
    _url_source,
)
from ..state import ControlState
from ..state_verification import _control_state_verification_payload
from ..tab_manager import _control_ensure_tab_available, _control_page_id
from ..targets import _control_viewport_size
from .protocol import ActionMeta

_CONTROL_SCREENSHOT_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class ScreenshotHandler:
    meta: ActionMeta = ActionMeta(True, False, False)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        request_context = kwargs.get("request_context") or {}
        contract_mode = str(request_context.get("contract_mode") or "LEGACY")
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
            request_context=request_context,
        )
        screenshot_type = kwargs.get("screenshot_type", "png")
        if contract_mode == "CANONICAL":
            return await _capture_canonical_screenshot(
                session,
                state=state,
                tab_id=tab_id,
                scope=(
                    "full_page"
                    if bool(kwargs.get("full_page", False))
                    else "viewport"
                ),
                screenshot_type=screenshot_type,
            )
        path = str(kwargs.get("path") or "").strip()
        if not path:
            ext = "jpeg" if screenshot_type == "jpeg" else "png"
            path = f"page-{int(time.time())}.{ext}"
        path = _resolve_output_path(path)
        try:
            result = await asyncio.wait_for(
                session.send(
                    "Page.captureScreenshot",
                    {
                        "format": screenshot_type,
                        "captureBeyondViewport": bool(
                            kwargs.get("full_page", False),
                        ),
                    },
                ),
                timeout=_CONTROL_SCREENSHOT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            payload = {
                "ok": False,
                "mode": "control",
                "error": (
                    "Screenshot timed out before Chrome returned image data"
                ),
                "needs_observation": True,
            }
            return _tool_response(
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, str) or not data:
            payload = {
                "ok": False,
                "mode": "control",
                "error": "Screenshot failed: CDP returned no image data",
            }
            return _tool_response(
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
        image_bytes = base64.b64decode(data)
        media_type = "image/jpeg" if screenshot_type == "jpeg" else "image/png"
        image_width, image_height = _control_image_size(
            image_bytes,
            media_type=media_type,
        )
        viewport_width, viewport_height = await _control_viewport_size(session)
        visual_hash = _control_snapshot_hash(
            "visual:" + hashlib.md5(image_bytes).hexdigest(),
        )
        escalated, escalation_info = _click_effect_check(
            state,
            tab_id,
            visual_hash,
        )
        _click_effect_record_snapshot(state, tab_id, visual_hash)
        _control_clear_observation_required(state, tab_id)
        _control_mark_visual_observation(state, tab_id, source="screenshot")
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        payload = {
            "ok": True,
            "mode": "control",
            "message": f"Screenshot saved to {path}",
            "path": path,
            "coordinate_space": _control_coordinate_space_payload(
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                screenshot_width=image_width,
                screenshot_height=image_height,
            ),
        }
        if escalated:
            payload["escalation"] = _control_escalation_payload(
                escalation_info,
            )
        if escalation_info.get("verification_pending"):
            network = escalation_info.get("network")
            payload[
                "state_verification"
            ] = _control_state_verification_payload(
                status="stale_view_possible",
                reason="previous_async_state_change_not_reflected_in_snapshot",
                network_metadata=network if isinstance(network, dict) else {},
            )
        block = DataBlock(
            source=_url_source(output_path.resolve().as_uri(), media_type),
            name=output_path.name,
        )
        return _tool_response_with_blocks(
            json.dumps(payload, ensure_ascii=False, indent=2),
            [block],
        )


async def _capture_canonical_screenshot(
    session: Any,
    *,
    state: ControlState,
    tab_id: int,
    scope: str,
    screenshot_type: str,
):
    """Capture exact bytes with controller-owned non-mutation facts."""
    before = await _canonical_screenshot_invariant(session, state)
    try:
        result = await asyncio.wait_for(
            session.send(
                "Page.captureScreenshot",
                {
                    "format": screenshot_type,
                    "captureBeyondViewport": scope == "full_page",
                },
            ),
            timeout=_CONTROL_SCREENSHOT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "mode": "canonical",
                    "error_code": "screenshot_timeout",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    after = await _canonical_screenshot_invariant(session, state)
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, str) or not data:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "mode": "canonical",
                    "error_code": "screenshot_incomplete",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    image_bytes = base64.b64decode(data)
    media_type = "image/jpeg" if screenshot_type == "jpeg" else "image/png"
    width, height = _control_image_size(image_bytes, media_type=media_type)
    return _tool_response(
        json.dumps(
            {
                "ok": True,
                "mode": "canonical",
                "tab_id": tab_id,
                "scope": scope,
                "image_base64": data,
                "media_type": media_type,
                "name": f"browser-{scope}.{screenshot_type}",
                "width": width,
                "height": height,
                "complete": True,
                "before": before,
                "after": after,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _canonical_screenshot_invariant(
    session: Any,
    state: ControlState,
) -> dict[str, Any]:
    frame_tree = await session.send("Page.getFrameTree")
    tree = (
        frame_tree.get("frameTree") if isinstance(frame_tree, dict) else None
    )
    frame = tree.get("frame") if isinstance(tree, dict) else None
    generation = (
        str(frame.get("loaderId") or "") if isinstance(frame, dict) else ""
    )
    runtime = await session.send(
        "Runtime.evaluate",
        {
            "expression": (
                "({x:Number(window.scrollX||0),y:Number(window.scrollY||0),"
                "dpr:Number(window.devicePixelRatio||1),"
                "focusedBackendNode:null})"
            ),
            "returnByValue": True,
            "awaitPromise": False,
        },
    )
    result = runtime.get("result") if isinstance(runtime, dict) else None
    value = result.get("value") if isinstance(result, dict) else None
    if not isinstance(value, dict):
        value = {}
    focused_backend_node = None
    try:
        focused = await session.send(
            "Runtime.evaluate",
            {
                "expression": "document.activeElement || null",
                "returnByValue": False,
                "awaitPromise": False,
            },
        )
        focused_result = (
            focused.get("result") if isinstance(focused, dict) else None
        )
        object_id = (
            focused_result.get("objectId")
            if isinstance(focused_result, dict)
            else None
        )
        if object_id:
            requested = await session.send(
                "DOM.requestNode",
                {"objectId": object_id},
            )
            node_id = (
                requested.get("nodeId")
                if isinstance(requested, dict)
                else None
            )
            if isinstance(node_id, int) and node_id > 0:
                described = await session.send(
                    "DOM.describeNode",
                    {"nodeId": node_id, "depth": 0},
                )
                node = (
                    described.get("node")
                    if isinstance(described, dict)
                    else None
                )
                candidate = (
                    node.get("backendNodeId")
                    if isinstance(node, dict)
                    else None
                )
                if isinstance(candidate, int):
                    focused_backend_node = candidate
    except (RuntimeError, OSError, TypeError, ValueError):
        focused_backend_node = None
    metrics = await session.send("Page.getLayoutMetrics")
    visual = (
        metrics.get("cssVisualViewport") if isinstance(metrics, dict) else None
    )
    content = (
        metrics.get("cssContentSize") if isinstance(metrics, dict) else None
    )
    if not isinstance(visual, dict):
        visual = {}
    if not isinstance(content, dict):
        content = {}
    network_events = state.get("control_network_events")
    watermark = len(network_events) if isinstance(network_events, list) else 0
    return {
        "generation": generation,
        "scroll_offset": [
            float(value.get("x") or 0),
            float(value.get("y") or 0),
        ],
        "focused_backend_node": focused_backend_node,
        "viewport": [
            int(visual.get("clientWidth") or visual.get("width") or 0),
            int(visual.get("clientHeight") or visual.get("height") or 0),
        ],
        "layout": [
            int(content.get("width") or 0),
            int(content.get("height") or 0),
        ],
        "event_watermark": watermark,
        "zoom": float(visual.get("scale") or 1.0),
        "device_pixel_ratio": float(value.get("dpr") or 1.0),
    }


SCREENSHOT_HANDLER = ScreenshotHandler()

__all__ = [
    "SCREENSHOT_HANDLER",
    "ScreenshotHandler",
    "_capture_canonical_screenshot",
]
