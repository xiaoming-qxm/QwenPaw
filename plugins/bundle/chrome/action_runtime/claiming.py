# -*- coding: utf-8 -*-
"""Tab claiming helpers for Chrome typed handlers."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from qwenpaw.browser.runtime.responses import (
    _CONTROL_BANNER_TIMEOUT_SECONDS,
    _tool_response,
    logger,
)
from .errors import ChromeRecoverableError, CDPCommandFailed
from .inference import (
    _control_claim_success_payload,
    _control_jsonrpc_error,
    _control_select_or_create_url_tab,
)
from .navigation import _control_page_id_is_tab_id, _control_tab_id
from .session_manager import (
    _control_get_existing_session,
    _control_get_session,
)
from .state import ControlState
from .tab_manager import (
    _control_ensure_tab_available,
    _control_forget_tab_state,
    _control_missing_tab_error,
    _control_page_id,
    _control_remember_page_alias,
    _control_tab_record,
)
from .targets import _control_align_tab_to_requested_url


def _json_response(payload: dict[str, Any]):
    return _tool_response(json.dumps(payload, ensure_ascii=False, indent=2))


async def _attach_tab(bridge: Any, tab_id: int, holder_id: str) -> None:
    try:
        await bridge.claim_tab(tab_id, holder_id)
        attach_response = await bridge.request(
            "tab.attach",
            {"tabId": tab_id, "holderId": holder_id},
        )
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        raise CDPCommandFailed(
            f"Failed to attach tab {tab_id}: {exc}",
        ) from exc
    attach_error = _control_jsonrpc_error(attach_response)
    if attach_error:
        raise CDPCommandFailed(attach_error)


async def _show_control_banner(bridge: Any, tab_id: int) -> None:
    try:
        await asyncio.wait_for(
            bridge.request(
                "banner.show",
                {"tabId": tab_id, "status_text": "QwenPaw control active"},
            ),
            timeout=_CONTROL_BANNER_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.debug("control banner.show timed out")
    except ChromeRecoverableError:
        logger.debug("control banner.show failed", exc_info=True)
    except (RuntimeError, OSError, ValueError, TypeError):
        logger.debug("control banner.show failed", exc_info=True)


async def claim_control_tab(
    state: ControlState,
    *,
    bridge: Any,
    holder_id: str,
    request_context: dict[str, Any],
    url: str = "",
    raw_page_id: str = "default",
    index: int = -1,
    user_initiated: bool = False,
):
    raw_page_id = (raw_page_id or "default").strip() or "default"
    selected_by_url = (
        bool(url)
        and not _control_page_id_is_tab_id(
            raw_page_id,
        )
        and index < 0
    )
    discovered_tab_url = ""
    tab_created_by_control = False
    if selected_by_url:
        (
            tab_id,
            discovered_tab_url,
            error,
            tab_created_by_control,
        ) = await _control_select_or_create_url_tab(
            state,
            bridge,
            url,
            request_context,
            holder_id,
            user_initiated=user_initiated,
        )
        if error or tab_id is None:
            return _json_response(
                {
                    "ok": False,
                    "mode": "control",
                    "error": error or "No tab selected",
                },
            )
    else:
        tab_id = _control_tab_id(_control_page_id(state, raw_page_id), index)

    existing = await _control_get_existing_session(
        state,
        tab_id=tab_id,
        holder_id=holder_id,
        bridge=bridge,
        request_context=request_context,
    )
    if existing is None:
        (
            tab_id,
            discovered_tab_url,
            tab_created_by_control,
        ) = await _claim_fresh(
            state,
            bridge=bridge,
            tab_id=tab_id,
            holder_id=holder_id,
            request_context=request_context,
            url=url,
            selected_by_url=selected_by_url,
            discovered_tab_url=discovered_tab_url,
            tab_created_by_control=tab_created_by_control,
            user_initiated=user_initiated,
        )
        if tab_id is None:
            return _json_response(
                {"ok": False, "mode": "control", "error": discovered_tab_url},
            )
        await _control_ensure_tab_available(bridge, tab_id)
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=request_context,
        )
        await _show_control_banner(bridge, tab_id)
    else:
        await _control_ensure_tab_available(bridge, tab_id)
        session = existing

    previous_tab = state.tabs.get(str(tab_id)) or {}
    current_url = discovered_tab_url or previous_tab.get("url") or ""
    tab_url = await _control_align_tab_to_requested_url(
        session,
        url,
        current_url,
    )
    state.tabs[str(tab_id)] = _control_tab_record(
        tab_id=tab_id,
        holder_id=holder_id,
        url=tab_url or current_url or url,
        created_by_control=bool(
            tab_created_by_control or previous_tab.get("created_by_control"),
        ),
        request_context=request_context,
        previous_tab=previous_tab,
    )
    state.current_page_id = str(tab_id)
    _control_remember_page_alias(state, raw_page_id, tab_id)
    return _json_response(
        _control_claim_success_payload(tab_id, tab_url or url),
    )


async def _claim_fresh(
    state: ControlState,
    *,
    bridge: Any,
    tab_id: int,
    holder_id: str,
    request_context: dict[str, Any],
    url: str,
    selected_by_url: bool,
    discovered_tab_url: str,
    tab_created_by_control: bool,
    user_initiated: bool,
) -> tuple[int | None, str, bool]:
    attach_attempt = 0
    while True:
        try:
            await _attach_tab(bridge, tab_id, holder_id)
            return tab_id, discovered_tab_url, tab_created_by_control
        except ChromeRecoverableError as exc:
            await _release_after_attach_failure(bridge, tab_id, holder_id)
            if (
                not selected_by_url
                or attach_attempt > 0
                or not _control_missing_tab_error(str(exc))
            ):
                return None, f"Failed to attach tab {tab_id}: {exc!s}", False
            await _control_forget_tab_state(state, tab_id)
            attach_attempt += 1
            (
                selected_tab_id,
                discovered_tab_url,
                error,
                tab_created_by_control,
            ) = await _control_select_or_create_url_tab(
                state,
                bridge,
                url,
                request_context,
                holder_id,
                user_initiated=user_initiated,
            )
            if error or selected_tab_id is None:
                return None, error or "No tab selected", False
            tab_id = selected_tab_id


async def _release_after_attach_failure(
    bridge: Any,
    tab_id: int,
    holder_id: str,
) -> None:
    try:
        await bridge.release(tab_id, holder_id)
    except ChromeRecoverableError:
        logger.debug(
            "Failed to release control lease after attach failure",
            exc_info=True,
        )
    except (RuntimeError, OSError, ValueError, TypeError):
        logger.debug(
            "Failed to release control lease after attach failure",
            exc_info=True,
        )


__all__ = ["claim_control_tab"]
