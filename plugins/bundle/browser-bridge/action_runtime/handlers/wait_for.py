# -*- coding: utf-8 -*-
"""Wait Browser Bridge action handler."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.runtime.responses import _tool_response
from ..session_manager import (
    _control_condition_next_hint,
    _control_condition_subscribe,
    _control_condition_unsubscribe,
    _control_get_session,
)
from ..snapshot_builder import capture_condition_probe_facts
from ..state import ControlState
from ..tab_manager import _control_page_id
from ..navigation import _control_tab_id
from .protocol import ActionMeta


@dataclass(frozen=True)
class WaitForHandler:
    meta: ActionMeta = ActionMeta(
        requires_tab_claimed=True,
        requires_observation=False,
        invalidates_snapshot=True,
    )

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        request_context = kwargs.get("request_context") or {}
        canonical_kwargs = dict(kwargs)
        canonical_kwargs.pop("request_context", None)
        return await self._execute_canonical(
            state,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
            **canonical_kwargs,
        )

    async def _execute_canonical(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        request_context: dict[str, Any],
        **kwargs: Any,
    ):
        operation = str(kwargs.get("probe_operation") or "")
        if operation not in {"check", "subscribe", "next_hint", "unsubscribe"}:
            return _canonical_response(
                operation,
                ok=False,
                code="condition_probe_operation_invalid",
            )
        owner_key = _condition_owner_key(request_context)
        if owner_key is None:
            return _canonical_response(
                operation,
                ok=False,
                code="condition_probe_owner_missing",
            )
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        if operation == "subscribe":
            token, watermark = _control_condition_subscribe(
                state,
                owner_key=owner_key,
                tab_id=tab_id,
            )
            return _canonical_response(
                operation,
                subscription=token,
                watermark=watermark,
            )
        token = str(kwargs.get("subscription") or "")
        if operation == "unsubscribe":
            removed = _control_condition_unsubscribe(
                state,
                token=token,
                owner_key=owner_key,
                tab_id=tab_id,
            )
            return _canonical_response(operation, ok=removed)
        if operation == "next_hint":
            sequence = _control_condition_next_hint(
                state,
                token=token,
                owner_key=owner_key,
                tab_id=tab_id,
            )
            if sequence is None:
                await _wait_for_condition_hint(
                    state,
                    token=token,
                    timeout_ms=int(kwargs.get("timeout_ms") or 0),
                )
                sequence = _control_condition_next_hint(
                    state,
                    token=token,
                    owner_key=owner_key,
                    tab_id=tab_id,
                )
            return _canonical_response(operation, sequence=sequence)
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        descriptors = tuple(kwargs.get("region_descriptors") or ())
        facts = await capture_condition_probe_facts(
            session,
            region_descriptors=descriptors,
        )
        return _canonical_response(
            operation,
            state="AVAILABLE",
            **facts,
        )


def _condition_owner_key(
    request_context: dict[str, Any],
) -> tuple[str, str] | None:
    root_task_id = str(request_context.get("root_task_id") or "").strip()
    browser_owner_id = str(
        request_context.get("browser_owner_id") or "",
    ).strip()
    if not root_task_id or not browser_owner_id:
        return None
    return (root_task_id, browser_owner_id)


async def _wait_for_condition_hint(
    state: ControlState,
    *,
    token: str,
    timeout_ms: int,
) -> None:
    entry = state.condition_subscriptions.get(token)
    event = entry.get("event") if isinstance(entry, dict) else None
    if not isinstance(event, asyncio.Event) or timeout_ms <= 0:
        return
    event.clear()
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_ms / 1000)
    except asyncio.TimeoutError:
        return


def _canonical_response(
    operation: str,
    *,
    ok: bool = True,
    code: str = "",
    **facts: Any,
):
    payload = {
        "ok": ok,
        "mode": "canonical",
        "operation": operation,
        **facts,
    }
    if code:
        payload["code"] = code
    return _tool_response(
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


WAIT_FOR_HANDLER = WaitForHandler()

__all__ = ["WAIT_FOR_HANDLER", "WaitForHandler"]
