# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from ...runtime import _tool_response
from ..claiming import claim_control_tab
from ..errors import BrowserControlRecoverableError, NavigationFailed
from .. import navigation as control_navigation
from ..navigation import _control_tab_id
from ..network_settle import _network_quiescence_wait
from ..observation import _click_effect_reset
from ..session_manager import _control_get_session
from ..state import ControlState
from ..tab_manager import (
    _control_ensure_tab_available,
    _control_page_id,
    _control_tab_record,
)
from .protocol import ActionMeta


@dataclass(frozen=True)
class NavigateHandler:
    meta: ActionMeta = ActionMeta(True, False, True)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        url = str(kwargs.get("url") or "").strip()
        if not url:
            return _json_response(
                {
                    "ok": False,
                    "mode": "control",
                    "error": "url required for navigate",
                },
            )
        try:
            navigate_kwargs = dict(kwargs)
            navigate_kwargs.pop("url", None)
            return await self._navigate(
                state,
                holder_id=holder_id,
                bridge=bridge,
                url=url,
                **navigate_kwargs,
            )
        except BrowserControlRecoverableError as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )

    async def _navigate(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        url: str,
        **kwargs: Any,
    ):
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        await _control_ensure_tab_available(bridge, tab_id)
        request_context = kwargs.get("request_context") or {}
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        wait_for_load = control_navigation._control_create_page_load_waiter(
            bridge,
            tab_id,
        )
        try:
            await _send_navigate(session, url)
        except (
            asyncio.TimeoutError,
            RuntimeError,
            OSError,
            ValueError,
            TypeError,
        ) as exc:
            raise NavigationFailed(
                f"navigation to {url} failed: {exc}",
            ) from exc
        page_settled = await wait_for_load(
            control_navigation._CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS,
        )
        network_metadata = None
        if page_settled:
            network_timeout = (
                control_navigation._CONTROL_NAVIGATE_NETWORK_TIMEOUT_SECONDS
            )
            network_metadata = await _network_quiescence_wait(
                session,
                bridge,
                state,
                tab_id,
                timeout=network_timeout,
            )
        _click_effect_reset(state, tab_id)
        state.current_page_id = str(tab_id)
        previous = state.tabs.get(str(tab_id)) or {}
        state.tabs[str(tab_id)] = _control_tab_record(
            tab_id=tab_id,
            holder_id=str(previous.get("holder_id") or holder_id),
            url=url,
            created_by_control=bool(previous.get("created_by_control")),
            request_context=request_context,
            previous_tab=previous,
        )
        payload = {
            "ok": True,
            "mode": "control",
            "tab_id": tab_id,
            "url": url,
            "page_settled": page_settled,
            "network_settled": _network_settled(network_metadata),
        }
        if (
            isinstance(network_metadata, dict)
            and int(network_metadata.get("async_requests_triggered") or 0) > 0
        ):
            payload["network"] = {
                "async_requests_triggered": int(
                    network_metadata.get("async_requests_triggered") or 0,
                ),
                "settled": bool(network_metadata.get("settled")),
                "timed_out": bool(network_metadata.get("timed_out")),
            }
        return _json_response(payload)


def _network_settled(metadata: dict[str, Any] | None) -> bool:
    return bool(metadata.get("settled")) if isinstance(metadata, dict) else False


async def _send_navigate(session: Any, url: str) -> None:
    try:
        await session.send_after_banner(
            "Page.navigate",
            {"url": url},
            {"status_text": "Navigate"},
        )
    except (
        asyncio.TimeoutError,
        RuntimeError,
        OSError,
        ValueError,
        TypeError,
    ) as exc:
        if not _is_banner_access_error(exc):
            raise
        await session.send("Page.navigate", {"url": url})


def _is_banner_access_error(exc: BaseException) -> bool:
    message = str(exc)
    return (
        "Cannot access contents of url" in message
        or "Extension manifest must request permission" in message
    )


def _json_response(payload: dict[str, Any]):
    return _tool_response(json.dumps(payload, ensure_ascii=False, indent=2))


NAVIGATE_HANDLER = NavigateHandler()
__all__ = ["NAVIGATE_HANDLER", "NavigateHandler", "claim_control_tab"]
