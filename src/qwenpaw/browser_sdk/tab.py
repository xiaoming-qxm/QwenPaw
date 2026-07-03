# -*- coding: utf-8 -*-
"""Tab facade for the unified Browser SDK."""
# pylint: disable=redefined-builtin

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .actions import TabActions
from .errors import BrowserObservationRequired
from .extract import extract_from_tab
from .observation import coerce_observation, coerce_screenshot
from .types import (
    BrowserActionResult,
    BrowserExtractionResult,
    BrowserObservation,
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
    url: str = ""
    title: str = ""
    _observation_required: bool = False
    actions: TabActions = field(init=False)

    def __post_init__(self) -> None:
        self._session = self.session
        self.actions = TabActions(self)

    @property
    def tab_id(self) -> str:
        """Compatibility alias for tab id."""
        return self.id

    async def snapshot(self) -> BrowserObservation:
        """Observe the tab and satisfy the fresh-observation guard."""
        result = coerce_observation(
            self.id,
            await self._session.snapshot(self.id),
        )
        self._sync_metadata(result.url, result.title)
        self._mark_observed()
        return result

    async def screenshot(self) -> BrowserScreenshot:
        """Capture a visual observation and satisfy the guard."""
        result = coerce_screenshot(
            self.id,
            await self._session.screenshot(self.id),
        )
        self._sync_metadata(result.url, result.title)
        self._mark_observed()
        return result

    async def evaluate(
        self,
        script: str,
        *,
        read_only: bool = False,
    ) -> Any:
        """Evaluate JavaScript in the tab.

        `read_only=True` intentionally does not satisfy the observation
        guard. Mutating evaluation follows the same guard as actions.
        """
        if not read_only:
            self._ensure_can_mutate("evaluate")
        result = await self._session.evaluate(
            self.id,
            script,
            read_only=read_only,
        )
        if not read_only:
            self._mark_mutated()
        return result

    async def close(self) -> BrowserActionResult:
        """Close or release the tab through the backend."""
        close_tab = getattr(self._session, "close_tab", None)
        if callable(close_tab):
            result = await close_tab(self.id)
        else:
            result = {"ok": True, "message": "closed"}
        return _coerce_action_result(result)

    async def extract(
        self,
        instruction: str,
        format: ExtractionFormat = "text",
    ) -> BrowserExtractionResult:
        """Extract lightweight text or JSON from the tab."""
        return await extract_from_tab(self, instruction, format=format)

    async def _call_action(self, name: str, **kwargs: Any) -> Any:
        return await self._session.action(self.id, name, **kwargs)

    def _ensure_can_mutate(self, action_name: str) -> None:
        if not self._observation_required:
            return
        raise BrowserObservationRequired(
            "Must call tab.snapshot() or tab.screenshot() before "
            f"{action_name}(). Browser SDK requires a fresh observation "
            "between page mutations.",
            action=action_name,
            backend_id=self.context.backend_id,
        )

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


__all__ = ["Tab", "tab_from_backend"]
