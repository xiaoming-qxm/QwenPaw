# -*- coding: utf-8 -*-
"""Read-only inspection helpers for Browser Control SDK tabs."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from .errors import BrowserSDKError
from .types import EvaluateResult, PageInfo


async def read_page_info(
    bridge: Any,
    *,
    tab_id: int,
    holder_id: str,
    fallback_url: str = "",
    fallback_title: str = "",
) -> PageInfo:
    """Read URL/title, viewport, content, and scroll metadata."""

    metrics = await send_tab_cdp(
        bridge,
        tab_id=tab_id,
        holder_id=holder_id,
        method="Page.getLayoutMetrics",
        timeout_ms=1000,
    )
    runtime = await send_tab_cdp(
        bridge,
        tab_id=tab_id,
        holder_id=holder_id,
        method="Runtime.evaluate",
        params={
            "expression": PAGE_INFO_SCRIPT,
            "returnByValue": True,
            "awaitPromise": False,
            "timeout": 1000,
        },
        timeout_ms=1000,
    )
    value = runtime_value(runtime)
    page = value if isinstance(value, dict) else {}
    layout = _dict_payload(metrics.get("layoutViewport"))
    visual = _dict_payload(metrics.get("visualViewport"))
    content = _dict_payload(metrics.get("contentSize"))

    viewport_width = rounded_number(
        first_number(
            page.get("viewportWidth"),
            visual.get("clientWidth"),
            layout.get("clientWidth"),
        ),
    )
    viewport_height = rounded_number(
        first_number(
            page.get("viewportHeight"),
            visual.get("clientHeight"),
            layout.get("clientHeight"),
        ),
    )
    content_width = rounded_number(
        first_number(page.get("scrollWidth"), content.get("width")),
    )
    content_height = rounded_number(
        first_number(page.get("scrollHeight"), content.get("height")),
    )
    scroll_x = rounded_number(
        first_number(page.get("scrollX"), visual.get("pageX"), 0),
    )
    scroll_y = rounded_number(
        first_number(page.get("scrollY"), visual.get("pageY"), 0),
    )
    max_scroll_y = rounded_number(
        first_number(
            page.get("maxScrollY"),
            max(float(content_height - viewport_height), 0.0),
        ),
    )
    scroll_percent = rounded_number(
        first_number(
            page.get("scrollPercent"),
            (scroll_y / max_scroll_y) * 100 if max_scroll_y else 0,
        ),
    )

    return PageInfo(
        url=str(page.get("url") or fallback_url or ""),
        title=str(page.get("title") or fallback_title or ""),
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        content_width=content_width,
        content_height=content_height,
        scroll_x=scroll_x,
        scroll_y=scroll_y,
        max_scroll_y=max_scroll_y,
        scroll_percent=scroll_percent,
        at_top=bool(page.get("atTop", scroll_y <= 0)),
        at_bottom=bool(page.get("atBottom", scroll_y >= max_scroll_y)),
        device_pixel_ratio=float(
            first_number(page.get("devicePixelRatio"), 1.0),
        ),
    )


async def evaluate_expression(
    bridge: Any,
    *,
    tab_id: int,
    holder_id: str,
    expression: str,
    timeout_ms: int = 1000,
    await_promise: bool = False,
) -> EvaluateResult:
    """Evaluate a bounded read-only JavaScript expression."""

    expression = str(expression or "").strip()
    if not expression:
        raise ValueError("expression is required")
    policy_error = read_only_policy_error(expression)
    if policy_error:
        return EvaluateResult(
            ok=False,
            type="error",
            exception_text=(
                "Expression rejected by read-only policy: "
                f"{policy_error}"
            ),
        )
    payload = await send_tab_cdp(
        bridge,
        tab_id=tab_id,
        holder_id=holder_id,
        method="Runtime.evaluate",
        params={
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": bool(await_promise),
            "timeout": int(timeout_ms),
        },
        timeout_ms=timeout_ms,
    )
    return evaluate_result(payload)


async def send_tab_cdp(
    bridge: Any,
    *,
    tab_id: int,
    holder_id: str,
    method: str,
    params: dict[str, Any] | None = None,
    timeout_ms: int | None = None,
) -> dict[str, Any]:
    """Send a tab-scoped CDP command through either local or remote bridge."""

    send_cdp = getattr(bridge, "send_cdp", None)
    if callable(send_cdp):
        result = send_cdp(
            int(tab_id),
            str(holder_id),
            str(method),
            params or {},
        )
        if hasattr(result, "__await__"):
            result = await _await_cdp_result(
                result,
                method=str(method),
                timeout_ms=timeout_ms,
            )
        return result if isinstance(result, dict) else {}

    request = getattr(bridge, "request", None)
    if not callable(request):
        raise BrowserSDKError("Browser bridge does not support CDP requests")
    response = request(
        "cdp.send",
        {
            "tabId": int(tab_id),
            "holderId": str(holder_id),
            "method": str(method),
            "params": params or {},
        },
    )
    if hasattr(response, "__await__"):
        response = await _await_cdp_result(
            response,
            method=str(method),
            timeout_ms=timeout_ms,
        )
    if not isinstance(response, dict):
        return {}
    error = response.get("error")
    if error:
        if isinstance(error, dict):
            message = str(error.get("message") or error)
        else:
            message = str(error)
        raise BrowserSDKError(message)
    result = response.get("result", {})
    return result if isinstance(result, dict) else {}


async def _await_cdp_result(
    awaitable: Any,
    *,
    method: str,
    timeout_ms: int | None,
) -> Any:
    if timeout_ms is None:
        return await awaitable
    timeout = max(float(timeout_ms) / 1000.0, 0.001)
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise BrowserSDKError(
            f"CDP command {method} timed out after {int(timeout_ms)} ms",
        ) from exc


def read_only_policy_error(expression: str) -> str:
    """Return a rejection reason for JavaScript with obvious side effects."""

    cleaned = strip_js_literals_and_comments(expression)
    if contains_assignment_or_update(cleaned):
        return "assignment and update operators are not allowed"
    for pattern, reason in READ_ONLY_DENY_PATTERNS:
        if pattern.search(cleaned):
            return reason
    return ""


def strip_js_literals_and_comments(source: str) -> str:
    """Replace JavaScript strings/templates/comments with whitespace."""

    result: list[str] = []
    index = 0
    length = len(source)
    state = "code"
    quote = ""
    while index < length:
        char = source[index]
        next_char = source[index + 1] if index + 1 < length else ""

        if state == "code":
            if char in {"'", '"', "`"}:
                state = "string"
                quote = char
                result.append(" ")
            elif char == "/" and next_char == "/":
                state = "line_comment"
                result.extend("  ")
                index += 1
            elif char == "/" and next_char == "*":
                state = "block_comment"
                result.extend("  ")
                index += 1
            else:
                result.append(char)
        elif state == "string":
            result.append("\n" if char == "\n" else " ")
            if char == "\\" and index + 1 < length:
                result.append(" ")
                index += 1
            elif char == quote:
                state = "code"
                quote = ""
        elif state == "line_comment":
            result.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "code"
        elif state == "block_comment":
            result.append("\n" if char == "\n" else " ")
            if char == "*" and next_char == "/":
                result.append(" ")
                index += 1
                state = "code"
        index += 1
    return "".join(result)


def contains_assignment_or_update(cleaned: str) -> bool:
    """Detect mutation-capable assignment/update operators in JS source."""

    index = 0
    length = len(cleaned)
    while index < length:
        char = cleaned[index]
        prev_char = cleaned[index - 1] if index > 0 else ""
        next_char = cleaned[index + 1] if index + 1 < length else ""
        next_next = cleaned[index + 2] if index + 2 < length else ""

        if char in {"+", "-"} and next_char == char:
            return True
        if char == "=":
            if next_char == ">":
                index += 2
                continue
            if prev_char in {"=", "!", "<", ">"} or next_char == "=":
                index += 1
                continue
            return True
        if (
            char in {"+", "-", "*", "/", "%", "|", "&", "^"}
            and next_char == "="
        ):
            return True
        if char == "?" and next_char == "?" and next_next == "=":
            return True
        if char in {"|", "&"} and next_char == char and next_next == "=":
            return True
        index += 1
    return False


def runtime_value(payload: dict[str, Any]) -> Any:
    remote_object = runtime_remote_object(payload)
    if not isinstance(remote_object, dict):
        return None
    if "value" in remote_object:
        return remote_object.get("value")
    return remote_object.get("unserializableValue")


def runtime_remote_object(payload: dict[str, Any]) -> dict[str, Any]:
    remote_object = payload.get("result") if isinstance(payload, dict) else {}
    if (
        isinstance(remote_object, dict)
        and "result" in remote_object
        and "type" not in remote_object
    ):
        remote_object = remote_object.get("result")
    return remote_object if isinstance(remote_object, dict) else {}


def evaluate_result(payload: dict[str, Any]) -> EvaluateResult:
    remote_object = runtime_remote_object(payload)
    exception_text = _exception_text(payload.get("exceptionDetails"))
    value = None
    if "value" in remote_object:
        value = remote_object.get("value")
    elif "unserializableValue" in remote_object:
        value = remote_object.get("unserializableValue")
    return EvaluateResult(
        ok=not bool(exception_text),
        type=str(remote_object.get("type") or ""),
        value=value,
        description=str(remote_object.get("description") or ""),
        exception_text=exception_text,
    )


def rounded_number(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    try:
        return int(round(float(str(value))))
    except (TypeError, ValueError):
        return 0


def first_number(*values: Any, default: float = 0.0) -> float:
    for value in values:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except (TypeError, ValueError):
            continue
    return float(default)


def _exception_text(exception_details: Any) -> str:
    if not isinstance(exception_details, dict):
        return ""
    exception = exception_details.get("exception")
    if isinstance(exception, dict):
        description = str(exception.get("description") or "")
        if description:
            return description
    return str(exception_details.get("text") or "")


def _dict_payload(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


READ_ONLY_DENY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\.\s*(?:click|submit|setAttribute|removeAttribute|"
            r"append|appendChild|prepend|before|after|replaceWith|"
            r"remove|insertAdjacentHTML|insertAdjacentText|"
            r"insertAdjacentElement|dispatchEvent)\s*\(",
        ),
        "DOM mutation or synthetic user-event methods are not allowed",
    ),
    (
        re.compile(r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\b"),
        "network APIs are not allowed",
    ),
    (
        re.compile(r"\b(?:localStorage|sessionStorage|indexedDB)\b"),
        "browser storage APIs are not allowed",
    ),
    (
        re.compile(r"\b(?:eval|Function)\b"),
        "dynamic code execution APIs are not allowed",
    ),
    (
        re.compile(r"\bnavigator\s*\.\s*(?:sendBeacon|clipboard)\b"),
        "browser side-effect APIs are not allowed",
    ),
    (
        re.compile(
            r"\b(?:history|location)\s*\.\s*"
            r"(?:pushState|replaceState|assign|replace)\s*\(",
        ),
        "history and location mutation APIs are not allowed",
    ),
    (
        re.compile(r"\bdocument\s*\.\s*(?:write|writeln)\s*\("),
        "document write APIs are not allowed",
    ),
    (
        re.compile(r"\bdelete\b"),
        "delete is not allowed",
    ),
)


PAGE_INFO_SCRIPT = """
(() => {
  const doc = document.scrollingElement
    || document.documentElement
    || document.body;
  const viewportWidth = window.innerWidth || doc.clientWidth || 0;
  const viewportHeight = window.innerHeight || doc.clientHeight || 0;
  const scrollWidth = Math.max(
    doc.scrollWidth || 0,
    document.documentElement ? document.documentElement.scrollWidth || 0 : 0,
    document.body ? document.body.scrollWidth || 0 : 0
  );
  const scrollHeight = Math.max(
    doc.scrollHeight || 0,
    document.documentElement ? document.documentElement.scrollHeight || 0 : 0,
    document.body ? document.body.scrollHeight || 0 : 0
  );
  const scrollX = window.scrollX || doc.scrollLeft || 0;
  const scrollY = window.scrollY || doc.scrollTop || 0;
  const maxScrollY = Math.max(0, scrollHeight - viewportHeight);
  const scrollPercent = maxScrollY > 0
    ? Math.round((scrollY / maxScrollY) * 100)
    : 0;
  return {
    url: window.location ? window.location.href : "",
    title: document.title || "",
    devicePixelRatio: window.devicePixelRatio || 1,
    viewportWidth,
    viewportHeight,
    scrollWidth,
    scrollHeight,
    scrollX,
    scrollY,
    maxScrollY,
    scrollPercent,
    atTop: scrollY <= 0,
    atBottom: maxScrollY <= 0 || scrollY >= maxScrollY - 2
  };
})()
""".strip()


__all__ = [
    "PAGE_INFO_SCRIPT",
    "contains_assignment_or_update",
    "evaluate_expression",
    "evaluate_result",
    "first_number",
    "read_page_info",
    "read_only_policy_error",
    "rounded_number",
    "runtime_remote_object",
    "runtime_value",
    "send_tab_cdp",
    "strip_js_literals_and_comments",
]
