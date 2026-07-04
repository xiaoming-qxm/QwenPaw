# -*- coding: utf-8 -*-
"""First-class isolated Playwright backend for the Browser SDK."""
# pylint: disable=redefined-builtin

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote_plus

from .._runtime import (
    _chromium_launch_args,
    _ensure_playwright_async,
    _parse_browser_args,
    _resolve_chromium_launch_target,
    _resolve_output_path,
    _use_webkit_fallback,
    is_playwright_available,
    logger,
)
from .._snapshot import build_role_snapshot_from_aria
from ..actions import BrowserActionResult
from ..backend_registry import get_default_backend_registry
from ..observation import coerce_observation, coerce_screenshot
from ..types import (
    BrowserBackendCapabilities,
    BrowserObservation,
    BrowserScreenshot,
    ResolvedBrowserContext,
)

BACKEND_ID = "isolated.playwright"
_BROWSER_SENTINEL_TAB_ID = "__browser__"


class IsolatedBrowserBackend:
    """Browser SDK backend backed by an SDK-owned Playwright runtime."""

    backend_id = BACKEND_ID

    def __init__(
        self,
        manager: "IsolatedPlaywrightRuntimeManager | None" = None,
    ) -> None:
        self._manager = manager or get_isolated_runtime_manager()

    def capabilities(self) -> BrowserBackendCapabilities:
        return BrowserBackendCapabilities(
            backend_id=self.backend_id,
            browser_context="isolated",
            features=frozenset({"playwright", "sdk_owned_runtime"}),
        )

    def is_available(self) -> bool:
        available = getattr(self._manager, "is_available", None)
        if callable(available):
            return bool(available())
        return is_playwright_available()

    async def connect(
        self,
        session_id: str,
        context: ResolvedBrowserContext,
    ) -> "IsolatedBrowserSession":
        runtime = await self._manager.connect(session_id, context)
        return IsolatedBrowserSession(
            manager=self._manager,
            runtime=runtime,
            session_id=session_id,
            context=context,
        )


class IsolatedBrowserSession:
    """Connected isolated browser session."""

    backend_id = BACKEND_ID

    def __init__(
        self,
        *,
        manager: Any,
        runtime: Any,
        session_id: str,
        context: ResolvedBrowserContext,
    ) -> None:
        self._manager = manager
        self.runtime = runtime
        self.session_id = session_id
        self.context = context

    async def close(self) -> None:
        close = getattr(self.runtime, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def stop(self) -> None:
        manager_stop = getattr(self._manager, "stop_session", None) or getattr(
            self._manager,
            "stop",
            None,
        )
        if callable(manager_stop):
            result = manager_stop(self.session_id)
            if hasattr(result, "__await__"):
                await result
            return
        stop = getattr(self.runtime, "stop", None)
        if callable(stop):
            result = stop()
            if hasattr(result, "__await__"):
                await result

    async def active_tab(self) -> dict[str, Any]:
        return await self.runtime.active_tab()

    async def open_tab(self, url: str | None = None) -> dict[str, Any]:
        return await self.runtime.open_tab(url)

    async def list_tabs(self) -> list[dict[str, Any]]:
        return await self.runtime.list_tabs()

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        return await self.runtime.select_tab(tab_id)

    async def snapshot(self, tab_id: str) -> BrowserObservation:
        return coerce_observation(tab_id, await self.runtime.snapshot(tab_id))

    async def screenshot(self, tab_id: str) -> BrowserScreenshot:
        return coerce_screenshot(tab_id, await self.runtime.screenshot(tab_id))

    async def evaluate(
        self,
        tab_id: str,
        script: str,
        *,
        read_only: bool = False,
    ) -> Any:
        return await self.runtime.evaluate(
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
        if tab_id == _BROWSER_SENTINEL_TAB_ID:
            return await self.runtime.browser_action(name, **kwargs)
        return await self.runtime.action(tab_id, name, **kwargs)

    async def close_tab(self, tab_id: str) -> BrowserActionResult:
        return await self.runtime.close_tab(tab_id)

    async def extract(
        self,
        tab_id: str,
        instruction: str,
        *,
        format: str = "text",
    ) -> str:
        del instruction, format
        observation = await self.snapshot(tab_id)
        return observation.text


class IsolatedPlaywrightRuntimeManager:
    """Owns isolated Playwright runtimes keyed by Browser SDK session id."""

    def __init__(self) -> None:
        self._runtimes: dict[str, IsolatedPlaywrightRuntime] = {}

    def is_available(self) -> bool:
        return is_playwright_available()

    async def connect(
        self,
        session_id: str,
        context: ResolvedBrowserContext,
    ) -> "IsolatedPlaywrightRuntime":
        del context
        key = str(session_id or "default")
        runtime = self._runtimes.get(key)
        if runtime is None or runtime.stopped:
            runtime = IsolatedPlaywrightRuntime(session_id=key)
            self._runtimes[key] = runtime
        return runtime

    async def stop(self, session_id: str) -> None:
        key = str(session_id or "default")
        runtime = self._runtimes.pop(key, None)
        if runtime is not None:
            await runtime.stop()

    async def stop_session(self, session_id: str) -> None:
        """Stop and forget one isolated browser runtime session."""
        await self.stop(session_id)

    async def stop_all(self) -> None:
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        for runtime in runtimes:
            await runtime.stop()


class IsolatedPlaywrightRuntime:
    """Minimal SDK-owned Playwright runtime for isolated browser sessions."""

    backend_id = BACKEND_ID

    def __init__(
        self,
        *,
        session_id: str,
        browser_args: str = "",
        executable_path: str = "",
    ) -> None:
        self.session_id = session_id
        self.browser_args = browser_args
        self.executable_path = executable_path
        self.playwright: Any | None = None
        self.browser: Any | None = None
        self.context: Any | None = None
        self.pages: dict[str, Any] = {}
        self.refs: dict[str, dict[str, dict[str, Any]]] = {}
        self.current_page_id: str | None = None
        self.page_counter = 0
        self.stopped = False

    async def close(self) -> None:
        """Release this SDK handle without closing the shared runtime."""
        return None

    async def stop(self) -> None:
        """Destroy the isolated Playwright runtime."""
        self.stopped = True
        try:
            if self.context is not None:
                await self.context.close()
        except Exception:  # pragma: no cover - best effort shutdown
            logger.debug(
                "Failed to close isolated browser context",
                exc_info=True,
            )
        try:
            if self.browser is not None:
                await self.browser.close()
        except Exception:  # pragma: no cover - best effort shutdown
            logger.debug("Failed to close isolated browser", exc_info=True)
        try:
            if self.playwright is not None:
                await self.playwright.stop()
        except Exception:  # pragma: no cover - best effort shutdown
            logger.debug("Failed to stop isolated Playwright", exc_info=True)
        self.playwright = None
        self.browser = None
        self.context = None
        self.pages.clear()
        self.refs.clear()
        self.current_page_id = None

    async def active_tab(self) -> dict[str, Any]:
        await self._ensure_started()
        if self.current_page_id and self.current_page_id in self.pages:
            return await self._tab_info(self.current_page_id)
        tabs = await self.list_tabs()
        if tabs:
            self.current_page_id = tabs[0]["id"]
            return tabs[0]
        return await self.open_tab("about:blank")

    async def open_tab(self, url: str | None = None) -> dict[str, Any]:
        await self._ensure_started()
        context = self.context
        if context is None:
            raise RuntimeError("Isolated browser context is not available")
        page = await context.new_page()
        page_id = self._page_id_for(page)
        if page_id is None:
            page_id = self._next_page_id()
            self._register_page(page_id, page)
        target = str(url or "about:blank")
        if target:
            await page.goto(target)
        self.current_page_id = page_id
        return await self._tab_info(page_id)

    async def list_tabs(self) -> list[dict[str, Any]]:
        await self._ensure_started()
        await self._sync_context_pages()
        tabs: list[dict[str, Any]] = []
        for page_id, page in list(self.pages.items()):
            if page is None or page.is_closed():
                self.pages.pop(page_id, None)
                self.refs.pop(page_id, None)
                continue
            tabs.append(await self._tab_info(page_id))
        return tabs

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        page_id = str(tab_id)
        page = await self._page(page_id)
        await page.bring_to_front()
        self.current_page_id = page_id
        return await self._tab_info(page_id)

    async def snapshot(self, tab_id: str) -> BrowserObservation:
        page_id = str(tab_id)
        page = await self._page(page_id)
        raw = ""
        try:
            raw = await page.locator(":root").aria_snapshot()
        except Exception:
            logger.debug("ARIA snapshot failed; falling back to body text")
        snapshot = ""
        refs: dict[str, dict[str, Any]] = {}
        if raw:
            snapshot, refs = build_role_snapshot_from_aria(
                str(raw),
                interactive=False,
                compact=False,
            )
        if not snapshot:
            snapshot = await _fallback_page_text(page)
        self.refs[page_id] = refs
        return BrowserObservation(
            tab_id=page_id,
            text=snapshot,
            url=str(getattr(page, "url", "") or ""),
            title=await _safe_title(page),
            refs=refs,
        )

    async def screenshot(self, tab_id: str) -> BrowserScreenshot:
        page_id = str(tab_id)
        page = await self._page(page_id)
        path = _resolve_output_path(f"page-{int(time.time())}.png")
        await page.screenshot(path=path, full_page=True, type="png")
        return BrowserScreenshot(
            tab_id=page_id,
            path=path,
            url=str(getattr(page, "url", "") or ""),
            title=await _safe_title(page),
        )

    async def evaluate(
        self,
        tab_id: str,
        script: str,
        *,
        read_only: bool = False,
    ) -> Any:
        del read_only
        page = await self._page(str(tab_id))
        source = str(script or "").strip()
        if not source:
            return None
        if source.startswith("(") or source.startswith("function"):
            return await page.evaluate(source)
        return await page.evaluate(f"() => {{ return ({source}); }}")

    async def browser_action(
        self,
        name: str,
        **kwargs: Any,
    ) -> BrowserActionResult:
        action = str(name or "").strip().lower()
        if action == "search":
            query = str(kwargs.get("query") or "").strip()
            engine = str(kwargs.get("engine") or "google").strip().lower()
            url = _search_url(query, engine)
            tab = await self.open_tab(url)
            return BrowserActionResult(
                ok=True,
                message=f"Searched for {query}",
                data={"tab": tab, "url": url},
            )
        return BrowserActionResult(
            ok=False,
            message=f"Unsupported browser action: {name}",
        )

    # pylint: disable=too-many-return-statements,too-many-branches
    async def action(
        self,
        tab_id: str,
        name: str,
        **kwargs: Any,
    ) -> BrowserActionResult:
        action = str(name or "").strip().lower()
        page_id = str(tab_id)
        page = await self._page(page_id)
        if action in {"open", "navigate"}:
            url = str(kwargs.get("url") or "").strip()
            if not url:
                return BrowserActionResult(ok=False, message="url required")
            await page.goto(url)
            return BrowserActionResult(ok=True, message=f"Opened {url}")
        if action == "click":
            locator = self._locator_for_target(page, page_id, kwargs)
            if locator is not None:
                await locator.click()
            elif _has_coordinates(kwargs):
                await page.mouse.click(float(kwargs["x"]), float(kwargs["y"]))
            else:
                return BrowserActionResult(
                    ok=False,
                    message="target, selector, ref, text, or x/y required",
                )
            return BrowserActionResult(ok=True, message="click")
        if action == "type":
            text = str(kwargs.get("text") or "")
            locator = self._locator_for_target(page, page_id, kwargs)
            if locator is None:
                return BrowserActionResult(
                    ok=False,
                    message="target, selector, ref, or text target required",
                )
            await locator.fill(text)
            return BrowserActionResult(ok=True, message="type")
        if action == "press":
            key = str(kwargs.get("key") or "")
            if not key:
                return BrowserActionResult(ok=False, message="key required")
            locator = self._locator_for_target(page, page_id, kwargs)
            if locator is not None:
                await locator.press(key)
            else:
                await page.keyboard.press(key)
            return BrowserActionResult(ok=True, message="press")
        if action == "scroll":
            direction = str(kwargs.get("direction") or "down").lower()
            amount = float(kwargs.get("amount") or 600)
            delta = -amount if direction in {"up", "left"} else amount
            if direction in {"left", "right"}:
                await page.mouse.wheel(delta, 0)
            else:
                await page.mouse.wheel(0, delta)
            return BrowserActionResult(ok=True, message="scroll")
        if action == "select":
            value = kwargs.get("value")
            locator = self._locator_for_target(page, page_id, kwargs)
            if locator is None:
                return BrowserActionResult(
                    ok=False,
                    message="target, selector, or ref required",
                )
            await locator.select_option(value)
            return BrowserActionResult(ok=True, message="select")
        if action == "wait_for":
            await self._wait_for(page, page_id, kwargs)
            return BrowserActionResult(ok=True, message="wait_for")
        if action == "hover":
            locator = self._locator_for_target(page, page_id, kwargs)
            if locator is None:
                return BrowserActionResult(
                    ok=False,
                    message="target, selector, ref, or text required",
                )
            await locator.hover()
            return BrowserActionResult(ok=True, message="hover")
        return BrowserActionResult(
            ok=False,
            message=f"Unsupported isolated action: {name}",
        )

    async def close_tab(self, tab_id: str) -> BrowserActionResult:
        page_id = str(tab_id)
        page = await self._page(page_id)
        await page.close()
        self.pages.pop(page_id, None)
        self.refs.pop(page_id, None)
        if self.current_page_id == page_id:
            self.current_page_id = next(iter(self.pages), None)
        return BrowserActionResult(ok=True, message=f"Closed {page_id}")

    async def _ensure_started(self) -> None:
        if self.context is not None and not self.stopped:
            return
        self.stopped = False
        async_playwright = _ensure_playwright_async()
        self.playwright = await async_playwright().start()
        default_kind, exe = _resolve_chromium_launch_target()
        if self.executable_path:
            exe = self.executable_path
        args = _chromium_launch_args()
        args.extend(_parse_browser_args(self.browser_args))
        if _use_webkit_fallback() or default_kind == "webkit":
            self.browser = await self.playwright.webkit.launch(headless=True)
        else:
            launch_kwargs: dict[str, Any] = {"headless": True}
            if args:
                launch_kwargs["args"] = args
            if exe:
                launch_kwargs["executable_path"] = exe
            self.browser = await self.playwright.chromium.launch(
                **launch_kwargs,
            )
        self.context = await self.browser.new_context(accept_downloads=True)
        self.context.on("page", self._on_page)

    async def _sync_context_pages(self) -> None:
        if self.context is None:
            return
        known = {id(page) for page in self.pages.values()}
        for page in self.context.pages:
            if id(page) in known or page.is_closed():
                continue
            self._register_page(self._next_page_id(), page)

    async def _page(self, page_id: str) -> Any:
        await self._ensure_started()
        await self._sync_context_pages()
        page = self.pages.get(page_id)
        if page is None or page.is_closed():
            raise ValueError(f"Page '{page_id}' not found")
        return page

    async def _tab_info(self, page_id: str) -> dict[str, Any]:
        page = self.pages[page_id]
        return {
            "id": page_id,
            "url": str(getattr(page, "url", "") or "about:blank"),
            "title": await _safe_title(page),
        }

    def _next_page_id(self) -> str:
        self.page_counter += 1
        return f"page_{self.page_counter}"

    def _register_page(self, page_id: str, page: Any) -> None:
        self.pages[page_id] = page
        self.refs.setdefault(page_id, {})

    def _on_page(self, page: Any) -> None:
        existing_page_id = self._page_id_for(page)
        if existing_page_id is not None:
            self.current_page_id = existing_page_id
            return
        page_id = self._next_page_id()
        self._register_page(page_id, page)
        self.current_page_id = page_id

    def _page_id_for(self, page: Any) -> str | None:
        for page_id, existing in self.pages.items():
            if existing is page:
                return page_id
        return None

    def _locator_for_target(
        self,
        page: Any,
        page_id: str,
        kwargs: dict[str, Any],
    ) -> Any | None:
        target = kwargs.get("target")
        if isinstance(target, dict):
            merged = dict(target)
            merged.update(dict(kwargs))
            kwargs = merged
        elif target and not kwargs.get("selector") and not kwargs.get("ref"):
            kwargs = {**kwargs, "ref": target}
        ref = str(kwargs.get("ref") or "").strip()
        if ref:
            info = self.refs.get(page_id, {}).get(ref)
            if info:
                role = str(info.get("role") or "generic")
                name = info.get("name")
                locator = page.get_by_role(role, name=name or None)
                nth = info.get("nth")
                if nth is not None:
                    locator = locator.nth(int(nth))
                return locator
        selector = str(kwargs.get("selector") or "").strip()
        if selector:
            return page.locator(selector).first
        text = kwargs.get("text") or kwargs.get("name")
        if text:
            return page.get_by_text(str(text)).first
        requested_role = kwargs.get("role")
        if requested_role:
            return page.get_by_role(
                str(requested_role),
                name=kwargs.get("name"),
            ).first
        return None

    async def _wait_for(
        self,
        page: Any,
        page_id: str,
        kwargs: dict[str, Any],
    ) -> None:
        timeout_ms = int(kwargs.get("timeout_ms") or 10000)
        locator = self._locator_for_target(page, page_id, kwargs)
        if locator is not None:
            await locator.wait_for(timeout=timeout_ms)
            return
        instruction = str(kwargs.get("instruction") or "").strip()
        if instruction:
            await page.get_by_text(instruction).first.wait_for(
                timeout=timeout_ms,
            )
            return
        await page.wait_for_timeout(min(timeout_ms, 1000))


_DEFAULT_RUNTIME_MANAGER = IsolatedPlaywrightRuntimeManager()


def get_isolated_runtime_manager() -> IsolatedPlaywrightRuntimeManager:
    """Return the process-global isolated Playwright runtime manager."""
    return _DEFAULT_RUNTIME_MANAGER


def register_isolated_backend_once(
    manager: IsolatedPlaywrightRuntimeManager | None = None,
) -> IsolatedBrowserBackend:
    """Register the isolated Playwright backend if absent."""
    registry = get_default_backend_registry()
    existing = registry.get(BACKEND_ID)
    if isinstance(existing, IsolatedBrowserBackend):
        return existing
    backend = IsolatedBrowserBackend(manager=manager)
    if existing is None:
        registry.register(backend)
    return backend


async def _safe_title(page: Any) -> str:
    try:
        return str(await page.title())
    except Exception:
        return ""


async def _fallback_page_text(page: Any) -> str:
    try:
        text = await page.locator("body").inner_text(timeout=1000)
        if text:
            return str(text)
    except Exception:
        logger.debug("Body text fallback failed", exc_info=True)
    try:
        return str(await page.content())
    except Exception:
        return ""


def _has_coordinates(kwargs: dict[str, Any]) -> bool:
    return kwargs.get("x") is not None and kwargs.get("y") is not None


def _search_url(query: str, engine: str) -> str:
    encoded = quote_plus(query)
    if engine in {"bing", "microsoft"}:
        return f"https://www.bing.com/search?q={encoded}"
    if engine in {"duckduckgo", "ddg"}:
        return f"https://duckduckgo.com/?q={encoded}"
    return f"https://www.google.com/search?q={encoded}"


__all__ = [
    "BACKEND_ID",
    "IsolatedBrowserBackend",
    "IsolatedBrowserSession",
    "IsolatedPlaywrightRuntime",
    "IsolatedPlaywrightRuntimeManager",
    "get_isolated_runtime_manager",
    "register_isolated_backend_once",
]
