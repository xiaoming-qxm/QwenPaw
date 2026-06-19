# -*- coding: utf-8 -*-
"""Browser Control plugin entry point."""

from __future__ import annotations

import logging

from qwenpaw.browser.connection_manager import (
    clear_bridge_connection_manager,
    set_bridge_connection_manager,
)
from qwenpaw.plugins.api import PluginApi

from .nm_bridge import get_nm_bridge
from .routes import api_router, get_extension_status, ws_router

logger = logging.getLogger(__name__)


class BrowserControlPlugin:
    """Register Browser Control plugin capabilities."""

    def register(self, api: PluginApi) -> None:
        """Register backend integrations."""
        bridge = get_nm_bridge()
        set_bridge_connection_manager(bridge)
        api.register_http_router(
            api_router,
            prefix="/extension",
            tags=["browser-control"],
        )
        api.register_http_router(
            ws_router,
            prefix="/ws",
            tags=["browser-control"],
            under_api=False,
        )
        api.register_shutdown_hook(
            hook_name="browser_control_clear_connection_manager",
            callback=clear_bridge_connection_manager,
            priority=120,
        )
        logger.info("Browser Control plugin registered: %s", api.plugin_id)

    def get_runtime_status(self) -> dict:
        """Return Browser Control runtime status for plugin detail pages."""
        return get_extension_status()


plugin = BrowserControlPlugin()
