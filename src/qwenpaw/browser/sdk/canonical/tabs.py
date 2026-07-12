# -*- coding: utf-8 -*-
"""Canonical Tab, BrowserTabs, and TabActions public surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..governance.errors import BrowserSDKGap
from ..runtime.resources import ResourceStore, TrustedOutputSource
from ..runtime.result_delivery import RequiredBlock, record_browser_result
from .contracts import (
    EvidenceRef,
    ScreenshotResult,
    VisualContextRef,
    _RUNTIME_VALUE_ISSUER,
    _issue_opaque_value,
    issue_operation_id,
)


Dispatch = Callable[..., Awaitable[Any]]


@dataclass(slots=True)
class TabActions:
    """S0 action surface; later stages activate individual capabilities."""

    dispatch: Dispatch | None = field(default=None, repr=False)

    async def click(self, *_args: Any, **_kwargs: Any) -> None:
        """Fail before backend dispatch until target/action stages activate."""
        raise _capability_blocked("tab.actions.click")


@dataclass(slots=True)
class Tab:
    """Canonical tab shell owned by this module."""

    id: str
    actions: TabActions = field(default_factory=TabActions)
    _session: Any = field(default=None, repr=False)
    _resources: ResourceStore | None = field(default=None, repr=False)

    async def screenshot(self) -> ScreenshotResult:
        """Capture and ingest a complete image before publishing success."""
        if self._session is None or self._resources is None:
            raise _capability_blocked("tab.screenshot")
        captured = await self._session.screenshot(self.id)
        location = str(getattr(captured, "path", "") or "")
        media_type = str(getattr(captured, "media_type", "image/png"))
        if not location:
            raise BrowserSDKGap(
                "Screenshot producer returned no complete output source.",
                action="tab.screenshot",
            )
        handle = await self._resources.ingest_output(
            TrustedOutputSource.from_file(Path(location)),
            media_type=media_type,
            name=Path(location).name,
            required_delivery=True,
        )
        evidence = _issue_opaque_value(
            EvidenceRef,
            _RUNTIME_VALUE_ISSUER,
            id=f"evidence-{handle.id}",
        )
        visual_context = _issue_opaque_value(
            VisualContextRef,
            _RUNTIME_VALUE_ISSUER,
            id=f"visual-{handle.id}",
        )
        assert isinstance(evidence, EvidenceRef)
        assert isinstance(visual_context, VisualContextRef)
        result = ScreenshotResult(
            operation_id=issue_operation_id(),
            status="SUCCEEDED",
            retry="NONE",
            evidence=evidence,
            image=handle,
            visual_context=visual_context,
        )
        record_browser_result(
            result,
            required_blocks=(
                RequiredBlock(
                    kind="image",
                    resource_id=str(handle.id),
                    media_type=media_type,
                    payload=handle,
                ),
            ),
        )
        return result


@dataclass(slots=True)
class BrowserTabs:
    """Canonical tab collection shell."""

    _session: Any = field(default=None, repr=False)
    _resources: ResourceStore | None = field(default=None, repr=False)

    async def active(self) -> Tab:
        raise _capability_blocked("browser.tabs.active")


def _capability_blocked(capability: str) -> BrowserSDKGap:
    return BrowserSDKGap(
        f"Canonical capability is not active in S0: {capability}",
        action=capability,
        metadata={"capability": capability, "backend_dispatch_count": 0},
    )


__all__ = ["BrowserTabs", "Tab", "TabActions"]
