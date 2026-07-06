# -*- coding: utf-8 -*-
"""Browser Bridge action handler protocol."""
# pylint: disable=unnecessary-ellipsis

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agentscope.tool import ToolChunk

from ..state import ControlState


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


__all__ = ["ActionHandler", "ActionMeta"]
