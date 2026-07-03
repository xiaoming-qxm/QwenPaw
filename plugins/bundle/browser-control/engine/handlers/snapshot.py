# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser_sdk._runtime import (
    _tool_response,
    _tool_response_with_blocks,
)
from ..network_settle import _network_quiescence_wait
from ..observation import (
    _click_effect_check,
    _click_effect_record_snapshot,
    _control_clear_observation_required,
    _control_clear_visual_observation,
)
from ..session_manager import _control_get_session
from ..snapshot_builder import (
    _control_escalation_payload,
    _control_snapshot_hash,
    _control_visual_context_block,
    build_control_snapshot,
)
from ..ref_scope import (
    _control_scope_snapshot_refs,
    _control_snapshot_payload_refs,
)
from ..state import ControlState
from ..state_verification import _control_state_verification_payload
from ..tab_manager import _control_ensure_tab_available, _control_page_id
from ..navigation import _control_tab_id
from .protocol import ActionMeta


@dataclass(frozen=True)
class SnapshotHandler:
    meta: ActionMeta = ActionMeta(True, False, False)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        await _control_ensure_tab_available(bridge, tab_id)
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=kwargs.get("request_context") or {},
        )
        if str(tab_id) in {str(item) for item in state.network_enabled_tabs}:
            await _network_quiescence_wait(
                session,
                bridge,
                state,
                tab_id,
                timeout=3.0,
                grace_ms=50.0,
            )
        snapshot, refs, degraded_snapshot = await build_control_snapshot(
            session,
        )
        snapshot_hash = _control_snapshot_hash(snapshot)
        snapshot, refs, ref_scope = _control_scope_snapshot_refs(
            state,
            tab_id,
            snapshot,
            refs,
        )
        escalated, escalation_info = _click_effect_check(
            state,
            tab_id,
            snapshot_hash,
        )
        _click_effect_record_snapshot(state, tab_id, snapshot_hash)
        state.refs[str(tab_id)] = refs
        _control_clear_observation_required(state, tab_id)
        _control_clear_visual_observation(state, tab_id)
        payload = {
            "ok": True,
            "mode": "control",
            "tab_id": tab_id,
            "snapshot": snapshot,
            "refs": _control_snapshot_payload_refs(refs),
        }
        if ref_scope:
            payload["ref_scope"] = ref_scope
        if escalated:
            payload["escalation"] = _control_escalation_payload(
                escalation_info,
            )
        if escalation_info.get("verification_pending"):
            network = escalation_info.get("network")
            payload[
                "state_verification"
            ] = _control_state_verification_payload(
                status="stale_view_possible",
                reason="previous_async_state_change_not_reflected_in_snapshot",
                network_metadata=network if isinstance(network, dict) else {},
            )
        blocks = []
        if degraded_snapshot or escalated:
            visual_block = await _control_visual_context_block(session)
            if visual_block is not None:
                blocks.append(visual_block)

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if blocks:
            return _tool_response_with_blocks(text, blocks)
        return _tool_response(text)


SNAPSHOT_HANDLER = SnapshotHandler()


__all__ = ["SNAPSHOT_HANDLER", "SnapshotHandler"]
