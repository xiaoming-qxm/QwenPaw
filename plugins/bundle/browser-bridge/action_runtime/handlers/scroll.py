# -*- coding: utf-8 -*-
"""Scroll Browser Bridge action handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.sdk.governance.errors import BrowserSDKError

from ..errors import BrowserBridgeRecoverableError
from ..interactions import canonical_native_interaction_control
from ..state import ControlState
from .navigate import _json_response
from .protocol import ActionMeta


@dataclass(frozen=True)
class ScrollHandler:
    meta: ActionMeta = ActionMeta(True, False, True)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        try:
            labels = (
                ("target",)
                if (kwargs.get("_canonical_target_tokens") or {}).get(
                    "target",
                )
                else ()
            )
            return await canonical_native_interaction_control(
                state,
                holder_id=holder_id,
                bridge=bridge,
                action="scroll",
                target_labels=labels,
                kwargs=kwargs,
            )
        except (BrowserBridgeRecoverableError, BrowserSDKError, ValueError) as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


async def _send_with_timeout(
    session: Any,
    method: str,
    params: dict[str, Any],
    timeout: float = 3.0,
) -> dict[str, Any]:
    return await asyncio.wait_for(
        session.send(method, params),
        timeout=timeout,
    )


SCROLL_HANDLER = ScrollHandler()
__all__ = ["SCROLL_HANDLER", "ScrollHandler"]
