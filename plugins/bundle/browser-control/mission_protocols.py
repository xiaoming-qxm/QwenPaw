# -*- coding: utf-8 -*-
"""Mission loop strategy protocols -- domain-agnostic interfaces."""

from __future__ import annotations

from typing import Any, Protocol


class GoalChecker(Protocol):
    """Check whether mission objectives are met."""

    def is_complete(self) -> bool:
        """Return whether all mission goals are complete."""

    def has_stories(self) -> bool:
        """Return whether the mission has any goal stories."""

    def incomplete_stories(self) -> list[dict[str, Any]]:
        """Return goal stories that still need work."""

    def read_snapshot(self) -> str:
        """Return current goal file text for diff comparison."""


class ContinuationBuilder(Protocol):
    """Build the prompt for the next iteration."""

    def build(
        self,
        iteration: int,
        max_iterations: int,
        incomplete_stories: list[dict[str, Any]],
        detector: Any,
    ) -> str:
        """Return continuation prompt text."""


class BlockerDetector(Protocol):
    """Detect unrecoverable blockers in agent output."""

    def is_blocked(self, message: Any) -> bool:
        """Return whether the agent reported an unrecoverable blocker."""


__all__ = ["BlockerDetector", "ContinuationBuilder", "GoalChecker"]
