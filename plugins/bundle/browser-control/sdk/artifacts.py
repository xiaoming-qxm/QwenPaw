# -*- coding: utf-8 -*-
"""Transient visual artifacts produced by Browser Control SDK calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_ARTIFACTS: list[dict[str, str]] = []


def record_image_artifact(
    path: str,
    *,
    media_type: str,
    name: str = "",
) -> None:
    """Record a local image artifact for the enclosing REPL tool result."""
    raw_path = str(path or "").strip()
    raw_media_type = str(media_type or "").strip()
    if not raw_path or not raw_media_type:
        return
    try:
        url = Path(raw_path).expanduser().resolve().as_uri()
    except (OSError, ValueError):
        url = raw_path
    _ARTIFACTS.append(
        {
            "url": url,
            "media_type": raw_media_type,
            "name": str(name or Path(raw_path).name or "screenshot"),
        },
    )


def drain_artifacts() -> list[dict[str, Any]]:
    """Return and clear artifacts recorded since the previous REPL call."""
    artifacts = [dict(item) for item in _ARTIFACTS]
    _ARTIFACTS.clear()
    return artifacts


__all__ = ["drain_artifacts", "record_image_artifact"]
