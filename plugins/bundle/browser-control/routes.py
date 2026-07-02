# -*- coding: utf-8 -*-
"""Native Messaging bridge router for Chrome browser control mode."""

from __future__ import annotations

import json
import secrets
import contextlib
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.responses import JSONResponse

from qwenpaw.browser.connection_manager import get_bridge_connection_manager
from qwenpaw.browser.nm_bridge_state import get_nm_bridge_route_state

from .extension_setup import (
    extension_install_status,
    open_chrome_extensions_page,
    resolve_default_ws_url,
    setup_extension_files,
)

ws_router = APIRouter(tags=["nm-bridge"])
api_router = APIRouter(tags=["nm-bridge"])
router = api_router

DEFAULT_CONFIG_PATH = Path.home() / ".qwenpaw" / "nm-bridge.json"

_bridge_state = get_nm_bridge_route_state()
if not _bridge_state.ws_url:
    _bridge_state.ws_url = resolve_default_ws_url()
if _bridge_state.config_path is None:
    _bridge_state.config_path = DEFAULT_CONFIG_PATH


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
    ws_url: str | None = None
    reset: bool = False


class OpenChromeExtensionsResponse(BaseModel):
    opened: bool
    url: str
    error: str | None = None


def configure_nm_bridge(
    *,
    token: str | None = None,
    ws_url: str | None = None,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> str:
    """Configure NM bridge auth and write the host-side config file."""
    ws_url = ws_url or resolve_default_ws_url()
    config_path = Path(config_path)
    token = token or _read_existing_token(config_path)
    token = token or secrets.token_urlsafe(32)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"ws_url": ws_url, "token": token}, indent=2),
        encoding="utf-8",
    )
    config_path.chmod(0o600)

    _bridge_state.token = token
    _bridge_state.ws_url = ws_url
    _bridge_state.config_path = config_path
    return token


def _expected_token() -> str:
    if _bridge_state.token is None:
        return configure_nm_bridge()
    return _bridge_state.token


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
    bridge = get_bridge_connection_manager()
    if bridge is not None:
        return bridge

    bridge = getattr(websocket.app.state, "nm_bridge", None)
    if bridge is not None:
        return bridge

    try:
        from .nm_bridge import get_nm_bridge
    except ImportError:
        return None
    return get_nm_bridge()


def _default_bridge() -> Any | None:
    bridge = get_bridge_connection_manager()
    if bridge is not None:
        return bridge

    try:
        from .nm_bridge import get_nm_bridge
    except ImportError:
        return None
    return get_nm_bridge()


async def _drop_connected_websocket(bridge: Any | None) -> None:
    websocket = _bridge_state.connected
    if websocket is None:
        return

    if bridge is not None and hasattr(bridge, "detach_websocket"):
        await bridge.detach_websocket(websocket)

    with contextlib.suppress(Exception):
        await websocket.close(code=1000)

    if _bridge_state.connected is websocket:
        _bridge_state.connected = None
        _bridge_state.connected_since = None


async def shutdown_nm_bridge() -> None:
    """Close the active native bridge connection before plugin unload."""
    bridge = _default_bridge()
    await _drop_connected_websocket(bridge)
    try:
        from .nm_bridge import shutdown_nm_bridge as shutdown_global_bridge
    except ImportError:
        return
    await shutdown_global_bridge()


@ws_router.on_event("startup")
async def startup_nm_bridge() -> None:
    _expected_token()


@ws_router.websocket("/nm-bridge")
async def nm_bridge_ws(websocket: WebSocket) -> None:
    """Accept the Native Messaging host WebSocket connection."""
    if _request_token(websocket) != _expected_token():
        await _deny(websocket, 401, "Invalid Native Messaging bridge token")
        return

    bridge = _resolve_bridge(websocket)
    if _bridge_state.connected is not None:
        await _drop_connected_websocket(bridge)

    await websocket.accept()
    _bridge_state.connected = websocket
    _bridge_state.connected_since = datetime.now(UTC)

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
        if _bridge_state.connected is websocket:
            _bridge_state.connected = None
            _bridge_state.connected_since = None


@ws_router.websocket("/browser-sdk")
async def browser_sdk_ws(websocket: WebSocket) -> None:
    """Accept Browser SDK client connections from REPL subprocesses."""
    if _request_token(websocket) != _expected_token():
        await _deny(websocket, 401, "Invalid Browser SDK bridge token")
        return

    bridge = _resolve_bridge(websocket)
    await websocket.accept()
    ws_send_lock = _AsyncSendLock()
    handlers = _register_sdk_event_forwarders(
        bridge,
        websocket,
        ws_send_lock,
    )
    try:
        while True:
            message = await websocket.receive_json()
            response = await _handle_sdk_ws_message(bridge, message)
            if response is not None:
                await ws_send_lock.send_json(websocket, response)
    except WebSocketDisconnect:
        pass
    finally:
        _remove_sdk_event_forwarders(bridge, handlers)


class _AsyncSendLock:
    """Serialize Starlette websocket writes from requests and events."""

    def __init__(self) -> None:
        import asyncio

        self._lock = asyncio.Lock()

    async def send_json(self, websocket: WebSocket, payload: dict) -> None:
        async with self._lock:
            await websocket.send_json(payload)


def _register_sdk_event_forwarders(
    bridge: Any | None,
    websocket: WebSocket,
    send_lock: _AsyncSendLock,
) -> list[tuple[str, Any]]:
    add_listener = getattr(bridge, "add_event_listener", None)
    if not callable(add_listener):
        return []

    handlers: list[tuple[str, Any]] = []

    def make_handler(method: str):
        async def handler(event: dict[str, Any]) -> None:
            await send_lock.send_json(
                websocket,
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": event,
                },
            )

        return handler

    for method in ("cdp.event", "runtime.event", "tab.updated"):
        handler = make_handler(method)
        add_listener(method, handler)
        handlers.append((method, handler))
    return handlers


def _remove_sdk_event_forwarders(
    bridge: Any | None,
    handlers: list[tuple[str, Any]],
) -> None:
    remove_listener = getattr(bridge, "remove_event_listener", None)
    if not callable(remove_listener):
        return
    for method, handler in handlers:
        with contextlib.suppress(Exception):
            remove_listener(method, handler)


async def _handle_sdk_ws_message(
    bridge: Any | None,
    message: dict[str, Any],
) -> dict[str, Any] | None:
    if message.get("type") == "hello":
        return {
            "type": "hello_ack",
            "status": "ok",
            "protocolVersion": int(message.get("protocolVersion") or 1),
        }

    request_id = message.get("id")
    if request_id is None:
        return None
    try:
        result = await _execute_sdk_bridge_method(
            bridge,
            str(message.get("method") or ""),
            message.get("params")
            if isinstance(message.get("params"), dict)
            else {},
        )
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:  # noqa: BLE001
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


async def _execute_sdk_bridge_method(
    bridge: Any | None,
    method: str,
    params: dict[str, Any],
) -> Any:
    if bridge is None or not bool(getattr(bridge, "connected", False)):
        raise RuntimeError("Chrome extension bridge is not connected")

    if method == "bridge.discover_tabs":
        return await bridge.discover_tabs()
    if method == "bridge.claim_tab":
        tab_id = int(params.get("tab_id") or 0)
        holder_id = str(params.get("holder_id") or "")
        ok = await bridge.claim_tab(tab_id, holder_id)
        version = None
        lease_version = getattr(bridge, "lease_version", None)
        if callable(lease_version):
            version = lease_version(tab_id, holder_id)
        return {"ok": bool(ok), "version": version}
    if method == "bridge.renew_lease":
        lease = await bridge.renew_lease(
            int(params.get("tab_id") or 0),
            str(params.get("holder_id") or ""),
            int(params.get("version") or 0),
        )
        return {
            "tab_id": getattr(lease, "tab_id", None),
            "holder_id": getattr(lease, "holder_id", None),
            "version": getattr(lease, "version", None),
            "expires_at": getattr(lease, "expires_at", None),
        }
    if method == "bridge.release":
        await bridge.release(
            int(params.get("tab_id") or 0),
            str(params.get("holder_id") or ""),
        )
        return {"ok": True}
    if method == "bridge.release_all":
        holder_id = params.get("holder_id")
        await bridge.release_all(None if holder_id is None else str(holder_id))
        return {"ok": True}
    if method == "bridge.request":
        request_method = str(params.get("method") or "")
        request_params = params.get("params")
        response = await bridge.request(
            request_method,
            request_params if isinstance(request_params, dict) else {},
            timeout=float(params.get("timeout") or 30.0),
        )
        if inspect.isawaitable(response):
            response = await response
        return response

    raise ValueError(f"Unsupported Browser SDK bridge method: {method}")


def get_extension_status() -> dict[str, Any]:
    bridge = _default_bridge()
    connected = _bridge_state.connected is not None
    if bridge is not None and hasattr(bridge, "is_connected"):
        connected = connected or bool(bridge.is_connected())

    return {
        **extension_install_status(),
        "connected": connected,
        "version": None,
        "connected_since": (
            _bridge_state.connected_since.isoformat()
            if connected and _bridge_state.connected_since is not None
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
