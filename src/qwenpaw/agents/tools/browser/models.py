# -*- coding: utf-8 -*-
"""Typed value models shared by browser tool backends."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ElementTarget:
    """A browser element target resolved from structured or visual context."""

    ref: str = ""
    selector: str = ""
    text: str = ""
    x: float | None = None
    y: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


@dataclass(slots=True)
class ActionResult:
    """Normalized result for a browser action."""

    ok: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    next_action: str | None = None
    navigation_occurred: bool = False
    needs_observation: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


@dataclass(slots=True)
class SnapshotResult:
    """Structured snapshot evidence returned by a browser backend."""

    snapshot: str
    refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    url: str = ""
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


@dataclass(slots=True)
class SessionContext:
    """Request/session identity used by browser-control backends."""

    workspace_id: str
    workspace_dir: str = ""
    holder_id: str = ""
    session_id: str = ""
    root_session_id: str = ""
    user_initiated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)
