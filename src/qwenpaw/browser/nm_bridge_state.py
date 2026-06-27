# -*- coding: utf-8 -*-
"""Stable Native Messaging bridge route state.

Browser Control plugin modules can be hot-reloaded while FastAPI still keeps
previous route handlers alive.  Keep the connection state in qwenpaw.browser so
old and new plugin module instances observe the same active WebSocket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class NMBridgeRouteState:
    """State shared by Browser Control route module instances."""

    token: str | None = None
    ws_url: str = ""
    config_path: Path | None = None
    connected: Any | None = None
    connected_since: datetime | None = None


_state = NMBridgeRouteState()


def get_nm_bridge_route_state() -> NMBridgeRouteState:
    """Return the process-wide Browser Control route state."""
    return _state
