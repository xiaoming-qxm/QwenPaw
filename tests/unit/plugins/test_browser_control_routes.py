# -*- coding: utf-8 -*-
"""Tests for Browser Bridge plugin route registration."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI

from qwenpaw.plugins.loader import PluginLoader


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.mark.asyncio
async def test_browser_bridge_plugin_registers_bridge_routes(
    tmp_path: Path,
) -> None:
    app = FastAPI()
    plugin_dir = _repo_root() / "plugins" / "bundle" / "browser-bridge"
    loader = PluginLoader([plugin_dir.parent])
    loader.registry.set_plugin_http_app(app)

    await loader.load_plugin_from_path(
        source_path=plugin_dir,
        install_dir=tmp_path,
    )

    paths = {getattr(route, "path", "") for route in app.router.routes}

    assert "/api/chrome/status" in paths
    assert "/api/chrome/setup" in paths
    assert "/ws/chrome" in paths
