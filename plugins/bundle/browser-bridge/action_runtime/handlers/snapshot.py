# -*- coding: utf-8 -*-
"""Canonical snapshot action handler."""
# pylint: disable=too-many-branches,too-many-statements

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from qwenpaw.browser.sdk.runtime.responses import _tool_response
from qwenpaw.browser.sdk.runtime.snapshot import ObservationBudget
from ..network_settle import _network_quiescence_wait
from ..observation import (
    _control_clear_observation_required,
    _control_clear_visual_observation,
)
from ..session_manager import _control_get_session
from ..snapshot_builder import build_canonical_snapshot
from ..ref_scope import (
    _control_bind_canonical_target,
    _control_note_canonical_document,
)
from ..state import ControlState
from ..tab_manager import _control_ensure_tab_available, _control_page_id
from ..navigation import _control_tab_id
from ..targets import (
    canonical_visual_backend_intersects_region,
    canonical_visual_candidate_backend_ids,
    canonical_visual_geometry_in_region,
    canonical_visual_target_is_current_hit,
)
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
        visual_region = kwargs.get("visual_region")
        raw_budget = kwargs.get("budget")
        budget = None
        if isinstance(visual_region, dict):
            raw_budget = visual_region.get("budget", raw_budget)
        if isinstance(raw_budget, dict):
            budget = ObservationBudget(
                capture_nodes=int(raw_budget["capture_nodes"]),
                output_targets=int(raw_budget["output_targets"]),
                hard_maximum=int(raw_budget["hard_maximum"]),
            )
        capture = await build_canonical_snapshot(session, budget=budget)
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
        if isinstance(visual_region, dict):
            payload = await _canonical_visual_grounding_payload(
                session,
                state=state,
                payload=payload,
                request=visual_region,
            )
        return _tool_response(
            json.dumps(payload, ensure_ascii=False, indent=2),
        )


def _canonical_snapshot_payload(
    state: ControlState,
    *,
    tab_id: int,
    request_context: dict[str, Any],
    capture: Any,
    observed_urls: dict[str, str] | None = None,
    include_trusted_bindings: bool = True,
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
            root_session_id=session_id,
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
            allowed_actions=("click", "hover", "drag")
            if target.executable
            else (),
            effect_ceiling=(
                ("PRESENTATION", "SESSION_STATE", "UNKNOWN")
                if target.executable
                else ()
            ),
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
    regions: list[dict[str, Any]] = []
    trusted_regions: dict[str, str] = {}
    for region in capture.regions:
        token = f"region_{uuid4().hex}"
        regions.append(
            {
                "kind": region.kind,
                "owner": region.owner,
                "owner_chain": list(region.owner_chain),
                "boundary": region.boundary,
                "accessible": region.accessible,
                "region_token": token,
            },
        )
        trusted_regions[token] = str(region.native_identity)
    payload = {
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
        "regions": regions,
    }
    if include_trusted_bindings:
        payload["_trusted_bindings"] = trusted_bindings
        payload["_trusted_regions"] = trusted_regions
    return payload


async def _canonical_visual_grounding_payload(
    session: Any,
    *,
    state: ControlState,
    payload: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """Keep every bounded hit candidate without proximity selection."""
    scoped_payload = await _canonical_visual_scope_payload(
        session,
        payload=payload,
        request=request,
    )
    if scoped_payload is None:
        return {
            **payload,
            "targets": [],
            "_trusted_bindings": {},
            "_trusted_surface_candidates": {},
        }
    payload = scoped_payload
    (
        grounding_state,
        _surface_backend_ids,
    ) = await canonical_visual_candidate_backend_ids(
        session,
        request,
    )
    if grounding_state in {"STALE", "UNAVAILABLE"}:
        return {
            **payload,
            "coverage": grounding_state,
            "targets": [],
            "_trusted_bindings": {},
            "_trusted_surface_candidates": {},
        }
    trusted = payload.get("_trusted_bindings")
    targets = payload.get("targets")
    if not isinstance(trusted, dict) or not isinstance(targets, list):
        return {**payload, "coverage": "UNAVAILABLE", "targets": []}
    selected: list[dict[str, Any]] = []
    selected_bindings: dict[str, dict[str, Any]] = {}
    surface_candidates: dict[str, dict[str, Any]] = {}
    surface_projection: list[dict[str, str]] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        token = str(target.get("binding_token") or "")
        binding = trusted.get(token)
        if not isinstance(binding, dict):
            continue
        native_id = _binding_backend_node_id(binding)
        if native_id is None:
            continue
        executable = bool(target.get("executable"))
        role = str(target.get("role") or "").lower()
        if not executable and role not in {"canvas", "map"}:
            continue
        geometry = await canonical_visual_geometry_in_region(
            session,
            native_id,
            request,
        )
        if geometry is None:
            continue
        if not await canonical_visual_target_is_current_hit(
            session,
            backend_id=native_id,
            point=geometry[1],
        ):
            continue
        action_state = dict(binding.get("action_state") or ())
        action_state.update(
            visible=True,
            stable=True,
            enabled=True,
        )
        enriched = {
            **binding,
            "action_state": tuple(action_state.items()),
            "geometry_digest": geometry[0],
            "visual_context_ref": str(
                request.get("visual_context_ref") or "",
            ),
            "visual_generation": str(request.get("generation") or ""),
            "visual_viewport": tuple(request.get("viewport") or ()),
            "visual_scroll": tuple(request.get("scroll") or ()),
            "visual_zoom": float(request.get("zoom") or 0),
            "visual_device_pixel_ratio": float(
                request.get("device_pixel_ratio") or 0,
            ),
            "visual_layout": tuple(request.get("layout") or ()),
            "single_use": True,
            "use_state": "FRESH",
        }
        if not executable:
            if (
                role not in {"canvas", "map"}
                or native_id not in _surface_backend_ids
            ):
                continue
            surface_identity = (
                f"{role}:{str(target.get('owner') or 'main')}:{native_id}"
            )
            enriched = {
                **enriched,
                "surface_origin": str(
                    request.get("_canonical_current_origin") or "",
                ),
                "surface_identity": surface_identity,
                "allowed_actions": (),
                "effect_ceiling": (),
            }
            surface_candidates[token] = enriched
            state.canonical_target_bindings[token] = enriched
            surface_projection.append({"binding_token": token})
            continue
        selected.append(target)
        selected_bindings[token] = enriched
        state.canonical_target_bindings[token] = enriched
    if len(selected) != 1:
        selected_bindings = {
            token: {
                **binding,
                "allowed_actions": (),
                "effect_ceiling": (),
            }
            for token, binding in selected_bindings.items()
        }
    for token, binding in selected_bindings.items():
        state.canonical_target_bindings[token] = binding
    if selected:
        surface_candidates = {}
        surface_projection = []
    return {
        **payload,
        "targets": selected,
        "surface_candidates": surface_projection,
        "_trusted_bindings": selected_bindings,
        "_trusted_surface_candidates": surface_candidates,
    }


async def _canonical_visual_scope_payload(
    session: Any,
    *,
    payload: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any] | None:
    """Discard only shadow omissions proven outside the requested region."""
    coverage = str(payload.get("coverage") or "UNAVAILABLE")
    if coverage == "COMPLETE":
        return payload
    if coverage != "PARTIAL":
        return None
    gaps = payload.get("gaps")
    if not isinstance(gaps, list) or not gaps or not all(
        _is_closed_shadow_gap(gap) for gap in gaps
    ):
        return None
    regions = payload.get("regions")
    if not isinstance(regions, list):
        return None
    closed_regions = [
        region
        for region in regions
        if isinstance(region, dict)
        and str(region.get("boundary") or "") == "CLOSED_SHADOW"
    ]
    if not closed_regions:
        return None
    trusted_regions = payload.get("_trusted_regions", {})
    if not isinstance(trusted_regions, dict):
        return None
    for region in closed_regions:
        backend_id = _region_backend_node_id(region, trusted_regions)
        if backend_id is None:
            return None
        intersects = await canonical_visual_backend_intersects_region(
            session,
            backend_id,
            request,
        )
        if intersects is not False:
            return None
    return {
        **payload,
        "coverage": "COMPLETE",
        "gaps": [],
        "regions": [
            region
            for region in regions
            if not (
                isinstance(region, dict)
                and str(region.get("boundary") or "")
                == "CLOSED_SHADOW"
            )
        ],
    }


def _is_closed_shadow_gap(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and str(value.get("stage") or "") == "CAPTURE"
        and str(value.get("source") or "") == "SHADOW"
        and str(value.get("reason") or "") == "CLOSED_SHADOW"
    )


def _region_backend_node_id(
    region: dict[str, Any],
    trusted_regions: dict[str, Any],
) -> int | None:
    native_identity = str(
        trusted_regions.get(str(region.get("region_token") or "")) or "",
    )
    backend_id = native_identity.removeprefix("backend:")
    return int(backend_id) if backend_id.isdigit() else None


def _binding_backend_node_id(binding: dict[str, Any]) -> int | None:
    for item in binding.get("native_identity", ()):
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and item[0] == "backendNodeId"
            and isinstance(item[1], int)
        ):
            return item[1]
    return None


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
