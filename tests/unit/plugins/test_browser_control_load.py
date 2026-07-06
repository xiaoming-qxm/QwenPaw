# -*- coding: utf-8 -*-
"""Tests for loading the bundled Browser Bridge plugin."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.plugins import router as plugins_router
from qwenpaw.plugins.architecture import PluginType
from qwenpaw.plugins.loader import PluginLoader


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_browser_bridge_bundle_plugin_loads() -> None:
    bundle_root = _repo_root() / "plugins" / "bundle"
    plugin_dir = bundle_root / "browser-bridge"
    loader = PluginLoader([bundle_root])
    loader.registry.set_plugin_http_app(FastAPI())

    record = await loader.load_plugin_from_path(
        source_path=plugin_dir,
        install_dir=bundle_root,
    )

    assert record.manifest.id == "browser-bridge"
    assert record.manifest.plugin_type is PluginType.GENERAL
    assert record.manifest.meta["builtin"] is True
    assert record.manifest.icon
    assert record.manifest.capabilities
    assert record.manifest.setup
    assert loader.get_loaded_plugin("browser-bridge") is record


def test_browser_bridge_manifest_is_discoverable() -> None:
    bundle_root = _repo_root() / "plugins" / "bundle"
    loader = PluginLoader([bundle_root])

    discovered = {manifest.id for manifest, _path in loader.discover_plugins()}

    assert "browser-bridge" in discovered


def test_browser_bridge_listed_before_loader_ready() -> None:
    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/plugins")

    assert response.status_code == 200
    assert "browser-bridge" in {plugin["id"] for plugin in response.json()}
