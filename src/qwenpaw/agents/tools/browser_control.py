# -*- coding: utf-8 -*-
"""Browser Control lifecycle helpers."""

from qwenpaw.browser.control_plugin import load_browser_control_submodule
from qwenpaw.browser.sdk.runtime.responses import (
    _get_workspace_state,
    _tool_response,
    _workspace_states,
    stop_all_browsers,
    stop_browsers_for_workspace_dirs,
)


def _control_tab_manager():
    return load_browser_control_submodule("engine.tab_manager")


async def cleanup_control_sessions_for_request(**kwargs):
    """Release and close browser-control resources for one request."""
    manager = _control_tab_manager()
    return await manager.cleanup_control_sessions_for_request(**kwargs)


async def release_control_sessions_for_request(**kwargs):
    """Release browser-control leases for one completed request."""
    manager = _control_tab_manager()
    return await manager.release_control_sessions_for_request(**kwargs)


async def _action_control(*args, **kwargs):
    """Dispatch a Browser Control action through the plugin engine."""
    from qwenpaw.browser.control_engine import get_control_engine

    if args and isinstance(args[0], dict):
        state = args[0]
        action = str(args[1] if len(args) > 1 else kwargs.pop("action", ""))
    else:
        action = str(args[0] if args else kwargs.pop("action", ""))
        workspace_id = str(kwargs.pop("workspace_id", "") or "default")
        state = _get_workspace_state(workspace_id)
    engine = get_control_engine()
    if engine is None:
        engine_impl = load_browser_control_submodule("engine_impl")
        engine = engine_impl.ControlEngineImpl()
    return await engine.dispatch(state, action, **kwargs)


__all__ = [
    "_action_control",
    "_get_workspace_state",
    "_tool_response",
    "_workspace_states",
    "cleanup_control_sessions_for_request",
    "release_control_sessions_for_request",
    "stop_all_browsers",
    "stop_browsers_for_workspace_dirs",
]
