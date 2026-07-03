# -*- coding: utf-8 -*-
"""Bootstrap code generation for Browser Control Python REPL kernels."""

from __future__ import annotations


def get_bootstrap_code(ws_url: str, token: str, sdk_path: str) -> str:
    """Return Python code that preloads the Browser SDK into a kernel."""
    _ = sdk_path  # Kept for KernelManager API compatibility.
    return f"""
import sys
from qwenpaw.browser.control_plugin import load_browser_control_submodule

_qwenpaw_browser_sdk = load_browser_control_submodule("sdk")
_qwenpaw_browser_sdk_prefix = _qwenpaw_browser_sdk.__name__
_qwenpaw_browser_modules = list(sys.modules.items())
for _qwenpaw_browser_name, _qwenpaw_browser_module in _qwenpaw_browser_modules:
    if (
        _qwenpaw_browser_name == _qwenpaw_browser_sdk_prefix
        or _qwenpaw_browser_name.startswith(_qwenpaw_browser_sdk_prefix + ".")
    ):
        _qwenpaw_browser_alias = _qwenpaw_browser_name.replace(
            _qwenpaw_browser_sdk_prefix,
            "sdk",
            1,
        )
        sys.modules.setdefault(_qwenpaw_browser_alias, _qwenpaw_browser_module)
Browser = _qwenpaw_browser_sdk.Browser

browser = await Browser.connect(
    ws_url={ws_url!r},
    token={token!r},
)
"""


__all__ = ["get_bootstrap_code"]
