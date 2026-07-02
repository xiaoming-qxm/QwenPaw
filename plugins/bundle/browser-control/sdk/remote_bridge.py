# -*- coding: utf-8 -*-
"""Remote bridge client used by Browser SDK subprocesses."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .errors import (
    BridgeDisconnected,
    BrowserSDKError,
    StaleLease,
    TabOccupied,
)

JSONRPC_VERSION = "2.0"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_MESSAGE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class RemoteLease:
    """Local representation of a backend-owned browser tab lease."""

    tab_id: int
    holder_id: str
    version: int
    expires_at: float | None = None


class RemoteBridge:
    """Cross-process proxy for the backend NMBridge.

    The Chrome extension keeps its exclusive connection to ``/ws/nm-bridge``.
    REPL kernels connect here as SDK clients and forward bridge operations to
    the backend process that owns the real NMBridge.
    """

    def __init__(
        self,
        ws_url: str,
        token: str,
        *,
        connector: Callable[..., Any] | None = None,
    ) -> None:
        self.ws_url = resolve_sdk_ws_url(ws_url)
        self.token = token
        self.connected = False
        self._connector = connector
        self._ws: Any | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._leases: dict[tuple[int, str], RemoteLease] = {}
        self._event_handlers: dict[
            str,
            list[Callable[[dict[str, Any]], Any]],
        ] = defaultdict(list)
        self._receiver_task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._reconnect_lock = asyncio.Lock()

    @classmethod
    async def connect(cls, ws_url: str, token: str) -> "RemoteBridge":
        """Create and connect a remote bridge client."""
        bridge = cls(ws_url, token)
        await bridge.start()
        return bridge

    async def start(self) -> None:
        """Open the SDK websocket."""
        if self.connected:
            return
        if not self.ws_url:
            raise BridgeDisconnected(
                "Browser Control bridge URL is not configured",
            )
        self._ws = await self._open_websocket()
        self.connected = True
        self._receiver_task = asyncio.create_task(self._receive_loop())

    async def _open_websocket(self) -> Any:
        connector = self._connector
        if connector is None:
            try:
                import websockets
            except ImportError as exc:
                raise BridgeDisconnected(
                    "Browser Control SDK requires the 'websockets' package",
                ) from exc

            connector = websockets.connect

        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            return await connector(
                self.ws_url,
                additional_headers=headers,
                max_size=DEFAULT_MAX_MESSAGE_BYTES,
            )
        except TypeError:
            try:
                return await connector(
                    self.ws_url,
                    extra_headers=headers,
                    max_size=DEFAULT_MAX_MESSAGE_BYTES,
                )
            except TypeError:
                try:
                    return await connector(
                        self.ws_url,
                        additional_headers=headers,
                    )
                except TypeError:
                    return await connector(self.ws_url, extra_headers=headers)
        except Exception as exc:
            raise BridgeDisconnected(
                f"Browser Control SDK could not connect: {self.ws_url}",
            ) from exc

    async def close(self) -> None:
        """Close the SDK websocket."""
        self.connected = False
        task = self._receiver_task
        self._receiver_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        ws = self._ws
        self._ws = None
        if ws is not None and hasattr(ws, "close"):
            with contextlib.suppress(Exception):
                result = ws.close()
                if inspect.isawaitable(result):
                    await result
        self._fail_pending(BridgeDisconnected("Browser SDK bridge closed"))

    def now(self) -> float:
        return time.monotonic()

    def lease_version(self, tab_id: int, holder_id: str) -> int | None:
        lease = self._leases.get((int(tab_id), str(holder_id)))
        return lease.version if lease is not None else None

    def validate_lease(
        self,
        tab_id: int,
        holder_id: str,
        lease_version: int | None = None,
    ) -> RemoteLease:
        key = (int(tab_id), str(holder_id))
        lease = self._leases.get(key)
        if lease is None:
            raise TabOccupied(f"Tab {tab_id} is not held by {holder_id}")
        if lease_version is not None and lease.version != lease_version:
            raise StaleLease(
                f"Lease version mismatch for tab {tab_id}: "
                f"{lease_version} != {lease.version}",
            )
        return lease

    async def discover_tabs(self) -> list[dict[str, Any]]:
        result = await self._rpc("bridge.discover_tabs")
        return result if isinstance(result, list) else []

    async def claim_tab(self, tab_id: int, holder_id: str) -> bool:
        result = await self._rpc(
            "bridge.claim_tab",
            {"tab_id": int(tab_id), "holder_id": str(holder_id)},
        )
        if not isinstance(result, dict):
            return False
        version = int(result.get("version") or 0)
        if version <= 0:
            version = self.lease_version(tab_id, holder_id) or 1
        self._leases[(int(tab_id), str(holder_id))] = RemoteLease(
            tab_id=int(tab_id),
            holder_id=str(holder_id),
            version=version,
        )
        return bool(result.get("ok", True))

    async def renew_lease(
        self,
        tab_id: int,
        holder_id: str,
        version: int,
    ) -> RemoteLease:
        result = await self._rpc(
            "bridge.renew_lease",
            {
                "tab_id": int(tab_id),
                "holder_id": str(holder_id),
                "version": int(version),
            },
        )
        if not isinstance(result, dict):
            raise StaleLease(f"Could not renew tab {tab_id}")
        lease = RemoteLease(
            tab_id=int(tab_id),
            holder_id=str(holder_id),
            version=int(result.get("version") or version),
            expires_at=_optional_float(result.get("expires_at")),
        )
        self._leases[(int(tab_id), str(holder_id))] = lease
        return lease

    async def release(self, tab_id: int, holder_id: str) -> None:
        await self._rpc(
            "bridge.release",
            {"tab_id": int(tab_id), "holder_id": str(holder_id)},
        )
        self._leases.pop((int(tab_id), str(holder_id)), None)

    async def release_all(self, holder_id: str | None = None) -> None:
        await self._rpc("bridge.release_all", {"holder_id": holder_id})
        if holder_id is None:
            self._leases.clear()
            return
        for key in list(self._leases):
            if key[1] == str(holder_id):
                self._leases.pop(key, None)

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        result = await self._rpc(
            "bridge.request",
            {
                "method": str(method),
                "params": params or {},
                "timeout": float(timeout),
            },
            timeout=timeout + 1.0,
        )
        return result if isinstance(result, dict) else {}

    async def send_cdp(
        self,
        tab_id: int,
        holder_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        lease_version: int | None = None,
    ) -> dict[str, Any]:
        self.validate_lease(tab_id, holder_id, lease_version)
        response = await self.request(
            "cdp.send",
            {
                "tabId": int(tab_id),
                "holderId": str(holder_id),
                "method": str(method),
                "params": params or {},
            },
        )
        if "error" in response:
            raise BrowserSDKError(str(response["error"]))
        result = response.get("result", {})
        return result if isinstance(result, dict) else {}

    def add_event_listener(
        self,
        method: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        self._event_handlers[str(method)].append(handler)

    def remove_event_listener(
        self,
        method: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        handlers = self._event_handlers.get(str(method))
        if not handlers:
            return
        with contextlib.suppress(ValueError):
            handlers.remove(handler)

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> Any:
        await self._ensure_connected()
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future
        message = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        try:
            async with self._send_lock:
                await self._ws.send(json.dumps(message))
            response = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

        if "error" in response:
            error = response["error"]
            message_text = (
                str(error.get("message") or error)
                if isinstance(error, dict)
                else str(error)
            )
            raise BrowserSDKError(message_text)
        return response.get("result")

    async def _ensure_connected(self) -> None:
        if self.connected and self._ws is not None:
            return
        async with self._reconnect_lock:
            if self.connected and self._ws is not None:
                return
            if self._ws is not None or self._receiver_task is not None:
                await self.close()
            await self.start()

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                message = _loads(raw)
                if not isinstance(message, dict):
                    continue
                if "id" in message:
                    request_id = int(message.get("id") or 0)
                    future = self._pending.get(request_id)
                    if future is not None and not future.done():
                        future.set_result(message)
                    continue
                method = message.get("method")
                params = message.get("params")
                if isinstance(method, str) and isinstance(params, dict):
                    await self._dispatch_event(method, params)
        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except Exception as exc:
            self._fail_pending(
                BridgeDisconnected(
                    f"Browser Control SDK bridge disconnected: {self.ws_url}",
                ),
            )
            self.connected = False
            if self._ws is not None:
                with contextlib.suppress(Exception):
                    close_result = self._ws.close()
                    if inspect.isawaitable(close_result):
                        await close_result
            if not isinstance(exc, (ConnectionError, OSError)):
                return
        finally:
            self.connected = False

    async def _dispatch_event(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        for handler in list(self._event_handlers.get(method, [])):
            result = handler(params)
            if inspect.isawaitable(result):
                await result

    def _fail_pending(self, exc: BaseException) -> None:
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()


def resolve_sdk_ws_url(ws_url: str) -> str:
    """Return the SDK websocket URL for a configured NM bridge URL."""
    raw = str(ws_url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    path = parts.path or "/ws/nm-bridge"
    if path.endswith("/browser-sdk"):
        sdk_path = path
    elif path.endswith("/nm-bridge"):
        sdk_path = f"{path[: -len('/nm-bridge')]}/browser-sdk"
    else:
        sdk_path = f"{path.rstrip('/')}/browser-sdk"
    return urlunsplit(
        (parts.scheme, parts.netloc, sdk_path, parts.query, parts.fragment),
    )


def _loads(raw: Any) -> Any:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["RemoteBridge", "RemoteLease", "resolve_sdk_ws_url"]
