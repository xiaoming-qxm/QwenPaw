# -*- coding: utf-8 -*-
"""Backend protocols for the unified Browser SDK."""
# pylint: disable=redefined-builtin,too-many-public-methods

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..condition_evaluator import ConditionProbe
from ..primitives.types import (
    BrowserActionResult,
    BrowserBackendCapabilities,
    BrowserExtractionResult,
    BrowserObservation,
    BrowserOwnershipContext,
    BrowserPageInfo,
    BrowserRetention,
    BrowserScreenshot,
    ResolvedBrowserContext,
)


@dataclass(frozen=True, slots=True)
class BackendProfile:
    """Exact build-reviewed backend variants and immutable fingerprints."""

    variants: dict[str, str]
    hard_limits: dict[str, int]
    contract_fingerprint: str
    profile_fingerprint: str
    build_fingerprint: str
    extension_fingerprint: str

    def __post_init__(self) -> None:
        if any(
            status not in {"READY", "BLOCKED"}
            for status in self.variants.values()
        ):
            raise ValueError("backend variant status must be READY or BLOCKED")
        if not all(
            (
                self.contract_fingerprint,
                self.profile_fingerprint,
                self.build_fingerprint,
                self.extension_fingerprint,
            ),
        ):
            raise ValueError("backend fingerprints are required")


@runtime_checkable
class BrowserSession(Protocol):
    """Runtime session returned by a browser backend."""

    backend_id: str

    async def close(self) -> None:
        """Release backend-owned resources for the session."""

    async def open_workspace_tab(self, url: str) -> dict[str, Any]:
        """Reuse or create the request workspace tab and navigate it."""

    async def create_tab(self, url: str | None = None) -> dict[str, Any]:
        """Create a new backend tab."""

    async def active_tab(self) -> dict[str, Any]:
        """Return the current backend tab."""

    async def list_tabs(self) -> list[dict[str, Any]]:
        """List backend tabs."""

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        """Select a backend tab."""

    async def close_tab(self, tab_id: str) -> BrowserActionResult:
        """Close a backend tab."""

    async def snapshot(self, tab_id: str) -> BrowserObservation:
        """Return a textual or semantic tab observation."""

    async def screenshot(self, tab_id: str) -> BrowserScreenshot:
        """Return a visual tab observation."""

    async def page_info(self, tab_id: str) -> BrowserPageInfo:
        """Return read-only tab metadata."""

    async def extract(
        self,
        tab_id: str,
        instruction: str,
        *,
        format: str = "text",
    ) -> BrowserExtractionResult | str:
        """Extract data from a tab."""

    def condition_probe(self, tab_id: str) -> ConditionProbe:
        """Return the sole private raw-fact probe for a receiver tab."""

    async def navigate(self, tab_id: str, url: str) -> BrowserActionResult:
        """Navigate a tab to a URL."""

    async def back(self, tab_id: str) -> BrowserActionResult:
        """Navigate a tab backward."""

    async def forward(self, tab_id: str) -> BrowserActionResult:
        """Navigate a tab forward."""

    async def reload(self, tab_id: str) -> BrowserActionResult:
        """Reload a tab."""

    async def click(
        self,
        tab_id: str,
        target: dict[str, Any],
        *,
        allow_new_context: bool = False,
    ) -> BrowserActionResult:
        """Click a resolved target."""

    async def fill(
        self,
        tab_id: str,
        target: dict[str, Any],
        text: str,
    ) -> BrowserActionResult:
        """Fill a resolved target."""

    async def press_key(
        self,
        tab_id: str,
        key: str,
    ) -> BrowserActionResult:
        """Press a page-level key."""

    async def scroll(
        self,
        tab_id: str,
        *,
        direction: str = "down",
        amount: str | int | None = None,
        target: dict[str, Any] | None = None,
    ) -> BrowserActionResult:
        """Scroll the page or a target."""

    async def select_option(
        self,
        tab_id: str,
        target: dict[str, Any],
        value: Any,
    ) -> BrowserActionResult:
        """Select a target option."""

    async def hover(
        self,
        tab_id: str,
        target: dict[str, Any],
    ) -> BrowserActionResult:
        """Hover over a resolved target."""

    async def upload_file(
        self,
        tab_id: str,
        target: dict[str, Any],
        file_path: str | list[str],
    ) -> BrowserActionResult:
        """Upload files through a target."""

    async def download_file(
        self,
        tab_id: str,
        target: dict[str, Any] | None = None,
        *,
        timeout_ms: int = 30000,
    ) -> BrowserActionResult:
        """Download a file from a tab."""

    async def handle_dialog(
        self,
        tab_id: str,
        *,
        accept: bool = True,
        prompt_text: str | None = None,
    ) -> BrowserActionResult:
        """Handle the next browser dialog."""


@runtime_checkable
class BrowserBackend(Protocol):
    """Protocol implemented by concrete browser execution backends."""

    backend_id: str

    async def connect(
        self,
        session_id: str,
        context: ResolvedBrowserContext,
        *,
        request_scope_key: str = "",
        retention: BrowserRetention = "clean",
        ownership_context: BrowserOwnershipContext | None = None,
    ) -> BrowserSession | Any:
        """Create or attach a browser session."""

    def is_available(self) -> bool:
        """Return whether this backend can be selected now."""

    def capabilities(self) -> BrowserBackendCapabilities:
        """Return static backend capabilities."""


__all__ = ["BackendProfile", "BrowserBackend", "BrowserSession"]
