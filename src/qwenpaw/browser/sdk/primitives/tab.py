# -*- coding: utf-8 -*-
"""Tab facade for the unified Browser SDK."""
# pylint: disable=redefined-builtin

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from ..actions.tab_actions import TabActions
from ..contract_runtime import BrowserContractRuntime
from ..contracts import BrowserAPIContract
from ..contracts import browser_api
from ..governance.error_codes import classify_browser_error
from ..governance.errors import BrowserObservationRequired
from ..runtime.kernel import record_browser_artifact
from ..telemetry.trace import record_browser_trace_event
from .extract import extract_from_tab
from .observation import coerce_observation, coerce_screenshot
from .trace_metadata import with_boundary_decision
from .trace_metadata import with_exception_metadata
from .trace_metadata import with_route_metadata
from .types import (
    BrowserActionResult,
    BrowserArtifact,
    BrowserExtractionResult,
    BrowserObservation,
    BrowserPageInfo,
    BrowserScreenshot,
    ExtractionFormat,
    ResolvedBrowserContext,
)


@dataclass
class Tab:
    """One browser tab selected through a Browser SDK backend."""

    id: str
    session: Any
    context: ResolvedBrowserContext
    session_id: str = ""
    url: str = ""
    title: str = ""
    _observation_required: bool = False
    _last_observation: BrowserObservation | None = field(
        default=None,
        init=False,
        repr=False,
    )
    actions: TabActions = field(init=False)

    def __post_init__(self) -> None:
        self._session = self.session
        self.actions = TabActions(self)

    @property
    def tab_id(self) -> str:
        """Compatibility alias for tab id."""
        return self.id

    @browser_api(
        public_name="tab.snapshot",
        kind="primitive",
        visibility="default",
        mutates=False,
        requires_observation=False,
        satisfies_observation=True,
        invalidates_observation=False,
        backend_op="snapshot",
    )
    async def snapshot(self) -> BrowserObservation:
        """Observe the tab and satisfy the fresh-observation guard."""
        return await BrowserContractRuntime().execute(
            _browser_api_contract(type(self).snapshot),
            self._snapshot_impl,
            owner=self,
        )

    async def _snapshot_impl(self) -> BrowserObservation:
        """Call the backend snapshot primitive."""
        api_id = _browser_api_contract(type(self).snapshot).api_id
        started = perf_counter()
        try:
            result = coerce_observation(
                self.id,
                await self._session.snapshot(self.id),
            )
            self._last_observation = result
            self._sync_metadata(result.url, result.title)
        except Exception as exc:
            self._trace(
                phase="observe",
                action="snapshot",
                api_id=api_id,
                status="error",
                duration_ms=_duration_ms(started),
                error_code=_error_code(exc),
                metadata={"error_type": type(exc).__name__},
            )
            raise
        self._trace(
            phase="observe",
            action="snapshot",
            api_id=api_id,
            status="ok",
            duration_ms=_duration_ms(started),
            url=result.url,
            metadata={
                "observation_source": _observation_source(
                    result.metadata,
                    "snapshot",
                ),
                "degraded": result.degraded,
            },
        )
        return result

    @browser_api(
        public_name="tab.screenshot",
        kind="primitive",
        visibility="default",
        mutates=False,
        requires_observation=False,
        satisfies_observation=True,
        invalidates_observation=False,
        backend_op="screenshot",
    )
    async def screenshot(self) -> BrowserScreenshot:
        """Capture a visual observation and satisfy the guard."""
        return await BrowserContractRuntime().execute(
            _browser_api_contract(type(self).screenshot),
            self._screenshot_impl,
            owner=self,
        )

    async def _screenshot_impl(self) -> BrowserScreenshot:
        """Call the backend screenshot primitive."""
        started = perf_counter()
        try:
            result = coerce_screenshot(
                self.id,
                await self._session.screenshot(self.id),
            )
            self._sync_metadata(result.url, result.title)
            if result.path:
                record_browser_artifact(_artifact_from_screenshot(result))
        except Exception as exc:
            self._trace(
                phase="screenshot",
                action="screenshot",
                status="error",
                duration_ms=_duration_ms(started),
                error_code=_error_code(exc),
                metadata={"error_type": type(exc).__name__},
            )
            raise
        self._trace(
            phase="screenshot",
            action="screenshot",
            status="ok",
            duration_ms=_duration_ms(started),
            url=result.url,
            metadata={
                "observation_source": _observation_source(
                    result.metadata,
                    "screenshot",
                ),
            },
        )
        return result

    @browser_api(
        public_name="tab.page_info",
        kind="primitive",
        mutates=False,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=False,
        backend_op="page_info",
    )
    async def page_info(self) -> BrowserPageInfo:
        """Read tab metadata without satisfying the observation guard."""
        page_info = getattr(self._session, "page_info", None)
        if callable(page_info):
            raw = await page_info(self.id)
            info = _coerce_page_info(self.id, raw)
        else:
            info = BrowserPageInfo(
                tab_id=self.id,
                url=self.url,
                title=self.title,
            )
        self._sync_metadata(info.url, info.title)
        return info

    async def evaluate(
        self,
        script: str,
        *,
        read_only: bool = True,
    ) -> Any:
        """Evaluate JavaScript in the tab.

        `read_only=True` intentionally does not satisfy the observation
        guard. Mutating evaluation follows the same guard as actions.
        """
        if not read_only:
            self._ensure_can_mutate("evaluate")
        started = perf_counter()
        phase = "read" if read_only else "action"
        try:
            result = await self._session.evaluate(
                self.id,
                script,
                read_only=read_only,
            )
        except Exception as exc:
            self._trace(
                phase=phase,
                action="evaluate",
                status="error",
                duration_ms=_duration_ms(started),
                error_code=_error_code(exc),
                metadata=with_exception_metadata(
                    {
                        "read_only": read_only,
                        "error_type": type(exc).__name__,
                    },
                    exc,
                ),
            )
            raise
        if not read_only:
            self._mark_mutated()
        self._trace(
            phase=phase,
            action="evaluate",
            status="ok",
            duration_ms=_duration_ms(started),
            metadata={
                "read_only": read_only,
                "needs_observation": not read_only,
            },
        )
        return result

    @browser_api(
        public_name="tab.wait_for",
        kind="primitive",
        mutates=False,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=False,
        backend_op="wait_for",
    )
    async def wait_for(
        self,
        instruction: str,
        max_wait_ms: int = 10000,
    ) -> BrowserActionResult:
        """Wait until the page matches a natural-language condition."""
        return await self.actions.wait_for(
            instruction,
            max_wait_ms=max_wait_ms,
        )

    @browser_api(
        public_name="tab.close",
        kind="primitive",
        mutates=True,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=False,
        backend_op="close_tab",
    )
    async def close(self) -> BrowserActionResult:
        """Close or release the tab through the backend."""
        close_tab = getattr(self._session, "close_tab", None)
        if callable(close_tab):
            result = await close_tab(self.id)
        else:
            result = {"ok": True, "message": "closed"}
        return _coerce_action_result(result)

    @browser_api(
        public_name="tab.extract",
        kind="primitive",
        mutates=False,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=False,
        backend_op="extract",
    )
    async def extract(
        self,
        instruction: str,
        format: ExtractionFormat = "text",
    ) -> BrowserExtractionResult:
        """Extract lightweight text or JSON from the tab."""
        started = perf_counter()
        try:
            result = await extract_from_tab(self, instruction, format=format)
        except Exception as exc:
            self._trace(
                phase="extraction",
                action="extract",
                status="error",
                duration_ms=_duration_ms(started),
                error_code=_error_code(exc),
                metadata={
                    "error_type": type(exc).__name__,
                    "format": format,
                },
            )
            raise
        self._trace(
            phase="extraction",
            action="extract",
            status="ok" if result.ok else "error",
            duration_ms=_duration_ms(started),
            error_code=result.error,
            metadata={"format": format},
        )
        return result

    async def _call_action(
        self,
        name: str,
        *,
        api_id: str = "",
        **kwargs: Any,
    ) -> Any:
        started = perf_counter()
        try:
            result = await self._session.action(self.id, name, **kwargs)
        except Exception as exc:
            self._trace(
                phase="action",
                action=name,
                api_id=api_id,
                status="error",
                duration_ms=_duration_ms(started),
                error_code=_error_code(exc),
                metadata=with_exception_metadata(
                    {
                        "kwargs": kwargs,
                        "error_type": type(exc).__name__,
                    },
                    exc,
                ),
            )
            raise
        action_result = _coerce_action_result(result)
        trace_metadata = {
            "kwargs": kwargs,
            "needs_observation": action_result.needs_observation,
            "post_mutation_observation_required": (
                action_result.needs_observation
            ),
        }
        trace_metadata = with_boundary_decision(
            trace_metadata,
            action_result.data.get("boundary_decision"),
        )
        self._trace(
            phase="action",
            action=name,
            api_id=api_id,
            status=_result_status(result),
            duration_ms=_duration_ms(started),
            metadata=trace_metadata,
        )
        return result

    def _trace(
        self,
        *,
        phase: str,
        action: str,
        status: str,
        duration_ms: float,
        api_id: str = "",
        url: str = "",
        error_code: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        effective_url = url or self.url
        record_browser_trace_event(
            session_id=self.session_id,
            phase=phase,
            backend_id=self.context.backend_id,
            requested_context=self.context.requested,
            selected_context=self.context.selected,
            api_id=api_id,
            action=action,
            tab_id=self.id,
            url=effective_url,
            domain=_domain_from_url(effective_url),
            status=status,
            duration_ms=duration_ms,
            error_code=error_code,
            metadata=with_route_metadata(metadata, self.context),
        )

    def _ensure_can_mutate(self, action_name: str) -> None:
        if not self._observation_required:
            return
        exc = BrowserObservationRequired(
            "Must call tab.snapshot() or tab.screenshot() before "
            f"{action_name}(). Browser SDK requires a fresh observation "
            "between page mutations.",
            action=action_name,
            backend_id=self.context.backend_id,
        )
        self._trace(
            phase="action",
            action=action_name,
            status="error",
            duration_ms=0.0,
            error_code=_error_code(exc),
            metadata={
                "error_type": type(exc).__name__,
                "needs_observation": True,
            },
        )
        raise exc

    def _mark_mutated(self) -> None:
        self._observation_required = True

    def _mark_observed(self) -> None:
        self._observation_required = False

    def _sync_metadata(self, url: str = "", title: str = "") -> None:
        if url:
            self.url = url
        if title:
            self.title = title


def tab_from_backend(
    raw: Any,
    *,
    session: Any,
    context: ResolvedBrowserContext,
    session_id: str = "",
    observation_required: bool = False,
) -> Tab:
    """Create a Tab facade from backend tab metadata."""
    if isinstance(raw, Tab):
        return raw
    if isinstance(raw, dict):
        tab_id = str(raw.get("id") or raw.get("tab_id") or raw.get("tabId"))
        url = str(raw.get("url") or "")
        title = str(raw.get("title") or "")
    else:
        tab_id = str(
            getattr(raw, "id", None)
            or getattr(raw, "tab_id", None)
            or getattr(raw, "tabId", None)
            or raw,
        )
        url = str(getattr(raw, "url", "") or "")
        title = str(getattr(raw, "title", "") or "")
    return Tab(
        id=tab_id,
        session=session,
        context=context,
        session_id=session_id,
        url=url,
        title=title,
        _observation_required=observation_required,
    )


def _coerce_action_result(value: Any) -> BrowserActionResult:
    if isinstance(value, BrowserActionResult):
        return value
    if isinstance(value, dict):
        return BrowserActionResult(
            ok=bool(value.get("ok", True)),
            message=str(value.get("message") or value.get("error") or ""),
            needs_observation=bool(value.get("needs_observation", True)),
            data=dict(value.get("data") or {}),
        )
    return BrowserActionResult(ok=True, message=str(value or ""))


def _coerce_page_info(tab_id: str, value: Any) -> BrowserPageInfo:
    if isinstance(value, BrowserPageInfo):
        return value
    if isinstance(value, dict):
        metadata = {
            key: item
            for key, item in value.items()
            if key not in {"id", "tab_id", "tabId", "url", "title"}
        }
        return BrowserPageInfo(
            tab_id=str(
                value.get("tab_id")
                or value.get("tabId")
                or value.get("id")
                or tab_id,
            ),
            url=str(value.get("url") or ""),
            title=str(value.get("title") or ""),
            metadata=metadata,
        )
    return BrowserPageInfo(
        tab_id=str(
            getattr(value, "tab_id", None)
            or getattr(value, "id", None)
            or tab_id,
        ),
        url=str(getattr(value, "url", "") or ""),
        title=str(getattr(value, "title", "") or ""),
    )


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _browser_api_contract(func: Any) -> BrowserAPIContract:
    contract = getattr(func, "__browser_api_contract__", None)
    if not isinstance(contract, BrowserAPIContract):
        raise TypeError(f"Missing Browser API contract for {func!r}")
    return contract


def _error_code(exc: Exception) -> str:
    return classify_browser_error(exc).code.value


def _result_status(result: Any) -> str:
    ok = getattr(result, "ok", None)
    if ok is not None:
        return "ok" if bool(ok) else "error"
    if isinstance(result, dict) and result.get("ok") is False:
        return "error"
    return "ok"


def _domain_from_url(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _observation_source(metadata: dict[str, Any], fallback: str) -> str:
    source = str(metadata.get("observation_source") or "").strip()
    return source or fallback


def _artifact_from_screenshot(
    screenshot: BrowserScreenshot,
) -> BrowserArtifact:
    raw_path = str(screenshot.path or "").strip()
    try:
        url = Path(raw_path).expanduser().resolve().as_uri()
    except (OSError, ValueError):
        url = raw_path
    return BrowserArtifact(
        kind="screenshot",
        url=url,
        media_type=screenshot.media_type,
        name=Path(raw_path).name or "screenshot",
        metadata={
            "tab_id": screenshot.tab_id,
            "path": raw_path,
            **screenshot.metadata,
        },
    )


__all__ = ["Tab", "tab_from_backend"]
