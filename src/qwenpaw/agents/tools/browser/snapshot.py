# -*- coding: utf-8 -*-
"""Snapshot helpers shared by browser backends."""

from __future__ import annotations

from typing import Any

from ..browser_snapshot import (
    build_role_snapshot_from_aria,
    from_cdp_ax_tree,
)


def is_trivial_snapshot(snapshot: str, *, min_length: int = 50) -> bool:
    """Return true when structured evidence is too small to act on."""
    text = str(snapshot or "").strip()
    return not text or text == "(empty)" or len(text) < min_length


def refs_from_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return refs from a snapshot-like payload."""
    refs = payload.get("refs")
    return refs if isinstance(refs, dict) else {}


__all__ = [
    "build_role_snapshot_from_aria",
    "from_cdp_ax_tree",
    "is_trivial_snapshot",
    "refs_from_snapshot_payload",
]
