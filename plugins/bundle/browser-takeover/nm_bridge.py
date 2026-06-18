# -*- coding: utf-8 -*-
"""Native Messaging bridge state for Chrome takeover mode."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.connection_manager import BridgeConnectionManager

JSONRPC_VERSION = "2.0"
LEASE_TTL_SECONDS = 30.0
logger = logging.getLogger(__name__)


class NMBridgeError(RuntimeError):
    """Base error for Native Messaging bridge failures."""


class NMBridgeDisconnectedError(NMBridgeError):
    """Raised when no Native Messaging WebSocket is connected."""


class TabOccupiedError(NMBridgeError):
    """Raised when a tab is already held by another holder."""


class StaleLeaseError(NMBridgeError):
    """Raised when a holder presents an old lease version."""


@dataclass(frozen=True)
class TabLease:
    tab_id: int
    holder_id: str
    version: int
    expires_at: float


class NMBridge(BridgeConnectionManager):
    """Central bridge that owns NM connection state and tab ownership."""

    def __init__(self, time_fn: Callable[[], float] | None = None) -> None:
        self._time_fn = time_fn or time.monotonic
        self._leases: dict[int, TabLease] = {}
        self._lease_versions: dict[int, int] = {}
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._ws: Any | None = None
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._event_handlers: dict[
            str,
            list[Callable[[dict[str, Any]], Any]],
        ] = defaultdict(list)
        self.connected = False

    def get_connection(self) -> "NMBridge":
        return self

    def is_connected(self) -> bool:
        return self.connected

    async def attach_websocket(self, websocket: Any) -> None:
        self._ws = websocket
        self.connected = True

    async def detach_websocket(self, websocket: Any | None = None) -> None:
        if websocket is not None and websocket is not self._ws:
            return
        self._ws = None
        self.connected = False
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(
                    NMBridgeDisconnectedError("NM bridge disconnected"),
                )
        self._pending.clear()
        self._leases.clear()

    def tab_holder(self, tab_id: int) -> str | None:
        lease = self.get_lease(tab_id)
        return lease.holder_id if lease is not None else None

    def now(self) -> float:
        return self._time_fn()

    def get_lease(self, tab_id: int) -> TabLease | None:
        lease = self._leases.get(tab_id)
        if lease is None:
            return None
        if lease.expires_at <= self._time_fn():
            self._leases.pop(tab_id, None)
            return None
        return lease

    def lease_version(self, tab_id: int, holder_id: str) -> int | None:
        lease = self.get_lease(tab_id)
        if lease is None or lease.holder_id != holder_id:
            return None
        return lease.version

    async def claim_tab(self, tab_id: int, holder_id: str) -> bool:
        current = self.get_lease(tab_id)
        if current is not None and current.holder_id != holder_id:
            raise TabOccupiedError(
                f"Tab {tab_id} is already held by {current.holder_id}",
            )
        if current is not None and current.holder_id == holder_id:
            return True
        version = self._lease_versions.get(tab_id, 0) + 1
        self._lease_versions[tab_id] = version
        self._leases[tab_id] = TabLease(
            tab_id=tab_id,
            holder_id=holder_id,
            version=version,
            expires_at=self._time_fn() + LEASE_TTL_SECONDS,
        )
        return True

    def validate_lease(
        self,
        tab_id: int,
        holder_id: str,
        lease_version: int | None = None,
    ) -> TabLease:
        current = self.get_lease(tab_id)
        if current is None or current.holder_id != holder_id:
            raise TabOccupiedError(f"Tab {tab_id} is not held by {holder_id}")
        if lease_version is not None and current.version != lease_version:
            raise StaleLeaseError(
                f"Lease version mismatch for tab {tab_id}: "
                f"{lease_version} != {current.version}",
            )
        return current

    async def renew_lease(
        self,
        tab_id: int,
        holder_id: str,
        version: int,
    ) -> TabLease:
        current = self.validate_lease(tab_id, holder_id, version)
        renewed = TabLease(
            tab_id=current.tab_id,
            holder_id=current.holder_id,
            version=current.version,
            expires_at=self._time_fn() + LEASE_TTL_SECONDS,
        )
        self._leases[tab_id] = renewed
        return renewed

    async def release(self, tab_id: int, holder_id: str) -> None:
        current = self.get_lease(tab_id)
        if current is None:
            return
        if current.holder_id != holder_id:
            raise TabOccupiedError(
                f"Tab {tab_id} is held by {current.holder_id}",
            )
        self._leases.pop(tab_id, None)

    async def release_all(self, holder_id: str | None = None) -> None:
        if holder_id is None:
            self._leases.clear()
            return
        for tab_id, lease in list(self._leases.items()):
            if lease.holder_id == holder_id:
                self._leases.pop(tab_id, None)

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._ws is None:
            raise NMBridgeDisconnectedError("NM bridge is not connected")

        async with self._lock:
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
            ws = self._ws
            if ws is None:
                raise NMBridgeDisconnectedError(
                    "NM bridge is not connected",
                )
            await ws.send_json(message)
            return await future
        except NMBridgeDisconnectedError:
            raise
        except Exception as exc:
            await self.detach_websocket(ws)
            raise NMBridgeDisconnectedError(
                "NM bridge disconnected",
            ) from exc
        finally:
            self._pending.pop(request_id, None)

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
                "tabId": tab_id,
                "holderId": holder_id,
                "method": method,
                "params": params or {},
            },
        )
        if "error" in response:
            raise NMBridgeError(str(response["error"]))
        return response.get("result", {})

    async def discover_tabs(self) -> list[dict[str, Any]]:
        response = await self.request("tabs.list", {"query": {}})
        if "error" in response:
            raise NMBridgeError(str(response["error"]))
        result = response.get("result", [])
        return result if isinstance(result, list) else []

    async def handle_ws_message(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id in self._pending:
            future = self._pending[request_id]
            if not future.done():
                future.set_result(message)
            return None

        method = message.get("method")
        if isinstance(method, str):
            params = message.get("params")
            event = params if isinstance(params, dict) else {}
            for handler in list(self._event_handlers.get(method, [])):
                try:
                    result = handler(event)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    logger.exception(
                        "Native Messaging bridge event handler failed: %s",
                        method,
                    )
        return None

    def add_event_listener(
        self,
        method: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        self._event_handlers[method].append(handler)

    def remove_event_listener(
        self,
        method: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        handlers = self._event_handlers.get(method)
        if not handlers:
            return
        with contextlib.suppress(ValueError):
            handlers.remove(handler)


_GLOBAL_BRIDGE: NMBridge | None = None


def get_nm_bridge() -> NMBridge:
    global _GLOBAL_BRIDGE
    if _GLOBAL_BRIDGE is None:
        _GLOBAL_BRIDGE = NMBridge()
    return _GLOBAL_BRIDGE
