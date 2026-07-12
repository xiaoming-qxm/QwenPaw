# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.sdk.runtime.responses import (
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
    build_canonical_snapshot,
    build_control_snapshot,
)
from ..ref_scope import (
    _control_bind_canonical_target,
    _control_note_canonical_document,
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
        request_context = kwargs.get("request_context") or {}
        contract_mode = str(request_context.get("contract_mode") or "LEGACY")
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
            request_context=request_context,
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
        if contract_mode == "CANONICAL":
            capture = await build_canonical_snapshot(session)
            _control_clear_observation_required(state, tab_id)
            _control_clear_visual_observation(state, tab_id)
            payload = _canonical_snapshot_payload(
                state,
                tab_id=tab_id,
                request_context=request_context,
                capture=capture,
                observed_urls=getattr(
                    session,
                    "_canonical_observed_urls",
                    {},
                ),
            )
            return _tool_response(
                json.dumps(payload, ensure_ascii=False, indent=2),
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


def _canonical_snapshot_payload(
    state: ControlState,
    *,
    tab_id: int,
    request_context: dict[str, Any],
    capture: Any,
    observed_urls: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build safe evidence plus a private trusted binding side channel."""
    root_task_id = str(request_context.get("root_task_id") or "").strip()
    browser_owner_id = str(
        request_context.get("browser_owner_id") or "",
    ).strip()
    session_id = str(
        request_context.get("root_session_id")
        or request_context.get("session_id")
        or "",
    ).strip()
    if not root_task_id or not browser_owner_id or not session_id:
        raise ValueError("canonical_snapshot_owner_missing")
    context = _control_note_canonical_document(
        state,
        tab_id=tab_id,
        document_token=str(capture.generation),
    )
    targets: list[dict[str, Any]] = []
    trusted_bindings: dict[str, dict[str, Any]] = {}
    observed_urls = observed_urls or {}
    for target in capture.targets:
        native_identity = _canonical_native_identity(
            str(target.native_identity),
        )
        token = _control_bind_canonical_target(
            state,
            owner_key=(root_task_id, browser_owner_id),
            tab_id=tab_id,
            frame_key=str(target.owner),
            context=context,
            native_identity=native_identity,
            action_state=tuple(
                [("executable", bool(target.executable))]
                + [(str(item), True) for item in target.states],
            ),
            geometry_digest="",
            visual_context_ref=None,
            allowed_actions=("click",) if target.executable else (),
            effect_ceiling=("DOM_INPUT",) if target.executable else (),
        )
        binding = state.canonical_target_bindings[token]
        trusted_bindings[token] = {
            **binding,
            "root_task_id": root_task_id,
            "browser_owner_id": browser_owner_id,
            "session_id": session_id,
            "backend_id": "user",
        }
        targets.append(
            {
                "binding_token": token,
                "owner": target.owner,
                "role": target.role,
                "name": target.name,
                "states": list(target.states),
                "sources": list(target.sources),
                "identity_conflict": target.identity_conflict,
                "executable": target.executable,
                "observed_url": (
                    observed_urls.get(str(target.native_identity))
                    if target.role == "link"
                    else None
                ),
            },
        )
    return {
        "ok": capture.coverage not in {"UNAVAILABLE", "STALE"},
        "mode": "canonical",
        "tab_id": tab_id,
        "generation": capture.generation,
        "coverage": capture.coverage,
        "gaps": [_canonical_gap_payload(gap) for gap in capture.gaps],
        "sources": [
            {
                "source": outcome.source,
                "available": outcome.available,
                "examined": outcome.examined,
                "error_code": outcome.error_code,
            }
            for outcome in capture.sources
        ],
        "context": dict(context),
        "targets": targets,
        "_trusted_bindings": trusted_bindings,
    }


def _canonical_native_identity(
    value: str,
) -> tuple[tuple[str, str | int], ...]:
    if value.startswith("backend:"):
        backend_id = value.removeprefix("backend:")
        if backend_id.isdigit():
            return (("backendNodeId", int(backend_id)),)
    if not value:
        raise ValueError("canonical_snapshot_native_identity_missing")
    return (("nativeIdentity", value),)


def _canonical_gap_payload(gap: Any) -> dict[str, Any]:
    """Project only closed, model-visible omission facts."""
    detail = gap.detail
    payload: dict[str, Any] = {
        "stage": gap.stage,
        "source": getattr(detail, "source", ""),
        "reason": detail.reason,
        "examined": detail.examined,
        "omitted": detail.omitted,
    }
    frontier = getattr(detail, "frontier", None)
    if frontier:
        payload["frontier"] = frontier
    return payload


SNAPSHOT_HANDLER = SnapshotHandler()


__all__ = ["SNAPSHOT_HANDLER", "SnapshotHandler"]
