# -*- coding: utf-8 -*-
"""CDP relay session for Chrome browser control mode."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse


class CDPRelayError(RuntimeError):
    """Raised when a relayed CDP command returns a JSON-RPC error."""


class CDPRelayPaused(CDPRelayError):
    """Raised when HITL pause blocks CDP commands."""


class CDPApprovalDenied(CDPRelayError):
    """Raised when CDP permission approval is denied or unavailable."""


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
        stop_callback: Callable[["CDPRelaySession", dict[str, Any]], Any]
        | None = None,
        heartbeat_interval: float = 10.0,
        watchdog_interval: float = 5.0,
        idle_timeout: float = 300.0,
    ) -> None:
        self.tab_id = tab_id
        self.holder_id = holder_id
        self.bridge = bridge
        self.approval_callback = approval_callback
        self.stop_callback = stop_callback
        self.request_context = request_context or {}
        if permissions_config is None:
            from .cdp_permissions import load_permissions

            permissions_config = load_permissions()
        self.permissions_config = permissions_config
        self.approved_domains = self.permissions_config.approved_domains
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
        self.paused = False
        self.last_snapshot: dict[str, Any] | None = None
        self._registered_bridge_handlers: list[
            tuple[str, Callable[[dict[str, Any]], Any]]
        ] = []
        if hasattr(self.bridge, "add_event_listener"):
            for method, handler in (
                ("hitl.paused", self._on_hitl_paused),
                ("hitl.resumed", self._on_hitl_resumed),
                ("hitl.stopped", self._on_hitl_stopped),
            ):
                self.bridge.add_event_listener(method, handler)
                self._registered_bridge_handlers.append((method, handler))
        self._start_heartbeat()
        self._start_watchdog()

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        ignore_paused: bool = False,
    ) -> dict[str, Any]:
        if self.paused and not ignore_paused:
            raise CDPRelayPaused("CDP relay is paused for user control")

        await self._ensure_approved(method, params or {})
        if hasattr(self.bridge, "validate_lease"):
            self.bridge.validate_lease(
                self.tab_id,
                self.holder_id,
                self.lease_version,
            )
        self._last_activity = self._now()

        response = await self.bridge.request(
            "cdp.send",
            {
                "tabId": self.tab_id,
                "holderId": self.holder_id,
                "method": method,
                "params": params or {},
            },
        )
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
        if hasattr(self.bridge, "remove_event_listener"):
            for method, handler in self._registered_bridge_handlers:
                with contextlib.suppress(ValueError):
                    self.bridge.remove_event_listener(method, handler)
        self._registered_bridge_handlers.clear()
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

    def _event_matches(self, params: dict[str, Any]) -> bool:
        tab_id = params.get("tabId")
        return tab_id is None or int(tab_id) == self.tab_id

    async def _on_hitl_paused(self, params: dict[str, Any]) -> None:
        if self._event_matches(params):
            self.paused = True

    async def _on_hitl_resumed(self, params: dict[str, Any]) -> None:
        if not self._event_matches(params):
            return
        self.paused = False
        self.last_snapshot = await self.send(
            "Accessibility.getFullAXTree",
            ignore_paused=True,
        )

    async def _on_hitl_stopped(self, params: dict[str, Any]) -> None:
        if not self._event_matches(params):
            return
        self.paused = True
        await self.close()
        if self.stop_callback is not None:
            result = self.stop_callback(self, params)
            if inspect.isawaitable(result):
                await result

    async def _ensure_approved(
        self,
        method: str,
        params: dict[str, Any],
    ) -> None:
        from .cdp_permissions import check_permission

        target_url = str(params.get("url") or "") or None
        result = check_permission(method, target_url, self.permissions_config)
        if result.decision == "allow":
            return
        if result.decision == "deny":
            raise CDPPermissionDenied(
                f"CDP command {method} denied by permission policy",
            )

        request = self._approval_request(method, params, result.decision)
        if request is None:
            raise CDPApprovalDenied(
                f"CDP command {method} requires approval but "
                "no request could be built",
            )
        approved = await self._request_approval(request)
        if not approved:
            raise CDPPermissionDenied(
                f"CDP command {method} denied by approval flow",
            )
        domain = request.get("domain")
        if domain:
            self.approved_domains.add(str(domain))

    def _approval_request(
        self,
        method: str,
        params: dict[str, Any],
        policy: str = "ask",
    ) -> dict[str, Any] | None:
        url = str(params.get("url") or "").strip()
        domain = (urlparse(url).hostname or "").lower() if url else ""
        return {
            "policy": policy,
            "method": method,
            "url": url,
            "domain": domain,
            "tab_id": self.tab_id,
            "holder_id": self.holder_id,
        }

    async def _request_approval(self, request: dict[str, Any]) -> bool:
        if self.approval_callback is not None:
            result = self.approval_callback(request)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)

        session_id = str(self.request_context.get("session_id") or "")
        if not session_id:
            raise CDPApprovalDenied(
                "CDP approval requires request_context.session_id",
            )

        from qwenpaw.app.approvals import get_approval_service
        from qwenpaw.app.approvals.models import ApprovalRequestSummary
        from qwenpaw.constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
        from qwenpaw.security.tool_guard.approval import ApprovalDecision

        svc = get_approval_service()
        pending = await svc.create_pending_summary(
            session_id=session_id,
            root_session_id=str(
                self.request_context.get("root_session_id") or session_id,
            ),
            owner_agent_id=str(
                self.request_context.get("root_agent_id") or "",
            ),
            user_id=str(self.request_context.get("user_id") or ""),
            channel=str(self.request_context.get("channel") or ""),
            agent_id=str(self.request_context.get("agent_id") or "unknown"),
            summary=ApprovalRequestSummary(
                source_type="browser_control_cdp",
                name="browser_use.control",
                severity="medium",
                findings_count=1,
                result_summary=(
                    "Chrome browser control wants to navigate to new domain "
                    f"{request['domain']}."
                ),
                payload=request,
            ),
            timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
            extra={
                "tool_call": {
                    "id": str(self.request_context.get("tool_call_id") or ""),
                    "name": "browser_use",
                    "input": request,
                },
            },
        )
        decision = await svc.wait_for_approval(
            pending.request_id,
            TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
        )
        return decision == ApprovalDecision.APPROVED

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
            lease = await self.bridge.renew_lease(
                self.tab_id,
                self.holder_id,
                self.lease_version,
            )
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
