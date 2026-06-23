# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Browser Control observe-before-act helpers."""

from ..runtime import *
from .session_manager import *
from .navigation import *
from .tab_manager import *


def _click_effect_records(state: dict) -> dict[str, Any]:
    records = state.setdefault("control_click_effects", {})
    if isinstance(records, dict):
        return records
    records = {}
    state["control_click_effects"] = records
    return records


def _click_effect_snapshot_hashes(state: dict) -> dict[str, str]:
    hashes = state.setdefault("control_snapshot_hashes", {})
    if isinstance(hashes, dict):
        return hashes
    hashes = {}
    state["control_snapshot_hashes"] = hashes
    return hashes


def _click_effect_record_snapshot(
    state: dict,
    tab_id: int,
    snapshot_hash: str,
) -> None:
    if not snapshot_hash:
        return
    _click_effect_snapshot_hashes(state)[str(tab_id)] = snapshot_hash


def _click_effect_last_snapshot_hash(state: dict, tab_id: int) -> str:
    hashes = state.get("control_snapshot_hashes")
    if not isinstance(hashes, dict):
        return ""
    return str(hashes.get(str(tab_id)) or "")


def _click_effect_record_click(
    state: dict,
    tab_id: int,
    ref: str,
    snapshot_hash: str,
) -> None:
    ref = str(ref or "").strip()
    if not ref:
        return

    key = str(tab_id)
    records = _click_effect_records(state)
    previous = records.get(key)
    previous_count = 0
    if isinstance(previous, dict) and previous.get("ref") == ref:
        previous_count = int(previous.get("consecutive_no_effect") or 0)

    records[key] = {
        "ref": ref,
        "snapshot_hash": str(snapshot_hash or ""),
        "consecutive_no_effect": previous_count,
        "pending": True,
    }


def _click_effect_reset(state: dict, tab_id: int) -> None:
    records = state.get("control_click_effects")
    if not isinstance(records, dict):
        return
    records.pop(str(tab_id), None)
    if not records:
        state.pop("control_click_effects", None)


def _click_effect_check(
    state: dict,
    tab_id: int,
    current_hash: str,
) -> tuple[bool, dict[str, Any]]:
    key = str(tab_id)
    records = state.get("control_click_effects")
    if not isinstance(records, dict):
        return False, {"no_effect": False}

    record = records.get(key)
    if not isinstance(record, dict) or not record.get("pending"):
        return False, {"no_effect": False}

    current_hash = str(current_hash or "")
    previous_hash = str(record.get("snapshot_hash") or "")
    if current_hash and previous_hash and current_hash == previous_hash:
        consecutive = int(record.get("consecutive_no_effect") or 0) + 1
        record["consecutive_no_effect"] = consecutive
        record["pending"] = False
        info = {
            "no_effect": True,
            "failed_ref": str(record.get("ref") or ""),
            "consecutive_no_effect": consecutive,
        }
        return consecutive >= 2, info

    _click_effect_reset(state, tab_id)
    return False, {"no_effect": False}


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
