# -*- coding: utf-8 -*-
"""Isolated Browser SDK backend wrapping legacy browser_use internals."""

from __future__ import annotations

import json
from typing import Any

from .actions import BrowserActionResult
from .backend_registry import get_default_backend_registry
from .observation import coerce_observation, coerce_screenshot
from .types import (
    BrowserBackendCapabilities,
    BrowserObservation,
    BrowserScreenshot,
    ResolvedBrowserContext,
)

BACKEND_ID = "isolated.playwright_legacy"


class IsolatedBrowserBackend:
    """Browser SDK backend that delegates to the legacy isolated browser."""

    backend_id = BACKEND_ID

    def __init__(self, adapter: Any | None = None) -> None:
        self._adapter = adapter or LegacyBrowserUseAdapter()

    def capabilities(self) -> BrowserBackendCapabilities:
        return BrowserBackendCapabilities(
            backend_id=self.backend_id,
            browser_context="isolated",
            features=frozenset({"legacy_browser_use_wrapper"}),
        )

    def is_available(self) -> bool:
        is_available = getattr(self._adapter, "is_available", None)
        if callable(is_available):
            return bool(is_available())
        return True

    async def connect(
        self,
        session_id: str,
        context: ResolvedBrowserContext,
    ) -> "IsolatedBrowserSession":
        del session_id
        return IsolatedBrowserSession(
            adapter=self._adapter,
            context=context,
        )


class IsolatedBrowserSession:
    """Connected isolated browser session wrapper."""

    backend_id = BACKEND_ID

    def __init__(
        self,
        *,
        adapter: Any,
        context: ResolvedBrowserContext,
    ) -> None:
        self._adapter = adapter
        self.context = context

    async def close(self) -> None:
        stop = getattr(self._adapter, "stop", None)
        if callable(stop):
            result = stop()
            if hasattr(result, "__await__"):
                await result

    async def active_tab(self) -> dict[str, Any]:
        return await self._adapter.active_tab()

    async def open_tab(self, url: str | None = None) -> dict[str, Any]:
        return await self._adapter.open_tab(url)

    async def list_tabs(self) -> list[dict[str, Any]]:
        return await self._adapter.list_tabs()

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        return await self._adapter.select_tab(tab_id)

    async def snapshot(self, tab_id: str) -> BrowserObservation:
        return coerce_observation(tab_id, await self._adapter.snapshot(tab_id))

    async def screenshot(self, tab_id: str) -> BrowserScreenshot:
        return coerce_screenshot(
            tab_id,
            await self._adapter.screenshot(tab_id),
        )

    async def evaluate(
        self,
        tab_id: str,
        script: str,
        *,
        read_only: bool = False,
    ) -> Any:
        return await self._adapter.evaluate(
            tab_id,
            script,
            read_only=read_only,
        )

    async def action(
        self,
        tab_id: str,
        name: str,
        **kwargs: Any,
    ) -> BrowserActionResult:
        return await self._adapter.action(tab_id, name, **kwargs)

    async def close_tab(self, tab_id: str) -> BrowserActionResult:
        return await self._adapter.close_tab(tab_id)


class LegacyBrowserUseAdapter:
    """Minimal adapter over the existing isolated browser_use dispatcher."""

    def is_available(self) -> bool:
        return True

    async def stop(self) -> None:
        await self._call("stop")

    async def active_tab(self) -> dict[str, Any]:
        return {"id": "default", "url": "", "title": ""}

    async def open_tab(self, url: str | None = None) -> dict[str, Any]:
        payload = await self._call("open", url=url or "about:blank")
        return {
            "id": str(payload.get("page_id") or "default"),
            "url": str(payload.get("url") or url or "about:blank"),
            "title": str(payload.get("title") or ""),
        }

    async def list_tabs(self) -> list[dict[str, Any]]:
        payload = await self._call("tabs", tab_action="list")
        tabs = payload.get("tabs") if isinstance(payload, dict) else None
        if not isinstance(tabs, list):
            return [{"id": "default", "url": "", "title": ""}]
        return [_normalize_tab(tab) for tab in tabs if isinstance(tab, dict)]

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        return {"id": str(tab_id), "url": "", "title": ""}

    async def snapshot(self, tab_id: str) -> BrowserObservation:
        payload = await self._call("snapshot", page_id=tab_id)
        return coerce_observation(tab_id, payload)

    async def screenshot(self, tab_id: str) -> BrowserScreenshot:
        payload = await self._call("screenshot", page_id=tab_id)
        return coerce_screenshot(tab_id, payload)

    async def evaluate(
        self,
        tab_id: str,
        script: str,
        *,
        read_only: bool = False,
    ) -> Any:
        del read_only
        return await self._call("evaluate", page_id=tab_id, code=script)

    async def action(
        self,
        tab_id: str,
        name: str,
        **kwargs: Any,
    ) -> BrowserActionResult:
        action, mapped = _legacy_action(name, kwargs)
        payload = await self._call(action, page_id=tab_id, **mapped)
        return _action_result(payload, name)

    async def close_tab(self, tab_id: str) -> BrowserActionResult:
        payload = await self._call("close", page_id=tab_id)
        return _action_result(payload, "close")

    async def _call(self, action: str, **kwargs: Any) -> dict[str, Any]:
        from qwenpaw.agents.tools.browser_control import (
            browser_use,
            legacy_browser_use_bypass,
        )

        with legacy_browser_use_bypass():
            result = await browser_use(action=action, **kwargs)
        return _chunk_payload(result)


def register_isolated_backend_once(
    adapter: Any | None = None,
) -> IsolatedBrowserBackend:
    """Register the isolated legacy backend if absent."""
    registry = get_default_backend_registry()
    existing = registry.get(BACKEND_ID)
    if isinstance(existing, IsolatedBrowserBackend):
        return existing
    backend = IsolatedBrowserBackend(adapter=adapter)
    if existing is None:
        registry.register(backend)
    return backend


def _legacy_action(
    name: str,
    kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    action = str(name or "").strip().lower()
    mapped = dict(kwargs)
    if action == "press":
        mapped["key"] = mapped.pop("key", "")
        return "press_key", mapped
    if action == "select":
        value = mapped.pop("value", "")
        mapped["values_json"] = json.dumps([value], ensure_ascii=False)
        return "select_option", mapped
    if action == "open":
        return "navigate", mapped
    if action in {"click", "type", "scroll", "wait_for", "hover"}:
        return action, mapped
    return action, mapped


def _normalize_tab(tab: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(tab.get("id") or tab.get("page_id") or "default"),
        "url": str(tab.get("url") or ""),
        "title": str(tab.get("title") or ""),
    }


def _action_result(payload: Any, name: str) -> BrowserActionResult:
    if isinstance(payload, BrowserActionResult):
        return payload
    if isinstance(payload, dict):
        return BrowserActionResult(
            ok=bool(payload.get("ok", True)),
            message=str(
                payload.get("message") or payload.get("error") or name,
            ),
            needs_observation=bool(payload.get("needs_observation", True)),
            data=dict(payload.get("data") or {}),
        )
    return BrowserActionResult(ok=True, message=str(payload or name))


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        return chunk
    try:
        content = getattr(chunk, "content", [])
        first = content[0] if content else None
        text = getattr(first, "text", "")
    except (AttributeError, IndexError, TypeError):
        text = str(chunk)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {"ok": False, "message": str(text or "")}
    return parsed if isinstance(parsed, dict) else {"ok": False}


__all__ = [
    "BACKEND_ID",
    "IsolatedBrowserBackend",
    "IsolatedBrowserSession",
    "LegacyBrowserUseAdapter",
    "register_isolated_backend_once",
]
