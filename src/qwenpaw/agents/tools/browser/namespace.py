# -*- coding: utf-8 -*-
# mypy: ignore-errors
"""Compatibility namespace for mechanically split browser modules."""

from __future__ import annotations

from importlib import import_module

_MODULE_NAMES = (
    "qwenpaw.agents.tools.browser.runtime",
    "qwenpaw.agents.tools.browser.backends.playwright_basic",
    "qwenpaw.agents.tools.browser.backends.playwright_advanced",
    "qwenpaw.agents.tools.browser.backends.playwright_interactions",
    "qwenpaw.agents.tools.browser.backends.playwright_batch_cdp",
    "qwenpaw.agents.tools.browser.backends.control",
    "qwenpaw.agents.tools.browser.public",
)

_modules = [import_module(name) for name in _MODULE_NAMES]
_combined = {}
for _module in _modules:
    _combined.update(
        {
            name: value
            for name, value in vars(_module).items()
            if not name.startswith("__")
        },
    )

for _module in _modules:
    vars(_module).update(_combined)

globals().update(_combined)

__all__ = [name for name in globals() if not name.startswith("__")]
