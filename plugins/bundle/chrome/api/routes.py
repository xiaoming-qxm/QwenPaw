# -*- coding: utf-8 -*-
"""Native Messaging bridge router for Chrome browser control mode."""

from __future__ import annotations

import json
import hashlib
import inspect
import secrets
import contextlib
import subprocess
from time import perf_counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from fastapi import (
    APIRouter,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from starlette.responses import JSONResponse

from qwenpaw.browser.backends.registry import get_default_backend_registry
from qwenpaw.browser.governance.error_codes import BrowserErrorCode
from qwenpaw.browser.telemetry.trace import (
    BrowserTraceEvent,
    get_browser_trace_store,
    summarize_browser_tab_ownership,
)
from qwenpaw.browser.primitives.types import (
    BrowserBackendDiagnostic,
    BrowserContext,
    BrowserDiagnosticCheck,
    BrowserDiagnosticStatus,
    BrowserDiagnostics,
)

from ..extension_setup import (  # type: ignore[misc]
    BRIDGE_MANIFEST_SCHEMA_VERSION,
    extension_install_status,
    open_chrome_extensions_page,
    open_extension_folder,
    resolve_default_ws_url,
    setup_extension_files,
)
from ..transport.state import get_nm_bridge_route_state  # type: ignore[misc]

ws_router = APIRouter(tags=["chrome"])
api_router = APIRouter(tags=["chrome"])
router = api_router

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[2]
DEFAULT_CONFIG_PATH = Path.home() / ".qwenpaw" / "nm-bridge.json"
CANONICAL_SETUP_URL = "/plugin/chrome"
EXTENSION_MANIFEST_PATH = (
    PLUGIN_ROOT
    / "assets"
    / "extensions"
    / "chrome"
    / "manifest.json"
)

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


class OpenExtensionFolderResponse(BaseModel):
    opened: bool
    path: str
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
    bridge = getattr(websocket.app.state, "nm_bridge", None)
    if bridge is not None:
        return bridge

    try:
        from ..transport.native_messaging import (  # type: ignore[misc]
            get_nm_bridge,
        )
    except ImportError:
        return None
    return get_nm_bridge()


def _default_bridge() -> Any | None:
    try:
        from ..transport.native_messaging import (  # type: ignore[misc]
            get_nm_bridge,
        )
    except ImportError:
        return None
    return get_nm_bridge()


async def _drop_connected_websocket(
    bridge: Any | None,
    *,
    reason: str = "replaced",
) -> None:
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
        _bridge_state.last_disconnected_at = datetime.now(UTC)
        _bridge_state.last_disconnect_reason = reason
        _bridge_state.last_error_code = str(
            BrowserErrorCode.BRIDGE_DISCONNECTED,
        )
        _bridge_state.last_error_message = "NM bridge disconnected"


async def shutdown_nm_bridge() -> None:
    """Close the active native bridge connection before plugin unload."""
    bridge = _default_bridge()
    await _drop_connected_websocket(bridge, reason="shutdown")
    try:
        from ..transport.native_messaging import (  # type: ignore[misc]
            shutdown_nm_bridge as shutdown_global_bridge,
        )
    except ImportError:
        return
    await shutdown_global_bridge()


@ws_router.on_event("startup")
async def startup_nm_bridge() -> None:
    _expected_token()


@ws_router.websocket("/chrome")
async def nm_bridge_ws(websocket: WebSocket) -> None:
    """Accept the Native Messaging host WebSocket connection."""
    if _request_token(websocket) != _expected_token():
        await _deny(websocket, 401, "Invalid Native Messaging bridge token")
        return

    bridge = _resolve_bridge(websocket)
    if _bridge_state.connected is not None:
        await _drop_connected_websocket(bridge, reason="replaced")

    await websocket.accept()
    now = datetime.now(UTC)
    if _bridge_state.last_connected_at is not None:
        _bridge_state.reconnect_count += 1
    _bridge_state.connected = websocket
    _bridge_state.connected_since = now
    _bridge_state.last_connected_at = now

    if bridge is not None and hasattr(bridge, "attach_websocket"):
        await bridge.attach_websocket(websocket)

    try:
        while True:
            message = await websocket.receive_json()
            _observe_bridge_message(message)
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
            _bridge_state.last_disconnected_at = datetime.now(UTC)
            _bridge_state.last_disconnect_reason = "websocket_disconnect"
            _bridge_state.last_error_code = str(
                BrowserErrorCode.BRIDGE_DISCONNECTED,
            )
            _bridge_state.last_error_message = "NM bridge disconnected"


def _observe_bridge_message(message: dict[str, Any]) -> None:
    if message.get("type") == "hello":
        _store_extension_version(message)
        return

    method = str(message.get("method") or "")
    params = message.get("params")
    payload = params if isinstance(params, dict) else {}
    if method == "bridge.connected":
        _store_extension_version(payload)
        return
    if method == "bridge.disconnected":
        _bridge_state.last_disconnected_at = datetime.now(UTC)
        _bridge_state.last_disconnect_reason = str(
            payload.get("reason") or "",
        )
        _bridge_state.last_error_code = str(
            BrowserErrorCode.BRIDGE_DISCONNECTED,
        )
        _bridge_state.last_error_message = "NM bridge disconnected"


def _store_extension_version(payload: dict[str, Any]) -> None:
    version = (
        payload.get("extension_version")
        or payload.get("extensionVersion")
        or payload.get("version")
    )
    version_text = str(version or "").strip()
    if version_text:
        _bridge_state.extension_version = version_text


async def _sdk_diagnostics_snapshot(context: str) -> BrowserDiagnostics:
    requested = context if context in {"auto", "user", "isolated"} else "auto"
    normalized = cast(BrowserContext, requested)
    diagnostic_items = []
    for backend in get_default_backend_registry().all():
        diagnostic_items.append(await _backend_diagnostic(backend))
    diagnostics = tuple(diagnostic_items)
    selected = _select_diagnostic_backend(normalized, diagnostics)
    return BrowserDiagnostics(
        requested_context=normalized,
        selected_backend_id=selected,
        backends=diagnostics,
    )


async def _backend_diagnostic(backend: Any) -> BrowserBackendDiagnostic:
    diagnose = getattr(backend, "diagnose", None)
    if callable(diagnose):
        raw = diagnose()
        if inspect.isawaitable(raw):
            raw = await raw
        if isinstance(raw, BrowserBackendDiagnostic):
            return raw
    capabilities = backend.capabilities()
    try:
        available = bool(backend.is_available())
        code = "" if available else "browser_backend_unavailable"
        message = "Available" if available else "Unavailable"
    except Exception as exc:  # noqa: BLE001 - diagnostic must stay available
        available = False
        code = type(exc).__name__
        message = str(exc)
    status: BrowserDiagnosticStatus = (
        "available" if available else "unavailable"
    )
    return BrowserBackendDiagnostic(
        backend_id=capabilities.backend_id,
        browser_context=capabilities.browser_context,
        available=available,
        status=status,
        code=code,
        reason="" if available else message,
        message=message,
        message_fallback=message,
        features=capabilities.features,
    )


def _select_diagnostic_backend(
    requested: BrowserContext,
    diagnostics: tuple[BrowserBackendDiagnostic, ...],
) -> str:
    contexts = ("user", "isolated") if requested == "auto" else (requested,)
    for browser_context in contexts:
        for diagnostic in diagnostics:
            if (
                diagnostic.browser_context == browser_context
                and diagnostic.available
            ):
                return diagnostic.backend_id
    return ""


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
        "reason": _sanitize_text(diagnostic.reason),
        "message": _sanitize_text(diagnostic.message),
        "hint_key": diagnostic.hint_key,
        "message_fallback": _sanitize_text(diagnostic.message_fallback),
        "checks": [
            _serialize_diagnostic_check(check) for check in diagnostic.checks
        ],
        "observed_at": diagnostic.observed_at,
        "features": sorted(diagnostic.features),
        "metadata": _sanitize_json_value(dict(diagnostic.metadata)),
    }


def _serialize_diagnostic_check(
    check: BrowserDiagnosticCheck,
) -> dict[str, Any]:
    return {
        "name": check.name,
        "status": check.status,
        "code": check.code,
        "message": _sanitize_text(check.message),
        "hint_key": check.hint_key,
        "metadata": _sanitize_json_value(dict(check.metadata)),
    }


def _sanitize_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    blocked = ("authorization", "bearer ", "token", "traceback")
    lines = [
        line
        for line in text.splitlines()
        if not any(marker in line.lower() for marker in blocked)
    ]
    if lines:
        return "\n".join(lines)
    return "Diagnostic detail redacted."


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_json_value(item)
            for key, item in value.items()
            if not _is_sensitive_key(str(key))
        }
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        marker in lowered
        for marker in (
            "authorization",
            "cookie",
            "credential",
            "password",
            "secret",
            "token",
        )
    )


def _bridge_connected() -> bool:
    bridge = _default_bridge()
    connected = _bridge_state.connected is not None
    if bridge is not None and hasattr(bridge, "is_connected"):
        connected = connected or bool(bridge.is_connected())
    return connected


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _extension_version() -> str:
    if _bridge_state.extension_version:
        return _bridge_state.extension_version
    try:
        raw = json.loads(EXTENSION_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(raw.get("version") or "")


def _bridge_lifecycle(connected: bool) -> dict[str, Any]:
    return {
        "connected": connected,
        "connected_since": (
            _iso_or_none(_bridge_state.connected_since) if connected else None
        ),
        "last_connected_at": _iso_or_none(_bridge_state.last_connected_at),
        "last_disconnected_at": _iso_or_none(
            _bridge_state.last_disconnected_at,
        ),
        "last_disconnect_reason": _bridge_state.last_disconnect_reason,
        "last_error_code": _bridge_state.last_error_code,
        "last_error_message": _bridge_state.last_error_message,
        "last_request_timeout_at": _iso_or_none(
            _bridge_state.last_request_timeout_at,
        ),
        "reconnect_count": _bridge_state.reconnect_count,
    }


def _trace_summary() -> dict[str, Any]:
    events = get_browser_trace_store().list()
    latest = events[-1] if events else None
    latest_cleanup = next(
        (event for event in reversed(events) if event.phase == "cleanup"),
        None,
    )
    lifecycle = _lifecycle_tab_summary(events, latest_cleanup)
    return {
        "event_count": len(events),
        "session_count": len({event.session_id for event in events}),
        "ownership_summary": summarize_browser_tab_ownership(events),
        "lifecycle": lifecycle,
        "latest_event": (
            {
                "event_id": latest.event_id,
                "session_id": latest.session_id,
                "phase": latest.phase,
                "action": latest.action,
                "status": latest.status,
                "backend_id": latest.backend_id,
                "domain": latest.domain,
            }
            if latest is not None
            else None
        ),
        "latest_cleanup": _cleanup_trace_summary(latest_cleanup),
    }


def _lifecycle_tab_summary(
    events: tuple[BrowserTraceEvent, ...],
    latest_cleanup: BrowserTraceEvent | None,
) -> dict[str, Any]:
    ownership = summarize_browser_tab_ownership(events)
    counts = ownership.get("counts") or {}
    cleanup_metadata = (
        latest_cleanup.to_dict().get("metadata", {})
        if latest_cleanup is not None
        else {}
    )
    if not isinstance(cleanup_metadata, dict):
        cleanup_metadata = {}
    controlled = int(counts.get("owned") or 0) + int(
        counts.get("borrowed") or 0,
    )
    residual = int(cleanup_metadata.get("remaining_orphaned_tabs") or 0)
    residual += int(cleanup_metadata.get("owned_tabs_remaining") or 0)
    protected = int(cleanup_metadata.get("skipped_protected_tabs") or 0)
    protected += int(counts.get("protected") or 0)
    return {
        "controlled_tab_count": controlled,
        "residual_tab_count": residual,
        "last_cleanup_reason": str(
            cleanup_metadata.get("cleanup_reason") or "",
        ),
        "protected_origin_status": "skipped" if protected else "clear",
    }


def _cleanup_trace_summary(
    event: BrowserTraceEvent | None,
) -> dict[str, Any] | None:
    if event is None:
        return None
    metadata = event.to_dict().get("metadata", {})
    return {
        "event_id": event.event_id,
        "session_id": event.session_id,
        "status": event.status,
        "backend_id": event.backend_id,
        "closed_owned_tabs": int(metadata.get("closed_owned_tabs") or 0),
        "released_borrowed_tabs": int(
            metadata.get("released_borrowed_tabs") or 0,
        ),
        "cleanup_reason": str(metadata.get("cleanup_reason") or ""),
        "skipped_protected_tabs": int(
            metadata.get("skipped_protected_tabs") or 0,
        ),
        "remaining_orphaned_tabs": int(
            metadata.get("remaining_orphaned_tabs") or 0,
        ),
        "error_code": str(
            metadata.get("error_code") or event.error_code or "",
        ),
    }


def _build_fingerprint() -> dict[str, Any]:
    return {
        "git_commit": _git_output("rev-parse", "--short", "HEAD"),
        "repo_dirty": bool(_git_output("status", "--short")),
        "frontend_fingerprint": _frontend_fingerprint(),
        "plugin_fingerprint": _plugin_fingerprint(),
    }


def _native_host_status(install_status: dict[str, Any]) -> dict[str, Any]:
    native_host_version = (
        f"chrome-native-host.v{BRIDGE_MANIFEST_SCHEMA_VERSION}"
    )
    if install_status.get("native_host_repair_required"):
        return {
            "status": "repair_required",
            "version": native_host_version,
            "message": _sanitize_text(
                install_status.get("native_host_repair_instruction")
                or "Run qwenpaw setup-extension --yes --reset.",
            ),
            "repair_action": "run_setup",
        }
    return {
        "status": "configured",
        "version": native_host_version,
        "message": "Native Host manifest configuration is current.",
        "repair_action": "none",
    }


def _build_freshness(build: dict[str, Any]) -> dict[str, Any]:
    if build.get("repo_dirty"):
        return {
            "status": "stale",
            "message": "Frontend or backend build has local changes.",
            "repair_action": "rebuild_frontend",
        }
    if (
        not build.get("git_commit")
        or not build.get("frontend_fingerprint")
        or not build.get("plugin_fingerprint")
    ):
        return {
            "status": "unknown",
            "message": "Build freshness could not be determined.",
            "repair_action": "restart_qwenpaw",
        }
    return {
        "status": "fresh",
        "message": "Frontend and backend build fingerprints are current.",
        "repair_action": "none",
    }


def _readiness_state_and_repair_action(
    *,
    install_status: dict[str, Any],
    connected: bool,
    diagnostics: BrowserDiagnostics,
    build_freshness: dict[str, Any],
) -> tuple[str, str]:
    if not install_status.get("installed"):
        return "setup_required", "run_setup"
    if install_status.get("native_host_repair_required"):
        return "setup_required", "run_setup"
    if not connected:
        return "blocked", "reload_extension"
    selected_available = any(
        backend.backend_id == diagnostics.selected_backend_id
        and backend.available
        for backend in diagnostics.backends
    )
    if not selected_available:
        return "blocked", "reload_extension"
    if build_freshness.get("status") == "stale":
        return "stale_build", "rebuild_frontend"
    return "ready", "none"


def _setup_lifecycle(
    *,
    install_status: dict[str, Any],
    connected: bool,
    build_freshness: dict[str, Any],
) -> dict[str, Any]:
    if not install_status.get("installed"):
        setup_phase = "setup_missing"
        recommended_action = "setup_extension"
        repair_actions = [
            "setup_extension",
            "open_chrome_extensions",
            "open_extension_folder",
        ]
        recovery_copy = (
            "Open the Chrome setup page and let QwenPaw prepare the "
            "local unpacked extension files."
        )
    elif install_status.get("native_host_repair_required"):
        setup_phase = "native_host_repair_required"
        recommended_action = "setup_extension"
        repair_actions = [
            "setup_extension",
            "reload_extension",
            "open_setup_page",
        ]
        recovery_copy = (
            "Open the Chrome setup page to repair the local Chrome "
            "connection files, then reload the Chrome extension."
        )
    elif build_freshness.get("status") == "stale":
        setup_phase = "stale_build"
        recommended_action = "setup_extension"
        repair_actions = [
            "setup_extension",
            "reload_extension",
            "open_setup_page",
        ]
        recovery_copy = (
            "Open the Chrome setup page so QwenPaw can refresh the "
            "local extension files."
        )
    elif not connected:
        setup_phase = "extension_loaded_bridge_disconnected"
        recommended_action = "reload_extension"
        repair_actions = [
            "reload_extension",
            "open_setup_page",
            "open_chrome_extensions",
            "open_extension_folder",
        ]
        recovery_copy = (
            "Open the Chrome setup page at /plugin/chrome, "
            "then reload or reconnect the Chrome extension."
        )
    else:
        setup_phase = "connected"
        recommended_action = "none"
        repair_actions = []
        recovery_copy = "Chrome is connected."

    return {
        "canonical_setup_url": CANONICAL_SETUP_URL,
        "setup_phase": setup_phase,
        "recommended_action": recommended_action,
        "repair_actions": repair_actions,
        "recovery_copy": recovery_copy,
    }


def _git_output(*args: str) -> str:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=0.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _frontend_fingerprint() -> str:
    static_dir = REPO_ROOT / "console" / "dist"
    index_path = static_dir / "index.html"
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        names = sorted(
            path.name
            for path in assets_dir.iterdir()
            if path.is_file() and path.suffix in {".js", ".css"}
        )
        if names:
            return ",".join(names[:20])
    if index_path.exists():
        stat = index_path.stat()
        return f"index:{int(stat.st_mtime)}:{stat.st_size}"
    return ""


def _plugin_fingerprint() -> str:
    return _hash_existing_files(
        [
            PLUGIN_ROOT / "plugin.json",
            EXTENSION_MANIFEST_PATH,
            PLUGIN_ROOT / "api" / "routes.py",
        ],
    )


def _hash_existing_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    seen = False
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        seen = True
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16] if seen else ""


def _check_payload(
    *,
    name: str,
    passed: bool,
    code: str,
    message: str,
    repair_action: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "status": "passed" if passed else "failed",
        "code": code,
        "message": _sanitize_text(message),
        "repair_action": repair_action or _repair_action_for_code(code),
        "metadata": _sanitize_json_value(dict(metadata or {})),
    }


def _repair_action_for_code(code: str) -> str:
    if code in {
        "bridge_disconnected",
        "chrome_disconnected",
        "browser_backend_unavailable",
    }:
        return "reload_extension"
    if code == "native_host_repair_required":
        return "run_setup"
    if code in {"build_dirty", "build_stale"}:
        return "rebuild_frontend"
    if code in {"isolated_backend_unavailable", "missing"}:
        return "restart_qwenpaw"
    return "none"


def _diagnostics_check(
    *,
    name: str,
    diagnostics: BrowserDiagnostics,
) -> dict[str, Any]:
    available = any(item.available for item in diagnostics.backends)
    first = diagnostics.backends[0] if diagnostics.backends else None
    code = "available" if available else (first.code if first else "missing")
    message = (
        first.message
        if first and first.message
        else ("Backend available" if available else "Backend unavailable")
    )
    return _check_payload(
        name=name,
        passed=available,
        code=code or ("available" if available else "unavailable"),
        message=message,
        repair_action=_repair_action_for_code(
            code or ("available" if available else "unavailable"),
        ),
        metadata={
            "requested_context": diagnostics.requested_context,
            "selected_backend_id": diagnostics.selected_backend_id,
        },
    )


async def run_extension_self_test() -> dict[str, Any]:
    started = perf_counter()
    checked_at = datetime.now(UTC).isoformat()
    user_diagnostics = await _sdk_diagnostics_snapshot("user")
    isolated_diagnostics = await _sdk_diagnostics_snapshot("isolated")
    build = _build_fingerprint()
    build_freshness = _build_freshness(build)

    trace_event = BrowserTraceEvent(
        event_id=f"self-test-{int(started * 1000)}",
        session_id="chrome-self-test",
        phase="self-test",
        action="trace_store",
        status="ok",
    )
    recorded = get_browser_trace_store().record(trace_event)
    trace_found = any(
        event.event_id == recorded.event_id
        for event in get_browser_trace_store().list(
            session_id="chrome-self-test",
        )
    )
    connected = _bridge_connected()
    install_status = extension_install_status()
    lifecycle = _setup_lifecycle(
        install_status=install_status,
        connected=connected,
        build_freshness=build_freshness,
    )
    checks = [
        _check_payload(
            name="extension_bridge",
            passed=connected,
            code="bridge_connected" if connected else "bridge_disconnected",
            message=(
                "Native Messaging bridge is connected."
                if connected
                else "Native Messaging bridge is not connected."
            ),
            repair_action="none" if connected else "reload_extension",
            metadata={
                "canonical_setup_url": lifecycle["canonical_setup_url"],
                "recommended_action": lifecycle["recommended_action"],
                "recovery_copy": lifecycle["recovery_copy"],
            },
        ),
        _diagnostics_check(
            name="user_backend",
            diagnostics=user_diagnostics,
        ),
        _diagnostics_check(
            name="isolated_backend",
            diagnostics=isolated_diagnostics,
        ),
        _check_payload(
            name="trace_write",
            passed=trace_found,
            code="trace_write_roundtrip" if trace_found else "trace_missing",
            message=(
                "Trace store write-read check passed."
                if trace_found
                else "Trace store write-read check failed."
            ),
            repair_action="none" if trace_found else "restart_qwenpaw",
        ),
        _check_payload(
            name="build_freshness",
            passed=build_freshness["status"] != "stale",
            code=(
                "build_clean"
                if build_freshness["status"] == "fresh"
                else "build_dirty"
                if build_freshness["status"] == "stale"
                else "build_unknown"
            ),
            message=str(build_freshness["message"]),
            repair_action=str(build_freshness["repair_action"]),
            metadata={"build_fingerprint": build},
        ),
    ]
    status = "passed" if all(check["passed"] for check in checks) else "failed"
    result = {
        "status": status,
        "checked_at": checked_at,
        "duration_ms": round((perf_counter() - started) * 1000, 3),
        "checks": checks,
    }
    sanitized = cast(dict[str, Any], _sanitize_json_value(result))
    _bridge_state.last_self_test = sanitized
    return sanitized


async def get_extension_status() -> dict[str, Any]:
    connected = _bridge_connected()
    diagnostics = await _sdk_diagnostics_snapshot("user")
    extension_version = _extension_version()
    install_status = extension_install_status()
    native_host_status = _native_host_status(install_status)
    build = _build_fingerprint()
    freshness = _build_freshness(build)
    readiness_state, repair_action = _readiness_state_and_repair_action(
        install_status=install_status,
        connected=connected,
        diagnostics=diagnostics,
        build_freshness=freshness,
    )
    trace_summary = _trace_summary()
    lifecycle_summary = dict(trace_summary.get("lifecycle") or {})
    setup_lifecycle = _setup_lifecycle(
        install_status=install_status,
        connected=connected,
        build_freshness=freshness,
    )

    return {
        **install_status,
        **setup_lifecycle,
        "connected": connected,
        "readiness_state": readiness_state,
        "repair_action": repair_action,
        "native_host_status": native_host_status,
        "native_host_version": str(native_host_status.get("version") or ""),
        "selected_backend_id": diagnostics.selected_backend_id,
        "version": extension_version,
        "extension_version": extension_version,
        "connected_since": (
            _bridge_state.connected_since.isoformat()
            if connected and _bridge_state.connected_since is not None
            else None
        ),
        "bridge_lifecycle": _bridge_lifecycle(connected),
        "build_fingerprint": build,
        "build_freshness": freshness,
        "last_self_test": _sanitize_json_value(_bridge_state.last_self_test),
        "trace_summary": trace_summary,
        "controlled_tab_count": int(
            lifecycle_summary.get("controlled_tab_count") or 0,
        ),
        "residual_tab_count": int(
            lifecycle_summary.get("residual_tab_count") or 0,
        ),
        "last_cleanup_reason": str(
            lifecycle_summary.get("last_cleanup_reason") or "",
        ),
        "protected_origin_status": str(
            lifecycle_summary.get("protected_origin_status") or "clear",
        ),
        "sdk_diagnostics": _serialize_diagnostics(diagnostics),
    }


@api_router.get("/status")
async def extension_status() -> dict[str, Any]:
    return await get_extension_status()


@api_router.post("/self-test")
async def extension_self_test() -> dict[str, Any]:
    return await run_extension_self_test()


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


@api_router.post("/open-extension-folder")
async def open_local_extension_folder() -> OpenExtensionFolderResponse:
    return OpenExtensionFolderResponse(**open_extension_folder())
