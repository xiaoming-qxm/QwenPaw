# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Playwright backend interaction actions."""

from ..runtime import (
    Path,
    ToolChunk,
    _USE_SYNC_PLAYWRIGHT,
    _configure_download_behavior,
    _ensure_browser,
    _get_context,
    _get_executor,
    _get_locator_by_ref,
    _get_page,
    _get_root,
    _get_tab_info_list,
    _is_browser_running,
    _next_page_id,
    _parse_json_param,
    _register_page,
    _resolve_output_path,
    _run_sync,
    _tool_response,
    asyncio,
    json,
    logger,
)
from .playwright_basic import *
from .playwright_advanced import *


async def _action_press_key(
    state: dict,
    page_id: str,
    key: str,
) -> ToolChunk:
    key = (key or "").strip()
    if not key:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "key required for press_key"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(page.keyboard.press, key)
        else:
            await page.keyboard.press(key)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Pressed key {key}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Press key failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_network_requests(
    state: dict,
    page_id: str,
    include_static: bool,
    filename: str,
) -> ToolChunk:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    requests = state["network_requests"].get(page_id, [])
    if not include_static:
        static = ("image", "stylesheet", "font", "media")
        requests = [r for r in requests if r.get("resourceType") not in static]
    lines = [
        f"{r.get('method', '')} {r.get('url', '')} {r.get('status', '')}"
        for r in requests
    ]
    text = "\n".join(lines)
    if filename and filename.strip():
        resolved = _resolve_output_path(filename.strip())
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(text)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Network requests saved to {resolved}",
                    "filename": resolved,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return _tool_response(
        json.dumps(
            {"ok": True, "requests": requests, "text": text},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_run_code(
    state: dict,
    page_id: str,
    code: str,
) -> ToolChunk:
    """Run JS in page (like eval). Use evaluate for element (ref)."""
    code = (code or "").strip()
    if not code:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "code required for run_code"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if code.strip().startswith("(") or code.strip().startswith("function"):
            if _USE_SYNC_PLAYWRIGHT:
                result = await _run_sync(page.evaluate, code)
            else:
                result = await page.evaluate(code)
        else:
            if _USE_SYNC_PLAYWRIGHT:
                result = await _run_sync(
                    page.evaluate,
                    f"() => {{ return ({code}); }}",
                )
            else:
                result = await page.evaluate(f"() => {{ return ({code}); }}")
        try:
            out = json.dumps(
                {"ok": True, "result": result},
                ensure_ascii=False,
                indent=2,
            )
        except TypeError:
            out = json.dumps(
                {"ok": True, "result": str(result)},
                ensure_ascii=False,
                indent=2,
            )
        return _tool_response(out)
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Run code failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_drag(
    state: dict,
    page_id: str,
    start_ref: str,
    end_ref: str,
    start_selector: str = "",
    end_selector: str = "",
    start_element: str = "",  # pylint: disable=unused-argument
    end_element: str = "",  # pylint: disable=unused-argument
    frame_selector: str = "",
) -> ToolChunk:
    start_ref = (start_ref or "").strip()
    end_ref = (end_ref or "").strip()
    start_selector = (start_selector or "").strip()
    end_selector = (end_selector or "").strip()
    use_refs = bool(start_ref and end_ref)
    use_selectors = bool(start_selector and end_selector)
    if not use_refs and not use_selectors:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "drag needs (start_ref,end_ref) or (start_sel,end_sel)"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        root = _get_root(page, frame_selector)
        if use_refs:
            start_locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                start_ref,
                frame_selector,
            )
            end_locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                end_ref,
                frame_selector,
            )
            if start_locator is None or end_locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": "Unknown ref for drag"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        else:
            start_locator = root.locator(start_selector).first
            end_locator = root.locator(end_selector).first
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(start_locator.drag_to, end_locator)
        else:
            await start_locator.drag_to(end_locator)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Drag completed"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Drag failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_hover(
    state: dict,
    page_id: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    selector: str = "",
    frame_selector: str = "",
) -> ToolChunk:
    ref = (ref or "").strip()
    selector = (selector or "").strip()
    if not ref and not selector:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "hover requires ref or selector"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if ref:
            locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                ref,
                frame_selector,
            )
            if locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": f"Unknown ref: {ref}"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        else:
            root = _get_root(page, frame_selector)
            locator = root.locator(selector).first
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(locator.hover)
        else:
            await locator.hover()
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Hovered {ref or selector}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Hover failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_select_option(
    state: dict,
    page_id: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    values_json: str = "",
    frame_selector: str = "",
) -> ToolChunk:
    ref = (ref or "").strip()
    values = _parse_json_param(values_json, [])
    if not isinstance(values, list):
        values = [values] if values is not None else []
    if not ref:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "ref required for select_option"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    if not values:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "values required (JSON array or comma-separated)",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        locator = _get_locator_by_ref(
            state,
            page,
            page_id,
            ref,
            frame_selector,
        )
        if locator is None:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"Unknown ref: {ref}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(locator.select_option, value=values)
        else:
            await locator.select_option(value=values)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Selected {values}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Select option failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_tabs(  # pylint: disable=too-many-return-statements
    state: dict,
    page_id: str,
    tab_action: str,
    index: int,
) -> ToolChunk:
    tab_action = (tab_action or "").strip().lower()
    if not tab_action:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "tab_action required (list, new, close, select)",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    pages = state["pages"]
    page_ids = list(pages.keys())
    if tab_action == "list":
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "tabs": page_ids,
                    "tab_list": await _get_tab_info_list(state),
                    "count": len(page_ids),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    if tab_action == "new":
        if _USE_SYNC_PLAYWRIGHT:
            if not state["_sync_context"]:
                ok = await _ensure_browser(state)
                if not ok:
                    err = (
                        state.get("_last_browser_error")
                        or "Browser not started"
                    )
                    return _tool_response(
                        json.dumps(
                            {"ok": False, "error": err},
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
        else:
            if not state["context"]:
                ok = await _ensure_browser(state)
                if not ok:
                    err = (
                        state.get("_last_browser_error")
                        or "Browser not started"
                    )
                    return _tool_response(
                        json.dumps(
                            {"ok": False, "error": err},
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
        try:
            if _USE_SYNC_PLAYWRIGHT:
                page = await _run_sync(state["_sync_context"].new_page)
            else:
                page = await state["context"].new_page()
            new_id = _next_page_id(state)
            _register_page(state, page, new_id)
            state["current_page_id"] = new_id
            await _configure_download_behavior(state)
            return _tool_response(
                json.dumps(
                    {
                        "ok": True,
                        "page_id": new_id,
                        "tabs": list(state["pages"].keys()),
                        "tab_list": await _get_tab_info_list(state),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except Exception as e:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"New tab failed: {e!s}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
    if tab_action == "close":
        target_id = page_ids[index] if 0 <= index < len(page_ids) else page_id
        return await _action_close(state, target_id)
    if tab_action == "select":
        target_id = page_ids[index] if 0 <= index < len(page_ids) else page_id
        state["current_page_id"] = target_id
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Use page_id={target_id} for later actions",
                    "page_id": target_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return _tool_response(
        json.dumps(
            {"ok": False, "error": f"Unknown tab_action: {tab_action}"},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_wait_for(
    state: dict,
    page_id: str,
    wait_time: float,
    text: str,
    text_gone: str,
) -> ToolChunk:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if wait_time and wait_time > 0:
            await asyncio.sleep(wait_time)
        text = (text or "").strip()
        text_gone = (text_gone or "").strip()
        if text:
            locator = page.get_by_text(text)
            if _USE_SYNC_PLAYWRIGHT:
                await _run_sync(
                    locator.wait_for,
                    state="visible",
                    timeout=30000,
                )
            else:
                await locator.wait_for(
                    state="visible",
                    timeout=30000,
                )
        if text_gone:
            locator = page.get_by_text(text_gone)
            if _USE_SYNC_PLAYWRIGHT:
                await _run_sync(
                    locator.wait_for,
                    state="hidden",
                    timeout=30000,
                )
            else:
                await locator.wait_for(
                    state="hidden",
                    timeout=30000,
                )
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Wait completed"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Wait failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


_BROWSER_DISK_CACHE_DIRS = [
    Path("Default") / "Cache",
    Path("Default") / "Code Cache",
    Path("Default") / "GPUCache",
    Path("Default") / "DawnWebGPUCache",
    Path("Default") / "DawnGraphiteCache",
    Path("GrShaderCache"),
    Path("ShaderCache"),
    Path("GraphiteDawnCache"),
]


async def _action_clear_browser_cache(state: dict) -> ToolChunk:
    """Clear browser cache.

    - Browser running: uses CDP Network.clearBrowserCache (no restart needed).
      Cookies and Local Storage are untouched.
    - Browser stopped: removes cache directories from user_data_dir on disk.
    """
    if _is_browser_running(state):
        context = _get_context(state)
        pages = list(state.get("pages", {}).values())
        if not context or not pages:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": "No open page to attach CDP session.",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        page = pages[0]
        cdp = None
        try:
            if _USE_SYNC_PLAYWRIGHT:
                loop = asyncio.get_event_loop()
                cdp = await loop.run_in_executor(
                    _get_executor(),
                    lambda: context.new_cdp_session(page),
                )
                assert cdp is not None
                cdp_session = cdp
                await loop.run_in_executor(
                    _get_executor(),
                    lambda: cdp_session.send("Network.clearBrowserCache"),
                )
            else:
                cdp = await context.new_cdp_session(page)
                await cdp.send("Network.clearBrowserCache")
            return _tool_response(
                json.dumps(
                    {"ok": True, "message": "HTTP cache cleared."},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except Exception as exc:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"CDP cache clear failed: {exc}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        finally:
            if cdp is not None:
                try:
                    if _USE_SYNC_PLAYWRIGHT:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            _get_executor(),
                            cdp.detach,
                        )
                    else:
                        await cdp.detach()
                except Exception:
                    logger.debug(
                        "Failed to detach cache clear CDP session",
                        exc_info=True,
                    )

    # Browser stopped: remove cache dirs from disk
    import shutil

    user_data_dir = state.get("user_data_dir") or ""
    if not user_data_dir:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "No user_data_dir configured for this workspace.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    base = Path(user_data_dir)
    removed: list[str] = []
    errors: list[str] = []
    for rel in _BROWSER_DISK_CACHE_DIRS:
        p = base / rel
        if p.exists():
            try:
                shutil.rmtree(p)
                removed.append(str(rel))
            except Exception as exc:
                errors.append(f"{rel}: {exc}")
    if errors:
        return _tool_response(
            json.dumps(
                {"ok": False, "removed": removed, "errors": errors},
                ensure_ascii=False,
                indent=2,
            ),
        )
    msg = (
        f"Cleared {len(removed)} cache director{'y' if len(removed) == 1 else 'ies'}."
        if removed
        else "No cache directories found."
    )
    return _tool_response(
        json.dumps(
            {"ok": True, "message": msg, "removed": removed},
            ensure_ascii=False,
            indent=2,
        ),
    )


__all__ = [name for name in globals() if not name.startswith("__")]
