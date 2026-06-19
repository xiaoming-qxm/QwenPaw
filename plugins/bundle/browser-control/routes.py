# -*- coding: utf-8 -*-
"""Native Messaging bridge router for Chrome browser control mode."""

from __future__ import annotations

import json
import secrets
import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.responses import JSONResponse

from .extension_setup import (
    DEFAULT_WS_URL,
    extension_install_status,
    open_chrome_extensions_page,
    setup_extension_files,
)

ws_router = APIRouter(tags=["nm-bridge"])
api_router = APIRouter(tags=["nm-bridge"])
router = api_router

DEFAULT_CONFIG_PATH = Path.home() / ".qwenpaw" / "nm-bridge.json"

_bridge_token: str | None = None
_bridge_ws_url: str = DEFAULT_WS_URL
_bridge_config_path: Path = DEFAULT_CONFIG_PATH
_connected: WebSocket | None = None
_connected_since: datetime | None = None


def _read_existing_token(config_path: Path) -> str | None:
    if not config_path.exists():
        return None
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = str(raw.get("token") or "").strip()
    return token or None


class ExtensionSetupRequest(BaseModel):
    install_mode: str = Field(default="unpacked", pattern="^(unpacked|cws)$")
    ws_url: str = DEFAULT_WS_URL
    reset: bool = False


class OpenChromeExtensionsResponse(BaseModel):
    opened: bool
    url: str
    error: str | None = None


def configure_nm_bridge(
    *,
    token: str | None = None,
    ws_url: str = DEFAULT_WS_URL,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> str:
    """Configure NM bridge auth and write the host-side config file."""
    global _bridge_token, _bridge_ws_url, _bridge_config_path

    config_path = Path(config_path)
    token = token or _read_existing_token(config_path)
    token = token or secrets.token_urlsafe(32)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"ws_url": ws_url, "token": token}, indent=2),
        encoding="utf-8",
    )
    config_path.chmod(0o600)

    _bridge_token = token
    _bridge_ws_url = ws_url
    _bridge_config_path = config_path
    return token


def _expected_token() -> str:
    global _bridge_token
    if _bridge_token is None:
        return configure_nm_bridge()
    return _bridge_token


def _request_token(websocket: WebSocket) -> str:
    header = websocket.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return websocket.query_params.get("token", "").strip()


async def _deny(websocket: WebSocket, status_code: int, detail: str) -> None:
    await websocket.send_denial_response(
        JSONResponse({"detail": detail}, status_code=status_code),
    )


def _resolve_bridge(websocket: WebSocket) -> Any | None:
    bridge = getattr(websocket.app.state, "nm_bridge", None)
    if bridge is not None:
        return bridge

    try:
        from .nm_bridge import get_nm_bridge
    except ImportError:
        return None
    return get_nm_bridge()


def _default_bridge() -> Any | None:
    try:
        from .nm_bridge import get_nm_bridge
    except ImportError:
        return None
    return get_nm_bridge()


async def _drop_connected_websocket(bridge: Any | None) -> None:
    global _connected, _connected_since

    websocket = _connected
    if websocket is None:
        return

    if bridge is not None and hasattr(bridge, "detach_websocket"):
        await bridge.detach_websocket(websocket)

    with contextlib.suppress(Exception):
        await websocket.close(code=1000)

    if _connected is websocket:
        _connected = None
        _connected_since = None


@ws_router.on_event("startup")
async def startup_nm_bridge() -> None:
    _expected_token()


@ws_router.websocket("/nm-bridge")
async def nm_bridge_ws(websocket: WebSocket) -> None:
    """Accept the Native Messaging host WebSocket connection."""
    global _connected, _connected_since

    if _request_token(websocket) != _expected_token():
        await _deny(websocket, 401, "Invalid Native Messaging bridge token")
        return

    bridge = _resolve_bridge(websocket)
    if _connected is not None:
        await _drop_connected_websocket(bridge)

    await websocket.accept()
    _connected = websocket
    _connected_since = datetime.now(UTC)

    if bridge is not None and hasattr(bridge, "attach_websocket"):
        await bridge.attach_websocket(websocket)

    try:
        while True:
            message = await websocket.receive_json()
            if bridge is not None and hasattr(bridge, "handle_ws_message"):
                response = await bridge.handle_ws_message(message)
                if response is not None:
                    await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
    finally:
        if bridge is not None and hasattr(bridge, "detach_websocket"):
            await bridge.detach_websocket(websocket)
        if _connected is websocket:
            _connected = None
            _connected_since = None


def get_extension_status() -> dict[str, Any]:
    bridge = _default_bridge()
    connected = _connected is not None
    if bridge is not None and hasattr(bridge, "is_connected"):
        connected = bool(bridge.is_connected())

    return {
        **extension_install_status(),
        "connected": connected,
        "version": None,
        "connected_since": (
            _connected_since.isoformat()
            if connected and _connected_since is not None
            else None
        ),
    }


@api_router.get("/status")
async def extension_status() -> dict[str, Any]:
    return get_extension_status()


@api_router.post("/setup")
async def extension_setup(request: ExtensionSetupRequest) -> dict[str, Any]:
    result = setup_extension_files(
        install_mode=request.install_mode,
        ws_url=request.ws_url,
        reset=request.reset,
    )
    configure_nm_bridge(
        ws_url=str(result["ws_url"]),
        config_path=str(result["config_path"]),
    )
    return {**result, **get_extension_status()}


@api_router.post("/open-chrome-extensions")
async def open_chrome_extensions() -> OpenChromeExtensionsResponse:
    return OpenChromeExtensionsResponse(**open_chrome_extensions_page())
