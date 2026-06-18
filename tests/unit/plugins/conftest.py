# -*- coding: utf-8 -*-
"""Shared isolation fixtures for plugin unit tests."""
# pylint: disable=protected-access

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_plugin_registry_and_browser_bridge():
    from qwenpaw.browser.connection_manager import (
        clear_bridge_connection_manager,
    )
    from qwenpaw.plugins.registry import PluginRegistry

    old_instance = PluginRegistry._instance
    PluginRegistry._instance = None
    clear_bridge_connection_manager()
    try:
        yield
    finally:
        clear_bridge_connection_manager()
        PluginRegistry._instance = old_instance
