# -*- coding: utf-8 -*-
"""Chrome navigation scope helpers."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from .state import StateMapping

_CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS = 15.0
_CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS = 5.0


def _control_create_page_load_waiter(bridge: Any, tab_id: int) -> Callable:
    """Return a waiter that resolves when the tab emits Page.loadEventFired."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()
    handlers: list[tuple[str, Callable[[dict[str, Any]], None]]] = []

    def on_cdp_event(params: dict[str, Any]) -> None:
        event_tab_id = params.get("tabId")
        if str(event_tab_id) != str(tab_id):
            return
        if str(params.get("method") or "") != "Page.loadEventFired":
            return
        if not future.done():
            future.set_result(True)

    if hasattr(bridge, "add_event_listener"):
        bridge.add_event_listener("cdp.event", on_cdp_event)
        handlers.append(("cdp.event", on_cdp_event))

    async def wait(timeout: float) -> bool:
        try:
            if not handlers:
                return False
            await asyncio.wait_for(future, timeout=max(float(timeout), 0.0))
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            if hasattr(bridge, "remove_event_listener"):
                for event_name, handler in handlers:
                    with contextlib.suppress(ValueError):
                        bridge.remove_event_listener(event_name, handler)

    return wait


def _control_tab_id(page_id: str, index: int = -1) -> int:
    if index >= 0:
        return index
    raw = (page_id or "").strip()
    if raw.startswith("tab_"):
        raw = raw[4:]
    if raw.isdigit():
        return int(raw)
    raise ValueError("control actions require page_id/tab id or index")


def _control_page_id_is_tab_id(page_id: str) -> bool:
    raw = (page_id or "").strip()
    if not raw or raw == "default":
        return False
    if raw.startswith("tab_"):
        raw = raw[4:]
    return raw.isdigit()


def _control_url_key(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def _control_site_domain(domain: str) -> str:
    domain = domain.lower().strip(".")
    if not domain or domain == "localhost":
        return domain
    parts = [part for part in domain.split(".") if part]
    if len(parts) <= 2:
        return domain
    if (
        len(parts) >= 3
        and len(parts[-1]) == 2
        and parts[-2] in {"ac", "co", "com", "edu", "gov", "net", "org"}
    ):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _control_navigation_domains(url: str) -> set[str]:
    domain = (urlparse(url).hostname or "").lower().strip(".")
    if not domain:
        return set()
    return {domain, _control_site_domain(domain)}


def _control_same_site(url_a: str, url_b: str) -> bool:
    domains_a = _control_navigation_domains(url_a)
    domains_b = _control_navigation_domains(url_b)
    return bool(domains_a and domains_b and domains_a.intersection(domains_b))


def _control_remember_approved_navigation(
    state: StateMapping,
    url: str,
) -> None:
    domains = _control_navigation_domains(url)
    if not domains:
        return
    approved = state.get("control_approved_domains")
    if not isinstance(approved, set):
        approved = set(approved or [])
        state["control_approved_domains"] = approved
    approved.update(domains)


def _control_sync_session_navigation_scope(
    state: StateMapping,
    session: Any,
) -> None:
    """Keep the legacy call site without sharing approval-domain state."""
    del state, session


__all__ = [
    "_control_navigation_domains",
    "_CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS",
    "_CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS",
    "_control_create_page_load_waiter",
    "_control_page_id_is_tab_id",
    "_control_remember_approved_navigation",
    "_control_same_site",
    "_control_site_domain",
    "_control_sync_session_navigation_scope",
    "_control_tab_id",
    "_control_url_key",
]
