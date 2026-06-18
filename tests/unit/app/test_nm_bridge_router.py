# -*- coding: utf-8 -*-
"""Unit tests for the Native Messaging bridge router."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from qwenpaw.app.routers import nm_bridge as nm_bridge_router


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


def _app_with_router(bridge: _Bridge) -> FastAPI:
    app = FastAPI()
    app.state.nm_bridge = bridge
    app.include_router(nm_bridge_router.router)
    app.include_router(nm_bridge_router.router, prefix="/api")
    return app


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
