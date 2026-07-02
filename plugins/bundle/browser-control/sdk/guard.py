# -*- coding: utf-8 -*-
"""Tab-local observe-before-act guard for the Browser Control SDK."""

from __future__ import annotations

from .errors import ObservationRequired


class ObserveActGuard:
    """Track whether one Tab has fresh observation evidence."""

    def __init__(self) -> None:
        self._has_fresh_observation = False

    def mark_observed(self) -> None:
        """Record that the tab has fresh page evidence."""
        self._has_fresh_observation = True

    def consume_observation(self) -> None:
        """Clear fresh page evidence after a mutating action."""
        self._has_fresh_observation = False

    def check_before_action(self, action_name: str) -> None:
        """Raise when a mutating action lacks fresh observation."""
        if not self._has_fresh_observation:
            raise ObservationRequired(
                "Must call snapshot() or screenshot() before "
                f"{action_name}(). Observe the page first to ensure "
                "correct targeting.",
            )
        self.consume_observation()
