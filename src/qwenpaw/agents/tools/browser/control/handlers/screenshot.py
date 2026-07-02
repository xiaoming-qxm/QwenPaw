# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentscope.message import DataBlock

from ...runtime import _resolve_output_path, _tool_response
from ...runtime import _tool_response_with_blocks
from ..navigation import _control_tab_id
from ..observation import _control_clear_observation_required
from ..session_manager import _control_get_session
from ..snapshot_builder import _url_source
from ..state import ControlState
from ..tab_manager import _control_ensure_tab_available, _control_page_id
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
        screenshot_type = kwargs.get("screenshot_type", "png")
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
        _control_clear_observation_required(state, tab_id)
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(data))
        media_type = "image/jpeg" if screenshot_type == "jpeg" else "image/png"
        payload = {
            "ok": True,
            "mode": "control",
            "message": f"Screenshot saved to {path}",
            "path": path,
        }
        block = DataBlock(
            source=_url_source(output_path.resolve().as_uri(), media_type),
            name=output_path.name,
        )
        return _tool_response_with_blocks(
            json.dumps(payload, ensure_ascii=False, indent=2),
            [block],
        )


SCREENSHOT_HANDLER = ScreenshotHandler()

__all__ = ["SCREENSHOT_HANDLER", "ScreenshotHandler"]
