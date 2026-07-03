# -*- coding: utf-8 -*-
"""Python REPL tools for Browser Control SDK scripting."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from typing import cast

from agentscope.message import DataBlock, TextBlock, ToolResultState, URLSource
from agentscope.tool import ToolChunk
from pydantic import AnyUrl
from qwenpaw.agents.tools.browser.control.session_manager import (
    _control_request_context,
)

from .repl.manager import KernelManager
from .routes import _expected_token, extension_install_status


_manager: KernelManager | None = None
_IDLE_TIMEOUT_SECONDS = 300  # 5 minutes


class _IdleTracker:
    """Auto-shutdown REPL after idle timeout."""

    def __init__(self) -> None:
        self._last_activity: float = 0
        self._timer_task: asyncio.Task | None = None

    def touch(self) -> None:
        """Record activity timestamp and ensure timer is running."""
        self._last_activity = time.monotonic()
        if self._timer_task is None or self._timer_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._timer_task = loop.create_task(self._idle_loop())
            except RuntimeError:
                pass

    async def _idle_loop(self) -> None:
        """Periodically check idle state."""
        while True:
            await asyncio.sleep(60)
            elapsed = time.monotonic() - self._last_activity
            if elapsed >= _IDLE_TIMEOUT_SECONDS:
                await shutdown_python_repl()
                break


_idle_tracker = _IdleTracker()


def _get_manager() -> KernelManager:
    global _manager  # pylint: disable=global-statement
    if _manager is None:
        plugin_dir = Path(__file__).parent
        status = extension_install_status()
        _manager = KernelManager(
            plugin_dir / "repl" / "kernel.py",
            plugin_dir / "sdk",
            ws_url=str(status.get("ws_url") or ""),
            token=_expected_token(),
        )
    return _manager


async def python_repl(code: str, timeout_ms: int = 30000) -> str | ToolChunk:
    """Execute Python code in the Browser Control REPL kernel."""
    _idle_tracker.touch()
    manager = _get_manager()
    result = await manager.execute(
        code,
        timeout_ms,
        request_context=_control_request_context(),
    )
    error = result.get("error")
    if error:
        text = (
            f"Error ({error['type']}): {error['message']}\n"
            f"{error.get('traceback', '')}"
        )
        return _with_artifacts(text, result.get("artifacts"))
    parts = []
    if result.get("output"):
        parts.append(result["output"])
    if result.get("return_value"):
        parts.append(result["return_value"])
    return _with_artifacts(
        "\n".join(parts) or "(no output)",
        result.get("artifacts"),
    )


def _with_artifacts(text: str, artifacts: Any) -> str | ToolChunk:
    blocks = _artifact_blocks(artifacts)
    if not blocks:
        return text
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text), *blocks],
    )


def _artifact_blocks(artifacts: Any) -> list[DataBlock]:
    if not isinstance(artifacts, list):
        return []
    blocks: list[DataBlock] = []
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        media_type = str(item.get("media_type") or "").strip()
        if not url or not media_type:
            continue
        blocks.append(
            DataBlock(
                source=URLSource(
                    url=cast(AnyUrl, url),
                    media_type=media_type,
                ),
                name=str(item.get("name") or ""),
            ),
        )
    return blocks


async def python_repl_reset() -> str:
    """Reset the Browser Control REPL kernel namespace."""
    manager = _get_manager()
    await manager.reset()
    return "Python REPL environment reset."


async def shutdown_python_repl() -> None:
    """Shutdown the Browser Control REPL kernel if it exists."""
    global _manager  # pylint: disable=global-statement
    if _manager is not None:
        await _manager.shutdown()
        _manager = None


__all__ = ["python_repl", "python_repl_reset", "shutdown_python_repl"]
