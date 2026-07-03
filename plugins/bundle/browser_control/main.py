# -*- coding: utf-8 -*-
"""Import-compatible wrapper for the browser-control plugin entry point."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_impl() -> ModuleType:
    module_name = "plugins.bundle.browser_control._impl"
    existing = sys.modules.get(module_name)
    if isinstance(existing, ModuleType):
        return existing

    plugin_dir = Path(__file__).resolve().parents[1] / "browser-control"
    spec = importlib.util.spec_from_file_location(
        module_name,
        plugin_dir / "main.py",
        submodule_search_locations=[str(plugin_dir)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            f"Cannot load Browser Control plugin module: {plugin_dir}",
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    module.__package__ = module_name
    module.__path__ = [str(plugin_dir)]  # type: ignore[attr-defined]
    spec.loader.exec_module(module)
    return module


_impl = _load_impl()
BrowserControlPlugin = _impl.BrowserControlPlugin
plugin = _impl.plugin

__all__ = ["BrowserControlPlugin", "plugin"]
