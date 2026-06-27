# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Playwright backend basic browser actions."""

from ..runtime import (
    Any,
    Path,
    ToolChunk,
    _HEADLESS_VERIFICATION_WARNING,
    _USE_SYNC_PLAYWRIGHT,
    _attach_context_listeners,
    _cancel_idle_watchdog,
    _chromium_launch_args,
    _configure_download_behavior,
    _ensure_browser,
    _ensure_playwright_async,
    _get_executor,
    _get_locator_by_ref,
    _get_page,
    _get_root,
    _is_browser_running,
    _parse_json_param,
    _register_page,
    _reset_browser_state,
    _resolve_chromium_launch_target,
    _resolve_output_path,
    _run_sync,
    _start_idle_watchdog,
    _start_managed_cdp_browser,
    _stop_owned_browser_process,
    _sync_browser_close,
    _sync_browser_launch,
    _tool_response,
    _touch_activity,
    _validate_executable_path,
    asyncio,
    build_role_snapshot_from_aria,
    json,
    shlex,
    socket,
    sys,
    time,
)


async def _action_start(
    state: dict,
    headed: bool = False,
    cdp_port: int = 0,
    private_mode: bool = False,
    browser_args: str = "",
    executable_path: str = "",
) -> ToolChunk:
    _validate_executable_path(executable_path)
    # Check browser state based on mode
    if _USE_SYNC_PLAYWRIGHT:
        browser_exists = (
            state["_sync_browser"] is not None
            or state["_sync_context"] is not None
        )
        current_headless = bool(state.get("_sync_headless", True))
    else:
        browser_exists = (
            state["browser"] is not None or state["context"] is not None
        )
        current_headless = bool(state["headless"])

    # If user asks for visible window (headed=True)
    # but browser is already running headless, restart with headed
    if browser_exists:
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
        if headed and current_headless:
            _cancel_idle_watchdog(state)
            try:
                await _action_stop(state)
            except Exception:
                pass
        else:
            result: dict[str, Any] = {
                "ok": True,
                "message": "Browser already running",
            }
            if current_headless:
                result["headless_warning"] = _HEADLESS_VERIFICATION_WARNING
            return _tool_response(
                json.dumps(result, ensure_ascii=False, indent=2),
            )
    # Default: headless (background). Only headed=True (e.g. browser_visible skill) shows window.
    state["headless"] = not headed

    if cdp_port:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
            if _s.connect_ex(("127.0.0.1", cdp_port)) == 0:
                return _tool_response(
                    json.dumps(
                        {
                            "ok": False,
                            "error": (
                                f"Port {cdp_port} is already in use. "
                                "Another browser may be running on this port. "
                                "Choose a different cdp_port or stop the existing process first."
                            ),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

    try:
        if not _USE_SYNC_PLAYWRIGHT and not bool(private_mode):
            await _start_managed_cdp_browser(
                state,
                cdp_port=cdp_port,
                ensure_pages=True,
                browser_args=browser_args,
                executable_path=executable_path,
            )
        elif _USE_SYNC_PLAYWRIGHT:
            loop = asyncio.get_event_loop()
            pw, browser, context = await loop.run_in_executor(
                _get_executor(),
                lambda: _sync_browser_launch(
                    state,
                    cdp_port,
                    browser_args,
                    executable_path,
                ),
            )
            state["_sync_playwright"] = pw
            state["_sync_browser"] = browser
            state["_sync_context"] = context
            state["_sync_headless"] = not headed
            state["connected_via_cdp"] = False
            state["cdp_url"] = None
            state["owned_browser_process"] = False
            state["browser_pid"] = None
            state["browser_process"] = None
            state["launch_mode"] = "playwright"
        else:
            async_playwright = _ensure_playwright_async()
            pw = await async_playwright().start()
            default_kind, exe = _resolve_chromium_launch_target()
            if executable_path:
                exe = executable_path
            extra_args = list(_chromium_launch_args())
            if browser_args:
                extra_args.extend(
                    shlex.split(browser_args, posix=sys.platform != "win32"),
                )
            if cdp_port:
                extra_args.append(f"--remote-debugging-port={cdp_port}")

            if exe:
                # Use persistent context so cookies/storage survive browser restarts
                user_data_dir = state["user_data_dir"]
                if user_data_dir:
                    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
                    context = await pw.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        headless=state["headless"],
                        executable_path=exe if exe else None,
                        args=extra_args if extra_args else [],
                        accept_downloads=True,
                    )
                    # launch_persistent_context returns context directly; no separate browser object
                    _attach_context_listeners(state, context)
                    state["playwright"] = pw
                    state[
                        "browser"
                    ] = None  # not needed for persistent context
                    state["context"] = context
                else:
                    launch_kwargs = {"headless": state["headless"]}
                    if extra_args:
                        launch_kwargs["args"] = extra_args
                    launch_kwargs["executable_path"] = exe
                    pw_browser = await pw.chromium.launch(**launch_kwargs)
                    context = await pw_browser.new_context(
                        accept_downloads=True,
                    )
                    _attach_context_listeners(state, context)
                    state["playwright"] = pw
                    state["browser"] = pw_browser
                    state["context"] = context
            elif default_kind == "webkit" or sys.platform == "darwin":
                pw_browser = await pw.webkit.launch(
                    headless=state["headless"],
                )
                context = await pw_browser.new_context(accept_downloads=True)
                _attach_context_listeners(state, context)
                state["playwright"] = pw
                state["browser"] = pw_browser
                state["context"] = context
            else:
                launch_kwargs = {"headless": state["headless"]}
                if extra_args:
                    launch_kwargs["args"] = extra_args
                pw_browser = await pw.chromium.launch(**launch_kwargs)
                context = await pw_browser.new_context(accept_downloads=True)
                _attach_context_listeners(state, context)
                state["playwright"] = pw
                state["browser"] = pw_browser
                state["context"] = context
            state["connected_via_cdp"] = False
            state["cdp_url"] = None
            state["owned_browser_process"] = False
            state["browser_pid"] = None
            state["browser_process"] = None
            state["launch_mode"] = "playwright"
        _touch_activity(state)
        _start_idle_watchdog(state)
        await _configure_download_behavior(state)
        # Store launch config for _ensure_browser fallback restarts
        state["_browser_args"] = browser_args
        state["_executable_path"] = executable_path
        msg = (
            "Browser started (visible window)"
            if not state["headless"]
            else "Browser started"
        )
        result = {
            "ok": True,
            "message": msg,
            "tip": "Enable browser-related skills in the agent config for a better experience.",
            "launch_mode": state.get("launch_mode"),
            "owned_browser_process": state.get("owned_browser_process", False),
            "private_mode": bool(private_mode),
        }
        if state["headless"]:
            result["headless_warning"] = _HEADLESS_VERIFICATION_WARNING
        if state.get("browser_pid"):
            result["browser_pid"] = state["browser_pid"]
        cdp_url = state.get("cdp_url") or (
            f"http://localhost:{cdp_port}" if cdp_port else None
        )
        if cdp_url:
            result["cdp_url"] = cdp_url
            result["message"] = (
                msg + f" with CDP port {cdp_url.rsplit(':', 1)[-1]}"
            )
        return _tool_response(
            json.dumps(result, ensure_ascii=False, indent=2),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Browser start failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_stop(state: dict) -> ToolChunk:
    _cancel_idle_watchdog(state)

    # Check browser state based on mode
    if not _is_browser_running(state):
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Browser not running"},
                ensure_ascii=False,
                indent=2,
            ),
        )

    # CDP-connected mode: just disconnect Playwright; optionally stop owned Chrome process.
    if state.get("connected_via_cdp"):
        cdp_url = state.get("cdp_url") or ""
        owned = bool(state.get("owned_browser_process"))
        pid = state.get("browser_pid")
        try:
            if state["context"] is not None:
                try:
                    await state["context"].close()
                except Exception:
                    pass
            if state["browser"] is not None:
                try:
                    await state["browser"].close()
                except Exception:
                    pass
            if state["playwright"] is not None:
                try:
                    await state["playwright"].stop()
                except Exception:
                    pass
            stopped = False
            if owned:
                stopped = await _stop_owned_browser_process(state)
        finally:
            _reset_browser_state(state)
        message = (
            f"Disconnected from Chrome and stopped owned browser process (pid={pid})"
            if owned
            else f"Disconnected from Chrome (process still running: {cdp_url})"
        )
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": message,
                    "owned_browser_process": owned,
                    "browser_stopped": stopped if owned else False,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    # Playwright-launched browser: terminate Chrome process.
    # Warn that other agents sharing this browser will lose their connection.
    warning = (
        "Chrome process will be terminated. "
        "Any other agents connected to this browser via CDP will be disconnected."
    )
    if _USE_SYNC_PLAYWRIGHT:
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                _get_executor(),
                lambda: _sync_browser_close(state),
            )
        except Exception as e:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"Browser stop failed: {e!s}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        finally:
            _reset_browser_state(state)
    else:
        try:
            # For persistent_context, close the context directly (no separate browser)
            if state["context"] is not None:
                try:
                    await state["context"].close()
                except Exception:
                    pass
            if state["browser"] is not None:
                try:
                    await state["browser"].close()
                except Exception:
                    pass
            if state["playwright"] is not None:
                try:
                    await state["playwright"].stop()
                except Exception:
                    pass
        except Exception as e:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"Browser stop failed: {e!s}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        finally:
            _reset_browser_state(state)

    return _tool_response(
        json.dumps(
            {"ok": True, "message": "Browser stopped", "warning": warning},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_open(state: dict, url: str, page_id: str) -> ToolChunk:
    url = (url or "").strip()
    if not url:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "url required for open"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    if not await _ensure_browser(state):
        err = state.get("_last_browser_error") or "Browser not started"
        return _tool_response(
            json.dumps(
                {"ok": False, "error": err},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            # Hybrid mode: create page in thread pool
            loop = asyncio.get_event_loop()
            # pylint: disable=unnecessary-lambda
            page = await loop.run_in_executor(
                _get_executor(),
                lambda: state["_sync_context"].new_page(),
            )
        else:
            # Standard async mode
            page = await state["context"].new_page()

        _register_page(state, page, page_id)
        await _configure_download_behavior(state)

        if _USE_SYNC_PLAYWRIGHT:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                _get_executor(),
                lambda: page.goto(url),
            )
        else:
            await page.goto(url)

        state["pages"][page_id] = page
        state["current_page_id"] = page_id
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Opened {url}",
                    "page_id": page_id,
                    "url": url,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Open failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_navigate(
    state: dict,
    url: str,
    page_id: str,
) -> ToolChunk:
    url = (url or "").strip()
    if not url:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "url required for navigate"},
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
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                _get_executor(),
                lambda: page.goto(url),
            )
        else:
            await page.goto(url)
        state["current_page_id"] = page_id
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Navigated to {url}",
                    "url": page.url,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Navigate failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_screenshot(
    state: dict,
    page_id: str,
    path: str,
    full_page: bool,
    screenshot_type: str = "png",
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    frame_selector: str = "",
) -> ToolChunk:
    path = (path or "").strip()
    if not path:
        ext = "jpeg" if screenshot_type == "jpeg" else "png"
        path = f"page-{int(time.time())}.{ext}"
    path = _resolve_output_path(path)
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
        if ref and ref.strip():
            locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                ref.strip(),
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
                await _run_sync(
                    locator.screenshot,
                    path=path,
                    type=(
                        screenshot_type if screenshot_type == "jpeg" else "png"
                    ),
                )
            else:
                await locator.screenshot(
                    path=path,
                    type=(
                        screenshot_type if screenshot_type == "jpeg" else "png"
                    ),
                )
        else:
            if frame_selector and frame_selector.strip():
                root = _get_root(page, frame_selector)
                locator = root.locator("body").first
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(
                        locator.screenshot,
                        path=path,
                        type=(
                            screenshot_type
                            if screenshot_type == "jpeg"
                            else "png"
                        ),
                    )
                else:
                    await locator.screenshot(
                        path=path,
                        type=(
                            screenshot_type
                            if screenshot_type == "jpeg"
                            else "png"
                        ),
                    )
            else:
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(
                        page.screenshot,
                        path=path,
                        full_page=full_page,
                        type=(
                            screenshot_type
                            if screenshot_type == "jpeg"
                            else "png"
                        ),
                    )
                else:
                    await page.screenshot(
                        path=path,
                        full_page=full_page,
                        type=(
                            screenshot_type
                            if screenshot_type == "jpeg"
                            else "png"
                        ),
                    )
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Screenshot saved to {path}",
                    "path": path,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Screenshot failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_click(  # pylint: disable=too-many-branches
    state: dict,
    page_id: str,
    selector: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    wait: int = 0,
    double_click: bool = False,
    button: str = "left",
    modifiers_json: str = "",
    frame_selector: str = "",
) -> ToolChunk:
    ref = (ref or "").strip()
    selector = (selector or "").strip()
    if not ref and not selector:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "selector or ref required for click"},
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
        if wait > 0:
            await asyncio.sleep(wait / 1000.0)
        mods = _parse_json_param(modifiers_json, [])
        if not isinstance(mods, list):
            mods = []
        kwargs: dict[str, Any] = {
            "button": (
                button if button in ("left", "right", "middle") else "left"
            ),
        }
        if mods:
            kwargs["modifiers"] = [
                m
                for m in mods
                if m in ("Alt", "Control", "ControlOrMeta", "Meta", "Shift")
            ]

        if _USE_SYNC_PLAYWRIGHT:
            loop = asyncio.get_event_loop()
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
                if double_click:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.dblclick(**kwargs),
                    )
                else:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.click(**kwargs),
                    )
            else:
                root = _get_root(page, frame_selector)
                locator = root.locator(selector).first
                if double_click:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.dblclick(**kwargs),
                    )
                else:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.click(**kwargs),
                    )
        else:
            # Standard async mode
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
                if double_click:
                    await locator.dblclick(**kwargs)
                else:
                    await locator.click(**kwargs)
            else:
                root = _get_root(page, frame_selector)
                locator = root.locator(selector).first
                if double_click:
                    await locator.dblclick(**kwargs)
                else:
                    await locator.click(**kwargs)

        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Clicked {ref or selector}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Click failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_type(
    state: dict,
    page_id: str,
    selector: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    text: str = "",
    submit: bool = False,
    slowly: bool = False,
    frame_selector: str = "",
) -> ToolChunk:
    ref = (ref or "").strip()
    selector = (selector or "").strip()
    if not ref and not selector:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "selector or ref required for type"},
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
            if _USE_SYNC_PLAYWRIGHT:
                loop = asyncio.get_event_loop()
                if slowly:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.press_sequentially(text or ""),
                    )
                else:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.fill(text or ""),
                    )
                if submit:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: locator.press("Enter"),
                    )
            else:
                if slowly:
                    await locator.press_sequentially(text or "")
                else:
                    await locator.fill(text or "")
                if submit:
                    await locator.press("Enter")
        else:
            root = _get_root(page, frame_selector)
            loc = root.locator(selector).first
            if _USE_SYNC_PLAYWRIGHT:
                loop = asyncio.get_event_loop()
                if slowly:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: loc.press_sequentially(text or ""),
                    )
                else:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: loc.fill(text or ""),
                    )
                if submit:
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: loc.press("Enter"),
                    )
            else:
                if slowly:
                    await loc.press_sequentially(text or "")
                else:
                    await loc.fill(text or "")
                if submit:
                    await loc.press("Enter")
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Typed into {ref or selector}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Type failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_eval(state: dict, page_id: str, code: str) -> ToolChunk:
    code = (code or "").strip()
    if not code:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "code required for eval"},
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
                {"ok": False, "error": f"Eval failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_pdf(state: dict, page_id: str, path: str) -> ToolChunk:
    path = (path or "page.pdf").strip() or "page.pdf"
    path = _resolve_output_path(path)
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
            await _run_sync(page.pdf, path=path)
        else:
            await page.pdf(path=path)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"PDF saved to {path}", "path": path},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"PDF failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_close(state: dict, page_id: str) -> ToolChunk:
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
            await _run_sync(page.close)
        else:
            await page.close()
        del state["pages"][page_id]
        for key in (
            "refs",
            "refs_frame",
            "console_logs",
            "network_requests",
            "pending_dialogs",
            "pending_file_choosers",
        ):
            state[key].pop(page_id, None)
        if state.get("current_page_id") == page_id:
            remaining = list(state["pages"].keys())
            state["current_page_id"] = remaining[0] if remaining else None
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Closed page '{page_id}'"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Close failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_snapshot(
    state: dict,
    page_id: str,
    filename: str,
    frame_selector: str = "",
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
        if _USE_SYNC_PLAYWRIGHT:
            # Hybrid mode: execute in thread pool
            loop = asyncio.get_event_loop()
            root = _get_root(page, frame_selector)
            locator = root.locator(":root")
            raw = await loop.run_in_executor(
                _get_executor(),
                lambda: locator.aria_snapshot(),  # pylint: disable=unnecessary-lambda
            )
        else:
            root = _get_root(page, frame_selector)
            locator = root.locator(":root")
            raw = await locator.aria_snapshot()

        raw_str = str(raw) if raw is not None else ""
        snapshot, refs = build_role_snapshot_from_aria(
            raw_str,
            interactive=False,
            compact=False,
        )
        state["refs"][page_id] = refs
        state["refs_frame"][page_id] = (
            frame_selector.strip() if frame_selector else ""
        )
        out = {
            "ok": True,
            "snapshot": snapshot,
            "refs": list(refs.keys()),
            "url": page.url,
        }
        if frame_selector and frame_selector.strip():
            out["frame_selector"] = frame_selector.strip()
        if filename and filename.strip():
            resolved = _resolve_output_path(filename.strip())
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(snapshot)
            out["filename"] = resolved
        return _tool_response(json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Snapshot failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_navigate_back(state: dict, page_id: str) -> ToolChunk:
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
            await _run_sync(page.go_back)
        else:
            await page.go_back()
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Navigated back", "url": page.url},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Navigate back failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


__all__ = [name for name in globals() if not name.startswith("__")]
