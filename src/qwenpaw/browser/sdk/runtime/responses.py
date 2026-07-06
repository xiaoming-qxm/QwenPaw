# -*- coding: utf-8 -*-
"""Runtime helpers shared by Browser SDK and Browser Control."""

from __future__ import annotations

import json
import logging
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from qwenpaw.config import (
    get_playwright_chromium_executable_path,
    get_system_default_browser,
    is_running_in_container,
)
from qwenpaw.config.context import get_current_workspace_dir
from qwenpaw.constant import EnvVarLoader, WORKING_DIR

logger = logging.getLogger("qwenpaw.browser.sdk")

_TRUSTED_BROWSER_KEYWORDS = frozenset(
    {
        "chrome",
        "chromium",
        "edge",
        "firefox",
        "brave",
        "vivaldi",
        "opera",
        "360se",
        "yandex",
        "tor",
    },
)

_workspace_states: dict[str, dict[str, Any]] = {}
_CONTROL_BANNER_TIMEOUT_SECONDS = 2.0


def _make_fresh_state(workspace_id: str, workspace_dir: str = "") -> dict:
    """Create a fresh browser runtime state dictionary."""
    user_data_dir = (
        str(Path(workspace_dir) / "browser" / "user_data")
        if workspace_dir
        else ""
    )
    return {
        "playwright": None,
        "browser": None,
        "context": None,
        "pages": {},
        "refs": {},
        "refs_frame": {},
        "console_logs": {},
        "network_requests": {},
        "pending_dialogs": {},
        "pending_file_choosers": {},
        "current_page_id": None,
        "page_counter": 0,
        "workspace_id": workspace_id,
        "workspace_dir": workspace_dir,
        "user_data_dir": user_data_dir,
        "headless": True,
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
    """Get or create shared runtime state for a workspace."""
    key = str(workspace_id or "default")
    if key not in _workspace_states:
        _workspace_states[key] = _make_fresh_state(key, workspace_dir)
    return _workspace_states[key]


def _tool_response(text: str) -> ToolChunk:
    """Wrap text for the AgentScope tool runtime."""
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


def _tool_response_with_blocks(text: str, blocks: list[Any]) -> ToolChunk:
    """Wrap text plus additional AgentScope content blocks."""
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text), *blocks],
    )


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    """Decode the first text block in a ToolChunk as a JSON object."""
    if isinstance(chunk, dict):
        return chunk
    try:
        content = getattr(chunk, "content", [])
        first = content[0] if content else None
        text = getattr(first, "text", "")
    except (AttributeError, IndexError, TypeError):
        text = str(chunk)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {"ok": False, "message": str(text or "")}
    return parsed if isinstance(parsed, dict) else {"ok": False}


def _validate_executable_path(executable_path: str) -> None:
    """Raise ValueError unless *executable_path* is a browser binary."""
    if not executable_path:
        return
    path = Path(executable_path)
    name = path.name.lower()
    if not any(keyword in name for keyword in _TRUSTED_BROWSER_KEYWORDS):
        raise ValueError(
            f"executable_path rejected: '{path.name}' does not match any "
            "trusted browser name",
        )
    if not path.is_file():
        raise ValueError(
            f"executable_path rejected: '{executable_path}' does not exist",
        )


def _resolve_output_path(path: str) -> str:
    """Resolve relative output paths under workspace_dir/browser."""
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
    """Return and create the browser output directory for a workspace."""
    workspace_dir = state.get("workspace_dir")
    base_dir = Path(workspace_dir) if workspace_dir else WORKING_DIR
    output_dir = base_dir / "browser" / name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _chromium_launch_args() -> list[str]:
    """Return extra Chromium launch args needed for this host."""
    args: list[str] = []
    if is_running_in_container() or sys.platform == "win32":
        args.extend(["--no-sandbox"])
    if is_running_in_container():
        args.extend(["--disable-dev-shm-usage"])
    if sys.platform == "win32":
        args.extend(["--disable-gpu"])
    return args


def _chromium_executable_path() -> str | None:
    """Return configured Playwright Chromium executable path."""
    return get_playwright_chromium_executable_path()


def _resolve_chromium_launch_target() -> tuple[str | None, str | None]:
    """Return browser kind and executable path for an isolated launch."""
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


def _use_webkit_fallback() -> bool:
    """Return whether macOS should use WebKit when Chromium is absent."""
    default_kind, exe = _resolve_chromium_launch_target()
    return sys.platform == "darwin" and default_kind == "webkit" and not exe


def _parse_browser_args(browser_args: str) -> list[str]:
    """Parse extra browser args using platform-appropriate shell rules."""
    if not browser_args:
        return []
    return shlex.split(browser_args, posix=sys.platform != "win32")


def _ensure_playwright_async():
    """Import async_playwright with the standard setup hint on failure."""
    try:
        from playwright.async_api import async_playwright

        return async_playwright
    except ImportError as exc:
        raise ImportError(
            "Playwright not installed. Use the same Python that runs "
            "QwenPaw, then install playwright and browser binaries.",
        ) from exc


def is_playwright_available() -> bool:
    """Return whether the Playwright Python package can be imported."""
    try:
        _ensure_playwright_async()
    except ImportError:
        return False
    return True


async def stop_all_browsers() -> None:
    """Stop all Browser SDK isolated runtimes."""
    from ..backends.isolated import get_isolated_runtime_manager

    await get_isolated_runtime_manager().stop_all()


async def stop_browsers_for_workspace_dirs(
    workspace_dirs: list[str],
) -> None:
    """Stop isolated runtimes affected by a workspace restore operation."""
    del workspace_dirs
    await stop_all_browsers()


__all__ = [
    "ToolChunk",
    "ToolResultState",
    "_CONTROL_BANNER_TIMEOUT_SECONDS",
    "_browser_output_dir",
    "_chunk_payload",
    "_chromium_executable_path",
    "_chromium_launch_args",
    "_ensure_playwright_async",
    "_get_workspace_state",
    "_make_fresh_state",
    "_parse_browser_args",
    "_resolve_chromium_launch_target",
    "_resolve_output_path",
    "_safe_download_filename",
    "_tool_response",
    "_tool_response_with_blocks",
    "_use_webkit_fallback",
    "_validate_executable_path",
    "_workspace_states",
    "is_playwright_available",
    "logger",
    "stop_all_browsers",
    "stop_browsers_for_workspace_dirs",
]
