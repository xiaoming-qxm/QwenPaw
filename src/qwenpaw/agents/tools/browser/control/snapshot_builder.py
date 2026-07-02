# -*- coding: utf-8 -*-
"""Structured snapshot builders for Browser Control."""

from __future__ import annotations

import asyncio
from typing import Any

import hashlib
from typing import cast

from agentscope.message import DataBlock, URLSource
from pydantic import AnyUrl

from ..runtime import logger
from .errors import BrowserControlRecoverableError

_DOM_TREE_FALLBACK_DEPTH = 8
_DOM_TREE_AX_FAILURE_FALLBACK_DEPTH = 18
_CONTROL_AX_SNAPSHOT_TIMEOUT_SECONDS = 5.0
_CONTROL_DOM_TREE_TIMEOUT_SECONDS = 5.0
_CONTROL_DOM_SNAPSHOT_TIMEOUT_SECONDS = 5.0
_CONTROL_VISUAL_CONTEXT_TIMEOUT_SECONDS = 5.0


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
        result = await _send_with_timeout(
            session,
            "Page.captureScreenshot",
            {"format": "jpeg", "quality": 60},
            timeout=_CONTROL_VISUAL_CONTEXT_TIMEOUT_SECONDS,
        )
    except (BrowserControlRecoverableError, asyncio.TimeoutError):
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
    from qwenpaw.agents.tools.browser_snapshot import from_cdp_ax_tree

    try:
        ax_tree = await _send_with_timeout(
            session,
            "Accessibility.getFullAXTree",
            timeout=_CONTROL_AX_SNAPSHOT_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "Failed to build control AX snapshot; using bounded DOM fallback",
            exc_info=True,
        )
        try:
            fallback_snapshot, fallback_refs = await _fallback_dom_snapshot(
                session,
                depth=_DOM_TREE_AX_FAILURE_FALLBACK_DEPTH,
                allow_dom_snapshot=False,
            )
        except Exception:
            logger.debug(
                "Failed to build deep DOM fallback; using shallow fallback",
                exc_info=True,
            )
            fallback_snapshot, fallback_refs = await _fallback_dom_snapshot(
                session,
                depth=_DOM_TREE_FALLBACK_DEPTH,
                allow_dom_snapshot=False,
            )
        return fallback_snapshot, fallback_refs, True

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


async def _fallback_dom_snapshot(
    session: Any,
    *,
    depth: int = _DOM_TREE_FALLBACK_DEPTH,
    allow_dom_snapshot: bool = True,
) -> tuple[str, dict[str, dict]]:
    dom_tree = await _send_with_timeout(
        session,
        "DOM.getDocument",
        {"depth": int(depth), "pierce": True},
        timeout=_CONTROL_DOM_TREE_TIMEOUT_SECONDS,
    )
    from qwenpaw.agents.tools.browser_snapshot import from_cdp_dom_tree

    tree_snapshot, tree_refs = from_cdp_dom_tree(dom_tree)
    if tree_snapshot != "(empty)":
        return tree_snapshot, tree_refs
    if not allow_dom_snapshot:
        return tree_snapshot, tree_refs

    # Some modern pages expose only the root node through AX and shallow DOM
    # snapshots. Use DOMSnapshot only after the bounded tree produced no text.
    dom_snapshot = await _send_with_timeout(
        session,
        "DOMSnapshot.captureSnapshot",
        {
            "computedStyles": [],
            "includeDOMRects": True,
            "includePaintOrder": True,
        },
        timeout=_CONTROL_DOM_SNAPSHOT_TIMEOUT_SECONDS,
    )
    from qwenpaw.agents.tools.browser_snapshot import from_cdp_dom_snapshot

    return from_cdp_dom_snapshot(dom_snapshot)


async def _send_with_timeout(
    session: Any,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float,
) -> dict[str, Any]:
    return await asyncio.wait_for(
        session.send(method, params or {}),
        timeout=max(float(timeout), 0.1),
    )


__all__ = [
    "_control_escalation_payload",
    "_control_snapshot_hash",
    "_control_visual_context_block",
    "_url_source",
    "build_control_snapshot",
]
