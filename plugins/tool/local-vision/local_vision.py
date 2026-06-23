# -*- coding: utf-8 -*-
"""Local Vision tool plugin entry point."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent


def _load_tool_module():
    """Load local_vision_tool.py from this plugin directory."""
    tool_path = _PLUGIN_DIR / "local_vision_tool.py"
    spec = importlib.util.spec_from_file_location(
        "local_vision_tool",
        tool_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load local vision tool from {tool_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["local_vision_tool"] = module
    spec.loader.exec_module(module)
    return module


class LocalVisionToolPlugin:
    """Register the Local Vision screenshot parser tool."""

    def register(self, api: PluginApi) -> None:
        tool = _load_tool_module()

        api.register_tool(
            tool_name="parse_screenshot",
            tool_func=tool.parse_screenshot,
            description=(
                "Parse a UI screenshot into structured visible and "
                "interactive elements with bounding boxes"
            ),
            icon="👁️",
            enabled=False,
        )
        api.register_startup_hook(
            hook_name="local_vision_start_worker",
            callback=tool.start_local_vision_worker,
            priority=90,
        )
        api.register_shutdown_hook(
            hook_name="local_vision_stop_worker",
            callback=tool.stop_local_vision_worker,
            priority=110,
        )
        logger.info("Local Vision tool plugin registered")


plugin = LocalVisionToolPlugin()
