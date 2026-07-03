# -*- coding: utf-8 -*-
"""Browser Control observe-before-act helpers."""
# pylint: disable=too-many-return-statements

from __future__ import annotations

import copy
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from agentscope.tool import ToolChunk

from qwenpaw.agents.tools.browser.runtime import _tool_response
from .tab_manager import _CONTROL_MUTATING_ACTIONS

_ASYNC_WRITE_GUARD_TEMPLATE_PATH = (
    Path(__file__).with_name("templates") / "async_write_guard_response.json"
)


def _click_effect_records(state: dict) -> dict[str, Any]:
    records = state.get("control_click_effects")
    if not isinstance(records, dict):
        records = {}
        state["control_click_effects"] = records
    return records


def _click_effect_snapshot_hashes(state: dict) -> dict[str, str]:
    hashes = state.get("control_snapshot_hashes")
    if not isinstance(hashes, dict):
        hashes = {}
        state["control_snapshot_hashes"] = hashes
    return hashes


def _control_visual_observation_records(state: dict) -> dict[str, Any]:
    records = state.get("control_visual_observations")
    if not isinstance(records, dict):
        records = {}
        state["control_visual_observations"] = records
    return records


def _control_mark_visual_observation(
    state: dict,
    tab_id: int,
    *,
    source: str,
) -> None:
    _control_visual_observation_records(state)[str(tab_id)] = {
        "tab_id": tab_id,
        "source": str(source or "visual"),
        "created_at": time.time(),
    }


def _control_clear_visual_observation(state: dict, tab_id: int) -> None:
    records = state.get("control_visual_observations")
    if not isinstance(records, dict):
        return
    records.pop(str(tab_id), None)
    if not records:
        state.pop("control_visual_observations", None)


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
    network_metadata: dict[str, Any] | None = None,
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

    record: dict[str, Any] = {
        "ref": ref,
        "snapshot_hash": str(snapshot_hash or ""),
        "consecutive_no_effect": previous_count,
        "pending": True,
    }
    if (
        isinstance(network_metadata, dict)
        and int(
            network_metadata.get("async_requests_triggered") or 0,
        )
        > 0
    ):
        record["network"] = {
            "async_requests_triggered": int(
                network_metadata.get("async_requests_triggered") or 0,
            ),
            "settled": bool(network_metadata.get("settled")),
            "timed_out": bool(network_metadata.get("timed_out")),
        }
    records[key] = record


@lru_cache(maxsize=1)
def _load_async_write_guard_template() -> dict[str, Any]:
    return json.loads(
        _ASYNC_WRITE_GUARD_TEMPLATE_PATH.read_text(encoding="utf-8"),
    )


def _control_async_write_guard_response(
    *,
    tab_id: int,
    target_ref: str,
    network: dict[str, Any],
) -> ToolChunk:
    async_requests = int(network.get("async_requests_triggered") or 0)
    payload = copy.deepcopy(_load_async_write_guard_template())
    payload["tab_id"] = tab_id
    payload["message"] = str(payload["message"]).format(
        target_ref_repr=repr(target_ref),
        async_requests=async_requests,
    )
    payload["blocked_ref"] = target_ref
    payload["previous_network"] = {
        "async_requests_triggered": async_requests,
        "settled": bool(network.get("settled")),
        "timed_out": bool(network.get("timed_out")),
    }
    return _tool_response(json.dumps(payload, ensure_ascii=False, indent=2))


def _control_async_write_guard(
    state: dict,
    tab_id: int,
    target_ref: str,
) -> ToolChunk | None:
    """Block duplicate clicks on an unverified async write target."""
    target_ref = str(target_ref or "").strip()
    if not target_ref:
        return None

    records = state.get("control_click_effects")
    if not isinstance(records, dict):
        return None
    record = records.get(str(tab_id))
    if not isinstance(record, dict):
        return None
    if str(record.get("ref") or "") != target_ref:
        return None

    network = record.get("network")
    if not isinstance(network, dict):
        return None
    if int(network.get("async_requests_triggered") or 0) <= 0:
        return None

    return _control_async_write_guard_response(
        tab_id=tab_id,
        target_ref=target_ref,
        network=network,
    )


def _control_coordinate_click_loop_guard_response(
    *,
    tab_id: int,
    target_ref: str,
    consecutive_no_effect: int,
) -> ToolChunk:
    payload = {
        "ok": False,
        "mode": "control",
        "tab_id": tab_id,
        "error": "coordinate_click_loop_guard",
        "message": (
            "A previous raw coordinate click at this nearby point was "
            "observed with no page change."
        ),
        "blocked_ref": target_ref,
        "consecutive_no_effect": consecutive_no_effect,
        "needs_observation": True,
        "next_action": "snapshot",
        "next_instruction": (
            "Do not repeat raw coordinate clicks at the same point. Use a "
            "fresh snapshot target by ref/text/selector, navigate directly "
            "when the destination URL is known, choose a different semantic "
            "target, or report that the page does not expose a reliable "
            "Browser Control target."
        ),
        "use_instead": [
            "snapshot",
            "click(ref=...)",
            "click(text=...)",
            "click(selector=...)",
            "navigate(url=...)",
        ],
    }
    return _tool_response(json.dumps(payload, ensure_ascii=False, indent=2))


def _control_visual_coordinate_click_guard_response(
    *,
    tab_id: int,
    target_ref: str,
    source: str,
) -> ToolChunk:
    payload = {
        "ok": False,
        "mode": "control",
        "tab_id": tab_id,
        "error": "visual_coordinate_click_guard",
        "message": (
            "The latest observation for this tab was a screenshot. "
            "Screenshot-derived coordinates are visual context only and "
            "cannot be used for raw coordinate clicks."
        ),
        "blocked_ref": target_ref,
        "visual_observation": {
            "source": source or "screenshot",
        },
        "needs_observation": True,
        "next_action": "snapshot",
        "next_instruction": (
            "Take a fresh snapshot and activate a structured "
            "ref/text/selector target. If the required control is not exposed "
            "as a reliable Browser Control target, choose a different real "
            "route or report a blocker instead of converting the screenshot "
            "into x/y coordinates."
        ),
        "use_instead": [
            "snapshot",
            "click(ref=...)",
            "click(text=...)",
            "click(selector=...)",
            "navigate(url=...)",
        ],
    }
    return _tool_response(json.dumps(payload, ensure_ascii=False, indent=2))


def _control_visual_coordinate_click_guard(
    state: dict,
    tab_id: int,
    target_ref: str,
) -> ToolChunk | None:
    """Block raw coordinate clicks immediately after visual observation."""
    target_ref = str(target_ref or "").strip()
    if not target_ref.startswith("point:"):
        return None

    records = state.get("control_visual_observations")
    if not isinstance(records, dict):
        return None
    record = records.get(str(tab_id))
    if not isinstance(record, dict):
        return None
    source = str(record.get("source") or "screenshot")
    return _control_visual_coordinate_click_guard_response(
        tab_id=tab_id,
        target_ref=target_ref,
        source=source,
    )


def _control_repeated_no_effect_record(
    state: dict,
    tab_id: int,
    target_ref: str,
) -> tuple[dict[str, Any], int] | None:
    target_ref = str(target_ref or "").strip()
    if not target_ref:
        return None

    records = state.get("control_click_effects")
    if not isinstance(records, dict):
        return None
    record = records.get(str(tab_id))
    if not isinstance(record, dict):
        return None
    if str(record.get("ref") or "") != target_ref:
        return None

    network = record.get("network")
    if (
        isinstance(network, dict)
        and int(network.get("async_requests_triggered") or 0) > 0
    ):
        return None

    consecutive = int(record.get("consecutive_no_effect") or 0)
    if consecutive <= 0 or bool(record.get("pending")):
        return None
    return record, consecutive


def _control_coordinate_click_loop_guard(
    state: dict,
    tab_id: int,
    target_ref: str,
) -> ToolChunk | None:
    """Block repeated raw coordinate clicks after an observed no-op."""
    target_ref = str(target_ref or "").strip()
    if not target_ref.startswith("point:"):
        return None

    record = _control_repeated_no_effect_record(state, tab_id, target_ref)
    if record is None:
        return None

    _, consecutive = record

    return _control_coordinate_click_loop_guard_response(
        tab_id=tab_id,
        target_ref=target_ref,
        consecutive_no_effect=consecutive,
    )


def _control_scroll_action_loop_guard_response(
    *,
    tab_id: int,
    target_ref: str,
    consecutive_no_effect: int,
) -> ToolChunk:
    payload = {
        "ok": False,
        "mode": "control",
        "tab_id": tab_id,
        "error": "scroll_action_loop_guard",
        "message": (
            "A previous scroll with the same direction and amount was "
            "observed with no page change."
        ),
        "blocked_ref": target_ref,
        "consecutive_no_effect": consecutive_no_effect,
        "needs_observation": True,
        "next_action": "snapshot",
        "next_instruction": (
            "Do not repeat ineffective scrolls. Use the current snapshot's "
            "refs/action targets, try an absolute top/bottom jump once, "
            "navigate directly to a canonical page, or report the blocker if "
            "the page does not expose the needed control."
        ),
        "use_instead": [
            "snapshot",
            "click(ref=...)",
            "click(text=...)",
            "scroll(direction='down', amount='bottom')",
            "navigate(url=...)",
        ],
    }
    return _tool_response(json.dumps(payload, ensure_ascii=False, indent=2))


def _control_scroll_action_loop_guard(
    state: dict,
    tab_id: int,
    target_ref: str,
) -> ToolChunk | None:
    """Block repeated same scrolls after an observed no-op."""
    target_ref = str(target_ref or "").strip()
    if not target_ref.startswith("scroll:"):
        return None

    record = _control_repeated_no_effect_record(state, tab_id, target_ref)
    if record is None:
        return None

    _, consecutive = record
    return _control_scroll_action_loop_guard_response(
        tab_id=tab_id,
        target_ref=target_ref,
        consecutive_no_effect=consecutive,
    )


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
    if not isinstance(record, dict):
        return False, {"no_effect": False}

    current_hash = str(current_hash or "")
    previous_hash = str(record.get("snapshot_hash") or "")
    network = record.get("network")
    async_requests = (
        int(network.get("async_requests_triggered") or 0)
        if isinstance(network, dict)
        else 0
    )
    network_payload = network if isinstance(network, dict) else {}

    if not record.get("pending"):
        if (
            async_requests <= 0
            and current_hash
            and previous_hash
            and current_hash != previous_hash
        ):
            _click_effect_reset(state, tab_id)
        return False, {"no_effect": False}

    if current_hash and previous_hash and current_hash == previous_hash:
        consecutive = int(record.get("consecutive_no_effect") or 0) + 1
        record["consecutive_no_effect"] = consecutive
        record["pending"] = False
        info = {
            "no_effect": True,
            "failed_ref": str(record.get("ref") or ""),
            "consecutive_no_effect": consecutive,
        }
        if async_requests > 0:
            info["verification_pending"] = True
            info["network"] = dict(network_payload)
        return consecutive >= 2, info

    if async_requests > 0 and network_payload:
        record["pending"] = False
        return False, {
            "no_effect": False,
            "failed_ref": str(record.get("ref") or ""),
            "verification_pending": True,
            "changed_after_async_write": True,
            "network": dict(network_payload),
        }

    _click_effect_reset(state, tab_id)
    return False, {"no_effect": False}


def _control_pending_observations(state: dict) -> dict[str, Any]:
    pending = state.get("control_pending_observations")
    if not isinstance(pending, dict):
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
                "error": (
                    "Fresh observation required. Observe the current page "
                    "with snapshot before taking another mutating browser "
                    "action. Use screenshot only as visual context when "
                    "snapshot cannot describe the page; do not turn a "
                    "screenshot into repeated raw coordinate clicks."
                ),
                "after_action": after_action,
                "next_action": "snapshot",
                "needs_observation": True,
                "next_instruction": (
                    "The previous browser action may have changed the page. "
                    "Observe the current page with snapshot before taking "
                    "another click, type, or key action. Prefer "
                    "ref/text/selector targets from the snapshot for "
                    "state-changing actions."
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


__all__ = [
    "_click_effect_check",
    "_click_effect_last_snapshot_hash",
    "_click_effect_record_click",
    "_click_effect_record_snapshot",
    "_click_effect_records",
    "_click_effect_reset",
    "_click_effect_snapshot_hashes",
    "_control_async_write_guard",
    "_control_clear_observation_required",
    "_control_clear_visual_observation",
    "_control_coordinate_click_loop_guard",
    "_control_coordinate_click_loop_guard_response",
    "_control_mark_observation_required",
    "_control_mark_visual_observation",
    "_control_observation_required_response",
    "_control_pending_observations",
    "_control_require_observation_before_action",
    "_control_repeated_no_effect_record",
    "_control_scroll_action_loop_guard",
    "_control_scroll_action_loop_guard_response",
    "_control_visual_coordinate_click_guard",
    "_control_visual_coordinate_click_guard_response",
]
