# -*- coding: utf-8 -*-
"""Message routing for browser-bridge."""

from __future__ import annotations

from typing import Any

try:
    from .lease_registry import LeaseRegistry
except ImportError:
    from lease_registry import LeaseRegistry  # type: ignore[no-redef]

RoutedMessage = tuple[str, dict[str, Any]]


class MessageRouter:
    """Route messages between one extension and many QwenPaw instances."""

    def __init__(self, lease_registry: LeaseRegistry) -> None:
        self._lease_registry = lease_registry
        self._instances: dict[str, Any] = {}
        self._msg_id_to_instance: dict[Any, str] = {}
        self._holder_to_instance: dict[str, str] = {}

    def register_instance(self, instance_id: str, ws: Any) -> None:
        self._instances[instance_id] = ws

    def unregister_instance(self, instance_id: str) -> None:
        self._instances.pop(instance_id, None)
        self._lease_registry.release_all(instance_id)
        for msg_id, owner in list(self._msg_id_to_instance.items()):
            if owner == instance_id:
                self._msg_id_to_instance.pop(msg_id, None)
        for holder_id, owner in list(self._holder_to_instance.items()):
            if owner == instance_id:
                self._holder_to_instance.pop(holder_id, None)

    def note_holder(self, holder_id: str, instance_id: str) -> None:
        self._holder_to_instance[str(holder_id)] = instance_id

    def instance_ws(self, instance_id: str) -> Any | None:
        return self._instances.get(instance_id)

    def route_backend_to_extension(
        self,
        instance_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        msg_id = message.get("id")
        if msg_id is not None:
            self._msg_id_to_instance[msg_id] = instance_id

        params = _params(message)
        holder_id = params.get("holderId")
        if holder_id:
            self.note_holder(str(holder_id), instance_id)
            self._apply_lease_side_effect(instance_id, message)
        return message

    def route_extension_to_backend(
        self,
        message: dict[str, Any],
    ) -> list[RoutedMessage]:
        msg_id = message.get("id")
        if msg_id in self._msg_id_to_instance and not message.get("method"):
            response_target = self._msg_id_to_instance.pop(msg_id)
            return [(response_target, message)]

        params = _params(message)
        holder_id = params.get("holderId")
        if holder_id:
            holder_target = self._holder_to_instance.get(str(holder_id))
            return self._targeted(holder_target, message)

        tab_id = params.get("tabId")
        if tab_id is not None:
            lease_target = self._lease_registry.owner(int(tab_id))
            return self._targeted(lease_target, message)

        if message.get("method"):
            return [(instance_id, message) for instance_id in self._instances]
        return []

    def _targeted(
        self,
        target: str | None,
        message: dict[str, Any],
    ) -> list[RoutedMessage]:
        if target is None or target not in self._instances:
            return []
        return [(target, message)]

    def _apply_lease_side_effect(
        self,
        instance_id: str,
        message: dict[str, Any],
    ) -> None:
        params = _params(message)
        tab_id = params.get("tabId")
        holder_id = params.get("holderId")
        if tab_id is None or not holder_id:
            return

        method = str(message.get("method") or "")
        if method in {"tab.attach", "tab.ensure"}:
            self._lease_registry.claim(int(tab_id), instance_id)
        elif method in {"tab.detach", "tab.close"}:
            self._lease_registry.release(int(tab_id), instance_id)
        else:
            owner = self._lease_registry.owner(int(tab_id))
            if owner == instance_id:
                self._lease_registry.validate_and_renew(
                    int(tab_id),
                    instance_id,
                )


def _params(message: dict[str, Any]) -> dict[str, Any]:
    params = message.get("params")
    return params if isinstance(params, dict) else {}


__all__ = ["LeaseRegistry", "MessageRouter", "RoutedMessage"]
