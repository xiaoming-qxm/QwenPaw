# -*- coding: utf-8 -*-
"""Browser integration interfaces."""

from .connection_manager import (
    BridgeConnectionManager,
    clear_bridge_connection_manager,
    get_bridge_connection_manager,
    set_bridge_connection_manager,
)

__all__ = [
    "BridgeConnectionManager",
    "clear_bridge_connection_manager",
    "get_bridge_connection_manager",
    "set_bridge_connection_manager",
]
