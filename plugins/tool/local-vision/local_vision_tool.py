# -*- coding: utf-8 -*-
"""Tool function and worker lifecycle for Local Vision."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk
from qwenpaw.plugins import get_tool_config

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).resolve().parent
_DEFAULT_READY_TIMEOUT = 120.0
_DEFAULT_PARSE_TIMEOUT = 30.0


def _load_model_manager():
    import importlib.util

    path = _PLUGIN_DIR / "model_manager.py"
    spec = importlib.util.spec_from_file_location(
        "local_vision_model_manager",
        path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load local vision model manager: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["local_vision_model_manager"] = module
    spec.loader.exec_module(module)
    return module


class LocalVisionWorkerManager:
    """Own the Local Vision worker subprocess and JSON-RPC calls."""

    def __init__(self, plugin_dir: Path = _PLUGIN_DIR) -> None:
        self.plugin_dir = plugin_dir
        self.process: asyncio.subprocess.Process | None = None
        self._rpc_lock = asyncio.Lock()
        self._stderr_task: asyncio.Task | None = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def start(self, config: dict[str, Any] | None = None) -> None:
        if self.is_running():
            return

        model_manager = _load_model_manager()
        selection = await asyncio.to_thread(
            model_manager.ensure_model_available,
            config or {},
        )
        env = os.environ.copy()
        env.update(
            {
                "VISION_MODEL_PATH": selection.model_path,
                "VISION_MODEL_ID": selection.model_id,
                "VISION_MODEL_SIZE": selection.model_size,
                "VISION_FRAMEWORK": selection.framework,
                "VISION_DEVICE": selection.device,
                "VISION_DEGRADED": "1" if selection.degraded else "0",
            },
        )
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "worker",
            cwd=str(self.plugin_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self._wait_until_ready()

    async def parse(
        self,
        params: dict[str, Any],
        timeout: float = _DEFAULT_PARSE_TIMEOUT,
    ) -> dict[str, Any]:
        await self.start(get_tool_config("parse_screenshot") or {})
        return await self.call("parse", params, timeout=timeout)

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = _DEFAULT_PARSE_TIMEOUT,
    ) -> dict[str, Any]:
        if not self.is_running():
            await self.start(get_tool_config("parse_screenshot") or {})
        assert self.process is not None
        assert self.process.stdin is not None
        assert self.process.stdout is not None

        request_id = str(uuid.uuid4())
        request = {
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        async with self._rpc_lock:
            self.process.stdin.write(
                (json.dumps(request, ensure_ascii=False) + "\n").encode(
                    "utf-8",
                ),
            )
            await self.process.stdin.drain()
            line = await asyncio.wait_for(
                self.process.stdout.readline(),
                timeout=timeout,
            )
        if not line:
            raise RuntimeError("Local Vision worker exited without response")
        response = json.loads(line.decode("utf-8"))
        if response.get("id") != request_id:
            raise RuntimeError("Local Vision worker returned mismatched id")
        if "error" in response:
            error = response["error"]
            raise RuntimeError(str(error.get("message") or error))
        return response.get("result") or {}

    async def stop(self) -> None:
        if self.process is None:
            return
        proc = self.process
        if proc.returncode is None:
            try:
                await self.call("shutdown", {}, timeout=5.0)
            except Exception:
                logger.debug("Local Vision graceful shutdown failed")
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
        self.process = None

    async def _wait_until_ready(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        line = await asyncio.wait_for(
            self.process.stdout.readline(),
            timeout=_DEFAULT_READY_TIMEOUT,
        )
        if not line:
            raise RuntimeError("Local Vision worker exited before ready")
        message = json.loads(line.decode("utf-8"))
        if not message.get("ready"):
            raise RuntimeError(f"Local Vision worker failed: {message}")

    async def _drain_stderr(self) -> None:
        if self.process is None or self.process.stderr is None:
            return
        while True:
            line = await self.process.stderr.readline()
            if not line:
                return
            logger.info("local-vision worker: %s", line.decode().rstrip())


_WORKER_MANAGER = LocalVisionWorkerManager()


def _tool_error(message: str) -> ToolChunk:
    return ToolChunk(
        state=ToolResultState.ERROR,
        content=[TextBlock(type="text", text=f"Error: {message}")],
    )


def _tool_success(text: str) -> ToolChunk:
    return ToolChunk(
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


def _format_element(index: int, element: dict[str, Any]) -> str:
    elem_type = str(element.get("type") or "other")
    text = str(element.get("text") or "").replace('"', '\\"')
    bbox = element.get("bbox") or [0, 0, 0, 0]
    confidence = element.get("confidence")
    base = (
        f'[{index}] {elem_type} "{text}" at '
        f"({bbox[0]},{bbox[1]})-({bbox[2]},{bbox[3]})"
    )
    if confidence is not None:
        base += f" confidence={float(confidence):.2f}"
    return base


def _format_parse_result(result: dict[str, Any]) -> str:
    elements = result.get("elements") or []
    elapsed = float(result.get("processing_time_ms") or 0.0) / 1000.0
    lines = [
        f"UI Elements detected ({len(elements)} elements, {elapsed:.1f}s):",
        "",
    ]
    for idx, element in enumerate(elements, start=1):
        lines.append(_format_element(idx, element))
    viewport = result.get("viewport") or {}
    width = int(viewport.get("width") or 0)
    height = int(viewport.get("height") or 0)
    model = str(result.get("model") or result.get("model_name") or "local")
    degraded = "Yes" if result.get("degraded") else "No"
    footer = " | ".join(
        [
            f"Viewport: {width}x{height}",
            f"Model: {model}",
            f"Degraded: {degraded}",
        ],
    )
    lines.extend(
        [
            "",
            footer,
        ],
    )
    return "\n".join(lines)


async def start_local_vision_worker() -> None:
    """Best-effort startup hook used when the plugin is enabled."""
    try:
        await _WORKER_MANAGER.start(get_tool_config("parse_screenshot") or {})
    except Exception as exc:
        logger.warning("Local Vision worker did not start: %s", exc)


async def stop_local_vision_worker() -> None:
    """Shutdown hook for the worker subprocess."""
    await _WORKER_MANAGER.stop()


async def parse_screenshot(
    image_path: str,
    max_elements: int = 50,
    viewport_width: int = 0,
    viewport_height: int = 0,
    timeout: float = _DEFAULT_PARSE_TIMEOUT,
) -> ToolChunk:
    """Parse a UI screenshot into visible elements and bounding boxes."""
    path = Path(str(image_path or "")).expanduser()
    if not path.exists() or not path.is_file():
        return _tool_error(f"Image not found: {path}")

    tool_config = get_tool_config("parse_screenshot") or {}
    configured_max = tool_config.get("max_elements")
    if configured_max is not None and max_elements == 50:
        max_elements = int(configured_max)
    max_elements = max(10, min(int(max_elements), 200))

    params = {
        "image_path": str(path),
        "max_elements": max_elements,
        "viewport_width": int(viewport_width or 0),
        "viewport_height": int(viewport_height or 0),
    }
    try:
        result = await _WORKER_MANAGER.parse(params, timeout=float(timeout))
    except Exception as exc:
        return _tool_error(str(exc))
    return _tool_success(_format_parse_result(result))
