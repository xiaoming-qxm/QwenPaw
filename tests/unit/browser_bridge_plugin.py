# -*- coding: utf-8 -*-
"""Test loader for bundled Browser Bridge plugin modules."""

from __future__ import annotations

import importlib.util
import sys
import types
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

_PACKAGE_NAME = "test_browser_bridge_plugin"
_PLUGIN_DIR = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "bundle"
    / "browser-bridge"
)
_SUBMODULE_ALIASES = {
    "routes": "api.routes",
    "nm_bridge": "transport.native_messaging",
}


def load_browser_bridge_submodule(name: str) -> ModuleType:
    """Load a Browser Bridge plugin submodule by package-relative name."""
    target = _SUBMODULE_ALIASES.get(name, name)
    if target.startswith("engine."):
        target = f"action_runtime.{target.removeprefix('engine.')}"
    module_name = f"{_PACKAGE_NAME}.{target}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached

    _ensure_package(_PACKAGE_NAME, _PLUGIN_DIR)
    parent_name = _PACKAGE_NAME
    parent_dir = _PLUGIN_DIR
    parts = target.split(".")
    for part in parts[:-1]:
        parent_dir = parent_dir / part
        parent_name = f"{parent_name}.{part}"
        _ensure_package(parent_name, parent_dir)

    spec, is_package = _submodule_spec(
        module_name,
        parent_dir,
        parts[-1],
        target,
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name if is_package else parent_name
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _ensure_package(package_name: str, package_dir: Path) -> ModuleType:
    package = sys.modules.get(package_name)
    if package is not None:
        return package
    init_path = package_dir / "__init__.py"
    if init_path.exists():
        spec = importlib.util.spec_from_file_location(
            package_name,
            init_path,
            submodule_search_locations=[str(package_dir)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(
                f"Cannot load Browser Bridge package: {package_name}",
            )
        package = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = package
        spec.loader.exec_module(package)
        return package
    package = types.ModuleType(package_name)
    package.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
    package.__package__ = package_name
    sys.modules[package_name] = package
    return package


def _submodule_spec(
    module_name: str,
    parent_dir: Path,
    final_name: str,
    public_name: str,
) -> tuple[ModuleSpec, bool]:
    package_dir = parent_dir / final_name
    init_path = package_dir / "__init__.py"
    is_package = init_path.exists()
    if is_package:
        spec = importlib.util.spec_from_file_location(
            module_name,
            init_path,
            submodule_search_locations=[str(package_dir)],
        )
    else:
        module_path = parent_dir / f"{final_name}.py"
        if not module_path.exists():
            raise ImportError(
                f"Cannot load Browser Bridge module: {public_name}",
            )
        spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Browser Bridge module: {public_name}")
    return spec, is_package
