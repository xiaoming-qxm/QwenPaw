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
_CONTROL_PAGE_STATE_TIMEOUT_SECONDS = 1.5
_CONTROL_ACTION_TARGETS_TIMEOUT_SECONDS = 1.5
_CONTROL_ACTION_TARGETS_LIMIT = 12


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
        fallback_snapshot = await _append_page_state(session, fallback_snapshot)
        fallback_snapshot = await _append_action_targets(
            session,
            fallback_snapshot,
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
    snapshot = await _append_page_state(session, snapshot)
    snapshot = await _append_action_targets(session, snapshot)
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


async def _append_page_state(session: Any, snapshot: str) -> str:
    line = await _control_page_state_line(session)
    if not line:
        return snapshot
    snapshot = snapshot.strip() or "(empty)"
    if snapshot == "(empty)":
        return line
    return f"{line}\n{snapshot}"


async def _append_action_targets(session: Any, snapshot: str) -> str:
    lines = await _control_action_target_lines(session)
    if not lines:
        return snapshot
    snapshot = snapshot.strip() or "(empty)"
    if snapshot == "(empty)":
        return "\n".join(lines)
    snapshot_lines = snapshot.splitlines()
    if snapshot_lines and snapshot_lines[0].startswith("- page_state "):
        return "\n".join([snapshot_lines[0], *lines, *snapshot_lines[1:]])
    return "\n".join([*lines, *snapshot_lines])


async def _control_action_target_lines(session: Any) -> list[str]:
    try:
        result = await _send_with_timeout(
            session,
            "Runtime.evaluate",
            {
                "expression": _CONTROL_ACTION_TARGETS_SCRIPT,
                "returnByValue": True,
                "awaitPromise": False,
                "timeout": 1000,
            },
            timeout=_CONTROL_ACTION_TARGETS_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Failed to read control action targets", exc_info=True)
        return []
    value = _runtime_evaluate_value(result)
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for item in value[:_CONTROL_ACTION_TARGETS_LIMIT]:
        if not isinstance(item, dict):
            continue
        text = _clean_action_target_text(item.get("text"))
        if not text:
            continue
        tag = _clean_action_target_token(item.get("tag") or "element")
        role = _clean_action_target_token(item.get("role"))
        x = _rounded_number(item.get("x"))
        y = _rounded_number(item.get("y"))
        dedupe_key = f"{text}|{tag}|{role}|{x}|{y}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        role_part = f" role={role}" if role else ""
        lines.append(
            f'- action_target "{_quote_snapshot_text(text)}" '
            f"tag={tag}{role_part} x={x} y={y}",
        )
    return lines


async def _control_page_state_line(session: Any) -> str:
    try:
        result = await _send_with_timeout(
            session,
            "Runtime.evaluate",
            {
                "expression": _CONTROL_PAGE_STATE_SCRIPT,
                "returnByValue": True,
                "awaitPromise": False,
                "timeout": 1000,
            },
            timeout=_CONTROL_PAGE_STATE_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Failed to read control page state", exc_info=True)
        return ""
    value = _runtime_evaluate_value(result)
    if not isinstance(value, dict):
        return ""
    scroll_y = _rounded_number(value.get("scrollY"))
    max_scroll_y = _rounded_number(value.get("maxScrollY"))
    percent = _rounded_number(value.get("scrollPercent"))
    at_top = bool(value.get("atTop"))
    at_bottom = bool(value.get("atBottom"))
    return (
        '- page_state "'
        f"scroll_y={scroll_y} max_scroll_y={max_scroll_y} "
        f"scroll={percent}% at_top={str(at_top).lower()} "
        f"at_bottom={str(at_bottom).lower()}"
        '"'
    )


def _runtime_evaluate_value(result: dict[str, Any]) -> Any:
    remote_object = result.get("result") if isinstance(result, dict) else None
    if isinstance(remote_object, dict) and "result" in remote_object:
        remote_object = remote_object.get("result")
    if isinstance(remote_object, dict):
        return remote_object.get("value")
    return None


def _rounded_number(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    try:
        return int(round(float(str(value))))
    except (TypeError, ValueError):
        return 0


def _clean_action_target_text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > 80:
        text = f"{text[:77]}..."
    return text


def _clean_action_target_token(value: Any) -> str:
    token = "".join(
        char.lower()
        for char in str(value or "").strip()
        if char.isalnum() or char in {"_", "-"}
    )
    return token[:32]


def _quote_snapshot_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


_CONTROL_PAGE_STATE_SCRIPT = """
(() => {
  const doc = document.scrollingElement
    || document.documentElement
    || document.body;
  const viewportHeight = window.innerHeight || doc.clientHeight || 0;
  const scrollHeight = Math.max(
    doc.scrollHeight || 0,
    document.documentElement ? document.documentElement.scrollHeight || 0 : 0,
    document.body ? document.body.scrollHeight || 0 : 0
  );
  const scrollY = window.scrollY || doc.scrollTop || 0;
  const maxScrollY = Math.max(0, scrollHeight - viewportHeight);
  const scrollPercent = maxScrollY > 0
    ? Math.round((scrollY / maxScrollY) * 100)
    : 0;
  return {
    scrollY: Math.round(scrollY),
    maxScrollY: Math.round(maxScrollY),
    scrollPercent,
    atTop: scrollY <= 2,
    atBottom: maxScrollY <= 2 || scrollY >= maxScrollY - 2,
  };
})()
""".strip()


_CONTROL_ACTION_TARGETS_SCRIPT = """
(() => {
  function qwenpawCollectActionTargets() {
    const normalize = (value) => String(value || "")
      .replace(/\\s+/g, " ")
      .trim();
    const actionText = new RegExp([
      "加入购物车", "加购", "购物车", "购买", "立即", "马上",
      "结算", "提交", "确定", "确认", "删除", "全选", "清空",
      "搜索", "add to cart", "cart", "buy", "checkout", "submit",
      "confirm", "delete", "search"
    ].join("|"), "i");
    const actionClass = new RegExp([
      "btn", "button", "action", "cart", "buy", "purchase",
      "checkout", "submit", "confirm", "delete", "search"
    ].join("|"), "i");
    const selector = [
      "button",
      "a[href]",
      "input",
      "textarea",
      "select",
      "summary",
      "[role='button']",
      "[role='link']",
      "[role='menuitem']",
      "[role='tab']",
      "[tabindex]:not([tabindex='-1'])",
      "[onclick]",
      "[class*='btn' i]",
      "[class*='button' i]",
      "[class*='action' i]",
      "[class*='cart' i]",
      "[class*='buy' i]",
      "[class*='purchase' i]",
      "[class*='submit' i]",
      "[class*='confirm' i]",
      "[class*='delete' i]",
      "[class*='search' i]"
    ].join(",");
    const textOf = (element) => normalize([
      element.getAttribute("aria-label"),
      element.getAttribute("title"),
      element.getAttribute("alt"),
      "value" in element ? element.value : "",
      element.innerText || element.textContent
    ].filter(Boolean).join(" "));
    const visibleRect = (element) => {
      if (!element || element.nodeType !== Node.ELEMENT_NODE) return null;
      const style = window.getComputedStyle(element);
      if (
        style.display === "none" ||
        style.visibility === "hidden" ||
        Number(style.opacity || "1") === 0
      ) return null;
      const rect = element.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return null;
      if (
        rect.bottom < 0 ||
        rect.right < 0 ||
        rect.top > window.innerHeight ||
        rect.left > window.innerWidth
      ) return null;
      return rect;
    };
    const isSemantic = (element) => {
      const tag = element.tagName;
      const role = String(element.getAttribute("role") || "").toLowerCase();
      return (
        tag === "A" ||
        tag === "BUTTON" ||
        tag === "INPUT" ||
        tag === "SELECT" ||
        tag === "TEXTAREA" ||
        role === "button" ||
        role === "link" ||
        role === "menuitem" ||
        role === "tab" ||
        element.hasAttribute("onclick") ||
        element.hasAttribute("tabindex")
      );
    };
    const targets = [];
    const seen = new Set();
    for (const element of Array.from(document.querySelectorAll(selector))) {
      const rect = visibleRect(element);
      if (!rect) continue;
      const text = textOf(element);
      if (!text) continue;
      const cls = String(element.className || "");
      const semantic = isSemantic(element);
      const classLooksActionable = actionClass.test(cls);
      if (!semantic && !classLooksActionable && !actionText.test(text)) {
        continue;
      }
      if (!semantic && text.length > 120) continue;
      const x = Math.round(rect.left + rect.width / 2);
      const y = Math.round(rect.top + rect.height / 2);
      const key = `${text}|${element.tagName}|${x}|${y}`;
      if (seen.has(key)) continue;
      seen.add(key);
      targets.push({
        text: text.slice(0, 100),
        tag: element.tagName.toLowerCase(),
        role: String(element.getAttribute("role") || "").toLowerCase(),
        x,
        y
      });
      if (targets.length >= 12) break;
    }
    return targets;
  }
  return qwenpawCollectActionTargets();
})()
""".strip()


__all__ = [
    "_control_escalation_payload",
    "_control_action_target_lines",
    "_control_page_state_line",
    "_control_snapshot_hash",
    "_control_visual_context_block",
    "_url_source",
    "build_control_snapshot",
]
