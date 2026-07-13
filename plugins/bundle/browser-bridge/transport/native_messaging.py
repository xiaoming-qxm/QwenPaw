# -*- coding: utf-8 -*-
# pylint:disable=too-many-public-methods
"""Native Messaging bridge state for Chrome browser control mode."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping

from qwenpaw.browser.sdk.governance.error_codes import BrowserErrorCode
from qwenpaw.browser.sdk.telemetry.trace import record_browser_trace_event

from .state import get_nm_bridge_route_state

BUILD_FINGERPRINT = "build-1"
CONTRACT_FINGERPRINT = "contract-v1"
PROFILE_FINGERPRINT = "profile-v1"
EXTENSION_FINGERPRINT = "extension@build-1"
PROVIDER_FINGERPRINT = "provider-v1"
MAX_RETAINED_STATE_TTL_SECONDS = 3600
MAX_LEGACY_TOKEN_TTL_SECONDS = 3600

JSONRPC_VERSION = "2.0"
SUPPORTED_PROTOCOL_VERSION = 2
LEASE_TTL_SECONDS = 30.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
logger = logging.getLogger(__name__)


class NMBridgeError(RuntimeError):
    """Base error for Native Messaging bridge failures."""

    browser_error_code = str(BrowserErrorCode.UNKNOWN.value)

    def __init__(
        self,
        message: str = "",
        *,
        code: str | BrowserErrorCode | None = None,
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        if code is not None:
            self.browser_error_code = (
                code.value if isinstance(code, BrowserErrorCode) else str(code)
            )


class NMBridgeDisconnectedError(NMBridgeError):
    """Raised when no Native Messaging WebSocket is connected."""


class CommandTransportUncertainError(NMBridgeError):
    """No response was observed; this never authorizes command replay."""

    def __init__(
        self,
        message: str,
        *,
        reconcile_keys: tuple[tuple[str, str], ...],
    ) -> None:
        super().__init__(message, code="command_transport_uncertain")
        self.reconcile_keys = reconcile_keys
        self.observed_state = "UNKNOWN"


class TabOccupiedError(NMBridgeError):
    """Raised when a tab is already held by another holder."""

    browser_error_code = str(BrowserErrorCode.BROWSER_TAB_OCCUPIED.value)


class StaleLeaseError(NMBridgeError):
    """Raised when a holder presents an old lease version."""

    browser_error_code = str(BrowserErrorCode.BROWSER_STALE_LEASE.value)


class ReceiptState(StrEnum):
    """Closed states that can be persisted by the extension."""

    RECEIVED = "RECEIVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    """One observed extension receipt for an exact command."""

    session_id: str
    command_id: str
    command_fingerprint: str
    state: ReceiptState
    result: object | None = None


@dataclass(frozen=True, slots=True)
class CommandFactProjection:
    """Host projection when a target receipt is absent or evicted."""

    observed_state: str


@dataclass(frozen=True, slots=True)
class CommandExecutionResponse:
    """Typed command.execute transport response."""

    receipt: CommandReceipt


@dataclass(frozen=True, slots=True)
class CommandStatusResponse:
    """Typed read-only status response with separate query identity."""

    query_receipt: CommandReceipt
    target_receipt: CommandReceipt | None
    target_command_fact: CommandFactProjection


@dataclass(frozen=True)
class TabLease:
    tab_id: int
    owner_id: str
    version: int
    expires_at: float

    @property
    def holder_id(self) -> str:
        """Compatibility alias for pre-v2 internal callers."""
        return self.owner_id


class NMBridge:
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
        self.protocol_error: dict[str, Any] | None = None
        self.connected = False
        self._closed = False

    def get_connection(self) -> "NMBridge":
        return self

    def is_connected(self) -> bool:
        return self.connected

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def attach_websocket(self, websocket: Any) -> None:
        if self._closed:
            raise NMBridgeDisconnectedError("NM bridge is closed")
        self._ws = websocket
        self.connected = True
        route_state = get_nm_bridge_route_state()
        now = datetime.now(UTC)
        is_reconnect = (
            route_state.last_connected_at is not None
            and route_state.connected is not websocket
        )
        route_state.connected = websocket
        route_state.connected_since = now
        route_state.last_connected_at = now
        if is_reconnect:
            route_state.reconnect_count += 1
        _record_lifecycle_trace(
            "reconnect" if is_reconnect else "connect",
            status="ok",
        )

    async def detach_websocket(
        self,
        websocket: Any | None = None,
        *,
        reason: str = "disconnected",
    ) -> None:
        if websocket is not None and websocket is not self._ws:
            return
        _mark_disconnected(
            websocket or self._ws,
            reason=reason,
            message="NM bridge disconnected",
        )
        self._ws = None
        self.connected = False
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(
                    NMBridgeDisconnectedError("NM bridge disconnected"),
                )
        self._pending.clear()
        self._leases.clear()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(
                    NMBridgeDisconnectedError("NM bridge closed"),
                )
        self._pending.clear()
        websocket = self._ws
        if websocket is not None:
            await self.detach_websocket(websocket, reason="closed")
        else:
            self.connected = False
            self._leases.clear()
            _mark_disconnected(
                None,
                reason="closed",
                message="NM bridge closed",
            )

    def tab_holder(self, tab_id: int) -> str | None:
        lease = self.get_lease(tab_id)
        return lease.owner_id if lease is not None else None

    def now(self) -> float:
        return self._time_fn()

    def get_lease(self, tab_id: int) -> TabLease | None:
        return self._leases.get(tab_id)

    def _is_expired(self, lease: TabLease) -> bool:
        return lease.expires_at <= self._time_fn()

    def lease_version(self, tab_id: int, holder_id: str) -> int | None:
        lease = self.get_lease(tab_id)
        if lease is None or lease.owner_id != holder_id:
            return None
        return lease.version

    async def claim_tab(self, tab_id: int, holder_id: str) -> int:
        current = self.get_lease(tab_id)
        if current is not None and self._is_expired(current):
            if current.owner_id == holder_id:
                raise StaleLeaseError(
                    f"Lease for tab {tab_id} held by {holder_id} expired",
                )
            raise TabOccupiedError(
                f"Tab {tab_id} is still owned by {current.owner_id}",
            )
        if current is not None and current.owner_id != holder_id:
            raise TabOccupiedError(
                f"Tab {tab_id} is already held by {current.owner_id}",
            )
        if current is not None and current.owner_id == holder_id:
            return current.version
        version = self._lease_versions.get(tab_id, 0) + 1
        self._lease_versions[tab_id] = version
        self._leases[tab_id] = TabLease(
            tab_id=tab_id,
            owner_id=holder_id,
            version=version,
            expires_at=self._time_fn() + LEASE_TTL_SECONDS,
        )
        return version

    async def reclaim_tab(self, tab_id: int, holder_id: str) -> int:
        current = self.get_lease(tab_id)
        if current is not None and current.owner_id != holder_id:
            raise TabOccupiedError(
                f"Tab {tab_id} is already held by {current.owner_id}",
            )
        version = self._lease_versions.get(tab_id, 0) + 1
        self._lease_versions[tab_id] = version
        self._leases[tab_id] = TabLease(
            tab_id=tab_id,
            owner_id=holder_id,
            version=version,
            expires_at=self._time_fn() + LEASE_TTL_SECONDS,
        )
        return version

    def validate_lease(
        self,
        tab_id: int,
        holder_id: str,
        lease_version: int | None = None,
    ) -> TabLease:
        current = self.get_lease(tab_id)
        if current is None or current.owner_id != holder_id:
            raise TabOccupiedError(f"Tab {tab_id} is not held by {holder_id}")
        if self._is_expired(current):
            raise StaleLeaseError(f"Lease for tab {tab_id} has expired")
        if lease_version is not None and current.version != lease_version:
            raise StaleLeaseError(
                f"Lease version mismatch for tab {tab_id}: "
                f"{lease_version} != {current.version}",
            )
        return current

    def validate_or_renew(
        self,
        tab_id: int,
        holder_id: str,
        lease_version: int | None = None,
    ) -> TabLease:
        current = self.validate_lease(tab_id, holder_id, lease_version)
        renewed = TabLease(
            tab_id=current.tab_id,
            owner_id=current.owner_id,
            version=current.version,
            expires_at=self._time_fn() + LEASE_TTL_SECONDS,
        )
        self._leases[tab_id] = renewed
        return renewed

    async def renew_lease(
        self,
        tab_id: int,
        holder_id: str,
        version: int,
    ) -> TabLease:
        return self.validate_or_renew(tab_id, holder_id, version)

    async def release(self, tab_id: int, holder_id: str) -> None:
        current = self.get_lease(tab_id)
        if current is None:
            return
        if current.owner_id != holder_id:
            raise TabOccupiedError(
                f"Tab {tab_id} is held by {current.owner_id}",
            )
        self._leases.pop(tab_id, None)

    async def release_all(self, holder_id: str | None = None) -> None:
        if holder_id is None:
            self._leases.clear()
            return
        for tab_id, lease in list(self._leases.items()):
            if lease.owner_id == holder_id:
                self._leases.pop(tab_id, None)

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        if self._closed:
            raise NMBridgeDisconnectedError("NM bridge is closed")
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
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            _mark_request_timeout(method, timeout)
            raise NMBridgeError(
                f"request '{method}' timed out after {timeout}s",
                code=BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT,
            ) from exc
        except NMBridgeDisconnectedError:
            raise
        except Exception as exc:
            await self.detach_websocket(ws, reason="send_failed")
            raise NMBridgeDisconnectedError(
                "NM bridge disconnected",
            ) from exc
        finally:
            self._pending.pop(request_id, None)

    async def execute_command(
        self,
        *,
        session_id: str,
        command_id: str,
        command_fingerprint: str,
        command_type: str,
        dispatch_context: Mapping[str, object],
        payload: Mapping[str, object],
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> CommandExecutionResponse:
        """Execute one independently identified extension command."""
        normalized_session = _required_command_text(session_id, "sessionId")
        normalized_command = _required_command_text(command_id, "commandId")
        normalized_fingerprint = _required_command_text(
            command_fingerprint,
            "commandFingerprint",
        )
        try:
            response = await self.request(
                "command.execute",
                {
                    "sessionId": normalized_session,
                    "commandId": normalized_command,
                    "commandFingerprint": normalized_fingerprint,
                    "commandType": _required_command_text(
                        command_type,
                        "commandType",
                    ),
                    "dispatchContext": dict(dispatch_context),
                    "payload": dict(payload),
                },
                timeout=timeout,
            )
        except NMBridgeError as exc:
            raise CommandTransportUncertainError(
                "command response was not observed",
                reconcile_keys=((normalized_command, normalized_fingerprint),),
            ) from exc
        if "error" in response:
            message = _wire_error_message(response["error"])
            raise NMBridgeError(
                message,
                code=(
                    "command_fingerprint_mismatch"
                    if "command_fingerprint_mismatch" in message
                    else "command_execute_failed"
                ),
            )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise NMBridgeError("command.execute returned an invalid result")
        return CommandExecutionResponse(
            receipt=_parse_command_receipt(result.get("receipt")),
        )

    async def query_command_status(
        self,
        *,
        session_id: str,
        query_command_id: str,
        query_command_fingerprint: str,
        target_command_id: str,
        target_command_fingerprint: str,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> CommandStatusResponse:
        """Issue a fresh read-only STATUS_QUERY for another command."""
        if query_command_id == target_command_id:
            raise NMBridgeError(
                "query and target command ids must be independent",
                code="command_identity_invalid",
            )
        normalized_query = _required_command_text(
            query_command_id,
            "queryCommandId",
        )
        normalized_query_fingerprint = _required_command_text(
            query_command_fingerprint,
            "queryCommandFingerprint",
        )
        normalized_target = _required_command_text(
            target_command_id,
            "targetCommandId",
        )
        normalized_target_fingerprint = _required_command_text(
            target_command_fingerprint,
            "targetCommandFingerprint",
        )
        try:
            response = await self.request(
                "command.status",
                {
                    "sessionId": _required_command_text(
                        session_id,
                        "sessionId",
                    ),
                    "queryCommandId": normalized_query,
                    "queryCommandFingerprint": normalized_query_fingerprint,
                    "targetCommandId": normalized_target,
                    "targetCommandFingerprint": normalized_target_fingerprint,
                },
                timeout=timeout,
            )
        except NMBridgeError as exc:
            raise CommandTransportUncertainError(
                "status response was not observed",
                reconcile_keys=(
                    (normalized_query, normalized_query_fingerprint),
                    (normalized_target, normalized_target_fingerprint),
                ),
            ) from exc
        if "error" in response:
            raise NMBridgeError(
                _wire_error_message(response["error"]),
                code="command_status_failed",
            )
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise NMBridgeError("command.status returned an invalid result")
        target_payload = result.get("targetReceipt")
        fact_payload = result.get("targetCommandFact")
        observed_state = (
            str(fact_payload.get("observedState") or "UNKNOWN")
            if isinstance(fact_payload, Mapping)
            else "UNKNOWN"
        )
        return CommandStatusResponse(
            query_receipt=_parse_command_receipt(
                result.get("queryReceipt"),
            ),
            target_receipt=(
                _parse_command_receipt(target_payload)
                if target_payload is not None
                else None
            ),
            target_command_fact=CommandFactProjection(observed_state),
        )

    async def send_cdp(
        self,
        tab_id: int,
        holder_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        lease_version: int | None = None,
    ) -> dict[str, Any]:
        self.validate_or_renew(tab_id, holder_id, lease_version)
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

    async def handle_ws_message(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any] | None:
        hello_ack = self.handle_bridge_hello(message)
        if hello_ack is not None:
            return hello_ack

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

    def handle_bridge_hello(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return hello_ack for browser-bridge backend handshakes."""
        if message.get("type") != "hello":
            return None
        _store_extension_version(message)
        actual_protocol_version = int(message.get("protocolVersion") or 1)
        if actual_protocol_version != SUPPORTED_PROTOCOL_VERSION:
            self.protocol_error = {
                "code": str(
                    BrowserErrorCode.BROWSER_PROTOCOL_VERSION_MISMATCH.value,
                ),
                "expected_protocol_version": SUPPORTED_PROTOCOL_VERSION,
                "actual_protocol_version": actual_protocol_version,
            }
            return {
                "type": "hello_ack",
                "status": "error",
                "entryId": str(message.get("entryId") or ""),
                **self.protocol_error,
            }
        actual_fingerprints = {
            "buildFingerprint": str(message.get("buildFingerprint") or ""),
            "contractFingerprint": str(
                message.get("contractFingerprint") or "",
            ),
            "profileFingerprint": str(
                message.get("profileFingerprint") or "",
            ),
            "extensionFingerprint": str(
                message.get("extensionFingerprint") or "",
            ),
            "providerFingerprint": str(
                message.get("providerFingerprint") or "",
            ),
            "maxRetainedStateTtlSeconds": int(
                message.get("maxRetainedStateTtlSeconds") or 0,
            ),
            "maxLegacyTokenTtlSeconds": int(
                message.get("maxLegacyTokenTtlSeconds") or 0,
            ),
        }
        expected_fingerprints = {
            "buildFingerprint": BUILD_FINGERPRINT,
            "contractFingerprint": CONTRACT_FINGERPRINT,
            "profileFingerprint": PROFILE_FINGERPRINT,
            "extensionFingerprint": EXTENSION_FINGERPRINT,
            "providerFingerprint": PROVIDER_FINGERPRINT,
            "maxRetainedStateTtlSeconds": MAX_RETAINED_STATE_TTL_SECONDS,
            "maxLegacyTokenTtlSeconds": MAX_LEGACY_TOKEN_TTL_SECONDS,
        }
        mismatched = {
            key: {"expected": expected, "actual": actual_fingerprints[key]}
            for key, expected in expected_fingerprints.items()
            if actual_fingerprints[key]
            and actual_fingerprints[key] != expected
        }
        if mismatched:
            self.protocol_error = {
                "code": "browser_capability_fingerprint_mismatch",
                "mismatched_fingerprints": mismatched,
            }
            return {
                "type": "hello_ack",
                "status": "error",
                "entryId": str(message.get("entryId") or ""),
                **self.protocol_error,
            }
        self.protocol_error = None
        return {
            "type": "hello_ack",
            "status": "ok",
            "entryId": str(message.get("entryId") or ""),
            "protocolVersion": SUPPORTED_PROTOCOL_VERSION,
            **expected_fingerprints,
        }

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


def _store_extension_version(payload: dict[str, Any]) -> None:
    version = (
        payload.get("extension_version")
        or payload.get("extensionVersion")
        or payload.get("version")
    )
    version_text = str(version or "").strip()
    if version_text:
        get_nm_bridge_route_state().extension_version = version_text


def _required_command_text(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise NMBridgeError(
            f"{field_name} is required",
            code="command_identity_invalid",
        )
    return normalized


def _parse_command_receipt(value: object) -> CommandReceipt:
    if not isinstance(value, Mapping):
        raise NMBridgeError("extension command receipt is invalid")
    try:
        state = ReceiptState(str(value.get("state") or ""))
    except ValueError as exc:
        raise NMBridgeError(
            "extension command receipt state is invalid",
        ) from exc
    return CommandReceipt(
        session_id=_required_command_text(value.get("sessionId"), "sessionId"),
        command_id=_required_command_text(value.get("commandId"), "commandId"),
        command_fingerprint=_required_command_text(
            value.get("commandFingerprint"),
            "commandFingerprint",
        ),
        state=state,
        result=value.get("result"),
    )


def _wire_error_message(value: object) -> str:
    if isinstance(value, Mapping):
        return str(value.get("message") or value.get("code") or "wire error")
    return str(value or "wire error")


def _mark_request_timeout(method: str, timeout: float) -> None:
    route_state = get_nm_bridge_route_state()
    now = datetime.now(UTC)
    route_state.last_error_code = BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT.value
    route_state.last_error_message = (
        f"request '{method}' timed out after {timeout}s"
    )
    route_state.last_request_timeout_at = now
    _record_lifecycle_trace(
        "request_timeout",
        status="error",
        error_code=BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT,
        metadata={"method": method, "timeout": timeout},
    )


def _mark_disconnected(
    websocket: Any | None,
    *,
    reason: str,
    message: str,
) -> None:
    if websocket is None:
        should_update = True
    else:
        should_update = get_nm_bridge_route_state().connected is websocket
    route_state = get_nm_bridge_route_state()
    if should_update:
        route_state.connected = None
        route_state.connected_since = None
        route_state.last_disconnected_at = datetime.now(UTC)
        route_state.last_disconnect_reason = reason
    route_state.last_error_code = str(BrowserErrorCode.BRIDGE_DISCONNECTED)
    route_state.last_error_message = message
    _record_lifecycle_trace(
        "close" if reason == "closed" else "disconnect",
        status="error",
        error_code=BrowserErrorCode.BRIDGE_DISCONNECTED,
        metadata={"reason": reason},
    )


def _record_lifecycle_trace(
    action: str,
    *,
    status: str,
    error_code: BrowserErrorCode | str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    record_browser_trace_event(
        session_id="nm-bridge",
        phase="bridge_lifecycle",
        backend_id="user.chrome_extension",
        selected_context="user",
        action=action,
        status=status,
        error_code=str(error_code or ""),
        metadata=metadata,
    )


_GLOBAL_BRIDGE: NMBridge | None = None


def get_nm_bridge() -> NMBridge:
    global _GLOBAL_BRIDGE
    if _GLOBAL_BRIDGE is None or _GLOBAL_BRIDGE.is_closed:
        _GLOBAL_BRIDGE = NMBridge()
    return _GLOBAL_BRIDGE


async def shutdown_nm_bridge() -> None:
    global _GLOBAL_BRIDGE
    if _GLOBAL_BRIDGE is None:
        return
    await _GLOBAL_BRIDGE.close()
    _GLOBAL_BRIDGE = None
