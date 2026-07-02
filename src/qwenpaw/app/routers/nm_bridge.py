# -*- coding: utf-8 -*-
"""Compatibility shim for the Browser Control plugin routes."""

from __future__ import annotations

from qwenpaw.browser.control_plugin import (
    export_public,
    load_browser_control_submodule,
)

_module = load_browser_control_submodule("routes")
export_public(_module, globals())
