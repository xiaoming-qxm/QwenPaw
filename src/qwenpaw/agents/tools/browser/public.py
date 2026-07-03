# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Public browser tool entry points."""

import math
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from typing import Any

from .runtime import (
    Iterable,
    Path,
    ToolChunk,
    _USE_SYNC_PLAYWRIGHT,
    _get_context,
    _get_executor,
    _get_workspace_state,
    _is_browser_running,
    _parse_json_param,
    _tool_response,
    _touch_activity,
    _workspace_states,
    asyncio,
    json,
    logger,
    tool_descriptor,
)
from .backends.playwright_basic import *
from .backends.playwright_advanced import *
from .backends.playwright_interactions import *
from .backends.playwright_batch_cdp import *
from qwenpaw.browser.control_engine import get_control_engine

from .backends.control import _action_control

_BROWSER_USE_LEGACY_BYPASS: ContextVar[bool] = ContextVar(
    "qwenpaw_browser_use_legacy_bypass",
    default=False,
)


class legacy_browser_use_bypass:
    """Temporarily route browser_use calls to the legacy dispatcher."""

    def __enter__(self):
        self._token = _BROWSER_USE_LEGACY_BYPASS.set(True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _BROWSER_USE_LEGACY_BYPASS.reset(self._token)


def _coordinate_validation_error(name: str, value: Any) -> ToolChunk:
    """Return a structured error for malformed viewport coordinates."""
    return _tool_response(
        json.dumps(
            {
                "ok": False,
                "error": "invalid_coordinate",
                "field": name,
                "value": str(value),
                "message": (
                    f"{name} must be a finite number or numeric string when "
                    "provided."
                ),
                "next_instruction": (
                    "Pass viewport coordinates as JSON numbers, or numeric "
                    "strings if the model cannot preserve numeric JSON values."
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def _coerce_optional_coordinate(
    value: float | str | None,
    name: str,
) -> tuple[float | None, ToolChunk | None]:
    """Normalize optional viewport coordinates at the public tool boundary."""
    if value is None:
        return None, None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None, None
        try:
            parsed = float(raw)
        except ValueError:
            return None, _coordinate_validation_error(name, value)
    elif isinstance(value, bool):
        return None, _coordinate_validation_error(name, value)
    elif isinstance(value, (int, float)):
        parsed = float(value)
    else:
        return None, _coordinate_validation_error(name, value)

    if not math.isfinite(parsed):
        return None, _coordinate_validation_error(name, value)
    return parsed, None


_CONTROL_BLOCKED_LEGACY_ACTIONS = {
    "connect_cdp",
    "list_cdp_targets",
}

_CONTROL_LIFECYCLE_LEGACY_ACTIONS = {
    "start",
    "stop",
}

_SDK_SUPPORTED_LEGACY_ACTIONS = {
    "open",
    "navigate",
    "back",
    "forward",
    "reload",
    "navigate_back",
    "navigate_forward",
    "snapshot",
    "screenshot",
    "take_screenshot",
    "click",
    "type",
    "press_key",
    "scroll",
    "hover",
    "select_option",
    "wait_for",
    "tabs",
    "evaluate",
    "eval",
    "run_code",
    "close",
}


def _has_control_session(state: dict[str, Any]) -> bool:
    engine = get_control_engine()
    return bool(engine and engine.has_active_session(state))


def _browser_control_invocation_context() -> dict[str, Any]:
    engine = get_control_engine()
    if engine is None:
        return {}
    try:
        return engine.get_request_context()
    except Exception:  # pragma: no cover - defensive boundary
        return {}


def _should_use_control_mode(
    *,
    mode: str,
    action: str,
    state: dict[str, Any],
) -> bool:
    engine = get_control_engine()
    if engine is None:
        return False

    requested_mode = str(mode or "").strip().lower()
    if requested_mode == "control":
        return True
    if requested_mode:
        return False

    control_action = action in engine.supported_actions()
    browser_control_context = bool(
        _browser_control_invocation_context().get(
            "browser_control_invocation",
        ),
    )
    if browser_control_context and (
        control_action or action in _CONTROL_BLOCKED_LEGACY_ACTIONS
    ):
        return True
    return control_action and _has_control_session(state)


def _should_preserve_legacy_control_lifecycle(
    *,
    mode: str,
    action: str,
) -> bool:
    requested_mode = str(mode or "").strip().lower()
    return (
        requested_mode == "control"
        and action in _CONTROL_LIFECYCLE_LEGACY_ACTIONS
    )


async def _browser_use_sdk_shim(**kwargs: Any) -> ToolChunk:
    action = str(kwargs.get("action") or "").strip().lower()
    if action not in _SDK_SUPPORTED_LEGACY_ACTIONS:
        return _sdk_gap_response(action)

    try:
        from qwenpaw.browser_sdk import Browser, BrowserSDKError

        context = _legacy_context(kwargs)
        browser = await Browser.connect(
            context=context,
            requires_user_state=(context == "user"),
        )
        result = await _run_sdk_legacy_action(browser, action, kwargs)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "action": action,
                    "sdk_backend": browser.context.backend_id,
                    "result": _jsonable(result),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except BrowserSDKError as exc:
        return _tool_response(
            json.dumps(exc.to_dict(), ensure_ascii=False, indent=2),
        )
    except Exception as exc:  # noqa: BLE001
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )


def _legacy_context(kwargs: dict[str, Any]) -> str:
    mode = str(kwargs.get("mode") or "").strip().lower()
    return "user" if mode == "control" else "isolated"


async def _run_sdk_legacy_action(
    browser: Any,
    action: str,
    kwargs: dict[str, Any],
) -> Any:
    if action == "open":
        return await browser.tabs.open(str(kwargs.get("url") or ""))

    tab = await _sdk_tab(browser, kwargs)
    if action == "navigate":
        return await tab.actions.open(str(kwargs.get("url") or ""))
    if action in {"back", "navigate_back"}:
        return await tab._call_action(
            "back",
        )  # pylint: disable=protected-access
    if action in {"forward", "navigate_forward"}:
        return await tab._call_action(
            "forward",
        )  # pylint: disable=protected-access
    if action == "reload":
        return await tab._call_action(
            "reload",
        )  # pylint: disable=protected-access
    if action == "snapshot":
        return await tab.snapshot()
    if action in {"screenshot", "take_screenshot"}:
        return await tab.screenshot()
    if action == "click":
        return await tab.actions.click(_legacy_target(kwargs))
    if action == "type":
        return await tab.actions.type(
            _legacy_target(kwargs),
            str(kwargs.get("text") or ""),
        )
    if action == "press_key":
        return await tab.actions.press(str(kwargs.get("key") or ""))
    if action == "scroll":
        return await tab.actions.scroll(
            direction=str(kwargs.get("direction") or "down"),
            amount=kwargs.get("amount"),
        )
    if action == "hover":
        return await tab._call_action(  # pylint: disable=protected-access
            "hover",
            **_legacy_target(kwargs),
        )
    if action == "select_option":
        return await tab.actions.select(
            _legacy_target(kwargs),
            _legacy_select_value(kwargs),
        )
    if action == "wait_for":
        instruction = str(
            kwargs.get("text")
            or kwargs.get("text_gone")
            or kwargs.get("wait_time")
            or "",
        )
        timeout_ms = int(float(kwargs.get("wait_time") or 10) * 1000)
        return await tab.actions.wait_for(instruction, timeout_ms=timeout_ms)
    if action == "tabs":
        return await _run_sdk_tabs_action(browser, tab, kwargs)
    if action in {"evaluate", "eval"}:
        return await tab.evaluate(
            str(kwargs.get("code") or ""),
            read_only=True,
        )
    if action == "run_code":
        return await tab.evaluate(
            str(kwargs.get("code") or ""),
            read_only=False,
        )
    if action == "close":
        return await tab.close()
    return _sdk_gap_payload(action)


async def _sdk_tab(browser: Any, kwargs: dict[str, Any]) -> Any:
    page_id = str(kwargs.get("page_id") or "default")
    if page_id and page_id != "default":
        return await browser.tabs.select(page_id)
    return await browser.tabs.active()


async def _run_sdk_tabs_action(
    browser: Any,
    tab: Any,
    kwargs: dict[str, Any],
) -> Any:
    tab_action = str(kwargs.get("tab_action") or "list").strip().lower()
    if tab_action in {"", "list"}:
        return await browser.tabs.list()
    if tab_action in {"new", "open"}:
        return await browser.tabs.open(str(kwargs.get("url") or "about:blank"))
    if tab_action == "select":
        index = int(kwargs.get("index") or 0)
        tabs = await browser.tabs.list()
        if 0 <= index < len(tabs):
            return await browser.tabs.select(tabs[index].id)
        return tab
    if tab_action == "close":
        return await tab.close()
    return _sdk_gap_payload(f"tabs.{tab_action}")


def _legacy_target(kwargs: dict[str, Any]) -> dict[str, Any]:
    target: dict[str, Any] = {}
    for key in ("ref", "selector", "element", "text", "x", "y"):
        value = kwargs.get(key)
        if value not in (None, ""):
            target[key] = value
    return target or {"target": ""}


def _legacy_select_value(kwargs: dict[str, Any]) -> Any:
    values_json = str(kwargs.get("values_json") or "")
    if not values_json:
        return ""
    try:
        values = json.loads(values_json)
    except (TypeError, ValueError):
        return values_json
    if isinstance(values, list) and values:
        return values[0]
    return values


def _sdk_gap_response(action: str) -> ToolChunk:
    return _tool_response(
        json.dumps(
            _sdk_gap_payload(action),
            ensure_ascii=False,
            indent=2,
        ),
    )


def _sdk_gap_payload(action: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "browser_sdk_gap",
        "sdk_gap": True,
        "action": action,
        "message": (
            "Legacy browser_use action is not supported by the Browser SDK "
            "compatibility shim. Request a Browser SDK capability instead."
        ),
    }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "id") and hasattr(value, "context"):
        return {
            "id": str(getattr(value, "id", "")),
            "url": str(getattr(value, "url", "")),
            "title": str(getattr(value, "title", "")),
        }
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


async def stop_all_browsers() -> None:
    """Gracefully stop all active browser instances across all workspaces.

    This should be called during application shutdown to ensure no zombie
    browser processes are left behind.
    """
    if not _workspace_states:
        return

    logger.info("Stopping all browser instances...")
    # Use list() to avoid mutation during iteration if stop resets state
    for state in list(_workspace_states.values()):
        if _is_browser_running(state):
            try:
                await _action_stop(state)
            except Exception as e:
                logger.error(
                    "Failed to stop browser for workspace %s: %s",
                    state.get("workspace_id", "unknown"),
                    e,
                )


async def stop_browsers_for_workspace_dirs(
    workspace_dirs: Iterable[str | Path],
) -> None:
    """Stop managed browsers whose profile lives under *workspace_dirs*.

    Backup restore uses this narrower cleanup before replacing workspace
    directories. It releases QwenPaw-owned Playwright/Chromium handles without
    disrupting browser sessions for unrelated workspaces.
    """
    targets = _resolved_workspace_dir_keys(workspace_dirs)
    if not targets:
        return

    for state in list(_workspace_states.values()):
        workspace_dir = state.get("workspace_dir") or ""
        if not workspace_dir:
            continue
        if _workspace_dir_key(workspace_dir) not in targets:
            continue
        if _is_browser_running(state):
            try:
                await _action_stop(state)
            except Exception as e:
                logger.error(
                    "Failed to stop browser for workspace %s before "
                    "restore: %s",
                    state.get("workspace_id", "unknown"),
                    e,
                )


def _resolved_workspace_dir_keys(
    workspace_dirs: Iterable[str | Path],
) -> set[str]:
    """Normalize workspace paths for matching browser state entries."""
    return {
        key
        for workspace_dir in workspace_dirs
        if (key := _workspace_dir_key(workspace_dir))
    }


def _workspace_dir_key(workspace_dir: str | Path) -> str:
    """Return a stable absolute path key, tolerating missing directories."""
    if not workspace_dir:
        return ""
    path = Path(workspace_dir).expanduser()
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


@tool_descriptor(
    enabled_by_default=False,
    async_execution=True,
    legacy=True,
    superseded_by_skills=("browser-control",),
)
async def browser_use(  # pylint: disable=R0911,R0912
    action: str,
    mode: str = "",
    url: str = "",
    page_id: str = "default",
    selector: str = "",
    text: str = "",
    code: str = "",
    path: str = "",
    wait: int = 0,
    full_page: bool = False,
    width: int = 0,
    height: int = 0,
    level: str = "info",
    filename: str = "",
    accept: bool = True,
    prompt_text: str = "",
    ref: str = "",
    element: str = "",
    x: float | str | None = None,
    y: float | str | None = None,
    paths_json: str = "",
    fields_json: str = "",
    key: str = "",
    submit: bool = False,
    slowly: bool = False,
    include_static: bool = False,
    screenshot_type: str = "png",
    snapshot_filename: str = "",
    double_click: bool = False,
    button: str = "left",
    modifiers_json: str = "",
    start_ref: str = "",
    end_ref: str = "",
    start_selector: str = "",
    end_selector: str = "",
    start_element: str = "",
    end_element: str = "",
    values_json: str = "",
    direction: str = "",
    amount: str | int = "page",
    tab_action: str = "",
    index: int = -1,
    wait_time: float = 0,
    text_gone: str = "",
    frame_selector: str = "",
    headed: bool = False,
    cdp_port: int = 0,
    private_mode: bool = False,
    browser_args: str = "",
    executable_path: str = "",
    actions_json: str = "",
    cdp_url: str = "",
    port: int = 0,
    port_min: int = 0,
    port_max: int = 0,
    user_initiated: bool = False,
    allow_new_context: bool = False,
) -> ToolChunk:
    """Control browser (Playwright). Default is headless. Use headed=True with
    action=start to open a visible browser window. Flow: start, open(url),
    snapshot to get refs, then click/type etc. with ref or selector. Use
    page_id for multiple tabs. Note: To enhance the experience, consider
    reminding the user to enable browser-related skills in the agent config.
    Once enabled, you will be able to proactively determine when to invoke the
    browser tool and pass the appropriate arguments.

    Args:
        action (str):
            Required. Action type. Values: start, stop, open, navigate,
            navigate_back, snapshot, screenshot, click, type, eval, evaluate,
            resize, console_messages, network_requests, handle_dialog,
            file_upload, file_download, fill_form, install, press_key,
            run_code, drag, hover, select_option, tabs, wait_for, pdf, close,
            cookies_get, cookies_set, cookies_clear, connect_cdp,
            list_cdp_targets, clear_browser_cache,
            batch. batch executes multiple sub-actions sequentially from
            actions_json; supported sub-actions: navigate, click, type,
            press_key, evaluate, eval, snapshot, screenshot, wait_for, hover,
            select_option, drag, resize.
            Commonly confused actions:
            - start: start browser only; does not open a target URL by itself.
            - open: create/open a page and go to URL; auto-starts browser if needed.
            - navigate: navigate an existing page_id to URL; page must already exist.
            - close: close one page/tab only; browser stays running if other tabs remain.
            - stop: stop/disconnect the whole browser session and clear browser state.
            - tabs with tab_action=close: close a tab by index; similar to close but
              selected by tab list position instead of page_id.
        url (str):
            URL to open. Required for action=open or navigate. For
            cookies_get, optional URL or JSON array of URLs to filter
            cookies by domain. For action=file_download, save this URL
            directly through the browser context.
        page_id (str):
            Page/tab identifier, default "default". Use different page_id for
            multiple tabs.
        selector (str):
            CSS selector to locate element for click/type/hover etc. Prefer
            ref when available.
        text (str):
            Text to type. Required for action=type. In control mode,
            action=click can also use visible text matching when ref/selector
            is unavailable.
        code (str):
            JavaScript code. Required for action=eval, evaluate, or run_code.
        path (str):
            File path for screenshot save, PDF export, or file_download output.
        wait (int):
            Milliseconds to wait after click. Used with action=click.
        full_page (bool):
            Whether to capture full page. Used with action=screenshot.
        width (int):
            Viewport width in pixels. Used with action=resize.
        height (int):
            Viewport height in pixels. Used with action=resize.
        level (str):
            Console log level filter, e.g. "info" or "error". Used with
            action=console_messages.
        filename (str):
            Filename for saving logs or screenshot. Used with
            console_messages, network_requests, screenshot, file_download.
        accept (bool):
            Whether to accept dialog (true) or dismiss (false). Used with
            action=handle_dialog.
        prompt_text (str):
            Input for prompt dialog. Used with action=handle_dialog when
            dialog is prompt.
        ref (str):
            Element ref from snapshot output; use for stable targeting. Prefer
            ref for click/type/hover/screenshot/evaluate/select_option. For
            action=file_download, click this ref and save the browser download
            produced by that click.
        element (str):
            Element description for evaluate etc. Prefer ref when available.
        x (float | str | None):
            Viewport x coordinate for control-mode click when no ref,
            selector, or visible text target is available. Numeric strings are
            accepted and normalized to float at the tool boundary.
        y (float | str | None):
            Viewport y coordinate for control-mode click when no ref,
            selector, or visible text target is available. Numeric strings are
            accepted and normalized to float at the tool boundary.
        paths_json (str):
            JSON array string of file paths. Used with action=file_upload.
        fields_json (str):
            JSON object string of form field name to value. Used with
            action=fill_form. For cookies_set, JSON array of cookie objects
            with keys: name, value, url (or domain+path), expires, httpOnly,
            secure, sameSite.
        key (str):
            Key name, e.g. "Enter", "Control+a". Required for
            action=press_key.
        submit (bool):
            Whether to submit (press Enter) after typing. Used with
            action=type.
        slowly (bool):
            Whether to type character by character. Used with action=type.
        include_static (bool):
            Whether to include static resource requests. Used with
            action=network_requests.
        screenshot_type (str):
            Screenshot format, "png" or "jpeg". Used with action=screenshot.
        snapshot_filename (str):
            File path to save snapshot output. Used with action=snapshot.
        double_click (bool):
            Whether to double-click. Used with action=click.
        button (str):
            Mouse button: "left", "right", or "middle". Used with
            action=click.
        modifiers_json (str):
            JSON array of modifier keys, e.g. ["Shift","Control"]. Used with
            action=click.
        start_ref (str):
            Drag start element ref. Used with action=drag.
        end_ref (str):
            Drag end element ref. Used with action=drag.
        start_selector (str):
            Drag start CSS selector. Used with action=drag.
        end_selector (str):
            Drag end CSS selector. Used with action=drag.
        start_element (str):
            Drag start element description. Used with action=drag.
        end_element (str):
            Drag end element description. Used with action=drag.
        values_json (str):
            JSON of option value(s) for select. Used with
            action=select_option.
        direction (str):
            Scroll direction: down, up, left, or right. Used with
            action=scroll.
        amount (str | int):
            Scroll amount: page, half, line, small, or a pixel count. Used
            with action=scroll.
        tab_action (str):
            Tab action: list, new, close, or select. Required for
            action=tabs.
        index (int):
            Tab index for tabs select, zero-based. Used with action=tabs.
        wait_time (float):
            Seconds to wait. Used with action=wait_for and as the download
            event timeout for action=file_download. Defaults to 30 seconds for
            file_download when omitted.
        text_gone (str):
            Wait until this text disappears from page. Used with
            action=wait_for.
        frame_selector (str):
            iframe selector, e.g. "iframe#main". Set when operating inside
            that iframe in snapshot/click/type etc.
        headed (bool):
            When True with action=start, launch a visible browser window
            (non-headless). User can see the real browser. Default False.
        cdp_port (int):
            When > 0 with action=start, use the specified CDP port. When 0,
            QwenPaw chooses a free local port automatically for managed CDP.
        private_mode (bool):
            When True with action=start, force direct Playwright management
            instead of managed CDP. Use this when the user explicitly does not
            want the browser to be connectable by other local tools/workspaces
            via CDP. Default False. By default, QwenPaw prefers managed CDP for
            both headless and headed starts.
        browser_args (str):
            Extra Chromium launch arguments, e.g. "--incognito" or
            "--proxy-server=http://127.0.0.1:7890". Multiple args separated by
            space. Applied to all launch paths (headless, headed, managed CDP).
            Default empty string (no extra args).
        executable_path (str):
            Custom browser executable path, e.g.
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe".
            When set, overrides the system default browser detection.
            Default empty string (use system default).
        actions_json (str):
            JSON array string of sub-action dicts for action=batch. Required
            when action=batch. Each sub-action dict has at least an "action"
            key specifying the sub-action type. Supported sub-actions:
            navigate, click, type, press_key, evaluate, eval, snapshot,
            screenshot, wait_for, hover, select_option, drag, resize.
            Optional keys per sub-action: "page_id" (override default),
            "wait" (seconds to wait after the action), "stop_on_error"
            (bool, default True). Example:
            [{"action": "navigate", "url": "https://example.com"},
             {"action": "click", "ref": "e1"}, {"action": "type", "ref": "e2", "text": "hello"}].
        cdp_url (str):
            CDP base URL, e.g. "http://localhost:9222". Required for
            action=connect_cdp.
        port (int):
            Scan a single specific port for action=list_cdp_targets.
        port_min (int):
            Lower bound of port range for action=list_cdp_targets.
            Defaults to 9000 when not specified.
        port_max (int):
            Upper bound of port range for action=list_cdp_targets.
            Defaults to 10000 when not specified.
        user_initiated (bool):
            Control mode only. Marks an open/claim navigation as explicitly
            requested by the user for same-site permission decisions.
        allow_new_context (bool):
            Control mode only. Allows a click or key action to keep both the
            opener and a newly created browser tab when the site opens one.
    """
    # Resolve per-workspace state using context var set by react_agent.py
    from qwenpaw.config.context import get_current_workspace_dir as _get_cwd

    _cwd = _get_cwd()
    _ws_id = _cwd.name if _cwd else "default"
    _ws_dir = str(_cwd) if _cwd else ""
    state = _get_workspace_state(_ws_id, _ws_dir)
    _touch_activity(state)

    action = (action or "").strip().lower()
    if not action:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "action required"},
                ensure_ascii=False,
                indent=2,
            ),
        )

    requested_page_id = (page_id or "default").strip() or "default"
    x, coordinate_error = _coerce_optional_coordinate(x, "x")
    if coordinate_error is not None:
        return coordinate_error
    y, coordinate_error = _coerce_optional_coordinate(y, "y")
    if coordinate_error is not None:
        return coordinate_error

    try:
        page_id = requested_page_id
        current = state.get("current_page_id")
        pages = state.get("pages") or {}
        if page_id == "default" and current and current in pages:
            page_id = current

        if not _BROWSER_USE_LEGACY_BYPASS.get() and not (
            _should_preserve_legacy_control_lifecycle(
                mode=mode,
                action=action,
            )
        ):
            return await _browser_use_sdk_shim(
                action=action,
                mode=mode,
                url=url,
                page_id=page_id,
                selector=selector,
                text=text,
                code=code,
                path=path,
                wait=wait,
                full_page=full_page,
                ref=ref,
                element=element,
                x=x,
                y=y,
                key=key,
                filename=filename,
                direction=direction,
                amount=amount,
                tab_action=tab_action,
                index=index,
                wait_time=wait_time,
                text_gone=text_gone,
                values_json=values_json,
            )

        if _should_use_control_mode(mode=mode, action=action, state=state):
            return await _action_control(
                state,
                action,
                page_id=page_id,
                url=url,
                selector=selector,
                text=text,
                path=path,
                wait=wait,
                full_page=full_page,
                width=width,
                height=height,
                filename=filename,
                ref=ref,
                element=element,
                x=x,
                y=y,
                key=key,
                submit=submit,
                include_static=include_static,
                screenshot_type=screenshot_type,
                snapshot_filename=snapshot_filename,
                double_click=double_click,
                button=button,
                modifiers_json=modifiers_json,
                values_json=values_json,
                direction=direction,
                amount=amount,
                tab_action=tab_action,
                index=index,
                wait_time=wait_time,
                text_gone=text_gone,
                user_initiated=user_initiated,
                allow_new_context=allow_new_context,
            )

        if action == "start":
            return await _action_start(
                state,
                headed=headed,
                cdp_port=cdp_port,
                private_mode=private_mode,
                browser_args=browser_args,
                executable_path=executable_path,
            )
        if action == "stop":
            return await _action_stop(state)
        if action == "connect_cdp":
            return await _action_connect_cdp(state, cdp_url)
        if action == "list_cdp_targets":
            return await _action_list_cdp_targets(port, port_min, port_max)
        if action == "open":
            return await _action_open(state, url, page_id)
        if action == "navigate":
            return await _action_navigate(state, url, page_id)
        if action == "navigate_back":
            return await _action_navigate_back(state, page_id)
        if action in ("screenshot", "take_screenshot"):
            return await _action_screenshot(
                state,
                page_id,
                path or filename,
                full_page,
                screenshot_type,
                ref,
                element,
                frame_selector,
            )
        if action == "snapshot":
            return await _action_snapshot(
                state,
                page_id,
                snapshot_filename or filename,
                frame_selector,
            )
        if action == "click":
            return await _action_click(
                state,
                page_id,
                selector,
                ref,
                element,
                wait,
                double_click,
                button,
                modifiers_json,
                frame_selector,
            )
        if action == "type":
            return await _action_type(
                state,
                page_id,
                selector,
                ref,
                element,
                text,
                submit,
                slowly,
                frame_selector,
            )
        if action == "eval":
            return await _action_eval(state, page_id, code)
        if action == "evaluate":
            return await _action_evaluate(
                state,
                page_id,
                code,
                ref,
                element,
                frame_selector,
            )
        if action == "resize":
            return await _action_resize(state, page_id, width, height)
        if action == "console_messages":
            return await _action_console_messages(
                state,
                page_id,
                level,
                filename or path,
            )
        if action == "handle_dialog":
            return await _action_handle_dialog(
                state,
                page_id,
                accept,
                prompt_text,
            )
        if action == "file_upload":
            return await _action_file_upload(state, page_id, paths_json)
        if action == "file_download":
            return await _action_file_download(
                state,
                page_id,
                path or filename,
                ref=ref,
                url=url,
                wait_time=wait_time,
            )
        if action == "fill_form":
            return await _action_fill_form(state, page_id, fields_json)
        if action == "install":
            return await _action_install()
        if action == "press_key":
            return await _action_press_key(state, page_id, key)
        if action == "network_requests":
            return await _action_network_requests(
                state,
                page_id,
                include_static,
                filename or path,
            )
        if action == "run_code":
            return await _action_run_code(state, page_id, code)
        if action == "drag":
            return await _action_drag(
                state,
                page_id,
                start_ref,
                end_ref,
                start_selector,
                end_selector,
                start_element,
                end_element,
                frame_selector,
            )
        if action == "hover":
            return await _action_hover(
                state,
                page_id,
                ref,
                element,
                selector,
                frame_selector,
            )
        if action == "select_option":
            return await _action_select_option(
                state,
                page_id,
                ref,
                element,
                values_json,
                frame_selector,
            )
        if action == "tabs":
            return await _action_tabs(state, page_id, tab_action, index)
        if action == "wait_for":
            return await _action_wait_for(
                state,
                page_id,
                wait_time,
                text,
                text_gone,
            )
        if action == "pdf":
            return await _action_pdf(state, page_id, path)
        if action == "close":
            return await _action_close(state, page_id)
        if action == "cookies_get":
            ctx = _get_context(state)
            if not ctx:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": "Browser not started"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            urls_list = _parse_json_param(url, None) if url else None
            if urls_list is None and url:
                urls_list = [url]
            urls_list = urls_list or []
            try:
                if _USE_SYNC_PLAYWRIGHT:
                    loop = asyncio.get_event_loop()
                    cookies = await loop.run_in_executor(
                        _get_executor(),
                        lambda: ctx.cookies(
                            urls=urls_list if urls_list else [],
                        ),
                    )
                else:
                    cookies = await ctx.cookies(
                        urls=urls_list if urls_list else [],
                    )
                return _tool_response(
                    json.dumps(
                        {"ok": True, "cookies": cookies},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            except Exception as e:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": str(e)},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        if action == "cookies_set":
            ctx = _get_context(state)
            if not ctx:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": "Browser not started"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            try:
                cookies = json.loads(fields_json) if fields_json else []
                if not isinstance(cookies, list) or not all(
                    isinstance(c, dict) and "name" in c and "value" in c
                    for c in cookies
                ):
                    return _tool_response(
                        json.dumps(
                            {
                                "ok": False,
                                "error": (
                                    "fields_json must be a JSON array of"
                                    " cookie objects with 'name' and 'value'"
                                ),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                if _USE_SYNC_PLAYWRIGHT:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        _get_executor(),
                        lambda: ctx.add_cookies(cookies),
                    )
                else:
                    await ctx.add_cookies(cookies)
                return _tool_response(
                    json.dumps(
                        {
                            "ok": True,
                            "message": f"Injected {len(cookies)} cookie(s)",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            except Exception as e:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": str(e)},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        if action == "cookies_clear":
            ctx = _get_context(state)
            if not ctx:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": "Browser not started"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            try:
                if _USE_SYNC_PLAYWRIGHT:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        _get_executor(),
                        ctx.clear_cookies,
                    )
                else:
                    await ctx.clear_cookies()
                return _tool_response(
                    json.dumps(
                        {"ok": True, "message": "All cookies cleared"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            except Exception as e:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": str(e)},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
        if action == "batch":
            return await _action_batch(state, page_id, actions_json)
        if action == "clear_browser_cache":
            return await _action_clear_browser_cache(state)
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Unknown action: {action}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        logger.error("Browser tool error: %s", e, exc_info=True)
        return _tool_response(
            json.dumps(
                {"ok": False, "error": str(e)},
                ensure_ascii=False,
                indent=2,
            ),
        )


__all__ = [name for name in globals() if not name.startswith("__")]
