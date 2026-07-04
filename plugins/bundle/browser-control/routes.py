# -*- coding: utf-8 -*-
"""Native Messaging bridge router for Chrome browser control mode."""

from __future__ import annotations

import json
import secrets
import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.responses import JSONResponse

from qwenpaw.browser.connection_manager import get_bridge_connection_manager
from qwenpaw.browser.nm_bridge_state import get_nm_bridge_route_state
from qwenpaw.browser_sdk import Browser
from qwenpaw.browser_sdk.trace import get_browser_trace_store
from qwenpaw.browser_sdk.types import (
    BrowserBackendDiagnostic,
    BrowserContext,
    BrowserDiagnosticCheck,
    BrowserDiagnostics,
)

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


async def _sdk_diagnostics_snapshot(context: str) -> BrowserDiagnostics:
    requested = context if context in {"auto", "user", "isolated"} else "auto"
    return await Browser.diagnostics(context=cast(BrowserContext, requested))


def _serialize_diagnostics(diagnostics: BrowserDiagnostics) -> dict[str, Any]:
    return {
        "requested_context": diagnostics.requested_context,
        "selected_backend_id": diagnostics.selected_backend_id,
        "backends": [
            _serialize_backend_diagnostic(item)
            for item in diagnostics.backends
        ],
    }


def _serialize_backend_diagnostic(
    diagnostic: BrowserBackendDiagnostic,
) -> dict[str, Any]:
    return {
        "backend_id": diagnostic.backend_id,
        "browser_context": diagnostic.browser_context,
        "available": diagnostic.available,
        "status": diagnostic.status,
        "code": diagnostic.code,
        "reason": diagnostic.reason,
        "message": diagnostic.message,
        "hint_key": diagnostic.hint_key,
        "message_fallback": diagnostic.message_fallback,
        "checks": [
            _serialize_diagnostic_check(check) for check in diagnostic.checks
        ],
        "observed_at": diagnostic.observed_at,
        "features": sorted(diagnostic.features),
        "metadata": dict(diagnostic.metadata),
    }


def _serialize_diagnostic_check(
    check: BrowserDiagnosticCheck,
) -> dict[str, Any]:
    return {
        "name": check.name,
        "status": check.status,
        "code": check.code,
        "message": check.message,
        "hint_key": check.hint_key,
        "metadata": dict(check.metadata),
    }


async def get_extension_status() -> dict[str, Any]:
    bridge = _default_bridge()
    connected = _bridge_state.connected is not None
    if bridge is not None and hasattr(bridge, "is_connected"):
        connected = connected or bool(bridge.is_connected())
    diagnostics = await _sdk_diagnostics_snapshot("user")

    return {
        **extension_install_status(),
        "connected": connected,
        "version": None,
        "connected_since": (
            _bridge_state.connected_since.isoformat()
            if connected and _bridge_state.connected_since is not None
            else None
        ),
        "sdk_diagnostics": _serialize_diagnostics(diagnostics),
    }


@api_router.get("/status")
async def extension_status() -> dict[str, Any]:
    return await get_extension_status()


@api_router.get("/traces")
async def extension_traces(
    session_id: str = "",
    limit: int = Query(default=100, ge=0, le=1000),
) -> dict[str, Any]:
    events = get_browser_trace_store().list(
        session_id=session_id or None,
        limit=limit,
    )
    return {
        "session_id": session_id,
        "limit": limit,
        "events": [event.to_dict() for event in events],
    }


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
    status = await get_extension_status()
    return {**result, **status}


@api_router.post("/open-chrome-extensions")
async def open_chrome_extensions() -> OpenChromeExtensionsResponse:
    return OpenChromeExtensionsResponse(**open_chrome_extensions_page())
