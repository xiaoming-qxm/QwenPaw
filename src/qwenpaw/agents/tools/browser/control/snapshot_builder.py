# -*- coding: utf-8 -*-
"""Structured snapshot builders for Browser Control."""

from __future__ import annotations

from typing import Any

import hashlib
from typing import cast

from agentscope.message import DataBlock, URLSource
from pydantic import AnyUrl

from ..runtime import logger
from .errors import BrowserControlRecoverableError

_DOM_TREE_FALLBACK_DEPTH = 8


def _url_source(url: str, media_type: str) -> URLSource:
    return URLSource(url=cast(AnyUrl, url), media_type=media_type)


def _control_snapshot_hash(snapshot: str) -> str:
    return hashlib.md5(snapshot.encode("utf-8")).hexdigest()[:16]


def _control_refs_have_interactive_role(refs: dict[str, dict]) -> bool:
    if not refs:
        return False
    from qwenpaw.agents.tools.browser_snapshot import INTERACTIVE_ROLES

    return any(
        str(ref.get("role") or "").lower() in INTERACTIVE_ROLES
        for ref in refs.values()
        if isinstance(ref, dict)
    )


async def _control_visual_context_block(session: Any) -> DataBlock | None:
    try:
        result = await session.send(
            "Page.captureScreenshot",
            {"format": "jpeg", "quality": 60},
        )
    except BrowserControlRecoverableError:
        logger.debug(
            "Failed to capture adaptive visual fallback",
            exc_info=True,
        )
        return None

    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, str) or not data:
        return None
    return DataBlock(
        source=_url_source(f"data:image/jpeg;base64,{data}", "image/jpeg"),
        name="browser-control-visual-context.jpg",
    )


def _control_escalation_payload(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "failed_ref": str(info.get("failed_ref") or ""),
        "consecutive_no_effect": int(info.get("consecutive_no_effect") or 0),
        "hint": (
            "The same target did not change the structured snapshot. "
            "Use the attached screenshot to inspect visual state before "
            "choosing a different target or coordinate click."
        ),
    }


async def build_control_snapshot(
    session: Any,
) -> tuple[str, dict[str, dict], bool]:
    """Build an accessibility snapshot with a bounded DOM fallback."""
    ax_tree = await session.send("Accessibility.getFullAXTree")
    from qwenpaw.agents.tools.browser_snapshot import from_cdp_ax_tree

    snapshot, refs = from_cdp_ax_tree(ax_tree)
    snapshot_text = snapshot.strip()
    degraded_snapshot = False
    if not refs and (
        len(snapshot_text) < 50 or snapshot_text.startswith("- RootWebArea")
    ):
        degraded_snapshot = True
        try:
            fallback_snapshot, fallback_refs = await _fallback_dom_snapshot(
                session,
            )
        except BrowserControlRecoverableError:
            logger.debug(
                "Failed to build control bounded DOM fallback",
                exc_info=True,
            )
        else:
            if fallback_snapshot != "(empty)":
                snapshot = fallback_snapshot
                refs = fallback_refs
    if refs and not _control_refs_have_interactive_role(refs):
        degraded_snapshot = True
    return snapshot, refs, degraded_snapshot


async def _fallback_dom_snapshot(session: Any) -> tuple[str, dict[str, dict]]:
    dom_tree = await session.send(
        "DOM.getDocument",
        {"depth": _DOM_TREE_FALLBACK_DEPTH, "pierce": True},
    )
    from qwenpaw.agents.tools.browser_snapshot import from_cdp_dom_tree

    tree_snapshot, tree_refs = from_cdp_dom_tree(dom_tree)
    if tree_snapshot != "(empty)":
        return tree_snapshot, tree_refs

    # Some modern pages expose only the root node through AX and shallow DOM
    # snapshots. Use DOMSnapshot only after the bounded tree produced no text.
    dom_snapshot = await session.send(
        "DOMSnapshot.captureSnapshot",
        {
            "computedStyles": [],
            "includeDOMRects": True,
            "includePaintOrder": True,
        },
    )
    from qwenpaw.agents.tools.browser_snapshot import from_cdp_dom_snapshot

    return from_cdp_dom_snapshot(dom_snapshot)


__all__ = [
    "_control_escalation_payload",
    "_control_snapshot_hash",
    "_control_visual_context_block",
    "_url_source",
    "build_control_snapshot",
]
