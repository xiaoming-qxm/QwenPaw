# -*- coding: utf-8 -*-
"""Tab-local observe-before-act guard for the Browser Control SDK."""

from __future__ import annotations

from .errors import ObservationRequired


class ObserveActGuard:
    """Track whether one Tab has fresh observation evidence."""

    def __init__(self) -> None:
        self._has_fresh_observation = False
        self._last_consumed_action: str | None = None

    def mark_observed(self) -> None:
        """Record that the tab has fresh page evidence."""
        self._has_fresh_observation = True
        self._last_consumed_action = None

    def consume_observation(self, action_name: str | None = None) -> None:
        """Clear fresh page evidence after a mutating action."""
        self._has_fresh_observation = False
        self._last_consumed_action = action_name

    def check_before_action(self, action_name: str) -> None:
        """Raise when a mutating action lacks fresh observation."""
        if not self._has_fresh_observation:
            previous = (
                f" The previous {self._last_consumed_action}() consumed the "
                "fresh observation."
                if self._last_consumed_action
                else ""
            )
            raise ObservationRequired(
                "Must call snapshot() or screenshot() before "
                f"{action_name}(). Observe the page first to ensure "
                "correct targeting."
                f"{previous} Each observation supports only one mutating "
                "browser action. Put the next state-changing action in a "
                "new python_repl call after observing; do not batch "
                "click/type/select/delete/confirm sequences in one cell.",
            )
        self.consume_observation(action_name)
