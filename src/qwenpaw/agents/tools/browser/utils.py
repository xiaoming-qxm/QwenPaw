# -*- coding: utf-8 -*-
"""Pure utility helpers for browser tools."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ....config import (
    get_playwright_chromium_executable_path,
    is_running_in_container,
)
from ....config.context import get_current_workspace_dir
from ....constant import WORKING_DIR

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


def _validate_executable_path(executable_path: str) -> None:
    """Raise ``ValueError`` unless *executable_path* is a browser binary."""
    if not executable_path:
        return
    path = Path(executable_path)
    name = path.name.lower()
    if not any(kw in name for kw in _TRUSTED_BROWSER_KEYWORDS):
        raise ValueError(
            f"executable_path rejected: '{path.name}' does not match any "
            "trusted browser name",
        )
    if not path.is_file():
        raise ValueError(
            f"executable_path rejected: '{executable_path}' does not exist",
        )


def _resolve_output_path(path: str) -> str:
    """Resolve relative output paths under ``workspace_dir/browser``."""
    if Path(path).is_absolute():
        return path
    base_dir = (get_current_workspace_dir() or WORKING_DIR) / "browser"
    base_dir.mkdir(parents=True, exist_ok=True)
    return str(base_dir / path)


def _safe_download_filename(
    filename: Any,
    default: str = "download",
) -> str:
    """Return a filesystem-safe browser download filename."""
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


def _chromium_launch_args() -> list[str]:
    """Return extra Chromium launch args needed for the host platform."""
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


def _use_webkit_fallback() -> bool:
    """Return whether macOS should use WebKit when Chromium is absent."""
    return sys.platform == "darwin" and _chromium_executable_path() is None


def _parse_json_param(value: str, default: Any = None) -> Any:
    """Parse a JSON parameter, returning *default* on empty/invalid input."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
