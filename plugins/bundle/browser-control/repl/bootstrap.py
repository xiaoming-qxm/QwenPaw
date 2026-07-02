# -*- coding: utf-8 -*-
"""Bootstrap code generation for Browser Control Python REPL kernels."""

from __future__ import annotations

from pathlib import Path


def get_bootstrap_code(ws_url: str, token: str, sdk_path: str) -> str:
    """Return Python code that preloads the Browser SDK into a kernel."""
    sdk_dir = Path(sdk_path)
    return f"""
import sys
from pathlib import Path

_qwenpaw_browser_sdk_path = Path({str(sdk_dir)!r})
_qwenpaw_browser_sdk_parent = _qwenpaw_browser_sdk_path.parent
for _qwenpaw_browser_path in (
    str(_qwenpaw_browser_sdk_parent),
    str(_qwenpaw_browser_sdk_path),
):
    if _qwenpaw_browser_path not in sys.path:
        sys.path.insert(0, _qwenpaw_browser_path)

from sdk import Browser

browser = await Browser.connect(
    ws_url={ws_url!r},
    token={token!r},
)
"""


__all__ = ["get_bootstrap_code"]
