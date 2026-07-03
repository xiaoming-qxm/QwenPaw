# -*- coding: utf-8 -*-
"""Helpers for loading the bundled Browser Control plugin modules."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import ModuleType

_PACKAGE_NAME = "plugin_browser_control"


def get_browser_control_plugin_dir() -> Path:
    """Return the bundled Browser Control plugin directory."""
    return (
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "bundle"
        / "browser-control"
    )


def load_browser_control_submodule(name: str) -> ModuleType:
    """Load a Browser Control plugin submodule by file name."""
    plugin_dir = get_browser_control_plugin_dir()
    module_name = f"{_PACKAGE_NAME}.{name}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached

    package = sys.modules.get(_PACKAGE_NAME)
    if package is None:
        package = types.ModuleType(_PACKAGE_NAME)
        package.__path__ = [str(plugin_dir)]  # type: ignore[attr-defined]
        package.__package__ = _PACKAGE_NAME
        sys.modules[_PACKAGE_NAME] = package

    parts = name.split(".")
    parent_name = _PACKAGE_NAME
    parent_dir = plugin_dir
    for part in parts[:-1]:
        parent_dir = parent_dir / part
        package_name = f"{parent_name}.{part}"
        package = sys.modules.get(package_name)
        init_path = parent_dir / "__init__.py"
        if package is None or (
            init_path.exists() and not getattr(package, "__file__", None)
        ):
            if init_path.exists():
                spec = importlib.util.spec_from_file_location(
                    package_name,
                    init_path,
                    submodule_search_locations=[str(parent_dir)],
                )
                if spec is None or spec.loader is None:
                    message = (
                        "Could not load browser control package: "
                        f"{package_name}"
                    )
                    raise ImportError(
                        message,
                    )
                package = importlib.util.module_from_spec(spec)
                sys.modules[package_name] = package
                spec.loader.exec_module(package)
            else:
                package = types.ModuleType(package_name)
                package.__path__ = [  # type: ignore[attr-defined]
                    str(parent_dir),
                ]
                package.__package__ = package_name
                sys.modules[package_name] = package
        parent_name = package_name

    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached

    final_name = parts[-1]
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
        spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load browser control module: {name}")

    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name if is_package else parent_name
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def export_public(
    module: ModuleType,
    target_globals: dict[str, object],
) -> None:
    """Copy public module attributes into a shim module's globals."""
    public_names = [
        name
        for name in dir(module)
        if not (name.startswith("__") and name != "__all__")
    ]
    for name in public_names:
        target_globals[name] = getattr(module, name)
    target_globals["__all__"] = [
        name for name in public_names if not name.startswith("_")
    ]
