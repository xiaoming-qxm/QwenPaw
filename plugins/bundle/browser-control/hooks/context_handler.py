# -*- coding: utf-8 -*-
"""Context pruning handler for Browser Control tool results."""

from __future__ import annotations

from typing import Any


def _block_get(block: Any, key: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _block_type(block: Any) -> str:
    value = _block_get(block, "type", "")
    return str(value or "")


class BrowserControlContextHandler:
    """Identify heavyweight Browser Control observations for pruning."""

    def is_observation_result(self, block: Any) -> bool:
        output = _block_get(block, "output")
        if isinstance(output, str):
            return '"snapshot"' in output or '"screenshot"' in output
        if isinstance(output, list):
            for item in output:
                if _block_type(item) != "text":
                    continue
                text = str(_block_get(item, "text", "") or "")
                if '"snapshot"' in text or '"screenshot"' in text:
                    return True
        return False


__all__ = ["BrowserControlContextHandler"]
