# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Playwright backend batch and CDP actions."""

from ..runtime import *
from .playwright_basic import *
from .playwright_advanced import *
from .playwright_interactions import *


async def _action_batch(  # pylint: disable=too-many-nested-blocks
    state: dict,
    page_id: str,
    actions_json: str,
) -> ToolChunk:
    """Execute multiple browser actions sequentially.

    Each action in the JSON array is a dict with at least an "action" key.
    Optional keys: "page_id" (override default), "wait" (seconds to wait
    after the action), "stop_on_error" (bool, default True).

    Reuses existing _action_* helper functions to avoid duplicating logic
    and ensure consistent behavior with single-action calls.
    """
    actions = _parse_json_param(actions_json, [])
    if not isinstance(actions, list) or not actions:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "actions_json must be a non-empty JSON array",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    results: list[dict[str, Any]] = []
    total = len(actions)

    for idx, act in enumerate(actions):
        if not isinstance(act, dict):
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"Action at index {idx} is not a dict",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        sub_action = (act.get("action") or "").strip().lower()
        if not sub_action:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"Action at index {idx} missing 'action' key",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        sub_page_id = act.get("page_id") or page_id
        sub_wait: float = act.get("wait", 0)  # seconds
        stop_on_error = act.get("stop_on_error", True)

        step_result: dict[str, Any] = {
            "step": idx,
            "action": sub_action,
            "ok": False,
        }

        try:
            resp: ToolChunk | None = None

            # --- navigate ---
            if sub_action == "navigate":
                resp = await _action_navigate(
                    state,
                    url=(act.get("url") or "").strip(),
                    page_id=sub_page_id,
                )

            # --- click ---
            elif sub_action == "click":
                resp = await _action_click(
                    state,
                    page_id=sub_page_id,
                    selector=(act.get("selector") or "").strip(),
                    ref=(act.get("ref") or "").strip(),
                    element=act.get("element", ""),
                    wait=act.get("wait", 0),
                    double_click=act.get("double_click", False),
                    button=act.get("button", "left"),
                    modifiers_json=act.get("modifiers_json", ""),
                    frame_selector=act.get("frame_selector", ""),
                )

            # --- type ---
            elif sub_action == "type":
                resp = await _action_type(
                    state,
                    page_id=sub_page_id,
                    selector=(act.get("selector") or "").strip(),
                    ref=(act.get("ref") or "").strip(),
                    element=act.get("element", ""),
                    text=act.get("text", ""),
                    submit=act.get("submit", False),
                    slowly=act.get("slowly", False),
                    frame_selector=act.get("frame_selector", ""),
                )

            # --- press_key ---
            elif sub_action == "press_key":
                resp = await _action_press_key(
                    state,
                    page_id=sub_page_id,
                    key=(act.get("key") or "").strip(),
                )

            # --- evaluate ---
            elif sub_action == "evaluate":
                resp = await _action_evaluate(
                    state,
                    page_id=sub_page_id,
                    code=(act.get("code") or "").strip(),
                    ref=(act.get("ref") or "").strip(),
                    element=act.get("element", ""),
                    frame_selector=act.get("frame_selector", ""),
                )

            # --- eval ---
            elif sub_action == "eval":
                resp = await _action_eval(
                    state,
                    page_id=sub_page_id,
                    code=(act.get("code") or "").strip(),
                )

            # --- snapshot ---
            elif sub_action == "snapshot":
                resp = await _action_snapshot(
                    state,
                    page_id=sub_page_id,
                    filename=act.get("filename", ""),
                    frame_selector=act.get("frame_selector", ""),
                )

            # --- screenshot ---
            elif sub_action == "screenshot":
                resp = await _action_screenshot(
                    state,
                    page_id=sub_page_id,
                    path=(act.get("path") or "").strip(),
                    full_page=act.get("full_page", False),
                    screenshot_type=act.get("screenshot_type", "png"),
                    ref=(act.get("ref") or "").strip(),
                    element=act.get("element", ""),
                    frame_selector=act.get("frame_selector", ""),
                )

            # --- wait_for ---
            elif sub_action == "wait_for":
                resp = await _action_wait_for(
                    state,
                    page_id=sub_page_id,
                    wait_time=act.get("wait_time", 0),
                    text=(act.get("text") or "").strip(),
                    text_gone=(act.get("text_gone") or "").strip(),
                )

            # --- hover ---
            elif sub_action == "hover":
                resp = await _action_hover(
                    state,
                    page_id=sub_page_id,
                    ref=(act.get("ref") or "").strip(),
                    element=act.get("element", ""),
                    selector=(act.get("selector") or "").strip(),
                    frame_selector=act.get("frame_selector", ""),
                )

            # --- select_option ---
            elif sub_action == "select_option":
                resp = await _action_select_option(
                    state,
                    page_id=sub_page_id,
                    ref=(act.get("ref") or "").strip(),
                    element=act.get("element", ""),
                    values_json=act.get("values_json", "[]"),
                    frame_selector=act.get("frame_selector", ""),
                )

            # --- drag ---
            elif sub_action == "drag":
                resp = await _action_drag(
                    state,
                    page_id=sub_page_id,
                    start_ref=(act.get("start_ref") or "").strip(),
                    end_ref=(act.get("end_ref") or "").strip(),
                    start_selector=(act.get("start_selector") or "").strip(),
                    end_selector=(act.get("end_selector") or "").strip(),
                    start_element=act.get("start_element", ""),
                    end_element=act.get("end_element", ""),
                    frame_selector=act.get("frame_selector", ""),
                )

            # --- resize ---
            elif sub_action == "resize":
                resp = await _action_resize(
                    state,
                    page_id=sub_page_id,
                    width=act.get("width", 0),
                    height=act.get("height", 0),
                )

            else:
                step_result[
                    "error"
                ] = f"Unknown batch sub-action: {sub_action}"

            # Parse helper response into step_result
            if resp is not None and resp.content:
                try:
                    # ToolChunk content is a list of TextBlocks; extract text from the first one
                    raw_text = str(getattr(resp.content[0], "text", ""))
                    resp_data = json.loads(raw_text)
                    if isinstance(resp_data, dict):
                        step_result.update(resp_data)
                except (json.JSONDecodeError, AttributeError, IndexError):
                    step_result[
                        "error"
                    ] = "Failed to parse sub-action response"

        except Exception as e:
            step_result["error"] = str(e)

        results.append(step_result)

        if not step_result.get("ok") and stop_on_error:
            break

        # Post-action wait
        if sub_wait > 0:
            await asyncio.sleep(sub_wait)

    completed = sum(1 for r in results if r.get("ok"))
    all_ok = completed == len(results)

    return _tool_response(
        json.dumps(
            {
                "ok": all_ok,
                "total": total,
                "completed": completed,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


_CDP_SCAN_PORT_MIN = 9000
_CDP_SCAN_PORT_MAX = 10000


def _fetch_cdp_json(port: int) -> list:
    """Fetch CDP /json endpoint synchronously. Raises on failure."""
    url = f"http://localhost:{port}/json"
    with urllib_request.urlopen(url, timeout=1) as resp:
        return json.loads(resp.read())


async def _action_list_cdp_targets(
    port: int = 0,
    port_min: int = 0,
    port_max: int = 0,
) -> ToolChunk:
    """List CDP targets on local ports.

    Priority: port (single) > port_min/port_max (range) > default range.
    """
    if port:
        ports_to_scan: Any = [port]
    elif port_min or port_max:
        lo = port_min or _CDP_SCAN_PORT_MIN
        hi = port_max or _CDP_SCAN_PORT_MAX
        ports_to_scan = range(lo, hi + 1)
    else:
        ports_to_scan = range(_CDP_SCAN_PORT_MIN, _CDP_SCAN_PORT_MAX + 1)
    loop = asyncio.get_event_loop()

    async def probe(p: int):
        try:
            targets = await loop.run_in_executor(None, _fetch_cdp_json, p)
            return p, targets
        except Exception:
            return p, None

    results = await asyncio.gather(*[probe(p) for p in ports_to_scan])
    found = {str(p): t for p, t in results if t is not None}
    if found:
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "found": found,
                    "message": f"Found CDP endpoints on port(s): {', '.join(found.keys())}",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    if port:
        scan_desc = f"port {port}"
    else:
        # ports_to_scan is a range when port is not set
        scan_desc = f"range {ports_to_scan.start}-{ports_to_scan.stop - 1}"
    msg = (
        f"No CDP endpoints found in {scan_desc}. "
        "Try expanding the range with port_min/port_max, "
        "or make sure Chrome is started with --remote-debugging-port=N."
    )
    return _tool_response(
        json.dumps(
            {"ok": False, "found": {}, "message": msg},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_connect_cdp(state: dict, cdp_url: str) -> ToolChunk:
    """Connect Playwright to a running Chrome via CDP."""
    if not cdp_url:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "cdp_url is required"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    if _is_browser_running(state):
        if state.get("connected_via_cdp"):
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": (
                            f"Already connected to an external browser via CDP "
                            f"({state.get('cdp_url') or 'unknown'}). "
                            "Disconnect first with action='stop'."
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "A Playwright-managed browser is currently running. "
                        "Stop it first with action='stop' before connecting via CDP."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    pw = None
    try:
        async_playwright = _ensure_playwright_async()
        pw = await async_playwright().start()
        from qwenpaw.tool_calls import cancellable_wait

        browser = await cancellable_wait(
            pw.chromium.connect_over_cdp(cdp_url),
            fallback_secs=_CDP_CONNECT_TIMEOUT_SECONDS,
        )
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context(accept_downloads=True)
        _attach_context_listeners(state, context)
        state["playwright"] = pw
        state["browser"] = browser
        state["context"] = context
        state["connected_via_cdp"] = True
        state["cdp_url"] = cdp_url
        state["launch_mode"] = "external_cdp"
        state["owned_browser_process"] = False
        state["browser_pid"] = None
        state["browser_process"] = None
        # Register existing pages
        for page in context.pages:
            page_id = _next_page_id(state)
            _register_page(state, page, page_id)
            if state["current_page_id"] is None:
                state["current_page_id"] = page_id
        if not state["pages"]:
            page = await context.new_page()
            page_id = _next_page_id(state)
            _register_page(state, page, page_id)
            state["current_page_id"] = page_id
        _touch_activity(state)
        _start_idle_watchdog(state)
        await _configure_download_behavior(state)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Connected to Chrome via CDP at {cdp_url}",
                    "pages": list(state["pages"].keys()),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except asyncio.TimeoutError:
        await _stop_playwright_instance(pw)
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "CDP connect timed out after "
                        f"{_CDP_CONNECT_TIMEOUT_SECONDS:g}s: {cdp_url}"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        await _stop_playwright_instance(pw)
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"CDP connect failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


__all__ = [name for name in globals() if not name.startswith("__")]
