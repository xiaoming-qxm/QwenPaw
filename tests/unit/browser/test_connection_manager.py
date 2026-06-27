# -*- coding: utf-8 -*-
"""Tests for the browser connection manager interface."""

from __future__ import annotations

import inspect
from typing import Any

from qwenpaw.browser.connection_manager import (
    BridgeConnectionManager,
    clear_bridge_connection_manager,
    get_bridge_connection_manager,
    set_bridge_connection_manager,
)


def test_bridge_connection_manager_is_abstract_interface() -> None:
    assert inspect.isabstract(BridgeConnectionManager)
    assert BridgeConnectionManager.__abstractmethods__ == {
        "get_connection",
        "is_connected",
    }


def test_bridge_connection_manager_accepts_concrete_implementation() -> None:
    class ConcreteConnectionManager(BridgeConnectionManager):
        def __init__(self) -> None:
            self.connection = object()

        def get_connection(self) -> Any:
            return self.connection

        def is_connected(self) -> bool:
            return True

    manager = ConcreteConnectionManager()

    assert manager.is_connected() is True
    assert manager.get_connection() is manager.connection


def test_bridge_connection_manager_registry_round_trips() -> None:
    class ConcreteConnectionManager(BridgeConnectionManager):
        def get_connection(self) -> Any:
            return "connection"

        def is_connected(self) -> bool:
            return True

    manager = ConcreteConnectionManager()
    clear_bridge_connection_manager()

    assert get_bridge_connection_manager() is None

    set_bridge_connection_manager(manager)

    assert get_bridge_connection_manager() is manager

    clear_bridge_connection_manager()

    assert get_bridge_connection_manager() is None
