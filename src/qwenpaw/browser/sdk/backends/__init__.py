# -*- coding: utf-8 -*-
"""Browser SDK backend implementations."""

from qwenpaw.browser.sdk.backends.protocols import (
    BrowserBackend,
    BrowserSession,
)
from qwenpaw.browser.sdk.backends.isolated import (
    IsolatedBrowserBackend,
    IsolatedBrowserSession,
    IsolatedPlaywrightRuntime,
    IsolatedPlaywrightRuntimeManager,
    get_isolated_runtime_manager,
    register_isolated_backend_once,
)
from qwenpaw.browser.sdk.backends.registry import (
    cleanup_browser_backend_request_resources,
    shutdown_registered_browser_backends,
)

__all__ = [
    "BrowserBackend",
    "BrowserSession",
    "cleanup_browser_backend_request_resources",
    "IsolatedBrowserBackend",
    "IsolatedBrowserSession",
    "IsolatedPlaywrightRuntime",
    "IsolatedPlaywrightRuntimeManager",
    "get_isolated_runtime_manager",
    "register_isolated_backend_once",
    "shutdown_registered_browser_backends",
]
