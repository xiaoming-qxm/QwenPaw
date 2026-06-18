# -*- coding: utf-8 -*-
"""Persisted plugin enable/disable state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..constant import WORKING_DIR

PLUGIN_STATE_FILE = "plugin-state.json"


class PluginStateStore:
    """Small JSON-backed store for plugin enablement state."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (WORKING_DIR / PLUGIN_STATE_FILE)

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"plugins": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"plugins": {}}
        if not isinstance(data, dict):
            return {"plugins": {}}
        plugins = data.get("plugins")
        if not isinstance(plugins, dict):
            data["plugins"] = {}
        return data

    def write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def is_enabled(self, plugin_id: str, default: bool = True) -> bool:
        plugins = self.read().get("plugins", {})
        state = plugins.get(plugin_id)
        if not isinstance(state, dict):
            return default
        enabled = state.get("enabled")
        return enabled if isinstance(enabled, bool) else default

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        data = self.read()
        plugins = data.setdefault("plugins", {})
        plugin_state = plugins.setdefault(plugin_id, {})
        plugin_state["enabled"] = enabled
        self.write(data)
