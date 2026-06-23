# -*- coding: utf-8 -*-
"""Network quiescence helpers for Browser Control click actions."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any


class _NetworkActivityTracker:
    """Track short-lived HTTP requests observed through CDP Network events."""

    def __init__(self, debounce_ms: float = 150.0) -> None:
        self.debounce_ms = max(float(debounce_ms), 0.0)
        self.total_triggered = 0
        self.inflight = 0
        self._active_request_ids: set[str] = set()
        self._settled_since = time.monotonic()
        self._settled_event = asyncio.Event()
        self._settled_event.set()

    def on_request_started(self, params: dict[str, Any]) -> None:
        """Record a started HTTP request."""
        request_id = str(params.get("requestId") or "").strip()
        request = params.get("request") or {}
        url = str(request.get("url") or "").strip().lower()
        if not request_id or not url.startswith(("http://", "https://")):
            return
        if request_id in self._active_request_ids:
            return
        self._active_request_ids.add(request_id)
        self.total_triggered += 1
        self.inflight += 1
        self._settled_event.clear()

    def on_request_finished(self, params: dict[str, Any]) -> None:
        """Record a finished or failed HTTP request."""
        request_id = str(params.get("requestId") or "").strip()
        if request_id and request_id in self._active_request_ids:
            self._active_request_ids.remove(request_id)
        if self.inflight > 0:
            self.inflight -= 1
        if self.inflight == 0:
            self._settled_since = time.monotonic()
            self._schedule_settled_event()

    @property
    def is_settled(self) -> bool:
        """Return whether network activity is idle and debounce has elapsed."""
        if self.total_triggered == 0:
            return True
        if self.inflight > 0:
            return False
        elapsed_ms = (time.monotonic() - self._settled_since) * 1000.0
        return elapsed_ms >= self.debounce_ms

    async def wait_until_settled(self) -> None:
        """Wait until the tracker reaches the settled state."""
        while not self.is_settled:
            timeout = max(
                (self.debounce_ms / 1000.0)
                - (time.monotonic() - self._settled_since),
                0.001,
            )
            try:
                await asyncio.wait_for(self._settled_event.wait(), timeout)
            except asyncio.TimeoutError:
                continue

    def _schedule_settled_event(self) -> None:
        if self.is_settled:
            self._settled_event.set()
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        def mark_if_still_settled() -> None:
            if self.is_settled:
                self._settled_event.set()

        loop.call_later(self.debounce_ms / 1000.0, mark_if_still_settled)


async def _network_quiescence_wait(
    session: Any,
    bridge: Any,
    state: dict,
    tab_id: int,
    *,
    timeout: float = 3.0,
    grace_ms: float = 100.0,
    debounce_ms: float = 150.0,
) -> dict[str, Any]:
    """Wait for post-click HTTP activity on a tab to become quiet."""
    try:
        await _ensure_network_enabled(session, state, tab_id)
    except Exception:
        return {
            "async_requests_triggered": 0,
            "settled": True,
            "timed_out": False,
            "unavailable": True,
        }

    tracker = _NetworkActivityTracker(debounce_ms=debounce_ms)

    def on_cdp_event(params: dict[str, Any]) -> None:
        event_tab_id = params.get("tabId")
        if event_tab_id != tab_id:
            return
        method = str(params.get("method") or "")
        event_params = params.get("params") or {}
        if method == "Network.requestWillBeSent":
            tracker.on_request_started(event_params)
        elif method in ("Network.loadingFinished", "Network.loadingFailed"):
            tracker.on_request_finished(event_params)

    if hasattr(bridge, "add_event_listener"):
        bridge.add_event_listener("cdp.event", on_cdp_event)
    try:
        await asyncio.sleep(max(float(grace_ms), 0.0) / 1000.0)
        if tracker.total_triggered == 0:
            return {
                "async_requests_triggered": 0,
                "settled": True,
                "timed_out": False,
            }
        try:
            await asyncio.wait_for(
                tracker.wait_until_settled(),
                timeout=max(float(timeout), 0.0),
            )
        except asyncio.TimeoutError:
            return {
                "async_requests_triggered": tracker.total_triggered,
                "settled": False,
                "timed_out": True,
            }
        return {
            "async_requests_triggered": tracker.total_triggered,
            "settled": tracker.is_settled,
            "timed_out": False,
        }
    finally:
        if hasattr(bridge, "remove_event_listener"):
            with contextlib.suppress(ValueError):
                bridge.remove_event_listener("cdp.event", on_cdp_event)


async def _ensure_network_enabled(
    session: Any,
    state: dict,
    tab_id: int,
) -> None:
    enabled = state.setdefault("control_network_enabled_tabs", set())
    if not isinstance(enabled, set):
        enabled = set(enabled) if isinstance(enabled, (list, tuple)) else set()
        state["control_network_enabled_tabs"] = enabled
    key = str(tab_id)
    if key in enabled:
        return
    await session.send("Network.enable")
    enabled.add(key)
