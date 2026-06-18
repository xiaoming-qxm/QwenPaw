#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native Messaging host for the QwenPaw Chrome browser bridge."""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO, Callable

DEFAULT_CONFIG_PATH = Path.home() / ".qwenpaw" / "nm-bridge.json"
DEFAULT_CONNECT_RETRY_SECONDS = 120.0
INITIAL_CONNECT_RETRY_DELAY_SECONDS = 0.5
MAX_CONNECT_RETRY_DELAY_SECONDS = 5.0


class InvalidTokenError(ValueError):
    """Raised when the Native Messaging bridge token is missing."""


def _dumps(message: Any) -> str:
    return json.dumps(message, separators=(",", ":"))


def read_nm_message(reader: BinaryIO) -> dict[str, Any] | None:
    raw_length = reader.read(4)
    if not raw_length:
        return None
    if len(raw_length) != 4:
        raise EOFError("Incomplete Native Messaging length prefix")

    length = struct.unpack("<I", raw_length)[0]
    payload = reader.read(length)
    if len(payload) != length:
        raise EOFError("Incomplete Native Messaging payload")
    return json.loads(payload.decode("utf-8"))


def write_nm_message(writer: BinaryIO, message: dict[str, Any]) -> None:
    payload = _dumps(message).encode("utf-8")
    writer.write(struct.pack("<I", len(payload)))
    writer.write(payload)
    flush = getattr(writer, "flush", None)
    if flush is not None:
        flush()


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, str]:
    with path.open("r", encoding="utf-8") as fh:
        config = json.load(fh)

    ws_url = str(config.get("ws_url") or "").strip()
    token = str(config.get("token") or "").strip()
    if not token:
        raise InvalidTokenError("Native Messaging bridge token is required")
    if not ws_url:
        raise ValueError("Native Messaging bridge ws_url is required")
    return {"ws_url": ws_url, "token": token}


async def connect_websocket(
    ws_url: str,
    token: str,
    connector: Callable[..., Any] | None = None,
) -> Any:
    token = token.strip()
    if not token:
        raise InvalidTokenError("Native Messaging bridge token is required")

    if connector is None:
        import websockets

        connector = websockets.connect

    return await connector(
        ws_url,
        additional_headers={"Authorization": f"Bearer {token}"},
    )


async def connect_websocket_with_retry(
    ws_url: str,
    token: str,
    connector: Callable[..., Any] | None = None,
    *,
    retry_seconds: float = DEFAULT_CONNECT_RETRY_SECONDS,
    sleep: Callable[[float], Any] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Any:
    """Connect to QwenPaw, tolerating a short local server restart."""
    if retry_seconds <= 0:
        return await connect_websocket(ws_url, token, connector)

    deadline = monotonic() + retry_seconds
    delay = INITIAL_CONNECT_RETRY_DELAY_SECONDS

    while True:
        try:
            return await connect_websocket(ws_url, token, connector)
        except Exception:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise
            wait_seconds = min(delay, remaining)

            result = sleep(wait_seconds)
            if asyncio.iscoroutine(result):
                await result
            delay = min(delay * 2, MAX_CONNECT_RETRY_DELAY_SECONDS)


async def pump_stdin_to_ws(reader: BinaryIO, ws: Any) -> None:
    while True:
        message = await asyncio.to_thread(read_nm_message, reader)
        if message is None:
            return
        await ws.send(_dumps(message))


async def pump_ws_to_stdout(ws: Any, writer: BinaryIO) -> None:
    async for raw_message in ws:
        if isinstance(raw_message, bytes):
            raw_message = raw_message.decode("utf-8")
        message = (
            json.loads(raw_message)
            if isinstance(raw_message, str)
            else raw_message
        )
        await asyncio.to_thread(write_nm_message, writer, message)


async def run_bridge(
    config_path: Path = DEFAULT_CONFIG_PATH,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    *,
    connect_retry_seconds: float = DEFAULT_CONNECT_RETRY_SECONDS,
) -> None:
    config = load_config(config_path)
    ws = await connect_websocket_with_retry(
        config["ws_url"],
        config["token"],
        retry_seconds=connect_retry_seconds,
    )
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer

    tasks = {
        asyncio.create_task(pump_stdin_to_ws(stdin, ws)),
        asyncio.create_task(pump_ws_to_stdout(ws, stdout)),
    }
    done, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
    for task in done:
        task.result()

    close = getattr(ws, "close", None)
    if close is not None:
        result = close()
        if asyncio.iscoroutine(result):
            await result


def main() -> int:
    asyncio.run(run_bridge())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
