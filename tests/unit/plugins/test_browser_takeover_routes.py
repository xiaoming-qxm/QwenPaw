# -*- coding: utf-8 -*-
"""Tests for Browser Takeover plugin route registration."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from qwenpaw.plugins.loader import PluginLoader


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_browser_takeover_plugin_registers_bridge_routes() -> None:
    app = FastAPI()
    plugin_dir = _repo_root() / "plugins" / "bundle" / "browser-takeover"
    loader = PluginLoader([plugin_dir.parent])
    loader.registry.set_plugin_http_app(app)

    await loader.load_plugin_from_path(
        source_path=plugin_dir,
        install_dir=plugin_dir.parent,
    )

    paths = {getattr(route, "path", "") for route in app.router.routes}

    assert "/api/extension/status" in paths
    assert "/api/extension/setup" in paths
    assert "/ws/nm-bridge" in paths
