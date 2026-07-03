# -*- coding: utf-8 -*-
"""Browser Control plugin entry point."""

from __future__ import annotations

import logging
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from qwenpaw.browser.connection_manager import (
    clear_bridge_connection_manager,
    set_bridge_connection_manager,
)
from qwenpaw.browser.control_engine import (
    clear_control_engine,
    register_control_engine,
)
from qwenpaw.loop.gates.rubric import PrematureStopGate
from qwenpaw.plugins.api import PluginApi

from .engine_impl import ControlEngineImpl
from .nm_bridge import get_nm_bridge
from .routes import (
    api_router,
    configure_nm_bridge,
    get_extension_status,
    resolve_default_ws_url,
    shutdown_nm_bridge,
    ws_router,
)
from .tool_repl import (
    python_repl,
    python_repl_reset,
)

logger = logging.getLogger(__name__)

_BROWSER_PREMATURE_STOP_PROMPT = (
    "You have used browser tools in this session but produced a "
    "text-only response. If the browser task is not verified "
    "complete, continue with a fresh tab.snapshot() to check "
    "the current state. Do not stop without verifying."
)

_PYTHON_REPL_DESCRIPTION = (
    "Execute Python code in the Browser Control SDK REPL. The REPL "
    "preloads `browser`; do not import `browser_sdk`. Use "
    "`await browser.tabs.open(...)`, "
    "`await browser.tabs.list(all=True)`, `await tab.snapshot()`, and "
    "`print(await browser.documentation())` for API help."
)

_premature_stop_gate = PrematureStopGate(
    prompt=_BROWSER_PREMATURE_STOP_PROMPT,
    max_interventions=2,
)


def _load_manifest_module() -> ModuleType:
    path = Path(__file__).parent / "assets" / "scripts" / "manifest.py"
    spec = importlib.util.spec_from_file_location(
        "qwenpaw_browser_control_manifest",
        path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            f"Cannot load Browser Control manifest module: {path}",
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_manifest_module = _load_manifest_module()
_manifest_register_instance = _manifest_module.register_instance
_manifest_deregister_instance = _manifest_module.deregister_instance


class BrowserControlPlugin:
    """Register Browser Control plugin capabilities."""

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
        clear_bridge_connection_manager()
        clear_control_engine()
        self._control_engine = None

    def register(self, api: PluginApi) -> None:
        """Register backend integrations."""
        bridge = get_nm_bridge()
        set_bridge_connection_manager(bridge)
        self._control_engine = ControlEngineImpl()
        register_control_engine(self._control_engine)
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
            callback=self.shutdown,
            priority=120,
        )
        api.register_startup_hook(
            hook_name="browser_control_register_manifest",
            callback=self.startup,
            priority=110,
        )
        api.register_tool(
            tool_name="python_repl",
            tool_func=python_repl,
            description=_PYTHON_REPL_DESCRIPTION,
            icon="🐍",
            enabled=True,
        )
        api.register_tool(
            tool_name="python_repl_reset",
            tool_func=python_repl_reset,
            description="Reset the Browser Control Python REPL environment",
            icon="↻",
            enabled=True,
        )
        api.register_skill_provider(
            skills_dir=Path(__file__).parent / "skills",
            enabled_by_default=True,
            channels=["all"],
        )
        api.register_agent_stop_handler(
            handler=_premature_stop_gate.check,
            priority=90,
            name="browser_control_premature_stop",
        )
        logger.info("Browser Control plugin registered: %s", api.plugin_id)

    def get_runtime_status(self) -> dict:
        """Return Browser Control runtime status for plugin detail pages."""
        return get_extension_status()


plugin = BrowserControlPlugin()
