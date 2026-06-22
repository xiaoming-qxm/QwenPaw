# -*- coding: utf-8 -*-
"""Tests for plugin enable/disable state."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.plugins import router as plugins_router
from qwenpaw.plugins.loader import PluginLoader


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


async def _load_browser_control(
    app: FastAPI,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> PluginLoader:
    from qwenpaw.plugins import state as plugin_state

    monkeypatch.setattr(plugin_state, "WORKING_DIR", tmp_path)
    plugin_dir = _repo_root() / "plugins" / "bundle" / "browser-control"
    loader = PluginLoader([plugin_dir.parent])
    loader.registry.set_plugin_http_app(app)
    await loader.load_plugin_from_path(
        source_path=plugin_dir,
        install_dir=plugin_dir.parent,
    )
    app.state.plugin_loader = loader
    return loader


@pytest.mark.asyncio
async def test_patch_plugin_disable_persists_and_unloads(
    tmp_path,
    monkeypatch,
) -> None:
    from qwenpaw.plugins.state import PluginStateStore

    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    loader = await _load_browser_control(app, tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.patch(
        "/api/plugins/browser-control",
        json={"enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    record = loader.get_loaded_plugin("browser-control")
    assert record is not None
    assert record.enabled is False
    assert record.instance is None
    assert PluginStateStore().is_enabled("browser-control") is False
    listed = {
        plugin["id"]: plugin for plugin in client.get("/api/plugins").json()
    }
    assert listed["browser-control"]["enabled"] is False
    assert listed["browser-control"]["loaded"] is False

    second_app = FastAPI()
    second_loader = await _load_browser_control(
        second_app,
        tmp_path,
        monkeypatch,
    )
    restarted = second_loader.get_loaded_plugin("browser-control")

    assert restarted is not None
    assert restarted.enabled is False
    assert restarted.instance is None


@pytest.mark.asyncio
async def test_patch_plugin_reenable_loads_plugin_again(
    tmp_path,
    monkeypatch,
) -> None:
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    loader = await _load_browser_control(app, tmp_path, monkeypatch)
    client = TestClient(app)

    disabled = client.patch(
        "/api/plugins/browser-control",
        json={"enabled": False},
    )
    enabled = client.patch(
        "/api/plugins/browser-control",
        json={"enabled": True},
    )

    assert disabled.status_code == 200
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    record = loader.get_loaded_plugin("browser-control")
    assert record is not None
    assert record.enabled is True
    assert record.instance is not None
