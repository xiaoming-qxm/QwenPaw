# -*- coding: utf-8 -*-
"""Lightweight extraction helpers for Browser SDK tabs."""

from __future__ import annotations

import json
from typing import Any

from .types import BrowserExtractionResult, ExtractionFormat


async def extract_from_tab(
    tab: Any,
    instruction: str,
    *,
    format: ExtractionFormat = "text",
) -> BrowserExtractionResult:
    """Run lightweight text or JSON extraction for a tab."""
    raw = await _raw_extract(tab, instruction, format=format)
    text = _result_text(raw)
    if format == "text":
        return BrowserExtractionResult(ok=True, format="text", text=text)
    if format != "json":
        return BrowserExtractionResult(
            ok=False,
            format="text",
            text=text,
            error="browser_extract_unsupported_format",
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return BrowserExtractionResult(
            ok=False,
            format="json",
            text=text,
            error="browser_extract_json_parse_error",
        )
    return BrowserExtractionResult(
        ok=True,
        format="json",
        text=text,
        data=data,
    )


async def _raw_extract(
    tab: Any,
    instruction: str,
    *,
    format: ExtractionFormat,
) -> Any:
    session = tab._session  # pylint: disable=protected-access
    extract = getattr(session, "extract", None)
    if callable(extract):
        return await extract(tab.id, instruction, format=format)
    observation = await tab.snapshot()
    return observation.text


def _result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "value"):
            if key in value:
                return str(value[key])
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


__all__ = ["extract_from_tab"]
