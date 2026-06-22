# -*- coding: utf-8 -*-
"""Observe-before-act guard for browser control loops."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


class ObservationRequired(RuntimeError):
    """Raised when a mutating browser action lacks fresh observation."""


@dataclass(slots=True)
class ObserveActGuard:
    """Track whether each page has fresh evidence before mutating actions."""

    observation_actions: frozenset[str] = frozenset(
        {"snapshot", "screenshot", "tabs"},
    )
    action_names: frozenset[str] = frozenset(
        {
            "click",
            "type",
            "press_key",
            "navigate",
            "open",
            "wait_for",
        },
    )
    _observed_pages: set[str] = field(default_factory=set)

    def mark_observed(
        self,
        page_id: str = "",
        source: str = "snapshot",
    ) -> None:
        """Record fresh page evidence from an observation action."""
        if source and source not in self.observation_actions:
            return
        self._observed_pages.add(self._key(page_id))

    def mark_observed_many(
        self,
        page_ids: Iterable[str],
        source: str = "snapshot",
    ) -> None:
        """Record fresh evidence for several pages."""
        for page_id in page_ids:
            self.mark_observed(page_id=page_id, source=source)

    def clear(self, page_id: str = "") -> None:
        """Clear fresh evidence for a page."""
        self._observed_pages.discard(self._key(page_id))

    def check_before_action(self, action: str, page_id: str = "") -> None:
        """Raise if *action* needs observation and none is available."""
        normalized = str(action or "").strip().lower()
        if normalized not in self.action_names:
            return
        key = self._key(page_id)
        if key not in self._observed_pages:
            raise ObservationRequired(
                "Browser action requires a fresh snapshot or screenshot "
                f"before calling action={normalized!r}.",
            )
        self._observed_pages.discard(key)

    @staticmethod
    def _key(page_id: str = "") -> str:
        return str(page_id or "__default__")
