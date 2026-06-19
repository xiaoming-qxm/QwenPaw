# -*- coding: utf-8 -*-
"""Compatibility shim for the Browser Control extension setup command."""

from __future__ import annotations

from qwenpaw.browser.control_plugin import (
    export_public,
    load_browser_control_submodule,
)

_module = load_browser_control_submodule("extension_setup")
export_public(_module, globals())
