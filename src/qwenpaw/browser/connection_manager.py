# -*- coding: utf-8 -*-
"""Interfaces for browser bridge connection ownership."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BridgeConnectionManager(ABC):
    """Core-facing interface owned by browser bridge implementations."""

    @abstractmethod
    def get_connection(self) -> Any:
        """Return the active bridge connection object, if any."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether a browser bridge connection is currently active."""


_bridge_connection_manager: BridgeConnectionManager | None = None


def set_bridge_connection_manager(
    manager: BridgeConnectionManager | None,
) -> None:
    """Register the active browser bridge connection manager."""
    global _bridge_connection_manager
    _bridge_connection_manager = manager


def get_bridge_connection_manager() -> BridgeConnectionManager | None:
    """Return the active browser bridge connection manager, if registered."""
    return _bridge_connection_manager


def clear_bridge_connection_manager() -> None:
    """Clear the active browser bridge connection manager."""
    set_bridge_connection_manager(None)
