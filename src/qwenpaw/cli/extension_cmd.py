# -*- coding: utf-8 -*-
"""Compatibility shim for the Browser Takeover extension setup command."""

from __future__ import annotations

from qwenpaw.browser.takeover_plugin import (
    export_public,
    load_browser_takeover_submodule,
)

_module = load_browser_takeover_submodule("extension_setup")
export_public(_module, globals())
