#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Native Messaging host for the QwenPaw Chrome browser bridge."""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO, Callable

try:
    from .handshake import send_hello, wait_hello_ack
    from .lease_registry import LeaseRegistry
    from .manifest import MANIFEST_PATH, load_manifest
    from .router import MessageRouter
except ImportError:
    from handshake import send_hello, wait_hello_ack  # type: ignore[no-redef]
    from lease_registry import LeaseRegistry  # type: ignore[no-redef]
    from manifest import MANIFEST_PATH, load_manifest  # type: ignore[no-redef]
    from router import MessageRouter  # type: ignore[no-redef]

DEFAULT_CONFIG_PATH = Path.home() / ".qwenpaw" / "nm-bridge.json"
DEFAULT_CONNECT_RETRY_SECONDS = 120.0
INITIAL_CONNECT_RETRY_DELAY_SECONDS = 0.5
MAX_CONNECT_RETRY_DELAY_SECONDS = 5.0
_EOF_SENTINEL = object()


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


def load_bridge_entries(
    config_path: Path = DEFAULT_CONFIG_PATH,
    manifest_path: Path = MANIFEST_PATH,
) -> list[dict[str, Any]]:
    """Load current multi-instance manifest entries."""
    del config_path
    try:
        manifest = load_manifest(manifest_path)
    except (OSError, json.JSONDecodeError):
        manifest = {"entries": []}

    entries = []
    for entry in manifest.get("entries", []):
        if not isinstance(entry, dict):
            continue
        ws_url = str(entry.get("wsUrl") or "").strip()
        token = str(entry.get("token") or "").strip()
        if not ws_url or not token:
            continue
        entries.append(
            {
                "entryId": str(entry.get("entryId") or ""),
                "wsUrl": ws_url,
                "token": token,
                "protocolVersion": int(entry.get("protocolVersion") or 1),
            },
        )
    if entries:
        return entries

    return []


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
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    def read_loop() -> None:
        while True:
            try:
                message = read_nm_message(reader)
            except BaseException as exc:  # noqa: BLE001
                item: Any = exc
            else:
                item = _EOF_SENTINEL if message is None else message

            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:
                return
            if item is _EOF_SENTINEL or isinstance(item, BaseException):
                return

    threading.Thread(
        target=read_loop,
        name="qwenpaw-nm-stdin-reader",
        daemon=True,
    ).start()

    while True:
        message = await queue.get()
        if message is _EOF_SENTINEL:
            return
        if isinstance(message, BaseException):
            raise message
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


async def pump_backend_to_stdout(
    instance_id: str,
    ws: Any,
    writer: BinaryIO,
    router: MessageRouter,
) -> None:
    """Forward one backend's websocket messages to the extension."""
    async for raw_message in ws:
        message = _loads_ws_message(raw_message)
        forwarded = router.route_backend_to_extension(instance_id, message)
        await asyncio.to_thread(write_nm_message, writer, forwarded)


async def pump_stdin_to_backends(
    reader: BinaryIO,
    router: MessageRouter,
) -> None:
    """Route extension Native Messaging messages to backend instances."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    def read_loop() -> None:
        while True:
            try:
                message = read_nm_message(reader)
            except BaseException as exc:  # noqa: BLE001
                item: Any = exc
            else:
                item = _EOF_SENTINEL if message is None else message

            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:
                return
            if item is _EOF_SENTINEL or isinstance(item, BaseException):
                return

    threading.Thread(
        target=read_loop,
        name="qwenpaw-nm-stdin-reader",
        daemon=True,
    ).start()

    while True:
        message = await queue.get()
        if message is _EOF_SENTINEL:
            return
        if isinstance(message, BaseException):
            raise message
        for instance_id, routed in router.route_extension_to_backend(message):
            ws = router.instance_ws(instance_id)
            if ws is not None:
                await ws.send(_dumps(routed))


async def connect_backend_entry(
    entry: dict[str, Any],
    connector: Callable[..., Any] | None = None,
    *,
    handshake: bool = True,
) -> Any:
    """Connect one manifest backend entry."""
    ws = await connect_websocket(
        str(entry["wsUrl"]),
        str(entry["token"]),
        connector,
    )
    if handshake:
        await send_hello(
            ws,
            str(entry.get("entryId") or ""),
            int(entry.get("protocolVersion") or 1),
        )
        await wait_hello_ack(ws)
    return ws


def _loads_ws_message(raw_message: Any) -> dict[str, Any]:
    if isinstance(raw_message, bytes):
        raw_message = raw_message.decode("utf-8")
    message = (
        json.loads(raw_message)
        if isinstance(raw_message, str)
        else raw_message
    )
    return message if isinstance(message, dict) else {}


async def run_bridge(
    config_path: Path = DEFAULT_CONFIG_PATH,
    manifest_path: Path = MANIFEST_PATH,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    *,
    connector: Callable[..., Any] | None = None,
) -> None:
    entries = load_bridge_entries(config_path, manifest_path)
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    if not entries:
        raise RuntimeError(
            "Browser Control Native Host manifest has no backend entries. "
            "Run qwenpaw setup-extension --yes --reset to repair setup.",
        )

    registry = LeaseRegistry()
    router = MessageRouter(registry)
    websockets: list[Any] = []
    tasks = set()
    for entry in entries:
        ws = await connect_backend_entry(entry, connector)
        instance_id = str(entry.get("entryId") or "")
        router.register_instance(instance_id, ws)
        websockets.append(ws)
        tasks.add(
            asyncio.create_task(
                pump_backend_to_stdout(instance_id, ws, stdout, router),
            ),
        )
    tasks.add(asyncio.create_task(pump_stdin_to_backends(stdin, router)))
    await _wait_and_close(tasks, websockets)


async def _run_single_backend_bridge(
    stdin: BinaryIO,
    stdout: BinaryIO,
    ws: Any,
) -> None:
    tasks = {
        asyncio.create_task(pump_stdin_to_ws(stdin, ws)),
        asyncio.create_task(pump_ws_to_stdout(ws, stdout)),
    }
    await _wait_and_close(tasks, [ws])


async def _wait_and_close(
    tasks: set[asyncio.Task],
    websockets: list[Any],
) -> None:
    done, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
    for task in done:
        task.result()

    for ws in websockets:
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
