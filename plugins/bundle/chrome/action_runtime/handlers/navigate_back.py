# -*- coding: utf-8 -*-
"""Navigate back Chrome action handler."""
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .. import navigation as control_navigation
from ..errors import ChromeRecoverableError, NavigationFailed
from ..navigation import _control_tab_id
from ..network_settle import _network_quiescence_wait
from ..observation import _click_effect_reset
from ..session_manager import _control_get_session
from ..state import ControlState
from ..tab_manager import (
    _control_ensure_tab_available,
    _control_page_id,
    _control_refresh_tab_url,
)
from .navigate import _json_response, _network_settled
from .protocol import ActionMeta


@dataclass(frozen=True)
class NavigateHistoryHandler:
    direction: str
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
            history = await session.send("Page.getNavigationHistory")
            entries = (
                history.get("entries") if isinstance(history, dict) else []
            )
            current = int(history.get("currentIndex") or 0)
            target_index = self._target_index(current)
            if (
                target_index < 0
                or not isinstance(entries, list)
                or target_index >= len(entries)
            ):
                return _json_response(
                    {
                        "ok": False,
                        "mode": "control",
                        "error": self._missing_history_message(),
                    },
                )
            target = entries[target_index]
            entry_id = int(target.get("id"))
            wait_for_load = (
                control_navigation._control_create_page_load_waiter(
                    bridge,
                    tab_id,
                )
            )
            try:
                await session.send_after_banner(
                    "Page.navigateToHistoryEntry",
                    {"entryId": entry_id},
                    {"status_text": self._status_text()},
                )
            except (
                asyncio.TimeoutError,
                RuntimeError,
                OSError,
                ValueError,
                TypeError,
            ) as exc:
                raise NavigationFailed(
                    f"{self._action_name()} failed: {exc}",
                ) from exc
            page_settled = await wait_for_load(
                control_navigation._CONTROL_NAVIGATE_LOAD_TIMEOUT_SECONDS,
            )
            url = str(target.get("url") or "")
            if url:
                state.current_page_id = str(tab_id)
                _control_refresh_tab_url(state, tab_id, url)
            network = await _network_quiescence_wait(
                session,
                bridge,
                state,
                tab_id,
                timeout=5.0,
            )
            _click_effect_reset(state, tab_id)
            return _json_response(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    f"navigated_{self.direction}": True,
                    "url": url,
                    "page_settled": page_settled,
                    "network_settled": _network_settled(network),
                },
            )
        except (ChromeRecoverableError, ValueError, TypeError) as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )

    def _target_index(self, current: int) -> int:
        return current + 1 if self.direction == "forward" else current - 1

    def _missing_history_message(self) -> str:
        if self.direction == "forward":
            return "No next page in history"
        return "No previous page in history"

    def _status_text(self) -> str:
        return "Forward" if self.direction == "forward" else "Back"

    def _action_name(self) -> str:
        return (
            "navigate_forward"
            if self.direction == "forward"
            else "navigate_back"
        )


@dataclass(frozen=True)
class NavigateBackHandler(NavigateHistoryHandler):
    direction: str = "back"


@dataclass(frozen=True)
class NavigateForwardHandler(NavigateHistoryHandler):
    direction: str = "forward"


NAVIGATE_BACK_HANDLER = NavigateBackHandler()
NAVIGATE_FORWARD_HANDLER = NavigateForwardHandler()
__all__ = [
    "NAVIGATE_BACK_HANDLER",
    "NAVIGATE_FORWARD_HANDLER",
    "NavigateBackHandler",
    "NavigateForwardHandler",
    "NavigateHistoryHandler",
]
