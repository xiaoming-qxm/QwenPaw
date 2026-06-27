# -*- coding: utf-8 -*-
"""Unit tests for the Native Messaging bridge router."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from qwenpaw.app import auth as auth_module
from qwenpaw.app.auth import AuthMiddleware
from qwenpaw.browser.control_plugin import load_browser_control_submodule

nm_bridge_router = load_browser_control_submodule("routes")


class _Bridge:
    def __init__(self) -> None:
        self.attached = False
        self.detached = False

    async def attach_websocket(self, _websocket) -> None:
        self.attached = True

    async def detach_websocket(self, _websocket) -> None:
        self.detached = True

    async def handle_ws_message(self, _message):
        return None


def _include_nm_bridge_routes(app: FastAPI) -> None:
    ws_router = getattr(nm_bridge_router, "ws_router", nm_bridge_router.router)
    api_router = getattr(
        nm_bridge_router,
        "api_router",
        nm_bridge_router.router,
    )
    app.include_router(ws_router, prefix="/ws")
    app.include_router(api_router, prefix="/api/extension")


def _app_with_router(bridge: _Bridge) -> FastAPI:
    app = FastAPI()
    app.state.nm_bridge = bridge
    _include_nm_bridge_routes(app)
    return app


def _app_with_auth_router(bridge: _Bridge) -> FastAPI:
    app = FastAPI()
    app.state.nm_bridge = bridge
    app.add_middleware(AuthMiddleware)
    _include_nm_bridge_routes(app)
    return app


def _enable_auth(monkeypatch) -> None:
    def load_config() -> Any:
        security = type("Security", (), {"allow_no_auth_hosts": []})()
        return type("Config", (), {"security": security})()

    monkeypatch.setattr(auth_module, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_module, "has_registered_users", lambda: True)
    monkeypatch.setattr(
        auth_module,
        "verify_token",
        lambda token: "user" if token == "valid" else None,
    )
    monkeypatch.setattr(
        "qwenpaw.config.load_config",
        load_config,
    )


def test_configure_nm_bridge_writes_private_config(tmp_path) -> None:
    config_path = tmp_path / "nm-bridge.json"

    token = nm_bridge_router.configure_nm_bridge(
        token="secret",
        ws_url="ws://127.0.0.1:8088/ws/nm-bridge",
        config_path=config_path,
    )

    assert token == "secret"
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert '"token": "secret"' in config_path.read_text(encoding="utf-8")


def test_ws_accepts_valid_bearer_token_and_rejects_invalid(tmp_path) -> None:
    bridge = _Bridge()
    nm_bridge_router.configure_nm_bridge(
        token="secret",
        config_path=tmp_path / "nm-bridge.json",
    )
    client = TestClient(_app_with_router(bridge))

    with client.websocket_connect(
        "/ws/nm-bridge",
        headers={"Authorization": "Bearer secret"},
    ):
        assert bridge.attached is True

    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect(
            "/ws/nm-bridge",
            headers={"Authorization": "Bearer wrong"},
        ):
            pass

    assert getattr(exc_info.value, "status_code", None) == 401


def test_extension_status_api_reports_bridge_state(monkeypatch) -> None:
    bridge = _Bridge()
    client = TestClient(_app_with_router(bridge))
    monkeypatch.setattr(
        nm_bridge_router,
        "extension_install_status",
        lambda: {
            "installed": True,
            "install_mode": "unpacked",
            "extension_id": "ext",
            "extension_dir": "/tmp/ext",
            "native_manifest_path": "/tmp/host.json",
            "native_host_path": "/tmp/host",
            "config_path": "/tmp/nm.json",
            "ws_url": "ws://127.0.0.1:8088/ws/nm-bridge",
            "chrome_extensions_url": "chrome://extensions",
        },
    )

    response = client.get("/api/extension/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["installed"] is True
    assert payload["connected"] is False
    assert payload["connected_since"] is None


def test_extension_setup_rest_requires_api_auth(monkeypatch) -> None:
    _enable_auth(monkeypatch)
    monkeypatch.setattr(
        nm_bridge_router,
        "setup_extension_files",
        lambda **_kwargs: {
            "installed": True,
            "install_mode": "unpacked",
            "extension_id": "ext",
            "extension_dir": "/tmp/ext",
            "native_manifest_path": "/tmp/host.json",
            "native_host_path": "/tmp/host",
            "config_path": "/tmp/nm.json",
            "ws_url": "ws://127.0.0.1:8088/ws/nm-bridge",
            "chrome_extensions_url": "chrome://extensions",
        },
    )
    monkeypatch.setattr(
        nm_bridge_router,
        "configure_nm_bridge",
        lambda **_: "",
    )
    monkeypatch.setattr(
        nm_bridge_router,
        "extension_install_status",
        lambda: {
            "installed": True,
            "install_mode": "unpacked",
            "extension_id": "ext",
            "extension_dir": "/tmp/ext",
            "native_manifest_path": "/tmp/host.json",
            "native_host_path": "/tmp/host",
            "config_path": "/tmp/nm.json",
            "ws_url": "ws://127.0.0.1:8088/ws/nm-bridge",
            "chrome_extensions_url": "chrome://extensions",
        },
    )
    client = TestClient(_app_with_auth_router(_Bridge()))

    root_response = client.post("/extension/setup", json={})
    api_response = client.post(
        "/api/extension/setup",
        json={},
        headers={"Authorization": "Bearer valid"},
    )

    assert root_response.status_code == 401
    assert api_response.status_code == 200
