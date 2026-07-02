#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subprocess JSON-RPC kernel for Browser Control Python REPL."""

from __future__ import annotations

import ast
import asyncio
import contextlib
import inspect
import io
import json
import sys
import traceback
from types import CodeType
from typing import Any


_RETURN_NAME = "__qwenpaw_repl_return__"


class ReplKernel:
    """Execute Python snippets inside a persistent namespace."""

    def __init__(self) -> None:
        self._namespace: dict[str, Any] = {"__builtins__": __builtins__}
        self._loop = asyncio.new_event_loop()

    def execute_sync(self, code: str, timeout_ms: int = 30000) -> dict:
        """Execute code from the stdin request loop."""
        return self._loop.run_until_complete(self._execute(code, timeout_ms))

    async def _execute(self, code: str, timeout_ms: int) -> dict:
        stdout_capture = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_capture):
                result = await asyncio.wait_for(
                    self._execute_code(code),
                    timeout=timeout_ms / 1000,
                )
            return {
                "output": stdout_capture.getvalue(),
                "return_value": repr(result) if result is not None else None,
                "error": None,
            }
        except asyncio.TimeoutError:
            return {
                "output": stdout_capture.getvalue(),
                "return_value": None,
                "error": {
                    "type": "TimeoutError",
                    "message": (f"Execution timed out after {timeout_ms}ms"),
                    "traceback": "",
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "output": stdout_capture.getvalue(),
                "return_value": None,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                },
            }

    async def _execute_code(self, code: str) -> Any:
        namespace = self._namespace
        namespace.pop(_RETURN_NAME, None)
        compiled = _compile_code(code)
        maybe_awaitable = eval(compiled, namespace)  # noqa: S307
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
        return namespace.pop(_RETURN_NAME, None)

    def reset(self) -> None:
        """Clear user-defined namespace values."""
        self._namespace = {"__builtins__": __builtins__}


def _compile_code(code: str) -> CodeType:
    tree = ast.parse(code, mode="exec")
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last_expr = tree.body[-1]
        tree.body[-1] = ast.Assign(
            targets=[
                ast.Name(
                    id=_RETURN_NAME,
                    ctx=ast.Store(),
                ),
            ],
            value=last_expr.value,
        )
        ast.fix_missing_locations(tree)
    return compile(
        tree,
        "<repl>",
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
    )


def _success_response(request_id: int, result: dict) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        },
    )


def _error_result(error_type: str, message: str) -> dict:
    return {
        "output": "",
        "return_value": None,
        "error": {
            "type": error_type,
            "message": message,
            "traceback": "",
        },
    }


def main() -> int:
    """Run the kernel stdin/stdout loop."""
    kernel = ReplKernel()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        method = request.get("method")
        request_id = int(request.get("id") or 0)
        if method == "exec":
            params = request.get("params") or {}
            result = kernel.execute_sync(
                str(params.get("code") or ""),
                int(params.get("timeout_ms") or 30000),
            )
        elif method == "reset":
            kernel.reset()
            result = {"output": "", "return_value": None, "error": None}
        elif method == "shutdown":
            break
        else:
            result = _error_result("ValueError", f"Unknown method: {method}")
        sys.stdout.write(_success_response(request_id, result) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
