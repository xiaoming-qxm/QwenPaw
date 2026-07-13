# -*- coding: utf-8 -*-
"""First-class isolated Playwright backend for the Browser SDK."""
# pylint: disable=redefined-builtin,too-many-public-methods

from __future__ import annotations

import time
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus
from urllib.parse import urlparse

from ..backends.registry import get_default_backend_registry
from ..governance.error_codes import BrowserErrorCode, classify_browser_error
from ..governance.errors import BrowserSDKError
from ..governance.boundary import (
    action_result_with_boundary_decision,
    evaluate_browser_boundary,
    policy_metadata_kwargs,
    raise_if_boundary_denied,
)
from ..governance.policy import BrowserPolicy, DefaultBrowserPolicy
from ..primitives.observation import coerce_observation, coerce_screenshot
from ..primitives.types import (
    BrowserActionResult,
    BrowserBackendCapabilities,
    BrowserBackendDiagnostic,
    BrowserDiagnosticCheck,
    BrowserDiagnosticStatus,
    BrowserObservation,
    BrowserOwnershipContext,
    BrowserPageInfo,
    BrowserRetention,
    BrowserScreenshot,
    ResolvedBrowserContext,
)
from ..runtime.responses import (
    _chromium_launch_args,
    _ensure_playwright_async,
    _parse_browser_args,
    _resolve_chromium_launch_target,
    _resolve_output_path,
    _use_webkit_fallback,
    is_playwright_available,
    logger,
)
from ..runtime.snapshot import build_role_snapshot_from_aria

BACKEND_ID = "isolated.playwright"
_BROWSER_SENTINEL_TAB_ID = "__browser__"


class IsolatedBrowserBackend:
    """Browser SDK backend backed by an SDK-owned Playwright runtime."""

    backend_id = BACKEND_ID

    def __init__(
        self,
        manager: "IsolatedPlaywrightRuntimeManager | None" = None,
        policy: BrowserPolicy | None = None,
    ) -> None:
        self._manager = manager or get_isolated_runtime_manager()
        self._policy = policy

    def set_policy(self, policy: BrowserPolicy) -> None:
        """Replace the action policy used by future isolated sessions."""
        self._policy = policy

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

    def diagnostics(self) -> dict[str, Any]:
        """Return isolated backend diagnostic metadata without connecting."""
        return {"playwright_available": self.is_available()}

    def diagnose(self) -> BrowserBackendDiagnostic:
        """Return typed isolated backend diagnostics without connecting."""
        runtime_manager_present = self._manager is not None
        playwright_available = self.is_available()
        available = runtime_manager_present and playwright_available
        status: BrowserDiagnosticStatus = (
            "available" if available else "unavailable"
        )
        code = "" if available else "isolated_backend_unavailable"
        message = (
            "Isolated Playwright backend is available."
            if available
            else "Isolated Playwright backend is unavailable."
        )
        hint_key = "" if available else "isolated_backend_unavailable"
        return BrowserBackendDiagnostic(
            backend_id=self.backend_id,
            browser_context="isolated",
            available=available,
            code=code,
            reason="" if available else message,
            status=status,
            message=message,
            hint_key=hint_key,
            message_fallback=message,
            checks=(
                BrowserDiagnosticCheck(
                    name="runtime_manager",
                    status="available"
                    if runtime_manager_present
                    else "unavailable",
                    code="" if runtime_manager_present else code,
                    message=(
                        "Runtime manager is configured."
                        if runtime_manager_present
                        else "Runtime manager is missing."
                    ),
                    hint_key="" if runtime_manager_present else hint_key,
                    metadata={"backend_id": self.backend_id},
                ),
                BrowserDiagnosticCheck(
                    name="playwright",
                    status="available"
                    if playwright_available
                    else "unavailable",
                    code="" if playwright_available else code,
                    message=(
                        "Playwright is available."
                        if playwright_available
                        else "Playwright is unavailable."
                    ),
                    hint_key="" if playwright_available else hint_key,
                    metadata={"backend_id": self.backend_id},
                ),
            ),
            observed_at=_diagnostic_observed_at(),
            features=self.capabilities().features,
            metadata={
                "runtime_manager_present": runtime_manager_present,
                "playwright_available": playwright_available,
            },
        )

    async def connect(
        self,
        session_id: str,
        context: ResolvedBrowserContext,
        *,
        request_scope_key: str = "",
        retention: BrowserRetention = "clean",
        ownership_context: BrowserOwnershipContext | None = None,
    ) -> "IsolatedBrowserSession":
        del request_scope_key, retention, ownership_context
        runtime = await self._manager.connect(session_id, context)
        return IsolatedBrowserSession(
            manager=self._manager,
            runtime=runtime,
            session_id=session_id,
            context=context,
            policy=self._policy,
        )

    async def shutdown(self) -> None:
        """Stop all SDK-owned isolated browser runtimes."""
        await self._manager.stop_all()


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
        policy: BrowserPolicy | None = None,
    ) -> None:
        self._manager = manager
        self.runtime = runtime
        self.session_id = session_id
        self.context = context
        self._policy = policy or _default_policy_for_context(context)

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

    async def create_tab(self, url: str | None = None) -> dict[str, Any]:
        create_tab = getattr(self.runtime, "create_tab", None)
        if callable(create_tab):
            return await create_tab(url)
        return await self.runtime.open_tab(url)

    async def open_tab(self, url: str | None = None) -> dict[str, Any]:
        return await self.runtime.open_tab(url)

    async def open_workspace_tab(self, url: str) -> dict[str, Any]:
        return await self.runtime.open_workspace_tab(url)

    async def list_tabs(self) -> list[dict[str, Any]]:
        return await self.runtime.list_tabs()

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        return await self.runtime.select_tab(tab_id)

    async def snapshot(self, tab_id: str) -> BrowserObservation:
        return coerce_observation(tab_id, await self.runtime.snapshot(tab_id))

    async def screenshot(self, tab_id: str) -> BrowserScreenshot:
        return coerce_screenshot(tab_id, await self.runtime.screenshot(tab_id))

    async def page_info(self, tab_id: str) -> BrowserPageInfo:
        raw = await self.runtime.page_info(tab_id)
        if isinstance(raw, BrowserPageInfo):
            return raw
        if isinstance(raw, dict):
            return BrowserPageInfo(
                tab_id=str(raw.get("tab_id") or raw.get("id") or tab_id),
                url=str(raw.get("url") or ""),
                title=str(raw.get("title") or ""),
                metadata={
                    key: value
                    for key, value in raw.items()
                    if key not in {"tab_id", "id", "url", "title"}
                },
            )
        return BrowserPageInfo(tab_id=str(tab_id))

    async def evaluate(
        self,
        tab_id: str,
        script: str,
        *,
        read_only: bool = False,
    ) -> Any:
        metadata = await self._action_metadata(
            tab_id,
            {
                "script": script,
                "code": script,
                "read_only": read_only,
            },
        )
        evaluation = await evaluate_browser_boundary(
            policy=self._policy,
            session_id=self.session_id,
            context=self.context,
            action="evaluate",
            metadata=metadata,
        )
        raise_if_boundary_denied(
            evaluation,
            action="evaluate",
            tab_id=tab_id,
            action_metadata=metadata,
            context=self.context,
            backend_id=self.backend_id,
        )
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
        metadata = await self._action_metadata(
            tab_id,
            policy_metadata_kwargs(name, kwargs),
        )
        evaluation = await evaluate_browser_boundary(
            policy=self._policy,
            session_id=self.session_id,
            context=self.context,
            action=name,
            metadata=metadata,
        )
        raise_if_boundary_denied(
            evaluation,
            action=name,
            tab_id=tab_id,
            action_metadata=metadata,
            context=self.context,
            backend_id=self.backend_id,
        )
        if tab_id == _BROWSER_SENTINEL_TAB_ID:
            payload = await self.runtime.browser_action(name, **kwargs)
        else:
            payload = await self.runtime.action(tab_id, name, **kwargs)
        return action_result_with_boundary_decision(
            payload,
            name,
            boundary_decision=evaluation.boundary_decision,
        )

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

    async def wait_for(
        self,
        tab_id: str,
        condition: dict[str, Any] | str,
        *,
        timeout_ms: int = 10000,
    ) -> BrowserActionResult:
        return await self.runtime.wait_for(
            tab_id,
            condition,
            timeout_ms=timeout_ms,
        )

    async def navigate(self, tab_id: str, url: str) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "navigate",
            {"url": url},
            lambda: self.runtime.navigate(tab_id, url),
        )

    async def back(self, tab_id: str) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "back",
            {},
            lambda: self.runtime.back(tab_id),
        )

    async def forward(self, tab_id: str) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "forward",
            {},
            lambda: self.runtime.forward(tab_id),
        )

    async def reload(self, tab_id: str) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "reload",
            {},
            lambda: self.runtime.reload(tab_id),
        )

    async def click(
        self,
        tab_id: str,
        target: dict[str, Any],
        *,
        allow_new_context: bool = False,
    ) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "click",
            {"target": target, "allow_new_context": allow_new_context},
            lambda: self.runtime.click(
                tab_id,
                target,
                allow_new_context=allow_new_context,
            ),
        )

    async def fill(
        self,
        tab_id: str,
        target: dict[str, Any],
        text: str,
    ) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "fill",
            {"target": target, "text": text},
            lambda: self.runtime.fill(tab_id, target, text),
        )

    async def press_key(
        self,
        tab_id: str,
        key: str,
    ) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "press_key",
            {"key": key},
            lambda: self.runtime.press_key(tab_id, key),
        )

    async def scroll(
        self,
        tab_id: str,
        *,
        direction: str = "down",
        amount: str | int | None = None,
        target: dict[str, Any] | None = None,
    ) -> BrowserActionResult:
        metadata: dict[str, Any] = {
            "direction": direction,
            "amount": amount,
        }
        if target is not None:
            metadata["target"] = target
        return await self._typed_action(
            tab_id,
            "scroll",
            metadata,
            lambda: self.runtime.scroll(
                tab_id,
                direction=direction,
                amount=amount,
                target=target,
            ),
        )

    async def select_option(
        self,
        tab_id: str,
        target: dict[str, Any],
        value: Any,
    ) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "select_option",
            {"target": target, "value": value},
            lambda: self.runtime.select_option(tab_id, target, value),
        )

    async def hover(
        self,
        tab_id: str,
        target: dict[str, Any],
    ) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "hover",
            {"target": target},
            lambda: self.runtime.hover(tab_id, target),
        )

    async def upload_file(
        self,
        tab_id: str,
        target: dict[str, Any],
        file_path: str | list[str],
    ) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "upload_file",
            {"target": target, "file_path": file_path},
            lambda: self.runtime.upload_file(tab_id, target, file_path),
        )

    async def download_file(
        self,
        tab_id: str,
        target: dict[str, Any] | None = None,
        *,
        timeout_ms: int = 30000,
    ) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "download_file",
            {"target": target, "timeout_ms": timeout_ms},
            lambda: self.runtime.download_file(
                tab_id,
                target,
                timeout_ms=timeout_ms,
            ),
        )

    async def handle_dialog(
        self,
        tab_id: str,
        *,
        accept: bool = True,
        prompt_text: str | None = None,
    ) -> BrowserActionResult:
        return await self._typed_action(
            tab_id,
            "handle_dialog",
            {"accept": accept, "prompt_text": prompt_text},
            lambda: self.runtime.handle_dialog(
                tab_id,
                accept=accept,
                prompt_text=prompt_text,
            ),
        )

    async def _typed_action(
        self,
        tab_id: str,
        name: str,
        kwargs: dict[str, Any],
        operation: Callable[[], Any],
    ) -> BrowserActionResult:
        metadata = await self._action_metadata(
            tab_id,
            policy_metadata_kwargs(name, kwargs),
        )
        evaluation = await evaluate_browser_boundary(
            policy=self._policy,
            session_id=self.session_id,
            context=self.context,
            action=name,
            metadata=metadata,
        )
        raise_if_boundary_denied(
            evaluation,
            action=name,
            tab_id=tab_id,
            action_metadata=metadata,
            context=self.context,
            backend_id=self.backend_id,
        )
        payload = operation()
        if hasattr(payload, "__await__"):
            payload = await payload
        return action_result_with_boundary_decision(
            payload,
            name,
            boundary_decision=evaluation.boundary_decision,
        )

    async def _action_metadata(
        self,
        tab_id: str,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(kwargs)
        if tab_id == _BROWSER_SENTINEL_TAB_ID:
            return metadata

        metadata["tab_id"] = str(tab_id)
        try:
            page = await self.page_info(tab_id)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return metadata

        if page.url and not metadata.get("url"):
            metadata["url"] = page.url
        if page.title and not metadata.get("title"):
            metadata["title"] = page.title

        url = str(metadata.get("url") or "")
        if url and not metadata.get("domain"):
            domain = _domain_from_url(url)
            if domain:
                metadata["domain"] = domain
        return metadata


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
        raise BrowserSDKError(
            "No current Browser tab exists for this request.",
            code="browser_no_current_tab",
            backend_id=BACKEND_ID,
            action="tabs.active",
            metadata={"creation_allowed": False},
        )

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

    async def create_tab(self, url: str | None = None) -> dict[str, Any]:
        return await self.open_tab(url)

    async def open_workspace_tab(self, url: str) -> dict[str, Any]:
        await self._ensure_started()
        target = str(url or "").strip()
        if not target:
            raise BrowserSDKError(
                "A non-empty target URL is required.",
                code="browser_target_url_required",
                backend_id=BACKEND_ID,
                action="tabs.open",
            )
        if self.current_page_id and self.current_page_id in self.pages:
            page_id = self.current_page_id
            page = await self._page(page_id)
        else:
            tabs = await self.list_tabs()
            if tabs:
                page_id = tabs[0]["id"]
                page = await self._page(page_id)
                self.current_page_id = page_id
            else:
                return await self.open_tab(target)
        await page.goto(target)
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

    async def page_info(self, tab_id: str) -> BrowserPageInfo:
        page_id = str(tab_id)
        page = await self._page(page_id)
        return BrowserPageInfo(
            tab_id=page_id,
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

    async def wait_for(
        self,
        tab_id: str,
        condition: dict[str, Any] | str,
        *,
        timeout_ms: int = 10000,
    ) -> BrowserActionResult:
        page_id = str(tab_id)
        page = await self._page(page_id)
        kwargs: dict[str, Any] = (
            dict(condition)
            if isinstance(condition, dict)
            else {"instruction": str(condition)}
        )
        kwargs["max_wait_ms"] = timeout_ms
        await self._wait_for(page, page_id, kwargs)
        return BrowserActionResult(ok=True, message="wait_for")

    async def navigate(self, tab_id: str, url: str) -> BrowserActionResult:
        return await self.action(tab_id, "navigate", url=url)

    async def back(self, tab_id: str) -> BrowserActionResult:
        return await self.action(tab_id, "back")

    async def forward(self, tab_id: str) -> BrowserActionResult:
        return await self.action(tab_id, "forward")

    async def reload(self, tab_id: str) -> BrowserActionResult:
        return await self.action(tab_id, "reload")

    async def click(
        self,
        tab_id: str,
        target: dict[str, Any],
        *,
        allow_new_context: bool = False,
    ) -> BrowserActionResult:
        return await self.action(
            tab_id,
            "click",
            target=target,
            allow_new_context=allow_new_context,
        )

    async def fill(
        self,
        tab_id: str,
        target: dict[str, Any],
        text: str,
    ) -> BrowserActionResult:
        return await self.action(tab_id, "type", target=target, text=text)

    async def press_key(self, tab_id: str, key: str) -> BrowserActionResult:
        return await self.action(tab_id, "press", key=key)

    async def scroll(
        self,
        tab_id: str,
        *,
        direction: str = "down",
        amount: str | int | None = None,
        target: dict[str, Any] | None = None,
    ) -> BrowserActionResult:
        kwargs: dict[str, Any] = {"direction": direction}
        if amount is not None:
            kwargs["amount"] = amount
        if target is not None:
            kwargs["target"] = target
        return await self.action(tab_id, "scroll", **kwargs)

    async def select_option(
        self,
        tab_id: str,
        target: dict[str, Any],
        value: Any,
    ) -> BrowserActionResult:
        return await self.action(tab_id, "select", target=target, value=value)

    async def hover(
        self,
        tab_id: str,
        target: dict[str, Any],
    ) -> BrowserActionResult:
        return await self.action(tab_id, "hover", target=target)

    async def upload_file(
        self,
        tab_id: str,
        target: dict[str, Any],
        file_path: str | list[str],
    ) -> BrowserActionResult:
        return await self.action(
            tab_id,
            "upload",
            target=target,
            file_path=file_path,
        )

    async def download_file(
        self,
        tab_id: str,
        target: dict[str, Any] | None = None,
        *,
        timeout_ms: int = 30000,
    ) -> BrowserActionResult:
        kwargs: dict[str, Any] = {"max_wait_ms": timeout_ms}
        if target is not None:
            kwargs["target"] = target
        return await self.action(tab_id, "download", **kwargs)

    async def handle_dialog(
        self,
        tab_id: str,
        *,
        accept: bool = True,
        prompt_text: str | None = None,
    ) -> BrowserActionResult:
        return await self.action(
            tab_id,
            "dialog",
            accept=accept,
            prompt_text=prompt_text,
        )

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
    # pylint: disable=too-many-statements
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
        if action == "back":
            await page.go_back()
            return BrowserActionResult(ok=True, message="back")
        if action == "forward":
            await page.go_forward()
            return BrowserActionResult(ok=True, message="forward")
        if action == "reload":
            await page.reload()
            return BrowserActionResult(ok=True, message="reload")
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
        if action == "upload":
            return await self._upload(page, page_id, kwargs)
        if action == "download":
            return await self._download(page, page_id, kwargs)
        if action == "dialog":
            return await self._dialog(page, kwargs)
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
        max_wait_ms = int(kwargs.get("max_wait_ms") or 10000)
        locator = self._locator_for_target(page, page_id, kwargs)
        if locator is not None:
            await locator.wait_for(timeout=max_wait_ms)
            return
        instruction = str(kwargs.get("instruction") or "").strip()
        if instruction:
            await page.get_by_text(instruction).first.wait_for(
                timeout=max_wait_ms,
            )
            return
        await page.wait_for_timeout(min(max_wait_ms, 1000))

    async def _upload(
        self,
        page: Any,
        page_id: str,
        kwargs: dict[str, Any],
    ) -> BrowserActionResult:
        file_path = kwargs.get("file_path")
        if file_path in (None, "", []):
            return BrowserActionResult(ok=False, message="file_path required")
        locator = self._locator_for_target(page, page_id, kwargs)
        if locator is None:
            return _capability_missing_result(
                "upload",
                "Upload requires a selector, ref, role, or text target.",
            )
        set_input_files = getattr(locator, "set_input_files", None)
        if not callable(set_input_files):
            return _capability_missing_result(
                "upload",
                "The selected target does not support file input upload.",
            )
        await _maybe_await(set_input_files(file_path))
        return BrowserActionResult(
            ok=True,
            message="upload",
            data={"backend_id": BACKEND_ID},
        )

    async def _download(
        self,
        page: Any,
        page_id: str,
        kwargs: dict[str, Any],
    ) -> BrowserActionResult:
        expect_download = getattr(page, "expect_download", None)
        if not callable(expect_download):
            return _capability_missing_result(
                "download",
                "The isolated runtime cannot observe browser downloads.",
            )
        max_wait_ms = int(kwargs.get("max_wait_ms") or 30000)
        async with expect_download(timeout=max_wait_ms) as download_info:
            locator = self._locator_for_target(page, page_id, kwargs)
            if locator is not None:
                await _maybe_await(locator.click())
            elif _has_coordinates(kwargs):
                await page.mouse.click(float(kwargs["x"]), float(kwargs["y"]))
        download = await _maybe_await(download_info.value)
        path = await _maybe_await(download.path())
        if not path:
            return _capability_missing_result(
                "download",
                "The browser reported a download without a readable path.",
            )
        path_obj = Path(str(path))
        media_type = (
            mimetypes.guess_type(path_obj.name)[0]
            or "application/octet-stream"
        )
        name = str(
            getattr(download, "suggested_filename", "") or path_obj.name,
        )
        artifact = {
            "kind": "download",
            "url": path_obj.resolve().as_uri(),
            "media_type": media_type,
            "name": name,
            "metadata": {
                "path": str(path_obj),
                "source_url": str(getattr(download, "url", "") or ""),
            },
        }
        return BrowserActionResult(
            ok=True,
            message="download",
            data={"backend_id": BACKEND_ID, "artifact": artifact},
        )

    async def _dialog(
        self,
        page: Any,
        kwargs: dict[str, Any],
    ) -> BrowserActionResult:
        once = getattr(page, "once", None)
        if not callable(once):
            return _capability_missing_result(
                "dialog",
                "The isolated runtime cannot register dialog handlers.",
            )
        accept = _bool_arg(kwargs.get("accept", True))
        prompt_text = kwargs.get("prompt_text")

        async def _handle_dialog(dialog: Any) -> None:
            if accept:
                await _maybe_await(dialog.accept(prompt_text=prompt_text))
            else:
                await _maybe_await(dialog.dismiss())

        once("dialog", _handle_dialog)
        return BrowserActionResult(
            ok=True,
            message="dialog handler registered",
            data={
                "backend_id": BACKEND_ID,
                "accept": accept,
                "prompt_text": prompt_text,
            },
        )


_DEFAULT_RUNTIME_MANAGER = IsolatedPlaywrightRuntimeManager()


def get_isolated_runtime_manager() -> IsolatedPlaywrightRuntimeManager:
    """Return the process-global isolated Playwright runtime manager."""
    return _DEFAULT_RUNTIME_MANAGER


def register_isolated_backend_once(
    manager: IsolatedPlaywrightRuntimeManager | None = None,
    policy: BrowserPolicy | None = None,
) -> IsolatedBrowserBackend:
    """Register the isolated Playwright backend if absent."""
    registry = get_default_backend_registry()
    existing = registry.get(BACKEND_ID)
    if isinstance(existing, IsolatedBrowserBackend):
        if policy is not None:
            existing.set_policy(policy)
        return existing
    backend = IsolatedBrowserBackend(manager=manager, policy=policy)
    if existing is None:
        registry.register(backend)
    return backend


def _default_policy_for_context(
    context: ResolvedBrowserContext,
) -> BrowserPolicy:
    if _is_degraded_isolated_context(context):
        from qwenpaw.browser.approval_policy import (
            QwenPawBrowserApprovalPolicy,
        )

        return QwenPawBrowserApprovalPolicy()
    return DefaultBrowserPolicy()


def _is_degraded_isolated_context(context: ResolvedBrowserContext) -> bool:
    return (
        context.requested == "auto"
        and context.selected == "isolated"
        and (
            context.selected_backend_degraded
            or context.fallback_reason == "user_browser_unavailable"
        )
    )


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


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _capability_missing_result(
    action: str,
    message: str,
) -> BrowserActionResult:
    info = classify_browser_error(BrowserErrorCode.CAPABILITY_MISSING)
    return BrowserActionResult(
        ok=False,
        message=message,
        data={
            "backend_id": BACKEND_ID,
            "action": action,
            "error_code": info.code.value,
            "recovery_hint": info.recovery_hint,
        },
    )


def _bool_arg(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _search_url(query: str, engine: str) -> str:
    encoded = quote_plus(query)
    if engine in {"bing", "microsoft"}:
        return f"https://www.bing.com/search?q={encoded}"
    if engine in {"duckduckgo", "ddg"}:
        return f"https://duckduckgo.com/?q={encoded}"
    return f"https://www.google.com/search?q={encoded}"


def _domain_from_url(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _diagnostic_observed_at() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "BACKEND_ID",
    "IsolatedBrowserBackend",
    "IsolatedBrowserSession",
    "IsolatedPlaywrightRuntime",
    "IsolatedPlaywrightRuntimeManager",
    "get_isolated_runtime_manager",
    "register_isolated_backend_once",
]
