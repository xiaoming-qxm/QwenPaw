# -*- coding: utf-8 -*-
"""Typed browser control state machines."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ControlSessionState(str, Enum):
    """Lifecycle states for a Browser Control session."""

    IDLE = "idle"
    CONNECTING = "connecting"
    ACTIVE = "active"
    RELEASING = "releasing"
    STOPPED = "stopped"
    ERROR = "error"


class TabState(str, Enum):
    """Lifecycle states for a controlled browser tab."""

    UNKNOWN = "unknown"
    CLAIMED = "claimed"
    ATTACHED = "attached"
    OBSERVED = "observed"
    MUTATING = "mutating"
    RELEASED = "released"
    CLOSED = "closed"
    ERROR = "error"


@dataclass(slots=True)
class BrowserState:
    """Explicit state container shared by browser backends."""

    workspace_id: str
    workspace_dir: str = ""
    session_state: ControlSessionState = ControlSessionState.IDLE
    tab_state: TabState = TabState.UNKNOWN
    current_page_id: str | None = None
    pages: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def transition_session(
        self,
        next_state: ControlSessionState,
    ) -> ControlSessionState:
        """Move the session state and return the new value."""
        self.session_state = next_state
        return self.session_state

    def transition_tab(self, next_state: TabState) -> TabState:
        """Move the tab state and return the new value."""
        self.tab_state = next_state
        return self.tab_state
