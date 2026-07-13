# -*- coding: utf-8 -*-
"""Browser Bridge extension setup command loader."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import ModuleType

_PACKAGE_NAME = "qwenpaw_browser_bridge_cli"


def _browser_bridge_plugin_dir() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "bundle"
        / "browser-bridge"
    )


def _load_extension_setup() -> ModuleType:
    plugin_dir = _browser_bridge_plugin_dir()
    package = sys.modules.get(_PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(_PACKAGE_NAME)
        package.__path__ = [str(plugin_dir)]  # type: ignore[attr-defined]
        package.__package__ = _PACKAGE_NAME
        sys.modules[_PACKAGE_NAME] = package

    module_name = f"{_PACKAGE_NAME}.extension_setup"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    module_path = plugin_dir / "extension_setup.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Browser Bridge setup: {module_path}")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _PACKAGE_NAME
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _export_public(module: ModuleType) -> None:
    public_names = [
        name
        for name in dir(module)
        if not (name.startswith("__") and name != "__all__")
    ]
    for name in public_names:
        globals()[name] = getattr(module, name)
    globals()["__all__"] = [
        name for name in public_names if not name.startswith("_")
    ]


_export_public(_load_extension_setup())
