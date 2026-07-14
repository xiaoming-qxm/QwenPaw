# -*- coding: utf-8 -*-
"""Browser Bridge plugin entry point."""

from __future__ import annotations

import logging
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from qwenpaw.browser.telemetry.trace import record_browser_trace_event
from qwenpaw.plugins.api import PluginApi

from .backend.user import register_user_backend_once
from .engine_impl import ControlEngineImpl
from .transport.native_messaging import get_nm_bridge
from .api.routes import (
    api_router,
    configure_nm_bridge,
    get_extension_status,
    resolve_default_ws_url,
    shutdown_nm_bridge,
    ws_router,
)

logger = logging.getLogger(__name__)


def _load_manifest_module() -> ModuleType:
    path = Path(__file__).parent / "assets" / "scripts" / "manifest.py"
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_browser_bridge_manifest",
        path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            f"Cannot load Browser Bridge manifest module: {path}",
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_manifest_module = _load_manifest_module()
_manifest_register_instance = _manifest_module.register_instance
_manifest_deregister_instance = _manifest_module.deregister_instance


class BrowserBridgePlugin:
    """Register Browser Bridge plugin capabilities."""

    def __init__(self) -> None:
        self._manifest_entry_id: str | None = None
        self._control_engine: ControlEngineImpl | None = None

    def startup(self) -> None:
        """Register this QwenPaw backend in the browser-bridge manifest."""
        if self._manifest_entry_id:
            return
        ws_url = resolve_default_ws_url()
        token = configure_nm_bridge(ws_url=ws_url)
        self._manifest_entry_id = _manifest_register_instance(
            ws_url,
            token,
            channel="stable",
            app_version="",
        )

    async def shutdown(self) -> None:
        """Release runtime bridge resources during plugin unload."""
        if self._manifest_entry_id:
            _manifest_deregister_instance(self._manifest_entry_id)
            self._manifest_entry_id = None
        await shutdown_nm_bridge()
        self._control_engine = None

    def register(self, api: PluginApi) -> None:
        """Register backend integrations."""
        bridge = get_nm_bridge()
        self._control_engine = ControlEngineImpl(bridge_manager=bridge)
        register_user_backend_once(
            bridge_manager=bridge,
            control_engine=self._control_engine,
            trace_recorder=record_browser_trace_event,
        )
        api.register_http_router(
            api_router,
            prefix="/chrome",
            tags=["chrome"],
        )
        api.register_http_router(
            ws_router,
            prefix="/ws",
            tags=["chrome"],
            under_api=False,
        )
        api.register_shutdown_hook(
            hook_name="browser_bridge_clear_connection_manager",
            callback=self.shutdown,
            priority=120,
        )
        api.register_startup_hook(
            hook_name="browser_bridge_register_manifest",
            callback=self.startup,
            priority=110,
        )
        logger.info("Browser Bridge plugin registered: %s", api.plugin_id)

    async def get_runtime_status(self) -> dict:
        """Return Browser Bridge runtime status for plugin detail pages."""
        return await get_extension_status()


plugin = BrowserBridgePlugin()
