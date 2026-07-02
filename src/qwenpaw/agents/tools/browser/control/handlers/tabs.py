# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ...runtime import _tool_response
from ..state import ControlState
from .protocol import ActionMeta


def _connected(bridge: Any) -> bool:
    return bridge is not None and bool(getattr(bridge, "connected", False))


def _bridge_error():
    return _tool_response(
        json.dumps(
            {
                "ok": False,
                "mode": "control",
                "error": "Chrome extension bridge is not connected",
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


@dataclass(frozen=True)
class TabsHandler:
    meta: ActionMeta = ActionMeta(False, False, False)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        del state, holder_id
        if not _connected(bridge):
            return _bridge_error()
        tab_action = str(kwargs.get("tab_action") or "list").strip().lower()
        if tab_action not in {"", "list"}:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "mode": "control",
                        "error": "control tabs only supports tab_action=list",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        tabs = await bridge.discover_tabs()
        return _tool_response(
            json.dumps(
                {"ok": True, "mode": "control", "tabs": tabs},
                ensure_ascii=False,
                indent=2,
            ),
        )


TABS_HANDLER = TabsHandler()

__all__ = ["TABS_HANDLER", "TabsHandler"]
