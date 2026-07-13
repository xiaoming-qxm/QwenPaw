# -*- coding: utf-8 -*-
"""Tests for Browser Bridge transport manager behavior."""

from __future__ import annotations

from tests.unit.browser_bridge_plugin import load_browser_bridge_submodule


_native_messaging = load_browser_bridge_submodule("transport.native_messaging")
NMBridge = _native_messaging.NMBridge


def test_nm_bridge_exposes_connection_manager_methods() -> None:
    bridge = NMBridge()

    assert bridge.get_connection() is bridge
    assert bridge.is_connected() is False
