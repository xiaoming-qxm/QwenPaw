# -*- coding: utf-8 -*-
"""Compatibility shim for the Browser Takeover plugin routes."""

from __future__ import annotations

from qwenpaw.browser.takeover_plugin import (
    export_public,
    load_browser_takeover_submodule,
)

_module = load_browser_takeover_submodule("routes")
export_public(_module, globals())
