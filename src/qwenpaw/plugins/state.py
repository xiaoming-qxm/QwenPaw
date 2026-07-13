# -*- coding: utf-8 -*-
"""Persistent enable/disable state for plugins."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..constant import WORKING_DIR as _DEFAULT_WORKING_DIR

logger = logging.getLogger(__name__)

WORKING_DIR = _DEFAULT_WORKING_DIR


class PluginStateStore:
    """Store per-plugin enabled flags under the QwenPaw working directory."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(WORKING_DIR) / "plugin_state.json"

    def is_enabled(self, plugin_id: str, default: bool = True) -> bool:
        """Return whether a plugin should be loaded by default."""
        state = self._read()
        plugin_state = state.get(plugin_id)
        if not isinstance(plugin_state, dict):
            return bool(default)
        return bool(plugin_state.get("enabled", default))

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        """Persist a plugin enabled flag."""
        state = self._read()
        state[plugin_id] = {"enabled": bool(enabled)}
        self._write(state)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Failed to read plugin state %s: %s",
                self.path,
                exc,
            )
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
