# -*- coding: utf-8 -*-
"""Browser Control action handler protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agentscope.tool import ToolChunk

from ..state import ControlState


@dataclass(frozen=True)
class ActionMeta:
    """Execution requirements for a Browser Control action handler."""

    requires_tab_claimed: bool = False
    requires_observation: bool = False
    invalidates_snapshot: bool = True


class ActionHandler(Protocol):
    """Protocol implemented by typed Browser Control action handlers."""

    meta: ActionMeta

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ) -> ToolChunk:
        """Execute an action against Browser Control state."""


__all__ = ["ActionHandler", "ActionMeta"]
