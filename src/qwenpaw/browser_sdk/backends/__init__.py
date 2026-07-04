# -*- coding: utf-8 -*-
"""Browser SDK backend implementations."""

from qwenpaw.browser_sdk.backend_protocols import BrowserBackend, BrowserSession
from qwenpaw.browser_sdk.backends.isolated import (
    IsolatedBrowserBackend,
    IsolatedBrowserSession,
    IsolatedPlaywrightRuntime,
    IsolatedPlaywrightRuntimeManager,
    get_isolated_runtime_manager,
    register_isolated_backend_once,
)
from qwenpaw.browser_sdk.backends.user import (
    ChromeExtensionBrowserBackend,
    ChromeExtensionBrowserSession,
    register_user_backend_once,
)

__all__ = [
    "BrowserBackend",
    "BrowserSession",
    "ChromeExtensionBrowserBackend",
    "ChromeExtensionBrowserSession",
    "IsolatedBrowserBackend",
    "IsolatedBrowserSession",
    "IsolatedPlaywrightRuntime",
    "IsolatedPlaywrightRuntimeManager",
    "get_isolated_runtime_manager",
    "register_isolated_backend_once",
    "register_user_backend_once",
]
