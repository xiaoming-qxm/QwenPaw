# -*- coding: utf-8 -*-
"""JSON-RPC protocol helpers for the Browser Control Python REPL."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecRequest:
    """Request the kernel to execute Python code."""

    id: int
    code: str
    timeout_ms: int = 30000
    request_context: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize this request as one JSON-RPC line."""
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self.id,
                "method": "exec",
                "params": {
                    "code": self.code,
                    "timeout_ms": self.timeout_ms,
                    "request_context": self.request_context,
                },
            },
        )


@dataclass
class ExecResult:
    """Result returned by the Python REPL kernel."""

    output: str
    return_value: str | None
    error: dict[str, Any] | None
    artifacts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ResetRequest:
    """Request the kernel to clear its namespace."""

    id: int

    def to_json(self) -> str:
        """Serialize this request as one JSON-RPC line."""
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": self.id,
                "method": "reset",
                "params": {},
            },
        )


def parse_response(line: str) -> tuple[int, ExecResult]:
    """Parse one JSON-RPC response line from the kernel."""
    message = json.loads(line)
    result = message["result"]
    return int(message["id"]), ExecResult(
        output=str(result.get("output") or ""),
        return_value=result.get("return_value"),
        error=result.get("error"),
        artifacts=(
            result.get("artifacts")
            if isinstance(result.get("artifacts"), list)
            else []
        ),
    )


__all__ = ["ExecRequest", "ExecResult", "ResetRequest", "parse_response"]
