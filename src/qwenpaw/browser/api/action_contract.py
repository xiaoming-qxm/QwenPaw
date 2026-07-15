# -*- coding: utf-8 -*-
"""Internal Canonical action metadata passed to trusted preflight."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BrowserTargetContract:
    """Target requirements derived from the Canonical API catalog."""

    required: bool
    methods: tuple[str, ...]
    snapshot_bound: bool

    def as_dict(self) -> dict[str, Any]:
        """Return a stable JSON-ready representation."""
        return {
            "required": self.required,
            "methods": list(self.methods),
            "snapshot_bound": self.snapshot_bound,
        }


@dataclass(frozen=True)
class BrowserAPIContract:
    """Trusted metadata for one Canonical Browser action."""

    api_id: str
    kind: str
    visibility: str
    mutates: bool
    requires_observation: bool
    satisfies_observation: bool
    invalidates_observation: bool
    public_name: str | None = None
    target: BrowserTargetContract | None = None
    backend_op: str | None = None
    callable_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return a stable JSON-ready representation."""
        payload: dict[str, Any] = {
            "api_id": self.api_id,
            "kind": self.kind,
            "visibility": self.visibility,
            "mutates": self.mutates,
            "requires_observation": self.requires_observation,
            "satisfies_observation": self.satisfies_observation,
            "invalidates_observation": self.invalidates_observation,
            "callable_path": self.callable_path,
        }
        if self.public_name is not None:
            payload["public_name"] = self.public_name
        if self.target is not None:
            payload["target"] = self.target.as_dict()
        if self.backend_op is not None:
            payload["backend_op"] = self.backend_op
        return payload


__all__ = ["BrowserAPIContract", "BrowserTargetContract"]
