# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Browser Control target resolution helpers."""

from ..runtime import *
from .session_manager import *
from .navigation import *
from .tab_manager import *
from .observation import *
from .inference import *
from .transitions import *


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


def _control_quad_center(quads: Any) -> tuple[float, float] | None:
    if not isinstance(quads, list) or not quads:
        return None
    quad = quads[0]
    if not isinstance(quad, list) or len(quad) < 8:
        return None
    xs = [float(quad[index]) for index in range(0, 8, 2)]
    ys = [float(quad[index]) for index in range(1, 8, 2)]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


async def _control_enable_dom(session: Any) -> None:
    await session.send("DOM.enable")


async def _control_resolve_point(
    session: Any,
    target: dict[str, Any],
    *,
    ref: str = "",
    fallback_x: Any = None,
    fallback_y: Any = None,
) -> tuple[float, float]:
    node_params = _control_node_params(target)
    if node_params is not None:
        await _control_enable_dom(session)
        params = dict(node_params)
        await session.send("DOM.scrollIntoViewIfNeeded", params)
        quads = await session.send("DOM.getContentQuads", params)
        point = _control_quad_center(quads.get("quads"))
        if point is not None:
            return point

    x = target.get("x", fallback_x)
    y = target.get("y", fallback_y)
    if x is not None and y is not None:
        return (float(x), float(y))

    if ref:
        raise ValueError(f"Unable to resolve coordinates for ref: {ref}")
    return (0.0, 0.0)


async def _control_selector_target(
    session: Any,
    selector: str,
) -> dict[str, Any]:
    await _control_enable_dom(session)
    document = await session.send(
        "DOM.getDocument",
        {"depth": -1, "pierce": True},
    )
    root = document.get("root") if isinstance(document, dict) else {}
    node_id = root.get("nodeId") if isinstance(root, dict) else None
    if not isinstance(node_id, int):
        raise ValueError("Unable to inspect document root for selector")

    result = await session.send(
        "DOM.querySelector",
        {"nodeId": node_id, "selector": selector},
    )
    matched_node_id = result.get("nodeId") if isinstance(result, dict) else 0
    if not isinstance(matched_node_id, int) or matched_node_id <= 0:
        raise ValueError(f"No element matches selector: {selector}")

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


async def _control_node_click_targets(
    session: Any,
    node_id: int,
    *,
    max_depth: int = 5,
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen: set[int] = set()
    current_node_id = node_id

    for _ in range(max_depth):
        if current_node_id <= 0 or current_node_id in seen:
            break
        seen.add(current_node_id)

        description = await session.send(
            "DOM.describeNode",
            {"nodeId": current_node_id},
        )
        node = description.get("node") if isinstance(description, dict) else {}
        if not isinstance(node, dict):
            break

        node_type = node.get("nodeType")
        backend_node_id = node.get("backendNodeId")
        parent_id = node.get("parentId")

        if node_type != 3:
            if isinstance(backend_node_id, int):
                targets.append({"backendNodeId": backend_node_id})
            else:
                targets.append({"nodeId": current_node_id})

        if not isinstance(parent_id, int) or parent_id <= 0:
            break
        current_node_id = parent_id

    if not targets:
        targets.append({"nodeId": node_id})
    return targets


def _control_visible_text_locator_script(text: str) -> str:
    query = json.dumps(text, ensure_ascii=False)
    return f"""
(() => {{
  const needle = {query};
  const normalize = (value) => String(value || "")
    .replace(/\\s+/g, " ")
    .trim();
  const wanted = normalize(needle);
  if (!wanted) return null;

  const interactiveSelector = [
    "a[href]",
    "button",
    "input",
    "textarea",
    "select",
    "summary",
    "[role='button']",
    "[role='link']",
    "[role='menuitem']",
    "[role='tab']",
    "[tabindex]:not([tabindex='-1'])",
    "[onclick]"
  ].join(",");

  const visibleRect = (element) => {{
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return null;
    const style = window.getComputedStyle(element);
    if (
      style.display === "none" ||
      style.visibility === "hidden" ||
      Number(style.opacity || "1") === 0
    ) {{
      return null;
    }}
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    if (
      rect.bottom < 0 ||
      rect.right < 0 ||
      rect.top > window.innerHeight ||
      rect.left > window.innerWidth
    ) {{
      return null;
    }}
    return rect;
  }};

  const elementText = (element) => normalize([
    element.getAttribute("aria-label"),
    element.getAttribute("title"),
    element.getAttribute("alt"),
    "value" in element ? element.value : "",
    element.textContent
  ].filter(Boolean).join(" ")).slice(0, 500);

  const roots = [document];
  for (const element of document.querySelectorAll("*")) {{
    if (roots.length >= 25) break;
    if (element.shadowRoot) roots.push(element.shadowRoot);
  }};

  const candidates = [];
  const addCandidate = (target, text, interactivePenalty) => {{
    const rect = visibleRect(target);
    if (!rect) return;
    const targetText = elementText(target) || text;
    const exact = targetText === wanted || text === wanted ? 0 : 1;
    const area = Math.max(1, rect.width * rect.height);
    const depth = (() => {{
      let value = 0;
      let current = target;
      while (current && current.parentElement) {{
        value += 1;
        current = current.parentElement;
      }}
      return value;
    }})();

    candidates.push({{
      score: exact * 100000000 + interactivePenalty * 10000000 + area - depth,
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      text: targetText || text,
      tagName: target.tagName,
    }});
  }};

  let inspectedInteractive = 0;
  for (const root of roots) {{
    for (const element of root.querySelectorAll(interactiveSelector)) {{
      if (++inspectedInteractive > 2500) break;
      const text = elementText(element);
      if (text && text.includes(wanted)) addCandidate(element, text, 0);
    }}
    if (candidates.length || inspectedInteractive > 2500) break;
  }}

  if (!candidates.length) {{
    let inspectedTextNodes = 0;
    for (const root of roots) {{
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node = walker.nextNode();
      while (node) {{
        if (++inspectedTextNodes > 5000) break;
        const text = normalize(node.nodeValue);
        if (text && text.includes(wanted)) {{
          const parent = node.parentElement;
          const interactive = parent ? parent.closest(interactiveSelector) : null;
          const target = interactive || parent;
          if (target) addCandidate(target, text, interactive ? 0 : 2);
        }}
        if (candidates.length) break;
        node = walker.nextNode();
      }}
      if (candidates.length || inspectedTextNodes > 5000) break;
    }}
  }}

  if (!candidates.length) {{
    let inspectedElements = 0;
    for (const root of roots) {{
      for (const element of root.querySelectorAll("*")) {{
        if (++inspectedElements > 2000) break;
        const text = elementText(element);
        if (!text || !text.includes(wanted)) continue;
        const interactive = element.closest(interactiveSelector);
        const target = interactive || element;
        if (!visibleRect(target) && !visibleRect(element)) continue;
        addCandidate(target, text, interactive ? 0 : 2);
        if (candidates.length) break;
      }}
      if (candidates.length || inspectedElements > 2000) break;
    }}
  }}

  candidates.sort((a, b) => a.score - b.score);
  const best = candidates[0];
  if (!best) return null;
  return {{
    x: best.x,
    y: best.y,
    text: String(best.text || "").slice(0, 200),
    tagName: best.tagName,
  }};
}})()
""".strip()


async def _control_runtime_visible_text_target(
    session: Any,
    text: str,
) -> dict[str, Any] | None:
    try:
        response = await asyncio.wait_for(
            session.bridge.request(
                "cdp.send",
                {
                    "tabId": session.tab_id,
                    "holderId": session.holder_id,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": _control_visible_text_locator_script(
                            text,
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
        logger.debug("control visible-text runtime locator timed out")
        return None
    except Exception:
        logger.debug(
            "control visible-text runtime locator failed",
            exc_info=True,
        )
        return None
    if isinstance(response, dict) and "error" in response:
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
    x = value.get("x")
    y = value.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return {
        "x": float(x),
        "y": float(y),
        "text": value.get("text") or text,
        "tagName": value.get("tagName") or "",
    }


async def _control_text_target(
    session: Any,
    text: str,
) -> dict[str, Any]:
    query = str(text or "").strip()
    if not query:
        raise ValueError("text required for visible-text click")

    await _control_enable_dom(session)
    search = await session.send(
        "DOM.performSearch",
        {"query": query, "includeUserAgentShadowDOM": True},
    )
    search_id = search.get("searchId") if isinstance(search, dict) else None
    result_count = search.get("resultCount") if isinstance(search, dict) else 0
    if not isinstance(search_id, str) or not search_id:
        raise ValueError(f"No element text matches: {query}")
    try:
        count = min(int(result_count or 0), 20)
        if count <= 0:
            raise ValueError(f"No element text matches: {query}")
        results = await session.send(
            "DOM.getSearchResults",
            {"searchId": search_id, "fromIndex": 0, "toIndex": count},
        )
        node_ids = results.get("nodeIds") if isinstance(results, dict) else []
        if not isinstance(node_ids, list):
            node_ids = []
        for raw_node_id in node_ids:
            if not isinstance(raw_node_id, int) or raw_node_id <= 0:
                continue
            for target in await _control_node_click_targets(
                session,
                raw_node_id,
            ):
                try:
                    await _control_resolve_point(session, target, ref=query)
                except Exception:
                    continue
                return target
        runtime_target = await _control_runtime_visible_text_target(
            session,
            query,
        )
        if runtime_target is not None:
            return runtime_target
    finally:
        await session.send("DOM.discardSearchResults", {"searchId": search_id})

    raise ValueError(f"Unable to resolve visible text: {query}")


async def _control_click_at(
    session: Any,
    x: float,
    y: float,
    status_text: str,
) -> None:
    try:
        await asyncio.wait_for(
            session.show_banner(
                {"cursor": {"x": x, "y": y}, "status_text": status_text},
            ),
            timeout=_CONTROL_BANNER_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.debug("control banner.show timed out before click")
    except Exception:
        logger.debug("control banner.show failed before click", exc_info=True)

    await session.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mousePressed",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        },
    )
    await session.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseReleased",
            "x": x,
            "y": y,
            "button": "left",
            "clickCount": 1,
        },
    )


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


_CONTROL_SPECIAL_KEYS: dict[str, tuple[str, str, int]] = {
    "enter": ("Enter", "Enter", 13),
    "return": ("Enter", "Enter", 13),
    "escape": ("Escape", "Escape", 27),
    "esc": ("Escape", "Escape", 27),
    "tab": ("Tab", "Tab", 9),
    "backspace": ("Backspace", "Backspace", 8),
    "delete": ("Delete", "Delete", 46),
    "arrowleft": ("ArrowLeft", "ArrowLeft", 37),
    "arrowright": ("ArrowRight", "ArrowRight", 39),
    "arrowup": ("ArrowUp", "ArrowUp", 38),
    "arrowdown": ("ArrowDown", "ArrowDown", 40),
}

_CONTROL_MODIFIER_BITS = {
    "alt": 1,
    "option": 1,
    "ctrl": 2,
    "control": 2,
    "meta": 4,
    "cmd": 4,
    "command": 4,
    "shift": 8,
}


def _control_key_params(key: str, event_type: str) -> dict[str, Any]:
    raw_parts = [part for part in re.split(r"\s*\+\s*", key.strip()) if part]
    if not raw_parts:
        raise ValueError("key required for press_key")

    modifiers = 0
    key_name = raw_parts[-1]
    for part in raw_parts[:-1]:
        modifiers |= _CONTROL_MODIFIER_BITS.get(part.lower(), 0)

    normalized = key_name.lower()
    key_value, code, virtual_key = _CONTROL_SPECIAL_KEYS.get(
        normalized,
        (key_name, f"Key{key_name.upper()}", ord(key_name.upper()[0])),
    )
    if len(key_name) == 1:
        key_value = key_name.upper() if modifiers & 8 else key_name
        code = f"Key{key_name.upper()}" if key_name.isalpha() else key_name
        virtual_key = ord(key_name.upper())

    return {
        "type": event_type,
        "key": key_value,
        "code": code,
        "windowsVirtualKeyCode": virtual_key,
        "nativeVirtualKeyCode": virtual_key,
        "modifiers": modifiers,
    }


async def _control_show_keyboard(
    session: Any,
    *,
    text: str = "",
    key: str = "",
    status_text: str = "Input",
) -> None:
    keyboard: dict[str, Any] = {}
    if text:
        keyboard["text"] = text
    if key:
        keyboard["key"] = key
    try:
        await asyncio.wait_for(
            session.show_banner(
                {
                    "status_text": status_text,
                    "keyboard": keyboard,
                },
            ),
            timeout=_CONTROL_BANNER_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.debug("control keyboard banner timed out")
    except Exception:
        logger.debug("control keyboard banner failed", exc_info=True)


async def _control_press_key(session: Any, key: str) -> None:
    normalized_key = str(key or "").strip()
    if not normalized_key:
        raise ValueError("key required for press_key")
    await _control_show_keyboard(
        session,
        key=normalized_key,
        status_text="Key",
    )
    await session.send(
        "Input.dispatchKeyEvent",
        _control_key_params(normalized_key, "rawKeyDown"),
    )
    await session.send(
        "Input.dispatchKeyEvent",
        _control_key_params(normalized_key, "keyUp"),
    )


__all__ = [name for name in globals() if not name.startswith("__")]
