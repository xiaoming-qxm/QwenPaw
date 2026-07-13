# -*- coding: utf-8 -*-
"""Browser Bridge action handler protocol."""
# pylint: disable=unnecessary-ellipsis

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from agentscope.tool import ToolChunk

from qwenpaw.browser.sdk.action_runner import DispatchContext
from ..state import ControlState


_TRUSTED_ENVELOPE_ISSUER = object()


@dataclass(frozen=True, slots=True, init=False)
class TrustedCommandEnvelope:
    """Internal envelope issued only after authoritative owner lookup."""

    dispatch_context: DispatchContext
    action: str
    command_payload: Mapping[str, object]
    _issuer: object

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("TrustedCommandEnvelope is Runtime-issued")

    def is_runtime_issued(self) -> bool:
        """Return whether the private issuer constructed this value."""
        return self._issuer is _TRUSTED_ENVELOPE_ISSUER


def _issue_trusted_command_envelope(
    context: DispatchContext,
    *,
    action: str,
    command_payload: Mapping[str, object],
) -> TrustedCommandEnvelope:
    """Seal a validated DispatchContext and closed command payload."""
    envelope = object.__new__(TrustedCommandEnvelope)
    object.__setattr__(envelope, "dispatch_context", context)
    object.__setattr__(envelope, "action", str(action))
    object.__setattr__(
        envelope,
        "command_payload",
        MappingProxyType(dict(command_payload)),
    )
    object.__setattr__(envelope, "_issuer", _TRUSTED_ENVELOPE_ISSUER)
    return envelope


def is_trusted_command_envelope(value: object) -> bool:
    """Return whether the envelope came from the private Runtime issuer."""
    return bool(
        isinstance(value, TrustedCommandEnvelope)
        and value.is_runtime_issued()
        and isinstance(value.dispatch_context, DispatchContext),
    )


@dataclass(frozen=True)
class ActionMeta:
    """Execution requirements for a Browser Bridge action handler."""

    requires_tab_claimed: bool = False
    requires_observation: bool = False
    invalidates_snapshot: bool = True


class ActionHandler(Protocol):
    """Protocol implemented by typed Browser Bridge action handlers."""

    @property
    def meta(self) -> ActionMeta:
        """Execution metadata for dispatcher pre/post handling."""
        ...

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ) -> ToolChunk:
        """Execute an action against Browser Bridge state."""


__all__ = [
    "ActionHandler",
    "ActionMeta",
    "TrustedCommandEnvelope",
    "is_trusted_command_envelope",
]
