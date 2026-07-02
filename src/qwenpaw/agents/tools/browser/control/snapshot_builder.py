# -*- coding: utf-8 -*-
"""Structured snapshot builders for Browser Control."""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any
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
_CONTROL_ACTION_DOM_DEPTH = 10
_CONTROL_ACTION_DOM_TIMEOUT_SECONDS = 2.0
_CONTROL_ACTION_QUAD_TIMEOUT_SECONDS = 0.8
_CONTROL_LINK_REF_ENRICH_TIMEOUT_SECONDS = 1.5
_CONTROL_LINK_REF_ENRICH_LIMIT = 30
_CONTROL_ACTION_MAX_LABEL_LENGTH = 96
_CONTROL_ACTION_MAX_AREA_RATIO = 0.2
_CONTROL_ACTION_TEXT_RE = re.compile(
    "|".join(
        (
            "加入购物车",
            "加购",
            "购物车",
            "购买",
            "立即",
            "结算",
            "提交",
            "确定",
            "确认",
            "删除",
            "全选",
            "清空",
            "搜索",
            "add to cart",
            "cart",
            "buy",
            "checkout",
            "submit",
            "confirm",
            "delete",
            "search",
        ),
    ),
    re.IGNORECASE,
)
_CONTROL_ACTION_CLASS_RE = re.compile(
    "|".join(
        (
            "btn",
            "button",
            "action",
            "cart",
            "buy",
            "purchase",
            "checkout",
            "submit",
            "confirm",
            "delete",
            "search",
            "sku",
            "spec",
            "variant",
            "option",
            "select",
        ),
    ),
    re.IGNORECASE,
)
_CONTROL_ACTION_SEMANTIC_LABELS = (
    (
        re.compile(
            r"(?:add|plus)[-_\s]*(?:to[-_\s]*)?cart|"
            r"cart[-_\s]*(?:add|plus)|addcart|cartadd",
            re.IGNORECASE,
        ),
        "add cart",
    ),
    (re.compile(r"cart|basket", re.IGNORECASE), "cart"),
    (re.compile(r"buy[-_\s]*now|buy|purchase", re.IGNORECASE), "buy"),
    (re.compile(r"checkout|settle", re.IGNORECASE), "checkout"),
    (re.compile(r"submit", re.IGNORECASE), "submit"),
    (re.compile(r"confirm|ok", re.IGNORECASE), "confirm"),
    (re.compile(r"delete|remove|clear", re.IGNORECASE), "delete"),
    (re.compile(r"search", re.IGNORECASE), "search"),
    (re.compile(r"sku|spec|variant|option|select", re.IGNORECASE), "option"),
)
_CONTROL_ACTION_TEXT_ATTRIBUTES = (
    "aria-label",
    "title",
    "alt",
    "placeholder",
    "value",
)
_CONTROL_ACTION_CLICK_ATTRIBUTES = {
    "onclick",
    "onmousedown",
    "onmouseup",
    "data-click",
    "data-clickid",
}
_CONTROL_ACTION_SKIPPED_NODES = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
}
_CONTROL_ACTION_STRUCTURAL_NODES = {
    "#document",
    "document",
    "html",
    "body",
}
_CONTROL_ACTION_INTERACTIVE_ROLES = {
    "button",
    "link",
    "menuitem",
    "tab",
    "option",
    "checkbox",
    "radio",
    "combobox",
    "listbox",
    "textbox",
    "searchbox",
    "switch",
}


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
            fallback_refs,
        )
        return fallback_snapshot, fallback_refs, True

    snapshot, refs = from_cdp_ax_tree(ax_tree)
    await _enrich_ax_link_refs_with_dom_attributes(session, refs)
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
    snapshot = await _append_action_targets(session, snapshot, refs)
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


async def _enrich_ax_link_refs_with_dom_attributes(
    session: Any,
    refs: dict[str, dict],
) -> None:
    enriched = 0
    for target in refs.values():
        if enriched >= _CONTROL_LINK_REF_ENRICH_LIMIT:
            return
        if not isinstance(target, dict):
            continue
        role = str(target.get("role") or "").strip().lower()
        if role != "link" or target.get("href"):
            continue
        backend_node_id = _positive_int(target.get("backendNodeId"))
        if backend_node_id is None:
            continue
        try:
            result = await _send_with_timeout(
                session,
                "DOM.describeNode",
                {"backendNodeId": backend_node_id, "depth": 0},
                timeout=_CONTROL_LINK_REF_ENRICH_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001
            logger.debug("Failed to enrich AX link ref", exc_info=True)
            continue
        attributes = _describe_node_attributes(result)
        href = str(attributes.get("href") or "").strip()
        if href:
            target["href"] = href
        link_target = str(attributes.get("target") or "").strip()
        if link_target:
            target["target"] = link_target
        enriched += 1


def _describe_node_attributes(result: dict[str, Any]) -> dict[str, str]:
    node = result.get("node") if isinstance(result, dict) else None
    if not isinstance(node, dict):
        result_value = (
            result.get("result") if isinstance(result, dict) else None
        )
        if isinstance(result_value, dict):
            node = result_value.get("node")
    if not isinstance(node, dict):
        return {}
    attributes = node.get("attributes")
    if not isinstance(attributes, list):
        return {}
    parsed: dict[str, str] = {}
    for index in range(0, len(attributes) - 1, 2):
        name = str(attributes[index] or "").strip().lower()
        if not name:
            continue
        parsed[name] = str(attributes[index + 1] or "")
    return parsed


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


async def _append_page_state(session: Any, snapshot: str) -> str:
    line = await _control_page_state_line(session)
    if not line:
        return snapshot
    snapshot = snapshot.strip() or "(empty)"
    if snapshot == "(empty)":
        return line
    return f"{line}\n{snapshot}"


async def _append_action_targets(
    session: Any,
    snapshot: str,
    refs: dict[str, dict],
) -> str:
    lines = await _control_dom_action_target_lines(session, refs)
    seen_text = {_action_target_line_text(line) for line in lines}
    for line in await _control_action_target_lines(session):
        line_text = _action_target_line_text(line)
        if line_text and line_text in seen_text:
            continue
        if line_text:
            seen_text.add(line_text)
        lines.append(line)
    if not lines:
        return snapshot
    snapshot = snapshot.strip() or "(empty)"
    if snapshot == "(empty)":
        return "\n".join(lines)
    snapshot_lines = snapshot.splitlines()
    if snapshot_lines and snapshot_lines[0].startswith("- page_state "):
        return "\n".join([snapshot_lines[0], *lines, *snapshot_lines[1:]])
    return "\n".join([*lines, *snapshot_lines])


async def _control_dom_action_target_lines(
    session: Any,
    refs: dict[str, dict],
) -> list[str]:
    try:
        result = await _send_with_timeout(
            session,
            "DOM.getDocument",
            {"depth": _CONTROL_ACTION_DOM_DEPTH, "pierce": True},
            timeout=_CONTROL_ACTION_DOM_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Failed to read DOM action targets", exc_info=True)
        return []

    root = result.get("root") if isinstance(result, dict) else None
    if not isinstance(root, dict):
        return []

    candidates = _collect_dom_action_candidates(root)
    if not candidates:
        return []

    viewport = await _dom_action_viewport_size(session)
    next_ref = _next_action_ref(refs)
    lines: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if len(lines) >= _CONTROL_ACTION_TARGETS_LIMIT:
            break
        node_params = _dom_action_node_params(candidate)
        if node_params is None:
            continue
        point = await _dom_action_point(
            session,
            node_params,
            viewport=viewport,
        )
        if point is None:
            continue
        text = _clean_action_target_text(candidate.get("text"))
        if not text:
            continue
        tag = _clean_action_target_token(candidate.get("tag") or "element")
        role = _clean_action_target_token(candidate.get("role") or "button")
        x, y = (_rounded_number(point[0]), _rounded_number(point[1]))
        dedupe_key = f"{text}|{tag}|{role}|{x}|{y}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        ref = next_ref()
        target = {
            "role": role or "button",
            "name": text,
            "x": x,
            "y": y,
        }
        target.update(node_params)
        href = str(candidate.get("href") or "").strip()
        if href:
            target["href"] = href
        link_target = str(candidate.get("target") or "").strip()
        if link_target:
            target["target"] = link_target
        refs[ref] = target
        role_part = f" role={role}" if role else ""
        lines.append(
            f'- action_target "{_quote_snapshot_text(text)}" '
            f"[ref={ref}] tag={tag}{role_part} x={x} y={y}",
        )
    return lines


def _collect_dom_action_candidates(
    root: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_nodes: set[tuple[str, str]] = set()
    order = 0

    def visit(node: dict[str, Any]) -> None:
        nonlocal order
        if len(candidates) >= _CONTROL_ACTION_TARGETS_LIMIT * 4:
            return
        node_name = str(node.get("nodeName") or "").lower()
        if node_name in _CONTROL_ACTION_SKIPPED_NODES:
            return
        node_type = node.get("nodeType")
        if node_type == 3 or node_name == "#text":
            return

        attributes = _dom_action_attributes(node.get("attributes"))
        visible_text = _dom_action_text(node, attributes)
        semantic_text = _dom_action_semantic_text(attributes)
        text = visible_text or semantic_text
        role = _dom_action_role(node_name, attributes)
        class_name = str(attributes.get("class") or "")
        has_action_text = bool(_CONTROL_ACTION_TEXT_RE.search(text))
        has_action_class = bool(_CONTROL_ACTION_CLASS_RE.search(class_name))
        has_click_attr = any(
            name in attributes for name in _CONTROL_ACTION_CLICK_ATTRIBUTES
        )
        is_structural = node_name in _CONTROL_ACTION_STRUCTURAL_NODES
        is_compound_label = len(text) > _CONTROL_ACTION_MAX_LABEL_LENGTH
        if text and (
            not is_structural
            and not is_compound_label
            and (
                role is not None
                or has_action_text
                or has_action_class
                or has_click_attr
            )
        ):
            key = (str(node.get("backendNodeId") or node.get("nodeId")), text)
            if key not in seen_nodes:
                seen_nodes.add(key)
                order += 1
                candidates.append(
                    {
                        "tag": node_name or "element",
                        "role": role or "button",
                        "text": text,
                        "backendNodeId": node.get("backendNodeId"),
                        "nodeId": node.get("nodeId"),
                        "href": attributes.get("href", ""),
                        "target": attributes.get("target", ""),
                        "priority": _dom_action_priority(
                            role,
                            has_action_text,
                            has_action_class,
                        ),
                        "order": order,
                    },
                )

        for key in ("children", "shadowRoots", "pseudoElements"):
            children = node.get(key)
            if not isinstance(children, list):
                continue
            for child in children:
                if isinstance(child, dict):
                    visit(child)

        content_document = node.get("contentDocument")
        if isinstance(content_document, dict):
            visit(content_document)

    visit(root)
    candidates.sort(
        key=lambda item: (
            _int_or_default(item.get("priority"), 99),
            _int_or_default(item.get("order"), 0),
        ),
    )
    return candidates


def _dom_action_attributes(attributes: Any) -> dict[str, str]:
    if not isinstance(attributes, list):
        return {}
    result: dict[str, str] = {}
    for index in range(0, len(attributes) - 1, 2):
        name = str(attributes[index] or "").strip().lower()
        if not name:
            continue
        result[name] = str(attributes[index + 1] or "")
    return result


def _dom_action_role(
    node_name: str,
    attributes: dict[str, str],
) -> str | None:
    role = str(attributes.get("role") or "").strip().lower()
    if role in _CONTROL_ACTION_INTERACTIVE_ROLES:
        return role
    if node_name == "a" and attributes.get("href"):
        return "link"
    if node_name in {"button", "summary"}:
        return "button"
    if node_name == "select":
        return "combobox"
    if node_name == "textarea":
        return "textbox"
    if node_name == "option":
        return "option"
    if node_name == "input":
        input_type = str(attributes.get("type") or "text").lower()
        if input_type == "checkbox":
            return "checkbox"
        if input_type == "radio":
            return "radio"
        if input_type == "search":
            return "searchbox"
        if input_type in {"button", "submit", "reset"}:
            return "button"
        return "textbox"
    class_name = str(attributes.get("class") or "")
    if _CONTROL_ACTION_CLASS_RE.search(class_name):
        return "button"
    if any(name in attributes for name in _CONTROL_ACTION_CLICK_ATTRIBUTES):
        return "button"
    return None


def _dom_action_text(
    node: dict[str, Any],
    attributes: dict[str, str],
) -> str:
    pieces: list[str] = []

    def add(value: Any) -> None:
        text = str(value or "")
        if text:
            pieces.append(text)

    for attr_name in _CONTROL_ACTION_TEXT_ATTRIBUTES:
        add(attributes.get(attr_name))

    def walk(current: dict[str, Any]) -> None:
        if len(" ".join(pieces)) >= 600:
            return
        node_name = str(current.get("nodeName") or "").lower()
        if node_name in _CONTROL_ACTION_SKIPPED_NODES:
            return
        node_type = current.get("nodeType")
        if node_type == 3 or node_name == "#text":
            add(current.get("nodeValue"))
            return
        current_attributes = _dom_action_attributes(
            current.get("attributes"),
        )
        for attr_name in _CONTROL_ACTION_TEXT_ATTRIBUTES:
            add(current_attributes.get(attr_name))
        for key in ("children", "shadowRoots", "pseudoElements"):
            children = current.get(key)
            if not isinstance(children, list):
                continue
            for child in children:
                if isinstance(child, dict):
                    walk(child)
                if len(" ".join(pieces)) >= 600:
                    return

    walk(node)
    text = " ".join(" ".join(pieces).split())
    return text[:180]


def _dom_action_semantic_text(attributes: dict[str, str]) -> str:
    source = " ".join(
        str(attributes.get(name) or "")
        for name in (
            "aria-label",
            "title",
            "alt",
            "data-title",
            "data-action",
            "data-role",
            "data-testid",
            "data-test",
            "id",
            "class",
            "href",
        )
    )
    if not source.strip():
        return ""

    labels: list[str] = []
    for pattern, label in _CONTROL_ACTION_SEMANTIC_LABELS:
        if pattern.search(source) and label not in labels:
            labels.append(label)
        if len(labels) >= 3:
            break
    if "add cart" in labels:
        return "add cart"
    if "buy" in labels:
        return "buy"
    return " ".join(labels)


def _dom_action_priority(
    role: str | None,
    has_action_text: bool,
    has_action_class: bool,
) -> int:
    if has_action_text:
        return 0
    if has_action_class:
        return 1
    if role in {"button", "option", "combobox", "checkbox", "radio"}:
        return 2
    return 3


def _dom_action_node_params(
    candidate: dict[str, Any],
) -> dict[str, int] | None:
    backend_node_id = _positive_int(candidate.get("backendNodeId"))
    if backend_node_id is not None:
        return {"backendNodeId": backend_node_id}
    node_id = _positive_int(candidate.get("nodeId"))
    if node_id is not None:
        return {"nodeId": node_id}
    return None


async def _dom_action_point(
    session: Any,
    node_params: dict[str, int],
    *,
    viewport: tuple[float, float] = (0.0, 0.0),
) -> tuple[float, float] | None:
    try:
        result = await _send_with_timeout(
            session,
            "DOM.getContentQuads",
            node_params,
            timeout=_CONTROL_ACTION_QUAD_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        return None
    quads = result.get("quads") if isinstance(result, dict) else None
    if _quad_area_exceeds_viewport(quads, viewport):
        return None
    return _quad_center(quads)


async def _dom_action_viewport_size(session: Any) -> tuple[float, float]:
    try:
        metrics = await _send_with_timeout(
            session,
            "Page.getLayoutMetrics",
            timeout=_CONTROL_PAGE_STATE_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        return (0.0, 0.0)
    if not isinstance(metrics, dict):
        return (0.0, 0.0)
    for key in (
        "cssVisualViewport",
        "visualViewport",
        "cssLayoutViewport",
        "layoutViewport",
        "contentSize",
    ):
        viewport = metrics.get(key)
        if not isinstance(viewport, dict):
            continue
        width = viewport.get("clientWidth", viewport.get("width"))
        height = viewport.get("clientHeight", viewport.get("height"))
        if isinstance(width, (int, float)) and isinstance(
            height,
            (int, float),
        ):
            if width > 0 and height > 0:
                return (float(width), float(height))
    return (0.0, 0.0)


def _quad_center(quads: Any) -> tuple[float, float] | None:
    if not isinstance(quads, list) or not quads:
        return None
    quad = quads[0]
    if not isinstance(quad, list) or len(quad) < 8:
        return None
    xs = [float(quad[index]) for index in range(0, 8, 2)]
    ys = [float(quad[index]) for index in range(1, 8, 2)]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _quad_area_exceeds_viewport(
    quads: Any,
    viewport: tuple[float, float],
) -> bool:
    if not isinstance(quads, list) or not quads:
        return False
    viewport_width, viewport_height = viewport
    viewport_area = float(viewport_width) * float(viewport_height)
    if viewport_area <= 0:
        return False
    area = _quad_area(quads[0])
    return area > viewport_area * _CONTROL_ACTION_MAX_AREA_RATIO


def _quad_area(quad: Any) -> float:
    if not isinstance(quad, list) or len(quad) < 8:
        return 0.0
    points = [
        (float(quad[index]), float(quad[index + 1]))
        for index in range(0, 8, 2)
    ]
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _next_action_ref(refs: dict[str, dict]):
    next_index = 1
    for ref in refs:
        if ref.startswith("e") and ref[1:].isdigit():
            next_index = max(next_index, int(ref[1:]) + 1)

    def build() -> str:
        nonlocal next_index
        while f"e{next_index}" in refs:
            next_index += 1
        ref = f"e{next_index}"
        next_index += 1
        return ref

    return build


def _action_target_line_text(line: str) -> str:
    match = re.search(r'- action_target "((?:\\"|[^"])*)"', line)
    if not match:
        return ""
    return match.group(1).replace('\\"', '"').replace("\\\\", "\\")


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
