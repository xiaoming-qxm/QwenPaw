# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Browser Control observe-before-act helpers."""

from ..runtime import *
from .session_manager import *
from .navigation import *
from .tab_manager import *


def _control_pending_observations(state: dict) -> dict[str, Any]:
    pending = state.setdefault("control_pending_observations", {})
    if isinstance(pending, dict):
        return pending
    pending = {}
    state["control_pending_observations"] = pending
    return pending


def _control_mark_observation_required(
    state: dict,
    tab_id: int,
    *,
    action: str,
) -> None:
    _control_pending_observations(state)[str(tab_id)] = {
        "tab_id": tab_id,
        "after_action": action,
        "created_at": time.time(),
    }


def _control_clear_observation_required(state: dict, tab_id: int) -> None:
    pending = state.get("control_pending_observations")
    if not isinstance(pending, dict):
        return
    pending.pop(str(tab_id), None)
    if not pending:
        state.pop("control_pending_observations", None)


def _control_observation_required_response(
    tab_id: int,
    pending: dict[str, Any],
) -> ToolChunk:
    after_action = str(pending.get("after_action") or "action")
    return _tool_response(
        json.dumps(
            {
                "ok": False,
                "mode": "control",
                "tab_id": tab_id,
                "error": "observation required before next action",
                "after_action": after_action,
                "next_action": "snapshot",
                "next_instruction": (
                    "The previous browser action may have changed the page. "
                    "Observe the current page with snapshot or screenshot "
                    "before taking another click, type, or key action."
                ),
                "use_instead": [
                    "snapshot",
                    "screenshot",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def _control_require_observation_before_action(
    state: dict,
    *,
    action: str,
    tab_id: int,
) -> ToolChunk | None:
    if action not in _CONTROL_MUTATING_ACTIONS:
        return None
    pending = state.get("control_pending_observations")
    if not isinstance(pending, dict):
        return None
    value = pending.get(str(tab_id))
    if not isinstance(value, dict):
        return None
    return _control_observation_required_response(tab_id, value)


__all__ = [name for name in globals() if not name.startswith("__")]
