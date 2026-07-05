# -*- coding: utf-8 -*-
"""Typed state container for Browser Control runtime data."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any, ClassVar


_MISSING = object()

CONTROL_STATE_KEY_TO_FIELD: dict[str, str] = {
    "workspace_id": "workspace_id",
    "current_page_id": "current_page_id",
    "control_tabs": "tabs",
    "tabs": "tabs",
    "control_sessions": "sessions",
    "sessions": "sessions",
    "refs": "refs",
    "control_pending_observations": "pending_observations",
    "pending_observations": "pending_observations",
    "control_visual_observations": "visual_observations",
    "visual_observations": "visual_observations",
    "control_click_effects": "click_effects",
    "click_effects": "click_effects",
    "control_snapshot_hashes": "snapshot_hashes",
    "snapshot_hashes": "snapshot_hashes",
    "control_network_enabled_tabs": "network_enabled_tabs",
    "network_enabled_tabs": "network_enabled_tabs",
    "control_page_aliases": "page_aliases",
    "page_aliases": "page_aliases",
    "control_approved_domains": "approved_domains",
    "approved_domains": "approved_domains",
    "control_pending_action_transition": "pending_action_transition",
    "pending_action_transition": "pending_action_transition",
}


StateMapping = MutableMapping[str, Any]


@dataclass
class ControlState(MutableMapping[str, Any]):
    """Browser Control state used by engine internals."""

    workspace_id: str = "default"
    current_page_id: str | None = None
    tabs: dict[str, dict[str, Any]] = field(default_factory=dict)
    sessions: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_observations: dict[str, Any] = field(default_factory=dict)
    visual_observations: dict[str, Any] = field(default_factory=dict)
    click_effects: dict[str, Any] = field(default_factory=dict)
    snapshot_hashes: dict[str, str] = field(default_factory=dict)
    network_enabled_tabs: set[int] = field(default_factory=set)
    page_aliases: dict[str, int] = field(default_factory=dict)
    approved_domains: set[str] = field(default_factory=set)
    pending_action_transition: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    _KEY_TO_FIELD: ClassVar[dict[str, str]] = CONTROL_STATE_KEY_TO_FIELD

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
        setattr(self, field_name, _coerce_field_value(field_name, value))

    def __delitem__(self, key: str) -> None:
        field_name = self._KEY_TO_FIELD.get(key)
        if field_name is None:
            del self.extra[key]
            return
        setattr(self, field_name, _default_field_value(field_name))

    def __iter__(self) -> Iterator[str]:
        yield from control_state_to_mapping(self)

    def __len__(self) -> int:
        return len(control_state_to_mapping(self))

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key in self.extra:
            return True
        field_name = self._KEY_TO_FIELD.get(key)
        if field_name is None:
            return False
        value = getattr(self, field_name)
        return value is not None and value != _default_field_value(field_name)

    def get(self, key: object, default: Any = None) -> Any:
        if not isinstance(key, str) or key not in self:
            return default
        return self[key]

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
        return control_state_to_mapping(self)


def control_state_from_mapping(
    data: Mapping[str, Any] | ControlState,
) -> ControlState:
    """Adapt an external workspace mapping into typed control state."""
    if isinstance(data, ControlState):
        return data
    kwargs: dict[str, Any] = {}
    consumed: set[str] = set()
    for key, field_name in CONTROL_STATE_KEY_TO_FIELD.items():
        if key not in data or field_name in kwargs:
            continue
        kwargs[field_name] = _coerce_field_value(field_name, data[key])
        consumed.add(key)
    kwargs["extra"] = {
        key: value for key, value in data.items() if key not in consumed
    }
    return ControlState(**kwargs)


def control_state_to_mapping(state: ControlState) -> dict[str, Any]:
    """Serialize typed control state to the external workspace mapping."""
    data = dict(state.extra)
    data["workspace_id"] = state.workspace_id
    if state.current_page_id is not None:
        data["current_page_id"] = state.current_page_id
    if state.tabs:
        data["control_tabs"] = state.tabs
    if state.sessions:
        data["control_sessions"] = state.sessions
    if state.refs:
        data["refs"] = state.refs
    if state.pending_observations:
        data["control_pending_observations"] = state.pending_observations
    if state.visual_observations:
        data["control_visual_observations"] = state.visual_observations
    if state.click_effects:
        data["control_click_effects"] = state.click_effects
    if state.snapshot_hashes:
        data["control_snapshot_hashes"] = state.snapshot_hashes
    if state.network_enabled_tabs:
        data["control_network_enabled_tabs"] = state.network_enabled_tabs
    if state.page_aliases:
        data["control_page_aliases"] = state.page_aliases
    if state.approved_domains:
        data["control_approved_domains"] = state.approved_domains
    if state.pending_action_transition is not None:
        data[
            "control_pending_action_transition"
        ] = state.pending_action_transition
    return data


def sync_control_state_to_mapping(
    state: ControlState,
    target: dict[str, Any],
) -> None:
    """Write typed control state back to an external workspace mapping."""
    target.clear()
    target.update(control_state_to_mapping(state))


def _coerce_field_value(field_name: str, value: Any) -> Any:
    if field_name == "network_enabled_tabs":
        return {int(tab_id) for tab_id in value or set()}
    if field_name == "approved_domains":
        return {str(domain) for domain in value or set()}
    return value


def _default_field_value(field_name: str) -> Any:
    if field_name in {
        "tabs",
        "sessions",
        "refs",
        "pending_observations",
        "visual_observations",
        "click_effects",
        "snapshot_hashes",
        "page_aliases",
        "extra",
    }:
        return {}
    if field_name in {"network_enabled_tabs", "approved_domains"}:
        return set()
    if field_name == "workspace_id":
        return "default"
    return None


__all__ = [
    "ControlState",
    "CONTROL_STATE_KEY_TO_FIELD",
    "StateMapping",
    "control_state_from_mapping",
    "control_state_to_mapping",
    "sync_control_state_to_mapping",
]
