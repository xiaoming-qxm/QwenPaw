# -*- coding: utf-8 -*-
"""Chrome target resolution helpers."""
# pylint: disable=consider-using-dict-items,too-many-return-statements

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable

from qwenpaw.browser.runtime.responses import logger
from qwenpaw.browser.canonical.contracts import CaptureGap, CoverageGap
from qwenpaw.browser.governance.errors import BrowserSDKError
from qwenpaw.browser.runtime.snapshot import (
    ProbeBatch,
    ProbeNode,
    ProbeRegion,
    SurfaceBoundary,
)
from .errors import RECOVERABLE_CONTROL_EXCEPTIONS, TargetResolutionFailed
from .navigation import _control_same_site, _control_url_key
from .ref_scope import (
    _control_canonical_context,
    _require_canonical_binding,
)
from .state import ControlState


_CANONICAL_ACTIONABLE_ROLES = {
    "button",
    "checkbox",
    "combobox",
    "link",
    "listbox",
    "menuitem",
    "option",
    "radio",
    "searchbox",
    "slider",
    "spinbutton",
    "switch",
    "tab",
    "textbox",
    "treeitem",
}

_CANONICAL_NON_VISIBLE_DOM_TAGS = frozenset(
    {"noscript", "script", "style", "template"},
)
_CANONICAL_STRUCTURAL_ARIA_ROLES = frozenset(
    {"generic", "none", "presentation"},
)


async def canonical_visual_candidate_backend_ids(
    session: Any,
    request: dict[str, Any],
) -> tuple[str, tuple[int, ...]]:
    """Hit-test bounded region samples after exact viewport revalidation."""
    try:
        frame_tree = await session.send("Page.getFrameTree")
        metrics = await session.send("Page.getLayoutMetrics")
        runtime = await session.send(
            "Runtime.evaluate",
            {
                "expression": (
                    "({x:Number(window.scrollX||0),"
                    "y:Number(window.scrollY||0),"
                    "dpr:Number(window.devicePixelRatio||1),"
                    "origin:String(window.location.origin||'')})"
                ),
                "returnByValue": True,
                "awaitPromise": False,
            },
        )
        frame = frame_tree.get("frameTree", {}).get("frame", {})
        visual = metrics.get("cssVisualViewport", {})
        content = metrics.get("cssContentSize", {})
        value = runtime.get("result", {}).get("value", {})
        viewport = (
            int(visual.get("clientWidth") or visual.get("width") or 0),
            int(visual.get("clientHeight") or visual.get("height") or 0),
        )
        current = {
            "generation": str(frame.get("loaderId") or ""),
            "viewport": viewport,
            "scroll": (
                float(value.get("x") or 0),
                float(value.get("y") or 0),
            ),
            "zoom": float(visual.get("scale") or 1.0),
            "device_pixel_ratio": float(value.get("dpr") or 1.0),
            "origin": str(value.get("origin") or ""),
            "layout": (
                int(content.get("width") or 0),
                int(content.get("height") or 0),
            ),
        }
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        return "UNAVAILABLE", ()
    if any(
        current[key] != _visual_request_value(request, key)
        for key in (
            "generation",
            "viewport",
            "scroll",
            "zoom",
            "device_pixel_ratio",
            "layout",
        )
    ):
        return "STALE", ()
    request["_canonical_current_origin"] = current["origin"]
    width, height = viewport
    x0 = float(request.get("x") or 0) * width
    y0 = float(request.get("y") or 0) * height
    x1 = x0 + float(request.get("width") or 0) * width
    y1 = y0 + float(request.get("height") or 0) * height
    points = (
        ((x0 + x1) / 2, (y0 + y1) / 2),
        (x0 + 1, y0 + 1),
        (x1 - 1, y0 + 1),
        (x0 + 1, y1 - 1),
        (x1 - 1, y1 - 1),
    )
    candidates: list[int] = []
    try:
        for x, y in points:
            hit = await session.send(
                "DOM.getNodeForLocation",
                {
                    "x": max(0, int(x)),
                    "y": max(0, int(y)),
                    "includeUserAgentShadowDOM": True,
                    "ignorePointerEventsNone": False,
                },
            )
            backend_id = hit.get("backendNodeId")
            if isinstance(backend_id, int) and backend_id not in candidates:
                candidates.append(backend_id)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return "UNAVAILABLE", ()
    return "AVAILABLE", tuple(candidates)


def _visual_request_value(request: dict[str, Any], key: str) -> object:
    value = request.get(key)
    if key in {"viewport", "scroll", "layout"} and isinstance(
        value,
        (list, tuple),
    ):
        return tuple(value)
    return value


def _canonical_geometry_digest(quad: tuple[float, ...]) -> str:
    return sha256(
        json.dumps(quad, separators=(",", ":")).encode(),
    ).hexdigest()


async def canonical_visual_geometry(
    session: Any,
    backend_id: int,
) -> tuple[str, tuple[float, float]] | None:
    """Read one exact native quad and its internal injection point."""
    quad = await _canonical_visual_quad(session, backend_id)
    if quad is None:
        return None
    point = (
        sum(quad[index] for index in (0, 2, 4, 6)) / 4,
        sum(quad[index] for index in (1, 3, 5, 7)) / 4,
    )
    return _canonical_geometry_digest(quad), point


async def canonical_visual_geometry_in_region(
    session: Any,
    backend_id: int,
    request: dict[str, Any],
) -> tuple[str, tuple[float, float]] | None:
    """Return exact geometry only when its quad intersects VisualRegion."""
    quad = await _canonical_visual_quad(session, backend_id)
    if quad is None:
        return None
    viewport = _visual_request_value(request, "viewport")
    if (
        not isinstance(viewport, tuple)
        or len(viewport) != 2
        or not all(isinstance(item, (int, float)) for item in viewport)
    ):
        return None
    width, height = float(viewport[0]), float(viewport[1])
    if width <= 0 or height <= 0:
        return None
    region_left = float(request.get("x") or 0) * width
    region_top = float(request.get("y") or 0) * height
    region_right = region_left + float(request.get("width") or 0) * width
    region_bottom = region_top + float(request.get("height") or 0) * height
    quad_left = min(quad[0::2])
    quad_right = max(quad[0::2])
    quad_top = min(quad[1::2])
    quad_bottom = max(quad[1::2])
    if (
        quad_right <= region_left
        or quad_left >= region_right
        or quad_bottom <= region_top
        or quad_top >= region_bottom
    ):
        return None
    point = (
        sum(quad[index] for index in (0, 2, 4, 6)) / 4,
        sum(quad[index] for index in (1, 3, 5, 7)) / 4,
    )
    return _canonical_geometry_digest(quad), point


async def canonical_visual_backend_intersects_region(
    session: Any,
    backend_id: int,
    request: dict[str, Any],
) -> bool | None:
    """Prove whether one private native surface intersects VisualRegion."""
    quad = await _canonical_visual_quad(session, backend_id)
    if quad is None:
        return None
    viewport = _visual_request_value(request, "viewport")
    if (
        not isinstance(viewport, tuple)
        or len(viewport) != 2
        or not all(isinstance(item, (int, float)) for item in viewport)
    ):
        return None
    width, height = float(viewport[0]), float(viewport[1])
    if width <= 0 or height <= 0:
        return None
    region_left = float(request.get("x") or 0) * width
    region_top = float(request.get("y") or 0) * height
    region_right = region_left + float(request.get("width") or 0) * width
    region_bottom = region_top + float(request.get("height") or 0) * height
    quad_left = min(quad[0::2])
    quad_right = max(quad[0::2])
    quad_top = min(quad[1::2])
    quad_bottom = max(quad[1::2])
    return not (
        quad_right <= region_left
        or quad_left >= region_right
        or quad_bottom <= region_top
        or quad_top >= region_bottom
    )


async def canonical_visual_target_is_current_hit(
    session: Any,
    *,
    backend_id: int,
    point: tuple[float, float],
) -> bool:
    """Prove issuance-time visibility and exact hit ancestry."""
    try:
        hit = await session.send(
            "DOM.getNodeForLocation",
            {
                "x": max(0, int(point[0])),
                "y": max(0, int(point[1])),
                "includeUserAgentShadowDOM": True,
                "ignorePointerEventsNone": False,
            },
        )
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False
    hit_backend_id = hit.get("backendNodeId")
    return isinstance(
        hit_backend_id,
        int,
    ) and await _canonical_hit_is_target_or_descendant(
        session,
        hit_backend_id=hit_backend_id,
        target_backend_id=backend_id,
    )


async def _canonical_visual_quad(
    session: Any,
    backend_id: int,
) -> tuple[float, ...] | None:
    """Read one bounded native content quad without page-derived ranking."""
    try:
        payload = await session.send(
            "DOM.getContentQuads",
            {"backendNodeId": int(backend_id)},
        )
        quads = payload.get("quads")
        if not isinstance(quads, list) or not quads:
            return None
        raw = quads[0]
        if not isinstance(raw, (tuple, list)) or len(raw) != 8:
            return None
        quad = tuple(float(item) for item in raw)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return None
    return quad


async def _canonical_current_visual_metrics(
    session: Any,
) -> dict[str, object] | None:
    try:
        frame_tree = await session.send("Page.getFrameTree")
        metrics = await session.send("Page.getLayoutMetrics")
        runtime = await session.send(
            "Runtime.evaluate",
            {
                "expression": (
                    "({x:Number(window.scrollX||0),"
                    "y:Number(window.scrollY||0),"
                    "dpr:Number(window.devicePixelRatio||1),"
                    "origin:String(window.location.origin||'')})"
                ),
                "returnByValue": True,
                "awaitPromise": False,
            },
        )
        frame = frame_tree.get("frameTree", {}).get("frame", {})
        visual = metrics.get("cssVisualViewport", {})
        content = metrics.get("cssContentSize", {})
        value = runtime.get("result", {}).get("value", {})
        return {
            "generation": str(frame.get("loaderId") or ""),
            "viewport": (
                int(visual.get("clientWidth") or visual.get("width") or 0),
                int(visual.get("clientHeight") or visual.get("height") or 0),
            ),
            "scroll": (
                float(value.get("x") or 0),
                float(value.get("y") or 0),
            ),
            "zoom": float(visual.get("scale") or 1.0),
            "device_pixel_ratio": float(value.get("dpr") or 1.0),
            "origin": str(value.get("origin") or ""),
            "layout": (
                int(content.get("width") or 0),
                int(content.get("height") or 0),
            ),
        }
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        return None


def _canonical_binding_backend_id(
    binding: dict[str, object],
) -> int | None:
    identity = binding.get("native_identity")
    if not isinstance(identity, (tuple, list)):
        return None
    for item in identity:
        if (
            isinstance(item, (tuple, list))
            and len(item) == 2
            and item[0] == "backendNodeId"
            and isinstance(item[1], int)
        ):
            return item[1]
    return None


async def canonical_live_target_point(
    session: Any,
    binding: dict[str, object],
) -> tuple[float, float] | None:
    """Revalidate visual epoch, native quad, and hit receiver."""
    if bool(binding.get("visual_context_ref")):
        current = await _canonical_current_visual_metrics(session)
        expected = {
            "generation": binding.get("visual_generation"),
            "viewport": binding.get("visual_viewport"),
            "scroll": binding.get("visual_scroll"),
            "zoom": binding.get("visual_zoom"),
            "device_pixel_ratio": binding.get(
                "visual_device_pixel_ratio",
            ),
            "layout": binding.get("visual_layout"),
        }
        if current is None or any(
            current[key] != expected[key] for key in expected
        ):
            return None
        surface_origin = str(binding.get("surface_origin") or "")
        if surface_origin and current.get("origin") != surface_origin:
            return None
    backend_id = _canonical_binding_backend_id(binding)
    if backend_id is None:
        return None
    geometry = await canonical_visual_geometry(session, backend_id)
    if geometry is None:
        return None
    geometry_digest, point = geometry
    expected_digest = str(binding.get("geometry_digest") or "")
    if expected_digest and geometry_digest != expected_digest:
        return None
    try:
        hit = await session.send(
            "DOM.getNodeForLocation",
            {
                "x": max(0, int(point[0])),
                "y": max(0, int(point[1])),
                "includeUserAgentShadowDOM": True,
                "ignorePointerEventsNone": False,
            },
        )
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return None
    hit_backend_id = hit.get("backendNodeId")
    if not isinstance(
        hit_backend_id,
        int,
    ) or not await _canonical_hit_is_target_or_descendant(
        session,
        hit_backend_id=hit_backend_id,
        target_backend_id=backend_id,
    ):
        return None
    return point


async def _canonical_hit_is_target_or_descendant(
    session: Any,
    *,
    hit_backend_id: int,
    target_backend_id: int,
) -> bool:
    """Prove exact native ancestry for icon descendants, never proximity."""
    if hit_backend_id == target_backend_id:
        return True
    try:
        described = await session.send(
            "DOM.describeNode",
            {"backendNodeId": int(hit_backend_id), "depth": 0, "pierce": True},
        )
        node = described.get("node")
        for _depth in range(64):
            if not isinstance(node, dict):
                return False
            if node.get("backendNodeId") == target_backend_id:
                return True
            parent_id = node.get("parentId")
            if not isinstance(parent_id, int):
                return False
            described = await session.send(
                "DOM.describeNode",
                {"nodeId": parent_id, "depth": 0, "pierce": True},
            )
            node = described.get("node")
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        return False
    return False


def canonical_probe_nodes_from_ax(
    payload: dict[str, Any],
) -> tuple[ProbeNode, ...]:
    """Normalize AX nodes using only explicit backend identity relations."""
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        return ()
    nodes: list[ProbeNode] = []
    for raw in raw_nodes:
        if not isinstance(raw, dict) or raw.get("ignored"):
            continue
        backend_id = raw.get("backendDOMNodeId") or raw.get("backendNodeId")
        if not isinstance(backend_id, int) or backend_id <= 0:
            continue
        role = _canonical_ax_value(raw.get("role")).lower()
        if not role:
            continue
        disabled = _canonical_ax_boolean_property(raw, "disabled")
        enabled = _canonical_ax_boolean_property(raw, "enabled")
        nodes.append(
            ProbeNode(
                source="AX",
                native_identity=f"backend:{backend_id}",
                owner=str(raw.get("frameId") or "main"),
                role=role,
                name=_canonical_ax_value(raw.get("name")),
                actionable=(
                    role in _CANONICAL_ACTIONABLE_ROLES
                    and disabled is not True
                    and enabled is not False
                ),
                states=_canonical_ax_states(raw),
            ),
        )
    return tuple(nodes)


def canonical_probe_nodes_from_dom(
    payload: dict[str, Any],
) -> tuple[ProbeNode, ...]:
    """Normalize actionable or explicit-semantic DOM probe nodes."""
    return canonical_probe_surface_from_dom(payload).nodes


# pylint: disable-next=too-many-branches
def canonical_probe_surface_from_dom(payload: dict[str, Any]) -> ProbeBatch:
    """Traverse accessible surfaces and expose blocked boundaries."""
    root = payload.get("root")
    if not isinstance(root, dict):
        return ProbeBatch()
    nodes: list[ProbeNode] = []
    regions: list[ProbeRegion] = []
    gaps: list[CoverageGap] = []
    pending: list[tuple[dict[str, Any], tuple[str, ...], bool]] = [
        (root, ("main",), False),
    ]
    while pending:
        raw, owner_chain, hidden_by_ancestor = pending.pop()
        frame_id = str(raw.get("frameId") or "").strip()
        if frame_id and owner_chain[-1] == "main":
            owner_chain = (*owner_chain, f"frame:{frame_id}")
        owner = owner_chain[-1]
        attributes = _canonical_dom_attributes(raw.get("attributes"))
        tag = str(raw.get("nodeName") or "").strip().lower()
        hidden_by_ancestor = (
            hidden_by_ancestor or tag in _CANONICAL_NON_VISIBLE_DOM_TAGS
        )
        role = str(attributes.get("role") or _canonical_native_role(tag))
        is_explicitly_semantic = (
            "role" in attributes
            and role not in _CANONICAL_STRUCTURAL_ARIA_ROLES
        )
        backend_id = raw.get("backendNodeId") or raw.get("backendDOMNodeId")
        if (
            not hidden_by_ancestor
            and isinstance(backend_id, int)
            and backend_id > 0
            and role
            and (
                role in _CANONICAL_ACTIONABLE_ROLES
                or is_explicitly_semantic
            )
        ):
            name = next(
                (
                    attributes[key]
                    for key in ("aria-label", "title", "alt", "placeholder")
                    if attributes.get(key)
                ),
                str(raw.get("nodeValue") or "").strip(),
            )
            nodes.append(
                ProbeNode(
                    source="DOM",
                    native_identity=f"backend:{backend_id}",
                    owner=owner,
                    owner_chain=owner_chain,
                    role=role,
                    name=name,
                    actionable=(
                        role in _CANONICAL_ACTIONABLE_ROLES
                        and "disabled" not in attributes
                    ),
                    states=tuple(
                        key
                        for key in (
                            "disabled",
                            "checked",
                            "selected",
                            "expanded",
                        )
                        if key in attributes
                    ),
                ),
            )
        if tag == "iframe" and isinstance(backend_id, int):
            content_document = raw.get("contentDocument")
            accessible = isinstance(content_document, dict) and not bool(
                raw.get("crossOrigin"),
            )
            frame_owner = ""
            if isinstance(content_document, dict):
                frame_owner = str(
                    content_document.get("frameId") or "",
                ).strip()
            frame_owner = frame_owner or f"backend-{backend_id}"
            frame_chain = (*owner_chain, f"frame:{frame_owner}")
            boundary: SurfaceBoundary = (
                "SAME_ORIGIN" if accessible else "CROSS_ORIGIN"
            )
            regions.append(
                ProbeRegion(
                    kind="FRAME",
                    native_identity=f"backend:{backend_id}",
                    owner=frame_chain[-1],
                    owner_chain=frame_chain,
                    boundary=boundary,
                    accessible=accessible,
                ),
            )
            if accessible and isinstance(content_document, dict):
                pending.append((content_document, frame_chain, False))
            else:
                gaps.append(
                    CoverageGap(
                        stage="CAPTURE",
                        detail=CaptureGap(
                            source="FRAME",
                            reason="CROSS_ORIGIN",
                            frame=None,
                        ),
                    ),
                )
        shadow_roots = raw.get("shadowRoots")
        if isinstance(shadow_roots, list) and isinstance(backend_id, int):
            for shadow in reversed(shadow_roots):
                if not isinstance(shadow, dict):
                    continue
                shadow_type = str(
                    shadow.get("shadowRootType") or "closed",
                ).lower()
                shadow_chain = (
                    *owner_chain,
                    f"shadow:backend:{backend_id}",
                )
                is_open = shadow_type == "open"
                regions.append(
                    ProbeRegion(
                        kind="OWNER",
                        native_identity=f"backend:{backend_id}",
                        owner=shadow_chain[-1],
                        owner_chain=shadow_chain,
                        boundary="OPEN_SHADOW" if is_open else "CLOSED_SHADOW",
                        accessible=is_open,
                    ),
                )
                if is_open:
                    pending.append((shadow, shadow_chain, hidden_by_ancestor))
                else:
                    gaps.append(
                        CoverageGap(
                            stage="CAPTURE",
                            detail=CaptureGap(
                                source="SHADOW",
                                reason="CLOSED_SHADOW",
                            ),
                        ),
                    )
        children = raw.get("children")
        if isinstance(children, list):
            pending.extend(
                (child, owner_chain, hidden_by_ancestor)
                for child in reversed(children)
                if isinstance(child, dict)
            )
    return ProbeBatch(
        nodes=tuple(nodes),
        regions=tuple(regions),
        gaps=tuple(gaps),
    )


def _canonical_ax_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or "").strip()
    return str(value or "").strip()


def _canonical_ax_states(raw: dict[str, Any]) -> tuple[str, ...]:
    properties = raw.get("properties")
    if not isinstance(properties, list):
        return ()
    states: list[str] = []
    for item in properties:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        value = _canonical_ax_value(item.get("value"))
        if name and value:
            states.append(f"{name}:{value}")
    return tuple(states)


def _canonical_ax_boolean_property(
    raw: dict[str, Any],
    property_name: str,
) -> bool | None:
    properties = raw.get("properties")
    if not isinstance(properties, list):
        return None
    for item in properties:
        if not isinstance(item, dict) or item.get("name") != property_name:
            continue
        value = item.get("value")
        if isinstance(value, dict):
            value = value.get("value")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "true":
                return True
            if normalized == "false":
                return False
        return None
    return None


def _canonical_dom_attributes(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    return {
        str(value[index]).strip().lower(): str(value[index + 1]).strip()
        for index in range(0, len(value) - 1, 2)
        if str(value[index]).strip()
    }


def _canonical_native_role(tag: str) -> str:
    return {
        "a": "link",
        "button": "button",
        "input": "textbox",
        "select": "combobox",
        "textarea": "textbox",
    }.get(tag, tag if tag not in {"#document", "html", "body"} else "")


def _control_node_params(target: dict[str, Any]) -> dict[str, int] | None:
    value = target.get("backendNodeId") or target.get("backendDOMNodeId")
    if isinstance(value, int):
        return {"backendNodeId": value}
    if isinstance(value, str) and value.isdigit():
        return {"backendNodeId": int(value)}
    node_id = target.get("nodeId")
    if isinstance(node_id, int):
        return {"nodeId": node_id}
    if isinstance(node_id, str) and node_id.isdigit():
        return {"nodeId": int(node_id)}
    return None


async def _control_enable_dom(session: Any) -> None:
    await session.send("DOM.enable")


async def _control_selector_target(
    session: Any,
    selector: str,
) -> dict[str, Any]:
    runtime_target = await _control_runtime_selector_target(
        session,
        selector,
    )
    if runtime_target is not None:
        return runtime_target

    await _control_enable_dom(session)
    document = await session.send(
        "DOM.getDocument",
        {"depth": -1, "pierce": True},
    )
    root = document.get("root") if isinstance(document, dict) else {}
    node_id = root.get("nodeId") if isinstance(root, dict) else None
    if not isinstance(node_id, int):
        raise TargetResolutionFailed(
            "Unable to inspect document root for selector",
        )

    result = await session.send(
        "DOM.querySelector",
        {"nodeId": node_id, "selector": selector},
    )
    matched_node_id = result.get("nodeId") if isinstance(result, dict) else 0
    if not isinstance(matched_node_id, int) or matched_node_id <= 0:
        raise TargetResolutionFailed(
            f"No element matches selector: {selector}",
        )

    description = await session.send(
        "DOM.describeNode",
        {"nodeId": matched_node_id},
    )
    node = description.get("node") if isinstance(description, dict) else {}
    backend_node_id = (
        node.get("backendNodeId") if isinstance(node, dict) else None
    )
    if isinstance(backend_node_id, int):
        return {"backendNodeId": backend_node_id}
    return {"nodeId": matched_node_id}


def _control_selector_locator_script(selector: str) -> str:
    query = json.dumps(str(selector or ""), ensure_ascii=False)
    return f"""
(() => {{
  const selector = {query};
  if (!selector) return null;
  const contexts = [{{ root: document, offsetX: 0, offsetY: 0 }}];
  const seenRoots = new Set([document]);
  let cursor = 0;

  const pushContext = (root, offsetX = 0, offsetY = 0) => {{
    if (!root || seenRoots.has(root) || contexts.length >= 80) return;
    seenRoots.add(root);
    contexts.push({{ root, offsetX, offsetY }});
  }};

  const visibleRect = (element) => {{
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return null;
    const style = element.ownerDocument.defaultView.getComputedStyle(element);
    if (
      style.display === "none" ||
      style.visibility === "hidden" ||
      Number(style.opacity || "1") === 0
    ) {{
      return null;
    }}
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    return rect;
  }};

  while (cursor < contexts.length && contexts.length < 80) {{
    const context = contexts[cursor++];
    const root = context.root;
    const elements = root.querySelectorAll("*");
    for (const element of elements) {{
      if (element.shadowRoot) {{
        pushContext(element.shadowRoot, context.offsetX, context.offsetY);
      }}
    }}
    for (const frame of root.querySelectorAll("iframe,frame")) {{
      let childDocument = null;
      try {{
        childDocument = frame.contentDocument;
      }} catch (_error) {{
        childDocument = null;
      }}
      if (!childDocument) continue;
      const rect = visibleRect(frame);
      if (!rect) continue;
      pushContext(
        childDocument,
        context.offsetX + rect.left,
        context.offsetY + rect.top,
      );
    }}
  }}

  const candidates = [];
  for (const context of contexts) {{
    let matches = [];
    try {{
      matches = Array.from(context.root.querySelectorAll(selector));
    }} catch (error) {{
      return {{
        error: "invalid_selector",
        message: String(error.message || error),
      }};
    }}
    for (const element of matches) {{
      const rect = visibleRect(element);
      if (!rect) continue;
      const text = String(
        element.getAttribute("aria-label") ||
        element.getAttribute("title") ||
        element.value ||
        element.textContent ||
        "",
      ).replace(/\\s+/g, " ").trim();
      candidates.push({{
        x: context.offsetX + rect.left + rect.width / 2,
        y: context.offsetY + rect.top + rect.height / 2,
        area: rect.width * rect.height,
        text: text.slice(0, 200),
        tagName: element.tagName,
        inFrame: context.offsetX !== 0 || context.offsetY !== 0,
      }});
    }}
  }}

  candidates.sort((a, b) => a.area - b.area);
  const best = candidates[0];
  if (!best) return null;
  return {{
    x: best.x,
    y: best.y,
    text: best.text,
    tagName: best.tagName,
    inFrame: best.inFrame,
  }};
}})()
""".strip()


async def _control_runtime_selector_target(
    session: Any,
    selector: str,
) -> dict[str, Any] | None:
    bridge = getattr(session, "bridge", None)
    request = getattr(bridge, "request", None)
    tab_id = getattr(session, "tab_id", None)
    holder_id = getattr(session, "holder_id", None)
    response: Any = None
    if callable(request) and tab_id is not None and holder_id is not None:
        try:
            response = await asyncio.wait_for(
                request(
                    "cdp.send",
                    {
                        "tabId": tab_id,
                        "holderId": holder_id,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": _control_selector_locator_script(
                                selector,
                            ),
                            "returnByValue": True,
                            "awaitPromise": False,
                            "timeout": 3000,
                        },
                    },
                ),
                timeout=4.0,
            )
        except asyncio.TimeoutError:
            logger.debug("control selector runtime locator timed out")
        except RECOVERABLE_CONTROL_EXCEPTIONS:
            logger.debug(
                "control selector runtime locator failed",
                exc_info=True,
            )
    if response is None or (
        isinstance(response, dict) and "error" in response
    ):
        return None
    result = response.get("result") if isinstance(response, dict) else None
    if isinstance(result, dict) and response.get("jsonrpc") == "2.0":
        remote_object = result.get("result")
    else:
        remote_object = result
    value = (
        remote_object.get("value") if isinstance(remote_object, dict) else None
    )
    if not isinstance(value, dict):
        return None
    if value.get("error") == "invalid_selector":
        raise TargetResolutionFailed(
            f"Invalid selector {selector!r}: {value.get('message') or ''}",
        )
    x = value.get("x")
    y = value.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return {
        "x": float(x),
        "y": float(y),
        "text": value.get("text") or selector,
        "tagName": value.get("tagName") or "",
        "inFrame": bool(value.get("inFrame")),
    }


async def _control_align_tab_to_requested_url(
    session: Any,
    requested_url: str,
    current_url: str,
) -> str:
    requested_url = str(requested_url or "").strip()
    current_url = str(current_url or "").strip()
    if not requested_url:
        return current_url
    if not current_url or _control_url_key(current_url) == _control_url_key(
        requested_url,
    ):
        return requested_url
    if not _control_same_site(current_url, requested_url):
        return current_url
    await session.send_after_banner(
        "Page.navigate",
        {"url": requested_url},
        {"status_text": "Open"},
    )
    return requested_url


_TRUSTED_TEST_COMMAND_ISSUER = object()


@dataclass(frozen=True, slots=True)
class _TrustedTestCommand:
    token: str
    action: str
    effect: str
    issuer_token: object


@dataclass(frozen=True, slots=True)
class _PreparedNativeInjection:
    token: str
    action: str
    effect: str
    native_identity: tuple[tuple[str, str | int], ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class _BoundaryProblem:
    code: str


@dataclass(frozen=True, slots=True)
class _NativeBoundaryResult:
    status: str
    retry: str
    problem: _BoundaryProblem | None = None


def _trusted_test_command(
    state: ControlState,
    *,
    token: str,
    action: str,
    effect: str,
) -> _TrustedTestCommand:
    """Issue a command only from an existing private binding in tests."""
    _require_canonical_binding(state, token)
    return _TrustedTestCommand(
        token=str(token),
        action=str(action),
        effect=str(effect),
        issuer_token=_TRUSTED_TEST_COMMAND_ISSUER,
    )


class _PrivateNativeTargetBoundary:
    """Trusted fake-only final validation and immediate inject turn."""

    def __init__(
        self,
        state: ControlState,
        *,
        owner_key: tuple[str, str],
        receiver_tab: int,
        facts_reader: Callable[[str], dict[str, object]],
    ) -> None:
        self._state = state
        self._owner_key = tuple(owner_key)
        self._receiver_tab = int(receiver_tab)
        self._facts_reader = facts_reader

    async def dispatch_for_test(
        self,
        command: _TrustedTestCommand,
        *,
        injector: Callable[[_PreparedNativeInjection], bool],
    ) -> _NativeBoundaryResult:
        """Validate and invoke a synchronous atomic fake injector."""
        prepared = self._prepare(command)
        if prepared is None:
            return _blocked_native_boundary()
        if not injector(prepared):
            return _blocked_native_boundary()
        return _NativeBoundaryResult(status="SUCCEEDED", retry="NONE")

    # pylint: disable-next=too-many-return-statements
    def _prepare(
        self,
        command: _TrustedTestCommand,
    ) -> _PreparedNativeInjection | None:
        if (
            not isinstance(command, _TrustedTestCommand)
            or command.issuer_token is not _TRUSTED_TEST_COMMAND_ISSUER
        ):
            return None
        try:
            binding = _require_canonical_binding(
                self._state,
                command.token,
            )
        except BrowserSDKError:
            return None
        if tuple(binding.get("owner_key", ())) != self._owner_key:
            return None
        if int(binding.get("tab_id", -1)) != self._receiver_tab:
            return None
        current_context = _control_canonical_context(
            self._state,
            tab_id=self._receiver_tab,
        )
        if binding.get("context") != current_context:
            return None
        allowed_actions = tuple(binding.get("allowed_actions", ()))
        effect_ceiling = tuple(binding.get("effect_ceiling", ()))
        if (
            command.action not in allowed_actions
            or command.effect not in effect_ceiling
        ):
            return None
        live = self._facts_reader(command.token)
        native_identity = tuple(binding.get("native_identity", ()))
        required = {
            "owner_key": self._owner_key,
            "receiver_tab": self._receiver_tab,
            "frame_key": binding.get("frame_key"),
            "context": current_context,
            "native_identity": native_identity,
            "visible": True,
            "stable": True,
            "enabled": True,
            "event_receiver": native_identity,
            "occluded": False,
            "geometry_digest": binding.get("geometry_digest"),
            "effect_ceiling": effect_ceiling,
        }
        if command.action == "type":
            required["editable"] = True
        if any(live.get(key) != value for key, value in required.items()):
            return None
        if bool(binding.get("single_use")):
            if binding.get("use_state") != "FRESH":
                return None
            binding["use_state"] = "CONSUMED"
        return _PreparedNativeInjection(
            token=command.token,
            action=command.action,
            effect=command.effect,
            native_identity=tuple(native_identity),
            fingerprint=_native_fact_fingerprint(live),
        )


def _native_fact_fingerprint(facts: dict[str, object]) -> str:
    """Seal all fake-native final facts checked by the atomic injector."""
    payload = json.dumps(
        facts,
        sort_keys=True,
        separators=(",", ":"),
        default=list,
    )
    return sha256(payload.encode()).hexdigest()


def _blocked_native_boundary() -> _NativeBoundaryResult:
    return _NativeBoundaryResult(
        status="BLOCKED",
        retry="AFTER_OBSERVATION",
        problem=_BoundaryProblem("canonical_target_revalidation_required"),
    )


def validate_ordered_targets(
    ordered: tuple[tuple[str, object], ...],
) -> tuple[object, object]:
    """Validate one distinct SOURCE followed by one DESTINATION."""
    if len(ordered) != 2 or tuple(item[0] for item in ordered) != (
        "SOURCE",
        "DESTINATION",
    ):
        raise BrowserSDKError(
            "ordered targets must be SOURCE then DESTINATION",
            code="target_order_invalid",
        )
    source, destination = ordered[0][1], ordered[1][1]
    if source is destination:
        raise BrowserSDKError(
            "drag endpoints must be distinct",
            code="target_order_invalid",
        )
    return source, destination


__all__ = [
    "_control_align_tab_to_requested_url",
    "_control_enable_dom",
    "_control_selector_locator_script",
    "_control_node_params",
    "_control_selector_target",
    "canonical_probe_nodes_from_ax",
    "canonical_probe_nodes_from_dom",
    "canonical_probe_surface_from_dom",
    "canonical_visual_candidate_backend_ids",
    "canonical_visual_geometry",
    "canonical_visual_geometry_in_region",
    "canonical_live_target_point",
]
