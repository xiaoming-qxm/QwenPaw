# -*- coding: utf-8 -*-
"""CDP relay session for Chrome browser control mode."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from qwenpaw.browser.governance.error_codes import BrowserErrorCode

from transport.native_messaging import StaleLeaseError, TabOccupiedError

_TRUSTED_READONLY_SNAPSHOT_EVALUATE_PURPOSES = {
    "snapshot.action_targets": "_CONTROL_ACTION_TARGETS_SCRIPT",
    "snapshot.page_state": "_CONTROL_PAGE_STATE_SCRIPT",
}
SCREENSHOT_VIEWPORT_METRICS_EXPRESSION = (
    "({x:Number(window.scrollX||0),y:Number(window.scrollY||0),"
    "dpr:Number(window.devicePixelRatio||1),focusedBackendNode:null})"
)
SCREENSHOT_FOCUSED_NODE_EXPRESSION = "document.activeElement || null"
_TRUSTED_READONLY_SCREENSHOT_EVALUATE_PURPOSES = {
    "screenshot.viewport_metrics": (
        SCREENSHOT_VIEWPORT_METRICS_EXPRESSION,
        True,
    ),
    "screenshot.focused_node": (SCREENSHOT_FOCUSED_NODE_EXPRESSION, False),
}
_TRUSTED_READONLY_EVALUATE_PARAM_KEYS = frozenset(
    {"expression", "returnByValue", "awaitPromise", "timeout"},
)
_TRUSTED_READONLY_EVALUATE_TIMEOUT_MS = 1000


class CDPRelayError(RuntimeError):
    """Raised when a relayed CDP command returns a JSON-RPC error."""

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


class CDPRelayPaused(CDPRelayError):
    """Raised when HITL pause blocks CDP commands."""


class CDPApprovalDenied(CDPRelayError):
    """Raised when CDP permission approval is denied or unavailable."""

    browser_error_code = str(BrowserErrorCode.APPROVAL_DENIED.value)


class CDPPermissionDenied(CDPApprovalDenied):
    """Raised when CDP permission policy denies a command."""


class CDPRelaySession:
    """Small Playwright-CDPSession-compatible facade over NMBridge."""

    def __init__(
        self,
        tab_id: int,
        holder_id: str,
        bridge: Any,
        approval_callback: Callable[[dict[str, Any]], Any] | None = None,
        request_context: dict[str, Any] | None = None,
        permissions_config: Any | None = None,
        heartbeat_interval: float = 10.0,
        watchdog_interval: float = 5.0,
        idle_timeout: float = 300.0,
    ) -> None:
        self.tab_id = tab_id
        self.holder_id = holder_id
        self.owner_id = holder_id
        self.bridge = bridge
        # Retained for callers that still pass the legacy approval plumbing.
        # CDP relay commands intentionally never invoke either value.
        self.approval_callback = approval_callback
        self.request_context = request_context or {}
        self.permissions_config = permissions_config
        self.approved_domains = getattr(
            permissions_config,
            "approved_domains",
            set(),
        )
        self.lease_version: int | None = None
        if hasattr(self.bridge, "lease_version"):
            self.lease_version = self.bridge.lease_version(tab_id, holder_id)
        self.event_handlers: dict[str, list[Callable[..., Any]]] = defaultdict(
            list,
        )
        self._closed = False
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._watchdog_interval = watchdog_interval
        self._idle_timeout = idle_timeout
        self._watchdog_task: asyncio.Task[None] | None = None
        self._last_activity = self._now()
        self.closed_by_watchdog = False
        self.last_snapshot: dict[str, Any] | None = None
        self._start_heartbeat()
        self._start_watchdog()

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_params = params or {}
        await self._ensure_approved(method, safe_params)
        return await self._send_unchecked(method, safe_params)

    async def send_trusted_readonly(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        purpose: str,
    ) -> dict[str, Any]:
        """Send one allowlisted internal read-only CDP command."""
        safe_params = dict(params or {})
        self._ensure_trusted_readonly(method, safe_params, purpose)
        return await self._send_unchecked(method, safe_params)

    async def _send_unchecked(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        validate_or_renew = getattr(self.bridge, "validate_or_renew", None)
        if callable(validate_or_renew):
            lease = validate_or_renew(
                self.tab_id,
                self.owner_id,
                self.lease_version,
            )
            self.lease_version = getattr(lease, "version", self.lease_version)
        elif hasattr(self.bridge, "validate_lease"):
            self.bridge.validate_lease(
                self.tab_id,
                self.owner_id,
                self.lease_version,
            )
        self._last_activity = self._now()

        try:
            response = await self.bridge.request(
                "cdp.send",
                {
                    "tabId": self.tab_id,
                    "ownerId": self.owner_id,
                    "holderId": self.holder_id,
                    "method": method,
                    "params": params,
                },
            )
        except Exception as exc:
            if _is_bridge_request_timeout(exc):
                raise CDPRelayError(
                    f"CDP command {method} timed out.",
                    code=BrowserErrorCode.CDP_COMMAND_TIMEOUT,
                ) from exc
            raise
        if isinstance(response, dict) and "error" in response:
            error = response["error"]
            message = (
                error.get("message", "CDP relay error")
                if isinstance(error, dict)
                else str(error)
            )
            raise CDPRelayError(message)
        if isinstance(response, dict) and response.get("jsonrpc") == "2.0":
            return response.get("result", {})
        return response

    def _ensure_trusted_readonly(
        self,
        method: str,
        params: dict[str, Any],
        purpose: str,
    ) -> None:
        if method != "Runtime.evaluate":
            raise CDPPermissionDenied(
                f"CDP command {method} denied by trusted readonly policy",
            )
        (
            expected_expression,
            expected_return_by_value,
        ) = _trusted_readonly_evaluate_spec(purpose)
        if str(params.get("expression") or "") != expected_expression:
            raise CDPPermissionDenied(
                "CDP Runtime.evaluate expression denied by trusted "
                "readonly policy",
            )
        if set(params) - _TRUSTED_READONLY_EVALUATE_PARAM_KEYS:
            raise CDPPermissionDenied(
                "CDP Runtime.evaluate params denied by trusted readonly "
                "policy",
            )
        timeout = params.get("timeout")
        timeout_ok = (
            isinstance(timeout, (int, float))
            and not isinstance(timeout, bool)
            and 0 < float(timeout) <= _TRUSTED_READONLY_EVALUATE_TIMEOUT_MS
        )
        if (
            params.get("returnByValue") is not expected_return_by_value
            or params.get("awaitPromise") is not False
            or not timeout_ok
        ):
            raise CDPPermissionDenied(
                "CDP Runtime.evaluate params denied by trusted readonly "
                "policy",
            )

    async def show_banner(
        self,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self.bridge.request(
            "banner.show",
            {"tabId": self.tab_id, **(params or {})},
        )
        if isinstance(response, dict) and "error" in response:
            error = response["error"]
            message = (
                error.get("message", "Banner relay error")
                if isinstance(error, dict)
                else str(error)
            )
            raise CDPRelayError(message)
        if isinstance(response, dict) and response.get("jsonrpc") == "2.0":
            return response.get("result", {})
        return response

    async def send_after_banner(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        banner_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self.show_banner(banner_params)
        return await self.send(method, params)

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        self.event_handlers[event].append(handler)

    async def _close_local(self) -> bool:
        if self._closed:
            return False
        self._closed = True
        current_task = asyncio.current_task()
        for task in (self._heartbeat_task, self._watchdog_task):
            if task is not None and task is not current_task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        return True

    async def abandon(self) -> None:
        """Drop this local session without touching the Chrome debugger.

        Used when Python-side cache contains a stale holder for a tab that is
        being reclaimed by a newer request. Detaching here would affect the
        current holder because Chrome's debugger attachment is tab-scoped.
        """
        await self._close_local()

    async def close(self) -> None:
        if not await self._close_local():
            return
        with contextlib.suppress(Exception):
            await self.bridge.request(
                "tab.detach",
                {"tabId": self.tab_id, "holderId": self.holder_id},
            )
        with contextlib.suppress(Exception):
            await self.bridge.request("banner.hide", {"tabId": self.tab_id})
        with contextlib.suppress(Exception):
            await self.bridge.release(self.tab_id, self.holder_id)

    async def _ensure_approved(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        """Accept every CDP command; legacy permission inputs are inert."""
        del method, params

    def _start_heartbeat(self) -> None:
        if (
            self.lease_version is None
            or self._heartbeat_interval <= 0
            or not hasattr(self.bridge, "renew_lease")
        ):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self._heartbeat_interval)
            if self._closed:
                return
            try:
                lease = await self.bridge.renew_lease(
                    self.tab_id,
                    self.holder_id,
                    self.lease_version,
                )
            except (StaleLeaseError, TabOccupiedError):
                # Cleanup may release the lease while this background task is
                # asleep. That is a normal terminal condition, not an
                # unobserved task exception.
                return
            self.lease_version = lease.version

    def _start_watchdog(self) -> None:
        if (
            self.lease_version is None
            or self._watchdog_interval <= 0
            or self._idle_timeout <= 0
        ):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def _watchdog_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self._watchdog_interval)
            if self._closed:
                return
            if self._now() - self._last_activity <= self._idle_timeout:
                continue
            self.closed_by_watchdog = True
            await self.close()
            return

    def _now(self) -> float:
        if hasattr(self.bridge, "now"):
            return self.bridge.now()
        return time.monotonic()


def _is_bridge_request_timeout(exc: BaseException) -> bool:
    code = str(getattr(exc, "browser_error_code", "") or "").casefold()
    if code == BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT.value:
        return True
    message = str(exc).casefold()
    return "timed out" in message and "request" in message


def _trusted_readonly_evaluate_spec(purpose: str) -> tuple[str, bool]:
    """Return the exact expression and serialization mode for one probe."""
    normalized_purpose = str(purpose or "")
    screenshot_probe = _TRUSTED_READONLY_SCREENSHOT_EVALUATE_PURPOSES.get(
        normalized_purpose,
    )
    if screenshot_probe is not None:
        return screenshot_probe

    attribute = _TRUSTED_READONLY_SNAPSHOT_EVALUATE_PURPOSES.get(
        normalized_purpose,
    )
    if attribute is None:
        raise CDPPermissionDenied(
            "CDP Runtime.evaluate purpose denied by trusted readonly policy",
        )
    from . import snapshot_builder

    return str(getattr(snapshot_builder, attribute)), True
