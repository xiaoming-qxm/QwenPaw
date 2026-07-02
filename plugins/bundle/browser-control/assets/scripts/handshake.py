# -*- coding: utf-8 -*-
"""Hello handshake helpers for browser-bridge backend connections."""

from __future__ import annotations

import asyncio
import json
from typing import Any


class HandshakeError(RuntimeError):
    """Raised when a backend hello handshake fails."""


async def send_hello(
    ws: Any,
    entry_id: str,
    protocol_version: int = 1,
) -> None:
    """Send bridge hello metadata to a backend websocket."""
    await ws.send(
        json.dumps(
            {
                "type": "hello",
                "entryId": entry_id,
                "protocolVersion": protocol_version,
                "capabilities": ["cdp", "tabs"],
            },
            separators=(",", ":"),
        ),
    )


async def wait_hello_ack(ws: Any, timeout: float = 5.0) -> dict:
    """Wait for and validate hello_ack."""
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise HandshakeError("Hello ack timeout") from exc

    message = json.loads(
        raw.decode("utf-8") if isinstance(raw, bytes) else raw,
    )
    if message.get("type") != "hello_ack" or message.get("status") != "ok":
        raise HandshakeError(f"Hello rejected: {message}")
    return message


__all__ = ["HandshakeError", "send_hello", "wait_hello_ack"]
