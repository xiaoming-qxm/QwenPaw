# -*- coding: utf-8 -*-
"""Tests for plugin detail API payloads."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.plugins import router as plugins_router
from qwenpaw.plugins.loader import PluginLoader


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_plugin_detail_includes_manifest_and_runtime_status(
    tmp_path: Path,
) -> None:
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    plugin_dir = _repo_root() / "plugins" / "bundle" / "browser-bridge"
    loader = PluginLoader([plugin_dir.parent])
    loader.registry.set_plugin_http_app(app)
    await loader.load_plugin_from_path(
        source_path=plugin_dir,
        install_dir=tmp_path,
    )
    app.state.plugin_loader = loader
    client = TestClient(app)

    response = client.get("/api/plugins/chrome/detail")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "chrome"
    assert payload["manifest"]["icon"] == "Chrome"
    assert payload["manifest"]["capabilities"]
    assert payload["manifest"]["setup"]["kind"] == "native-messaging"
    assert payload["runtime_status"]["connected"] is False
    assert payload["runtime_status"]["installed"] in {True, False}
