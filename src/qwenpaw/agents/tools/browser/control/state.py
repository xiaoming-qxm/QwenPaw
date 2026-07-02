# -*- coding: utf-8 -*-
"""Typed state container for Browser Control runtime data."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, ClassVar


_MISSING = object()


@dataclass
class ControlState(dict[str, Any]):
    """Browser Control state with legacy dict compatibility."""

    workspace_id: str = "default"
    current_page_id: str | None = None
    tabs: dict[str, dict[str, Any]] = field(default_factory=dict)
    sessions: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_observations: dict[str, Any] = field(default_factory=dict)
    click_effects: dict[str, Any] = field(default_factory=dict)
    snapshot_hashes: dict[str, str] = field(default_factory=dict)
    network_enabled_tabs: set[int] = field(default_factory=set)
    page_aliases: dict[str, int] = field(default_factory=dict)
    approved_domains: set[str] = field(default_factory=set)
    pending_action_transition: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    _KEY_TO_FIELD: ClassVar[dict[str, str]] = {
        "workspace_id": "workspace_id",
        "current_page_id": "current_page_id",
        "control_tabs": "tabs",
        "control_sessions": "sessions",
        "refs": "refs",
        "control_pending_observations": "pending_observations",
        "control_click_effects": "click_effects",
        "control_snapshot_hashes": "snapshot_hashes",
        "control_network_enabled_tabs": "network_enabled_tabs",
        "control_page_aliases": "page_aliases",
        "control_approved_domains": "approved_domains",
        "control_pending_action_transition": "pending_action_transition",
    }

    def __post_init__(self) -> None:
        """Keep the underlying dict shape useful for dict-native consumers."""
        self._refresh_mapping()

    def _refresh_mapping(self) -> None:
        super().clear()
        super().update(self.to_dict())

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | "ControlState",
    ) -> "ControlState":
        """Create typed state from the existing Browser Control dict shape."""
        if isinstance(data, ControlState):
            return data
        known = cls._KEY_TO_FIELD
        kwargs: dict[str, Any] = {}
        for key, field_name in known.items():
            if key not in data:
                continue
            value = data[key]
            if field_name == "network_enabled_tabs":
                value = set(value or set())
            elif field_name == "approved_domains":
                value = {str(domain) for domain in value or set()}
            kwargs[field_name] = value
        kwargs["extra"] = {
            key: value for key, value in data.items() if key not in known
        }
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Return the legacy dict shape expected by older call sites."""
        data = dict(self.extra)
        data["workspace_id"] = self.workspace_id
        if self.current_page_id is not None:
            data["current_page_id"] = self.current_page_id
        if self.tabs:
            data["control_tabs"] = self.tabs
        if self.sessions:
            data["control_sessions"] = self.sessions
        if self.refs:
            data["refs"] = self.refs
        if self.pending_observations:
            data["control_pending_observations"] = self.pending_observations
        if self.click_effects:
            data["control_click_effects"] = self.click_effects
        if self.snapshot_hashes:
            data["control_snapshot_hashes"] = self.snapshot_hashes
        if self.network_enabled_tabs:
            data["control_network_enabled_tabs"] = self.network_enabled_tabs
        if self.page_aliases:
            data["control_page_aliases"] = self.page_aliases
        if self.approved_domains:
            data["control_approved_domains"] = self.approved_domains
        if self.pending_action_transition is not None:
            data[
                "control_pending_action_transition"
            ] = self.pending_action_transition
        else:
            data.pop("control_pending_action_transition", None)
        return data

    def sync_to(self, target: dict[str, Any]) -> None:
        """Copy the typed state back into an existing legacy dict."""
        target.clear()
        target.update(self.to_dict())

    def __getitem__(self, key: str) -> Any:
        field_name = self._KEY_TO_FIELD.get(key)
        if field_name is None:
            return self.extra[key]
        return getattr(self, field_name)

    def __setitem__(self, key: str, value: Any) -> None:
        field_name = self._KEY_TO_FIELD.get(key)
        if field_name is None:
            self.extra[key] = value
            return
        if field_name == "network_enabled_tabs":
            value = set(value or set())
        elif field_name == "approved_domains":
            value = {str(domain) for domain in value or set()}
        setattr(self, field_name, value)
        self._refresh_mapping()

    def __delitem__(self, key: str) -> None:
        field_name = self._KEY_TO_FIELD.get(key)
        if field_name is None:
            del self.extra[key]
            return
        default = type(self)().__getitem__(key)
        setattr(self, field_name, default)
        self._refresh_mapping()

    def __iter__(self) -> Iterator[str]:
        yield from self.to_dict()

    def __len__(self) -> int:
        return len(self.to_dict())

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return key in self._KEY_TO_FIELD or key in self.extra

    def get(self, key: object, default: Any = None) -> Any:
        if not isinstance(key, str):
            return default
        return self[key] if key in self else default

    def pop(self, key: str, default: Any = _MISSING) -> Any:
        if key in self:
            value = self[key]
            del self[key]
            return value
        if default is _MISSING:
            raise KeyError(key)
        return default

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key not in self:
            self[key] = default
        return self[key]

    def update(self, *args: Any, **kwargs: Any) -> None:
        updates = dict(*args, **kwargs)
        for key, value in updates.items():
            self[str(key)] = value

    def copy(self) -> dict[str, Any]:
        return self.to_dict()


__all__ = ["ControlState"]
