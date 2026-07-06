# -*- coding: utf-8 -*-
"""Browser Bridge backend adapters."""

from .user import (
    ChromeExtensionBrowserBackend,
    ChromeExtensionBrowserSession,
    register_user_backend_once,
)

__all__ = [
    "ChromeExtensionBrowserBackend",
    "ChromeExtensionBrowserSession",
    "register_user_backend_once",
]
