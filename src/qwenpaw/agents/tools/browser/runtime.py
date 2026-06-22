# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: E501
"""Browser automation tool using Playwright.

Single tool with action-based API matching browser MCP: start, stop, open,
navigate, navigate_back, screenshot, snapshot, click, type, eval, evaluate,
resize, console_messages, handle_dialog, file_upload, file_download, fill_form, install,
press_key, network_requests, run_code, drag, hover, select_option, tabs,
wait_for, pdf, close. Uses refs from snapshot for ref-based actions.
"""

import asyncio
import atexit
import base64
import contextlib
from collections.abc import Callable, Iterable
from concurrent import futures
import json
import logging
import re
import shlex
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from typing import Any, Optional
from urllib.parse import urljoin, urlparse
from urllib import request as urllib_request

from agentscope.message import DataBlock, TextBlock, URLSource
from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState

from qwenpaw.config import (
    get_playwright_chromium_executable_path,
    get_system_default_browser,
    is_running_in_container,
)
from qwenpaw.config.context import get_current_workspace_dir
from qwenpaw.constant import WORKING_DIR, EnvVarLoader
from qwenpaw.exceptions import DirectUrlDownloadRejectedError
from qwenpaw.runtime.tool_registry import tool_descriptor

from qwenpaw.agents.tools.browser_snapshot import build_role_snapshot_from_aria

logger = logging.getLogger(__name__)

_MAX_DIRECT_URL_DOWNLOAD_BYTES = 10 * 1024 * 1024
_CDP_CONNECT_TIMEOUT_SECONDS = 30.0
_CONTROL_BANNER_TIMEOUT_SECONDS = 2.0
_HEADLESS_VERIFICATION_WARNING = (
    "Headless browser launches are more likely to trigger verification. "
    "If verification appears, call browser_use with action='stop' to stop "
    "the current browser, then call browser_use with action='start' and "
    "headed=true to open a visible browser and continue there."
)


# Keywords used to validate executable_path — the binary filename must
# contain at least one of these (case-insensitive) to be accepted.
_TRUSTED_BROWSER_KEYWORDS = frozenset(
    {
        "chrome",  # Google Chrome
        "chromium",  # Chromium (open-source)
        "edge",  # Microsoft Edge
        "firefox",  # Mozilla Firefox
        "brave",  # Brave Browser
        "vivaldi",  # Vivaldi Browser
        "opera",  # Opera
        "360se",  # 360 Secure Browser
        "yandex",  # Yandex Browser
        "tor",  # Tor Browser
    },
)


def _validate_executable_path(executable_path: str) -> None:
    """Raise ValueError if *executable_path* is not a trusted browser binary."""
    if not executable_path:
        return
    name = Path(executable_path).name.lower()
    if not any(kw in name for kw in _TRUSTED_BROWSER_KEYWORDS):
        raise ValueError(
            f"executable_path rejected: '{Path(executable_path).name}' "
            f"does not match any trusted browser name "
            f"(keywords: {', '.join(sorted(_TRUSTED_BROWSER_KEYWORDS))})",
        )
    if not Path(executable_path).is_file():
        raise ValueError(
            f"executable_path rejected: '{executable_path}' does not exist",
        )


def _resolve_output_path(path: str) -> str:
    """Resolve relative output paths under workspace_dir/browser/."""
    if Path(path).is_absolute():
        return path
    base_dir = (get_current_workspace_dir() or WORKING_DIR) / "browser"
    base_dir.mkdir(parents=True, exist_ok=True)
    return str(base_dir / path)


def _safe_download_filename(filename: Any, default: str = "download") -> str:
    """Return a filesystem-safe filename for browser downloads."""
    name = Path(str(filename or "")).name.strip()
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name)
    name = name.strip(" .")
    return name or default


def _browser_output_dir(state: dict, name: str) -> Path:
    """Return workspace browser output directory and create it if needed."""
    workspace_dir = state.get("workspace_dir")
    base_dir = Path(workspace_dir) if workspace_dir else WORKING_DIR
    output_dir = base_dir / "browser" / name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


async def _configure_download_behavior(state: dict) -> None:
    """Configure Chromium CDP download path when available."""
    context = _get_context(state)
    page = next(iter(state["pages"].values()), None)
    if context is None or page is None or _USE_SYNC_PLAYWRIGHT:
        return
    cdp = None
    try:
        cdp = await context.new_cdp_session(page)
        await cdp.send(
            "Browser.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(_browser_output_dir(state, "downloads")),
                "eventsEnabled": True,
            },
        )
    except Exception:
        logger.debug(
            "Failed to configure browser download behavior",
            exc_info=True,
        )
    finally:
        if cdp is not None:
            try:
                await cdp.detach()
            except Exception:
                logger.debug(
                    "Failed to detach download behavior CDP session",
                    exc_info=True,
                )


# Hybrid mode detection: Windows + Uvicorn reload mode requires sync Playwright
# to avoid NotImplementedError with asyncio.create_subprocess_exec.
# On other platforms or without reload, use async Playwright for better performance.
_USE_SYNC_PLAYWRIGHT = sys.platform == "win32" and EnvVarLoader.get_bool(
    "QWENPAW_RELOAD_MODE",
)

if _USE_SYNC_PLAYWRIGHT:
    _executor: Optional[futures.ThreadPoolExecutor] = None

    def _get_executor() -> futures.ThreadPoolExecutor:
        global _executor
        if _executor is None:
            _executor = futures.ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="playwright",
            )
        return _executor

    async def _run_sync(func, *args, **kwargs):
        """Run a sync function in the thread pool and await the result."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _get_executor(),
            lambda: func(*args, **kwargs),
        )

else:

    async def _run_sync(func, *args, **kwargs):
        """Fallback: directly call async function (should not be used in async mode)."""
        return await func(*args, **kwargs)


# Per-workspace browser states: workspace_id -> state dict
_workspace_states: dict[str, dict[str, Any]] = {}


def _make_fresh_state(workspace_id: str, workspace_dir: str) -> dict[str, Any]:
    """Create a fresh browser state dict for a workspace."""
    user_data_dir = (
        str(Path(workspace_dir) / "browser" / "user_data")
        if workspace_dir
        else ""
    )
    return {
        "playwright": None,
        "browser": None,
        "context": None,
        "_sync_playwright": None,
        "_sync_browser": None,
        "_sync_context": None,
        "pages": {},
        "refs": {},  # page_id -> ref -> {role, name?, nth?}
        "refs_frame": {},  # page_id -> frame for last snapshot
        "console_logs": {},  # page_id -> list of {level, text}
        "network_requests": {},  # page_id -> list of request dicts
        "pending_dialogs": {},  # page_id -> dialog handlers
        "pending_file_choosers": {},  # page_id -> FileChooser list
        "headless": True,
        "current_page_id": None,
        "page_counter": 0,  # monotonic counter for page_N ids, avoids reuse after close
        "last_activity_time": 0.0,  # monotonic timestamp of last browser activity
        "_idle_task": None,  # background asyncio.Task for idle watchdog
        "_last_browser_error": None,  # message when launch failed (for user-facing error)
        "workspace_id": workspace_id,
        "workspace_dir": workspace_dir,
        "user_data_dir": user_data_dir,
        "connected_via_cdp": False,
        "cdp_url": None,
        "launch_mode": None,
        "owned_browser_process": False,
        "browser_pid": None,
        "browser_process": None,
    }


def _get_workspace_state(
    workspace_id: str,
    workspace_dir: str = "",
) -> dict[str, Any]:
    """Get or create the browser state for a workspace."""
    if workspace_id not in _workspace_states:
        _workspace_states[workspace_id] = _make_fresh_state(
            workspace_id,
            workspace_dir,
        )
    return _workspace_states[workspace_id]


# Stop the browser after this many seconds of inactivity (default 10 minutes).
_BROWSER_IDLE_TIMEOUT = 600.0


def _touch_activity(state: dict) -> None:
    """Record the current time as the last browser activity timestamp."""
    state["last_activity_time"] = time.monotonic()


def _is_browser_running(state: dict) -> bool:
    """Check if browser is currently running (sync or async mode)."""
    if _USE_SYNC_PLAYWRIGHT:
        return (
            state.get("_sync_context") is not None
            or state.get("_sync_browser") is not None
        )
    return state.get("browser") is not None or state.get("context") is not None


def _reset_browser_state(state: dict) -> None:
    """Reset all browser-related state variables."""
    # Clear sync/async specific state
    state["playwright"] = None
    state["browser"] = None
    state["context"] = None
    state["_sync_playwright"] = None
    state["_sync_browser"] = None
    state["_sync_context"] = None
    # Clear shared state
    state["pages"].clear()
    state["refs"].clear()
    state["refs_frame"].clear()
    state["console_logs"].clear()
    state["network_requests"].clear()
    state["pending_dialogs"].clear()
    state["pending_file_choosers"].clear()
    state["current_page_id"] = None
    state["page_counter"] = 0
    state["last_activity_time"] = 0.0
    state["headless"] = True
    state["connected_via_cdp"] = False
    state["cdp_url"] = None
    state["launch_mode"] = None
    state["owned_browser_process"] = False
    state["browser_pid"] = None
    state["browser_process"] = None


async def _idle_watchdog(
    state: dict,
    idle_seconds: float = _BROWSER_IDLE_TIMEOUT,
) -> None:
    """Background task: stop the browser after it has been idle for *idle_seconds*.

    This reclaims Chrome renderer processes that accumulate when pages are
    opened during agent tasks but never explicitly closed.
    """
    try:
        check_interval = max(1.0, min(60.0, idle_seconds / 2))
        while True:
            await asyncio.sleep(check_interval)
            if not _is_browser_running(state):
                return
            idle = time.monotonic() - state.get("last_activity_time", 0.0)
            if idle >= idle_seconds:
                logger.info(
                    "Browser idle for %.0fs (limit %.0fs), stopping to release resources",
                    idle,
                    idle_seconds,
                )
                await _action_stop(state)
                return
    except asyncio.CancelledError:
        pass


def _atexit_cleanup() -> None:
    """Best-effort browser cleanup registered with :func:`atexit`.

    Playwright child processes are cleaned up by the OS when the parent
    exits, but this gives Playwright a chance to flush any pending I/O and
    close Chrome gracefully before the process disappears.
    """
    if not _workspace_states:
        return

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running() or loop.is_closed():
            return
        for ws_state in list(_workspace_states.values()):
            if _is_browser_running(ws_state):
                try:
                    loop.run_until_complete(_action_stop(ws_state))
                except Exception:
                    pass
    except Exception:
        pass


atexit.register(_atexit_cleanup)


def _tool_response(text: str) -> ToolChunk:
    """Wrap text for agentscope Toolkit (return ToolChunk)."""
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


def _tool_response_with_blocks(text: str, blocks: list[Any]) -> ToolChunk:
    """Wrap text plus additional content blocks for agentscope Toolkit."""
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text), *blocks],
    )


def _chromium_launch_args() -> list[str]:
    """Extra args for Chromium when running in container or Windows."""
    args = []
    if is_running_in_container() or sys.platform == "win32":
        args.extend(["--no-sandbox"])

    if is_running_in_container():
        args.extend(["--disable-dev-shm-usage"])
    # Windows always needs --disable-gpu to run properly
    if sys.platform == "win32":
        args.extend(["--disable-gpu"])
    return args


def _chromium_executable_path() -> str | None:
    """Chromium executable path when set (e.g. container); else None."""
    return get_playwright_chromium_executable_path()


def _use_webkit_fallback() -> bool:
    """True only on macOS when no system Chrome/Edge/Chromium found.
    Use WebKit (Safari) to avoid downloading Chromium. Windows has no system
    WebKit, so we never use webkit there.
    """
    return sys.platform == "darwin" and _chromium_executable_path() is None


def _ensure_playwright_async():
    """Import async_playwright; raise ImportError with hint if missing."""
    try:
        from playwright.async_api import async_playwright

        return async_playwright
    except ImportError as exc:
        raise ImportError(
            "Playwright not installed. Use the same Python that runs QwenPaw (e.g. "
            "activate your venv or use 'uv run'): "
            f"'{sys.executable}' -m pip install playwright && "
            f"'{sys.executable}' -m playwright install",
        ) from exc


def _ensure_playwright_sync():
    """Import sync_playwright; raise ImportError with hint if missing."""
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError as exc:
        raise ImportError(
            "Playwright not installed. Use the same Python that runs QwenPaw (e.g. "
            "activate your venv or use 'uv run'): "
            f"'{sys.executable}' -m pip install playwright && "
            f"'{sys.executable}' -m playwright install",
        ) from exc


async def _stop_playwright_instance(pw: Any) -> None:
    """Best-effort stop for a locally-started Playwright driver."""
    if pw is None:
        return
    try:
        await pw.stop()
    except Exception:
        pass


def _sync_browser_launch(
    state: dict,
    cdp_port: int = 0,
    browser_args: str = "",
    executable_path: str = "",
):
    """Launch browser using sync Playwright (for hybrid mode)."""
    sync_playwright = _ensure_playwright_sync()
    pw = sync_playwright().start()  # Start without context manager
    use_default = not is_running_in_container() and EnvVarLoader.get_bool(
        "QWENPAW_BROWSER_USE_DEFAULT",
        True,
    )
    default_kind, default_path = (
        get_system_default_browser() if use_default else (None, None)
    )
    exe: Optional[str] = None
    if default_kind == "chromium" and default_path:
        exe = default_path
    elif default_kind != "webkit":
        exe = _chromium_executable_path()
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
        user_data_dir = state["user_data_dir"]
        if user_data_dir:
            Path(user_data_dir).mkdir(parents=True, exist_ok=True)
            context = pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=state["headless"],
                executable_path=exe,
                args=extra_args if extra_args else [],
                accept_downloads=True,
            )
            _attach_context_listeners(state, context)
            return pw, None, context
        launch_kwargs = {"headless": state["headless"]}
        if extra_args:
            launch_kwargs["args"] = extra_args
        launch_kwargs["executable_path"] = exe
        browser = pw.chromium.launch(**launch_kwargs)
    elif default_kind == "webkit" or sys.platform == "darwin":
        browser = pw.webkit.launch(headless=state["headless"])
    else:
        launch_kwargs = {"headless": state["headless"]}
        if extra_args:
            launch_kwargs["args"] = extra_args
        browser = pw.chromium.launch(**launch_kwargs)

    context = browser.new_context(accept_downloads=True)
    _attach_context_listeners(state, context)
    return pw, browser, context


def _sync_browser_close(state: dict):
    """Close browser using sync Playwright (for hybrid mode)."""
    if state["_sync_browser"] is not None:
        try:
            state["_sync_browser"].close()
        except Exception:
            pass
    elif state["_sync_context"] is not None:
        # persistent context mode: no separate browser object, close context directly
        try:
            state["_sync_context"].close()
        except Exception:
            pass
    if state["_sync_playwright"] is not None:
        try:
            state["_sync_playwright"].stop()
        except Exception:
            pass


def _resolve_chromium_launch_target() -> tuple[Optional[str], Optional[str]]:
    """Return (browser_kind, executable_path) for Chromium-family launches."""
    use_default = not is_running_in_container() and EnvVarLoader.get_bool(
        "QWENPAW_BROWSER_USE_DEFAULT",
        True,
    )
    default_kind, default_path = (
        get_system_default_browser() if use_default else (None, None)
    )
    if default_kind == "chromium" and default_path:
        return default_kind, default_path
    if default_kind == "webkit":
        return default_kind, None
    return default_kind, _chromium_executable_path()


def _find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


async def _wait_for_cdp_ready(
    port: int,
    timeout: float = 15.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    url = f"http://127.0.0.1:{port}/json/version"
    while time.monotonic() < deadline:
        try:
            with urllib_request.urlopen(url, timeout=1.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(0.2)
    raise RuntimeError(
        f"Timed out waiting for Chrome CDP endpoint on port {port}: {last_error}",
    )


async def _start_managed_cdp_browser(
    state: dict,
    cdp_port: int = 0,
    ensure_pages: bool = False,
    browser_args: str = "",
    executable_path: str = "",
) -> None:
    default_kind, exe = _resolve_chromium_launch_target()
    if executable_path:
        exe = executable_path
    if not exe:
        if default_kind == "webkit" or sys.platform == "darwin":
            raise RuntimeError(
                "Managed CDP mode requires "
                "Chrome/Chromium/Edge. Safari/WebKit "
                "is not supported.",
            )
        raise RuntimeError(
            "Managed CDP mode requires a Chrome/Chromium executable, "
            "but none was found.",
        )

    chosen_cdp_port = cdp_port or _find_free_local_port()
    proc = _start_managed_chromium_process(
        executable_path=exe,
        user_data_dir=state["user_data_dir"],
        headless=state["headless"],
        cdp_port=chosen_cdp_port,
        browser_args=browser_args,
    )
    pw = None
    try:
        await _wait_for_cdp_ready(chosen_cdp_port)
        async_playwright = _ensure_playwright_async()
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(
            f"http://127.0.0.1:{chosen_cdp_port}",
        )
        contexts = browser.contexts
        context = (
            contexts[0]
            if contexts
            else await browser.new_context(
                accept_downloads=True,
            )
        )
        _attach_context_listeners(state, context)
        state["playwright"] = pw
        state["browser"] = browser
        state["context"] = context
        state["connected_via_cdp"] = True
        state["cdp_url"] = f"http://127.0.0.1:{chosen_cdp_port}"
        state["launch_mode"] = "managed_cdp"
        state["owned_browser_process"] = True
        state["browser_pid"] = proc.pid
        state["browser_process"] = proc
        if ensure_pages:
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
    except Exception:
        await _stop_playwright_instance(pw)
        try:
            if proc.poll() is None:
                proc.kill()
                await asyncio.to_thread(proc.wait, 5)
        except Exception:
            pass
        raise


def _start_managed_chromium_process(
    executable_path: str,
    user_data_dir: str,
    headless: bool,
    cdp_port: int,
    browser_args: str = "",
) -> subprocess.Popen:
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    args = [
        executable_path,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-features=Translate,MediaRouter,AutomationControlled",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--password-store=basic",
    ]
    args.extend(_chromium_launch_args())
    if browser_args:
        args.extend(shlex.split(browser_args, posix=sys.platform != "win32"))
    if headless:
        args.extend(["--headless=new", "--disable-gpu"])

    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "cwd": str(Path(user_data_dir).parent),
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    return subprocess.Popen(args, **popen_kwargs)


async def _stop_owned_browser_process(state: dict) -> bool:
    proc = state.get("browser_process")
    if proc is None:
        return False

    if proc.poll() is not None:
        return True

    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        await asyncio.to_thread(proc.wait, 5)
        return True
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            await asyncio.to_thread(proc.wait, 5)
            return True
        except Exception:
            return False
    except Exception:
        return False


def _parse_json_param(value: str, default: Any = None):
    """Parse optional JSON string param (e.g. fields, paths, values)."""
    if not value or not isinstance(value, str):
        return default
    value = value.strip()
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        if "," in value:
            return [x.strip() for x in value.split(",")]
        return default


def _get_page(state: dict, page_id: str):
    """Return page for page_id or None if not found."""
    return state["pages"].get(page_id)


async def _get_tab_info_list(state: dict) -> list[dict[str, str]]:
    """Return a list of dicts with page_id, url, and title for all pages.
    Safely handles closed or detached pages without raising exceptions.
    """
    pages = state.get("pages", {})
    tab_list = []
    for pid, p in list(pages.items()):
        try:
            # Basic sanity check: if the page object is gone or explicitly closed
            if p is None:
                continue

            # Playwright pages might be closed but still in our dict
            # We use a try-except block to catch 'Target closed' errors during property access
            if _USE_SYNC_PLAYWRIGHT:
                is_closed = await _run_sync(p.is_closed)
                if is_closed:
                    continue
                url = p.url
                title = await _run_sync(p.title)
            else:
                if p.is_closed():
                    continue
                url = p.url
                title = await p.title()

            tab_list.append(
                {
                    "page_id": pid,
                    "url": url or "about:blank",
                    "title": title or "Untitled",
                },
            )
        except Exception:
            # If any error occurs (e.g. page detached, browser crashed),
            # we skip this tab or provide a fallback if we know it exists.
            logger.debug("Failed to get info for tab %s, skipping", pid)
            continue
    return tab_list


def _get_context(state: dict):
    """Return the active browser context regardless of sync/async mode."""
    return state["context"] or state.get("_sync_context")


def _get_refs(state: dict, page_id: str) -> dict[str, dict]:
    """Return refs map for page_id (ref -> {role, name?, nth?})."""
    return state["refs"].setdefault(page_id, {})


def _get_root(page, frame_selector: str = ""):
    """Return page or frame for frame_selector (ref/selector)."""
    if not (frame_selector and frame_selector.strip()):
        return page
    return page.frame_locator(frame_selector.strip())


def _get_locator_by_ref(
    state: dict,
    page,
    page_id: str,
    ref: str,
    frame_selector: str = "",
):
    """Resolve snapshot ref to locator; frame_selector for iframe."""
    refs = _get_refs(state, page_id)
    info = refs.get(ref)
    if not info:
        return None
    role = info.get("role", "generic")
    name = info.get("name")
    nth = info.get("nth")
    root = _get_root(page, frame_selector)
    locator = root.get_by_role(role, name=name or None)
    if nth is not None:
        locator = locator.nth(nth)
    return locator


def _attach_page_listeners(state: dict, page, page_id: str) -> None:
    """Attach console and request listeners for a page."""
    logs = state["console_logs"].setdefault(page_id, [])

    def on_console(msg):
        logs.append({"level": msg.type, "text": msg.text})

    page.on("console", on_console)

    def on_request(req):
        requests_list.append(
            {
                "url": req.url,
                "method": req.method,
                "resourceType": getattr(req, "resource_type", None),
            },
        )

    def on_crash(_p):
        logger.error("Browser page crashed: %s", page_id)

    page.on("crash", on_crash)

    requests_list = state["network_requests"].setdefault(page_id, [])

    def on_response(res):
        for r in requests_list:
            if r.get("url") == res.url and "status" not in r:
                r["status"] = res.status
                break

    page.on("request", on_request)
    page.on("response", on_response)
    dialogs = state["pending_dialogs"].setdefault(page_id, [])

    def on_dialog(dialog):
        dialogs.append(dialog)

    page.on("dialog", on_dialog)
    choosers = state["pending_file_choosers"].setdefault(page_id, [])

    def on_filechooser(chooser):
        choosers.append(chooser)

    page.on("filechooser", on_filechooser)


def _next_page_id(state: dict) -> str:
    """Return a unique page_id (page_N).
    Uses monotonic counter so IDs are not reused after close."""
    state["page_counter"] = state.get("page_counter", 0) + 1
    return f"page_{state['page_counter']}"


def _register_page(state: dict, page, page_id: str) -> None:
    """Initialize state and listeners for a page."""
    state["refs"][page_id] = {}
    state["console_logs"][page_id] = []
    state["network_requests"][page_id] = []
    state["pending_dialogs"][page_id] = []
    state["pending_file_choosers"][page_id] = []
    _attach_page_listeners(state, page, page_id)
    state["pages"][page_id] = page


def _attach_context_listeners(state: dict, context) -> None:
    """When the page opens a new tab (e.g. target=_blank, window.open),
    register it and set as current."""

    def on_page(page):
        new_id = _next_page_id(state)
        _register_page(state, page, new_id)
        state["current_page_id"] = new_id
        logger.debug(
            "New tab opened by page, registered as page_id=%s",
            new_id,
        )

    context.on("page", on_page)


# pylint: disable=too-many-branches,too-many-statements
async def _ensure_browser(
    state: dict,
) -> bool:
    """Start browser if not running. Return True if ready, False on failure."""
    # CDP-connected mode: verify the connection is still alive; never auto-restart.
    if state.get("connected_via_cdp"):
        browser = state.get("browser")
        if browser is not None and browser.is_connected():
            _touch_activity(state)
            return True
        cdp_url = state.get("cdp_url") or "unknown"
        state["_last_browser_error"] = (
            f"CDP connection lost (was: {cdp_url}). "
            "Reconnect with action='connect_cdp'."
        )
        _reset_browser_state(state)
        return False

    # Check browser state based on mode
    if _USE_SYNC_PLAYWRIGHT:
        if state["_sync_context"] is not None:
            # Check if sync browser is still connected
            browser = state.get("_sync_browser")
            is_connected = True
            if browser:
                try:
                    is_connected = browser.is_connected()
                except Exception:
                    is_connected = False

            if is_connected:
                _touch_activity(state)
                return True
            else:
                logger.warning(
                    "Sync browser process disconnected, resetting state",
                )
                _reset_browser_state(state)
    else:
        # Accept both regular context (browser+context) and persistent context
        # (context only, no separate browser object)
        if state["context"] is not None:
            # Check if async browser is still connected
            browser = state.get("browser")
            is_connected = True
            if browser:
                is_connected = browser.is_connected()

            if is_connected:
                _touch_activity(state)
                return True
            else:
                logger.warning(
                    "Async browser process disconnected, resetting state",
                )
                _reset_browser_state(state)

    try:
        if _USE_SYNC_PLAYWRIGHT:
            # Hybrid mode: use sync Playwright in thread pool
            loop = asyncio.get_event_loop()
            pw, browser, context = await loop.run_in_executor(
                _get_executor(),
                lambda: _sync_browser_launch(
                    state,
                    browser_args=state.get("_browser_args", ""),
                    executable_path=state.get("_executable_path", ""),
                ),
            )
            state["_sync_playwright"] = pw
            state["_sync_browser"] = browser
            state["_sync_context"] = context
            state["connected_via_cdp"] = False
            state["cdp_url"] = None
            state["owned_browser_process"] = False
            state["browser_pid"] = None
            state["browser_process"] = None
            state["launch_mode"] = "playwright"
        else:
            try:
                await _start_managed_cdp_browser(
                    state,
                    ensure_pages=True,
                    browser_args=state.get("_browser_args", ""),
                    executable_path=state.get("_executable_path", ""),
                )
            except Exception:
                await _action_start(
                    state,
                    headed=not state["headless"],
                    private_mode=True,
                    browser_args=state.get("_browser_args", ""),
                    executable_path=state.get("_executable_path", ""),
                )
        state["_last_browser_error"] = None
        _touch_activity(state)
        _start_idle_watchdog(state)
        await _configure_download_behavior(state)
        return True
    except Exception as e:
        state["_last_browser_error"] = str(e)
        return False


def _start_idle_watchdog(state: dict) -> None:
    """Cancel any existing idle watchdog and start a fresh one."""
    old_task = state.get("_idle_task")
    if old_task and not old_task.done():
        old_task.cancel()
    state["_idle_task"] = asyncio.ensure_future(_idle_watchdog(state))


def _cancel_idle_watchdog(state: dict) -> None:
    """Cancel the idle watchdog, if running.

    Note: If called from within the watchdog task itself (e.g., during _action_stop
    triggered by idle timeout), we don't cancel the current task - just clear the
    reference and let the watchdog exit naturally after _action_stop returns.
    """
    task = state.get("_idle_task")
    current = asyncio.current_task()
    if task and not task.done() and task is not current:
        task.cancel()
    state["_idle_task"] = None


# pylint: disable=R0912,R0915


__all__ = [name for name in globals() if not name.startswith("__")]
