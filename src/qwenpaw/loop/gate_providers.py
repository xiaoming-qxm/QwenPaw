# -*- coding: utf-8 -*-
"""Generic React Loop gate provider registry."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from .gates.base import StopGate


class LoopGateProvider(Protocol):
    """Provides StopGate instances for a workspace's React Loop."""

    name: str

    def gates(
        self,
        workspace: Any,
        running_config: Any,
    ) -> Iterable[StopGate]:
        """Return gates to register for this workspace."""


_PROVIDERS: dict[str, LoopGateProvider] = {}


def register_loop_gate_provider(provider: LoopGateProvider) -> None:
    """Register a loop gate provider by stable provider name."""

    name = str(getattr(provider, "name", "") or "").strip()
    if not name:
        raise ValueError("loop gate provider requires a non-empty name")
    if name in _PROVIDERS:
        return
    _PROVIDERS[name] = provider


def iter_loop_gate_providers() -> tuple[LoopGateProvider, ...]:
    """Return currently registered providers in registration order."""

    return tuple(_PROVIDERS.values())


def clear_loop_gate_providers_for_tests() -> None:
    """Clear provider registry for focused tests."""

    _PROVIDERS.clear()


__all__ = [
    "LoopGateProvider",
    "clear_loop_gate_providers_for_tests",
    "iter_loop_gate_providers",
    "register_loop_gate_provider",
]
