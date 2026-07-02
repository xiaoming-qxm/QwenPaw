# -*- coding: utf-8 -*-
"""Lifecycle manager for the Browser Control Python REPL kernel."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from .bootstrap import get_bootstrap_code
from .protocol import ExecRequest, ResetRequest, parse_response


class KernelManager:
    """Manage one persistent REPL kernel subprocess."""

    def __init__(
        self,
        kernel_script: Path,
        sdk_path: Path | None = None,
        *,
        ws_url: str = "",
        token: str = "",
    ) -> None:
        self._kernel_script = Path(kernel_script)
        self._sdk_path = Path(sdk_path) if sdk_path is not None else None
        self._ws_url = ws_url
        self._token = token
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._bootstrapped = False

    @property
    def process(self) -> asyncio.subprocess.Process | None:
        """Return the current kernel process, if started."""
        return self._process

    async def ensure_running(self) -> None:
        """Start the kernel if it is not already alive."""
        if self._process is not None and self._process.returncode is None:
            if not self._bootstrapped:
                await self._bootstrap()
            return
        env = os.environ.copy()
        if self._sdk_path is not None:
            env["PYTHONPATH"] = _prepend_pythonpath(
                str(self._sdk_path.parent),
                env.get("PYTHONPATH", ""),
            )
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self._kernel_script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._bootstrapped = False
        await self._bootstrap()

    async def execute(
        self,
        code: str,
        timeout_ms: int = 30000,
    ) -> dict[str, Any]:
        """Execute code in the kernel and return its result payload."""
        await self.ensure_running()
        request = ExecRequest(
            id=self._next_request_id(),
            code=code,
            timeout_ms=timeout_ms,
        )
        try:
            return await self._execute_request(request, timeout_ms)
        except _KernelResponseTimeout:
            await self._kill_and_restart()
            return {
                "output": "",
                "return_value": None,
                "error": {
                    "type": "TimeoutError",
                    "message": "Kernel unresponsive, restarted",
                    "traceback": "",
                },
            }

    async def reset(self) -> None:
        """Clear the running kernel namespace."""
        await self.ensure_running()
        process = self._require_process()
        request = ResetRequest(id=self._next_request_id())
        await self._write_request(process, request.to_json())
        await self._read_response_line(process)
        self._bootstrapped = False
        await self._bootstrap()

    async def shutdown(self) -> None:
        """Stop the kernel subprocess."""
        process = self._process
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        self._process = None

    async def _kill_and_restart(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        self._process = None
        self._bootstrapped = False
        await self.ensure_running()

    async def _bootstrap(self) -> None:
        if self._sdk_path is None:
            self._bootstrapped = True
            return
        request = ExecRequest(
            id=self._next_request_id(),
            code=get_bootstrap_code(
                ws_url=self._ws_url,
                token=self._token,
                sdk_path=str(self._sdk_path),
            ),
            timeout_ms=30000,
        )
        result = await self._execute_request(request, timeout_ms=30000)
        if result.get("error"):
            error = result["error"]
            raise RuntimeError(
                "Browser Control REPL bootstrap failed: "
                f"{error.get('type')}: {error.get('message')}",
            )
        self._bootstrapped = True

    async def _execute_request(
        self,
        request: ExecRequest,
        timeout_ms: int,
    ) -> dict[str, Any]:
        process = self._require_process()
        await self._write_request(process, request.to_json())
        try:
            line = await asyncio.wait_for(
                self._read_response_line(process),
                timeout=(timeout_ms + 2000) / 1000,
            )
        except asyncio.TimeoutError as exc:
            raise _KernelResponseTimeout from exc
        _, result = parse_response(line.decode("utf-8"))
        return {
            "output": result.output,
            "return_value": result.return_value,
            "error": result.error,
        }

    def _next_request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise RuntimeError("Kernel process is not running")
        return self._process

    async def _write_request(
        self,
        process: asyncio.subprocess.Process,
        payload: str,
    ) -> None:
        if process.stdin is None:
            raise RuntimeError("Kernel stdin is not available")
        process.stdin.write(payload.encode("utf-8") + b"\n")
        await process.stdin.drain()

    async def _read_response_line(
        self,
        process: asyncio.subprocess.Process,
    ) -> bytes:
        if process.stdout is None:
            raise RuntimeError("Kernel stdout is not available")
        line = await process.stdout.readline()
        if not line:
            raise RuntimeError("Kernel closed stdout without a response")
        return line


def _prepend_pythonpath(path: str, current: str) -> str:
    if not current:
        return path
    return path + os.pathsep + current


class _KernelResponseTimeout(RuntimeError):
    """Raised when the kernel does not produce a JSON-RPC response."""


__all__ = ["KernelManager"]
