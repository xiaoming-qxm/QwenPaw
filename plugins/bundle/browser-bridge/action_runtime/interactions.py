# -*- coding: utf-8 -*-
"""Interaction helpers for Browser Bridge typed handlers."""
# pylint: disable=too-many-branches,too-many-statements
# pylint: disable=too-many-return-statements,protected-access

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from time import monotonic
from typing import Any
from urllib.parse import urljoin, urlsplit

from qwenpaw.browser.sdk.action_runner import DispatchContext
from qwenpaw.browser.sdk.governance.errors import BrowserSDKError
from qwenpaw.browser.sdk.governance.policy import (
    trusted_surface_rule_fingerprint,
)
from qwenpaw.browser.sdk.runtime.responses import _tool_response
from .navigation import (
    _control_remember_approved_navigation,
    _control_sync_session_navigation_scope,
    _control_tab_id,
    _control_url_key,
)
from .network_settle import (
    _network_quiescence_monitor as _default_network_monitor,
    _network_quiescence_wait as _default_network_wait,
)
from .observation import (
    _click_effect_last_snapshot_hash,
    _click_effect_record_click,
    _control_async_write_guard,
    _control_coordinate_click_loop_guard,
    _control_visual_coordinate_click_guard,
    _control_mark_observation_required,
)
from .ref_scope import (
    _control_canonical_binding_status,
    _control_current_snapshot_ref,
    _require_canonical_binding,
)
from .session_manager import _control_get_session
from .state import ControlState, StateMapping
from .state_verification import _control_state_verification_payload
from .coordinates import (
    _control_coordinate_space_payload,
    _control_point_tracking_ref,
    _control_validate_viewport_coordinates,
)
from .errors import TargetResolutionFailed
from .tab_manager import (
    _control_ensure_tab_available,
    _control_discover_tabs_safe,
    _control_int_tab_id,
    _control_is_http_url,
    _control_live_tab_map,
    _control_page_id,
    _control_refresh_tab_url,
    _control_tab_url,
)
from .targets import (
    canonical_live_target_point,
    _control_click_at,
    _control_press_key,
    _control_prepare_silent_new_context_at_point,
    _control_resolve_point,
    _control_selector_target,
    _control_show_keyboard,
    _control_snap_to_element,
    _control_text_target,
    _control_viewport_size,
)
from .transitions import (
    _control_create_action_transition_waiter,
    _control_resolve_action_transition,
)

_network_quiescence_wait_impl: Any = _default_network_wait
_network_quiescence_monitor_impl: Any = _default_network_monitor


class _DeferredNetworkWaitMonitor:
    """Adapter for tests or callers that still inject a wait coroutine."""

    def __init__(
        self,
        wait_func: Any,
        session: Any,
        bridge: Any,
        state: StateMapping,
        tab_id: int,
    ) -> None:
        self._wait_func = wait_func
        self._session = session
        self._bridge = bridge
        self._state = state
        self._tab_id = tab_id

    async def wait(self) -> dict[str, Any]:
        return await self._wait_func(
            self._session,
            self._bridge,
            self._state,
            self._tab_id,
        )

    def close(self) -> None:
        return None


def _json_response(payload: dict[str, Any]):
    return _tool_response(json.dumps(payload, ensure_ascii=False, indent=2))


def _canonical_runner_request(request_context: dict[str, Any]) -> bool:
    """Return whether S3 owns all condition truth for this command."""
    return (
        bool(request_context.get("canonical_dispatch_context"))
        or str(
            request_context.get("contract_mode") or "",
        ).upper()
        == "CANONICAL"
    )


def _canonical_raw_command_hint(tab_id: int, action: str):
    """Emit no postcondition truth from the Bridge interaction helper."""
    return _json_response(
        {
            "ok": True,
            "mode": "control",
            "tab_id": tab_id,
            "action": action,
            "raw_change_hint": True,
            "condition_truth": "NOT_EVALUATED",
        },
    )


_CANONICAL_FORBIDDEN_TARGET_KEYS = {
    "selector",
    "x",
    "y",
    "native_id",
    "nativeId",
    "backendNodeId",
    "nodeId",
}


async def _canonical_execute_interaction(
    state: ControlState,
    *,
    action: str,
    target_labels: tuple[str, ...],
    kwargs: dict[str, Any],
    injector: Callable[
        [tuple[dict[str, object], ...], dict[str, object]],
        Awaitable[object],
    ],
) -> dict[str, object]:
    """Validate exact native bindings, then inject once in the same turn."""
    request_context = kwargs.get("request_context")
    context = (
        request_context.get("canonical_dispatch_context")
        if isinstance(request_context, Mapping)
        else None
    )
    if not isinstance(context, DispatchContext):
        raise BrowserSDKError(
            "Canonical interaction requires a trusted DispatchContext",
            code="canonical_dispatch_context_missing",
        )
    if any(
        key in kwargs and kwargs.get(key) not in (None, "")
        for key in _CANONICAL_FORBIDDEN_TARGET_KEYS
    ):
        raise BrowserSDKError(
            "Canonical interaction cannot use selector or coordinates",
            code="canonical_target_escape_forbidden",
        )
    target_tokens = kwargs.get("_canonical_target_tokens")
    native_facts = kwargs.get("_canonical_native_facts")
    surface_policy_facts = kwargs.get("_canonical_surface_policy_facts", {})
    if not isinstance(target_tokens, Mapping) or not isinstance(
        native_facts,
        Mapping,
    ) or not isinstance(surface_policy_facts, Mapping):
        raise BrowserSDKError(
            "Canonical native target facts are unavailable",
            code="target_binding_invalid",
        )
    owner_key = (context.root_task_id, context.browser_owner_id)
    try:
        receiver_tab = int(context._receiver_tab_key)
    except (TypeError, ValueError) as exc:
        raise BrowserSDKError(
            "Canonical receiver tab is invalid",
            code="target_wrong_receiver",
        ) from exc
    prepared: list[dict[str, object]] = []
    seen_tokens: set[str] = set()
    normalized_action = str(action or "").strip()
    for label in target_labels:
        token = str(target_tokens.get(label) or "")
        if not token or token in seen_tokens:
            raise BrowserSDKError(
                "Canonical ordered target binding is invalid",
                code="target_binding_invalid",
            )
        binding = _require_canonical_binding(state, token)
        native_identity = native_facts.get(label)
        if not isinstance(native_identity, tuple):
            raise BrowserSDKError(
                "Canonical current native identity is unavailable",
                code="target_unavailable",
            )
        status = _control_canonical_binding_status(
            state,
            token=token,
            owner_key=owner_key,
            receiver_tab=receiver_tab,
            current_native_identity=native_identity,
            visual=bool(binding.get("visual_context_ref")),
        )
        if status != "VALID":
            raise BrowserSDKError(
                "Canonical target changed before native injection",
                code="target_stale",
            )
        _validate_canonical_surface(binding)
        surface_policy = _validated_surface_policy_facts(
            surface_policy_facts.get(label),
            context=context,
            action=normalized_action,
        )
        _validate_canonical_actionability(
            binding,
            normalized_action,
            policy_authorized=surface_policy is not None,
        )
        _validate_canonical_effect_ceiling(
            binding,
            context,
            ceiling_override=(
                surface_policy.get("effect_ceiling")
                if surface_policy is not None
                else None
            ),
        )
        prepared.append(
            {
                "label": label,
                "token": token,
                "frame_key": str(binding.get("frame_key") or ""),
                "native_identity": tuple(native_identity),
                "geometry_digest": str(
                    binding.get("geometry_digest") or "",
                ),
                "surface_origin": (
                    str(surface_policy.get("origin") or "")
                    if surface_policy is not None
                    else ""
                ),
                "surface_identity": (
                    str(surface_policy.get("surface_identity") or "")
                    if surface_policy is not None
                    else ""
                ),
                "surface_policy_revision": (
                    str(surface_policy.get("revision") or "")
                    if surface_policy is not None
                    else ""
                ),
            },
        )
        seen_tokens.add(token)
    arguments = {
        key: value
        for key, value in kwargs.items()
        if key
        not in {
            "request_context",
            "_canonical_target_tokens",
            "_canonical_native_facts",
            "_canonical_surface_policy_facts",
        }
        and key not in _CANONICAL_FORBIDDEN_TARGET_KEYS
    }
    native_result = await injector(tuple(prepared), arguments)
    result: dict[str, object] = {
        "ok": True,
        "action": normalized_action,
        "raw_change_hint": True,
        "condition_truth": "NOT_EVALUATED",
    }
    if isinstance(native_result, Mapping):
        result.update(
            {
                str(key): value
                for key, value in native_result.items()
                if str(key) not in {"condition_truth"}
            },
        )
    return result


def _validate_canonical_surface(binding: Mapping[str, object]) -> None:
    frame_key = str(binding.get("frame_key") or "")
    invalid_markers = ("detached", "replaced", "closed", "cross-origin")
    valid = (
        frame_key == "main"
        or frame_key.startswith("frame:")
        or frame_key.startswith("shadow:open:")
    )
    if not valid or any(
        marker in frame_key.lower() for marker in invalid_markers
    ):
        raise BrowserSDKError(
            "Canonical target surface is unavailable",
            code="target_unavailable",
        )


def _validate_canonical_actionability(
    binding: Mapping[str, object],
    action: str,
    *,
    policy_authorized: bool = False,
) -> None:
    raw_allowed = binding.get("allowed_actions", ())
    if not isinstance(raw_allowed, (tuple, list)):
        raise BrowserSDKError(
            "Canonical allowed-action binding is invalid",
            code="target_binding_invalid",
        )
    allowed = tuple(str(item) for item in raw_allowed)
    aliases = {
        "fill": "type",
        "type_text": "type",
        "set_checked": "click",
    }
    accepted = {action, aliases.get(action, action)}
    if not accepted.intersection(allowed) and not policy_authorized:
        raise BrowserSDKError(
            "Canonical action is not allowed by the target binding",
            code="target_action_forbidden",
        )
    raw_states = binding.get("action_state", ())
    if not isinstance(raw_states, (tuple, list)):
        raise BrowserSDKError(
            "Canonical action-state binding is invalid",
            code="target_binding_invalid",
        )
    states = dict(raw_states)
    required = {"visible", "stable"}
    if action not in {"hover", "scroll"}:
        required.add("enabled")
    if action in {"fill", "type_text"}:
        required.add("editable")
    if any(states.get(name) is not True for name in required):
        raise BrowserSDKError(
            "Canonical target is not actionable",
            code="target_not_actionable",
        )


def _validate_canonical_effect_ceiling(
    binding: Mapping[str, object],
    context: DispatchContext,
    *,
    ceiling_override: object = None,
) -> None:
    raw_ceiling = (
        binding.get("effect_ceiling", ())
        if ceiling_override is None
        else ceiling_override
    )
    if not isinstance(raw_ceiling, (tuple, list)):
        raise BrowserSDKError(
            "Canonical effect ceiling binding is invalid",
            code="target_binding_invalid",
        )
    ceiling = {str(item) for item in raw_ceiling}
    effects = {str(item) for item in context.classified_effects}
    if effects and not effects.issubset(ceiling):
        raise BrowserSDKError(
            "Canonical target effect ceiling is insufficient",
            code="effect_ceiling_mismatch",
        )


def _validated_surface_policy_facts(
    raw: object,
    *,
    context: DispatchContext,
    action: str,
) -> dict[str, object] | None:
    proof_refs = tuple(
        item
        for item in str(context.effect_proof_ref or "").split("|")
        if item
    )
    if raw is None:
        if proof_refs:
            raise BrowserSDKError(
                "Canonical surface policy facts are unavailable",
                code="effect_proof_invalid",
            )
        return None
    if not isinstance(raw, Mapping):
        raise BrowserSDKError(
            "Canonical surface policy facts are invalid",
            code="effect_proof_invalid",
        )
    origin = str(raw.get("origin") or "")
    surface_identity = str(raw.get("surface_identity") or "")
    revision = str(raw.get("revision") or "")
    evidence_ref = str(raw.get("evidence_ref") or "")
    ceiling = raw.get("effect_ceiling")
    expires_at = raw.get("expires_at")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not surface_identity
        or not revision
        or not isinstance(ceiling, (tuple, list))
        or not ceiling
        or any(
            str(item) not in {"PRESENTATION", "SESSION_STATE"}
            for item in ceiling
        )
    ):
        raise BrowserSDKError(
            "Canonical surface policy proof does not match",
            code="effect_proof_invalid",
        )
    try:
        fingerprint = trusted_surface_rule_fingerprint(
            origin=origin.rstrip("/"),
            surface_identity=surface_identity,
            action=action,
            revision=revision,
            evidence_ref=evidence_ref,
            effect_ceiling=tuple(str(item) for item in ceiling),
            expires_at=float(expires_at),
        )
    except BrowserSDKError as exc:
        raise BrowserSDKError(
            "Canonical surface policy proof does not match",
            code="effect_proof_invalid",
        ) from exc
    if fingerprint not in proof_refs:
        raise BrowserSDKError(
            "Canonical surface policy proof does not match",
            code="effect_proof_invalid",
        )
    if monotonic() >= float(expires_at):
        raise BrowserSDKError(
            "Canonical surface policy proof expired",
            code="surface_policy_expired",
        )
    return {
        "origin": origin.rstrip("/"),
        "surface_identity": surface_identity,
        "revision": revision,
        "evidence_ref": evidence_ref,
        "effect_ceiling": tuple(str(item) for item in ceiling),
        "expires_at": float(expires_at),
    }


async def _canonical_set_checked_decision(
    *,
    current: bool,
    requested: bool,
) -> str:
    """Return the no-send ensure decision for an exact checked state."""
    if not isinstance(current, bool) or not isinstance(requested, bool):
        raise TypeError("checked state must be boolean")
    return "ALREADY_SATISFIED" if current == requested else "INJECT"


async def canonical_interaction_control(
    state: ControlState,
    *,
    action: str,
    target_labels: tuple[str, ...],
    kwargs: dict[str, Any],
):
    """Run a Canonical handler through its private native injector seam."""
    injector = kwargs.get("_canonical_native_injector")
    if not callable(injector):
        raise BrowserSDKError(
            "Canonical native injector is unavailable",
            code="canonical_native_injector_missing",
        )
    result = await _canonical_execute_interaction(
        state,
        action=action,
        target_labels=target_labels,
        kwargs=kwargs,
        injector=injector,
    )
    return _json_response(result)


async def canonical_native_interaction_control(
    state: ControlState,
    *,
    holder_id: str,
    bridge: Any,
    action: str,
    target_labels: tuple[str, ...],
    kwargs: dict[str, Any],
):
    """Own live target revalidation and pointer injection in one handler."""
    request_context = kwargs.get("request_context")
    context = (
        request_context.get("canonical_dispatch_context")
        if isinstance(request_context, Mapping)
        else None
    )
    if not isinstance(context, DispatchContext):
        raise BrowserSDKError(
            "Canonical interaction requires a trusted DispatchContext",
            code="canonical_dispatch_context_missing",
        )
    try:
        tab_id = int(context._receiver_tab_key)
    except (TypeError, ValueError) as exc:
        raise BrowserSDKError(
            "Canonical receiver tab is invalid",
            code="target_wrong_receiver",
        ) from exc
    await _control_ensure_tab_available(bridge, tab_id)
    session = await _control_get_session(
        state,
        tab_id=tab_id,
        holder_id=holder_id,
        bridge=bridge,
        request_context=request_context,
    )

    async def inject(
        prepared: tuple[dict[str, object], ...],
        arguments: dict[str, object],
    ) -> object:
        points: list[tuple[float, float]] = []
        bindings: list[dict[str, Any]] = []
        for item in prepared:
            binding = _require_canonical_binding(
                state,
                str(item.get("token") or ""),
            )
            live_binding = dict(binding)
            surface_origin = str(item.get("surface_origin") or "")
            if surface_origin:
                live_binding["surface_origin"] = surface_origin
                live_binding["surface_identity"] = str(
                    item.get("surface_identity") or "",
                )
                live_binding["surface_policy_revision"] = str(
                    item.get("surface_policy_revision") or "",
                )
            point = await canonical_live_target_point(session, live_binding)
            if point is None:
                raise BrowserSDKError(
                    "Canonical target changed before native input",
                    code="target_stale",
                )
            points.append(point)
            bindings.append(binding)
        for binding in bindings:
            if bool(binding.get("single_use")):
                if binding.get("use_state") != "FRESH":
                    raise BrowserSDKError(
                        "Canonical target was already consumed",
                        code="target_stale",
                    )
                binding["use_state"] = "CONSUMED"
        await _dispatch_canonical_pointer(
            session,
            action=action,
            points=tuple(points),
            arguments=arguments,
        )
        return {"tab_id": tab_id}

    result = await _canonical_execute_interaction(
        state,
        action=action,
        target_labels=target_labels,
        kwargs=kwargs,
        injector=inject,
    )
    return _json_response(result)


async def _dispatch_canonical_pointer(
    session: Any,
    *,
    action: str,
    points: tuple[tuple[float, float], ...],
    arguments: dict[str, object],
) -> None:
    if action == "hover" and len(points) == 1:
        await session.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": points[0][0],
                "y": points[0][1],
                "button": "none",
            },
        )
        return
    if action == "drag" and len(points) == 2:
        source, destination = points
        await session.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": source[0],
                "y": source[1],
                "button": "left",
                "clickCount": 1,
            },
        )
        await session.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": destination[0],
                "y": destination[1],
                "button": "left",
                "buttons": 1,
            },
        )
        await session.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": destination[0],
                "y": destination[1],
                "button": "left",
                "clickCount": 1,
            },
        )
        return
    if action != "click" or len(points) != 1:
        raise BrowserSDKError(
            "Canonical pointer action shape is invalid",
            code="interaction_action_invalid",
        )
    buttons = {
        "primary": "left",
        "secondary": "right",
        "middle": "middle",
    }
    button = buttons.get(str(arguments.get("button") or "primary"))
    count = arguments.get("count", 1)
    if button is None or count not in {1, 2}:
        raise BrowserSDKError(
            "Canonical click arguments are invalid",
            code="interaction_action_invalid",
        )
    modifiers = _canonical_modifier_mask(arguments.get("modifiers"))
    for event_type in ("mousePressed", "mouseReleased"):
        await session.send(
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": points[0][0],
                "y": points[0][1],
                "button": button,
                "clickCount": int(count),
                "modifiers": modifiers,
            },
        )


def _canonical_modifier_mask(raw: object) -> int:
    values = tuple(raw) if isinstance(raw, (tuple, list)) else ()
    if len(set(values)) != len(values):
        raise BrowserSDKError(
            "Canonical click modifiers are invalid",
            code="interaction_action_invalid",
        )
    bits = {"alt": 1, "control": 2, "meta": 4, "shift": 8}
    if any(value not in bits for value in values):
        raise BrowserSDKError(
            "Canonical click modifiers are invalid",
            code="interaction_action_invalid",
        )
    return sum(bits[value] for value in values)


async def canonical_paste_control(
    state: ControlState,
    *,
    kwargs: dict[str, Any],
    injector: Callable[
        [tuple[dict[str, object], ...], dict[str, object]],
        Awaitable[object],
    ],
):
    """Final-revalidate and inject one controlled target paste."""
    result = await _canonical_execute_interaction(
        state,
        action="paste",
        target_labels=("target",),
        kwargs=kwargs,
        injector=injector,
    )
    return _json_response(result)


def _control_link_href(target: dict[str, Any], base_url: str) -> str:
    role = str(target.get("role") or "").strip().lower()
    href = str(target.get("href") or "").strip()
    if role != "link" or not href:
        return ""
    lower_href = href.lower()
    if lower_href.startswith(("javascript:", "mailto:", "tel:", "#")):
        return ""
    resolved = urljoin(str(base_url or ""), href)
    return resolved if _control_is_http_url(resolved) else ""


async def _control_activate_semantic_link(
    state: ControlState,
    session: Any,
    tab_id: int,
    href: str,
) -> Any:
    _control_remember_approved_navigation(state, href)
    _control_sync_session_navigation_scope(state, session)
    await session.send_after_banner(
        "Page.navigate",
        {"url": href},
        {"status_text": "Open"},
    )
    _control_refresh_tab_url(state, tab_id, href)
    _control_mark_observation_required(state, tab_id, action="click")
    return _json_response(
        {
            "ok": True,
            "mode": "control",
            "tab_id": tab_id,
            "navigation_occurred": True,
            "activated_semantic_link": True,
            "url": href,
            "needs_observation": True,
            "ready_for_observation": True,
            "next_action": "snapshot",
            "next_instruction": (
                "The link target was opened in the current controlled tab. "
                "Observe it with snapshot before taking another action."
            ),
        },
    )


def set_network_quiescence_wait(func: Any) -> None:
    global _network_quiescence_monitor_impl, _network_quiescence_wait_impl
    _network_quiescence_wait_impl = func
    if func is _default_network_wait:
        _network_quiescence_monitor_impl = _default_network_monitor
        return

    async def monitor_factory(
        session: Any,
        bridge: Any,
        state: StateMapping,
        tab_id: int,
    ) -> _DeferredNetworkWaitMonitor:
        return _DeferredNetworkWaitMonitor(
            func,
            session,
            bridge,
            state,
            tab_id,
        )

    _network_quiescence_monitor_impl = monitor_factory


def _control_cached_tab_url(state: ControlState | dict, tab_id: int) -> str:
    control_tabs = (
        state.tabs
        if isinstance(state, ControlState)
        else state.get("control_tabs") or {}
    )
    tab = control_tabs.get(str(tab_id))
    if not isinstance(tab, dict):
        return ""
    return str(tab.get("url") or "")


def _control_tab_url_from_tabs(
    tabs: list[dict[str, Any]] | None,
    tab_id: int,
) -> str:
    live_tabs = _control_live_tab_map(tabs)
    if not live_tabs:
        return ""
    tab = live_tabs.get(tab_id)
    if not isinstance(tab, dict):
        return ""
    return _control_tab_url(tab)


def _control_click_navigation_status(
    state: ControlState,
    *,
    tab_id: int,
    before_tabs: list[dict[str, Any]] | None,
    after_tabs: list[dict[str, Any]] | None,
    before_url: str = "",
) -> tuple[bool, str]:
    before_url = (
        before_url
        or _control_cached_tab_url(state, tab_id)
        or _control_tab_url_from_tabs(before_tabs, tab_id)
    )
    after_url = _control_tab_url_from_tabs(after_tabs, tab_id)
    if after_url:
        _control_refresh_tab_url(state, tab_id, after_url)
    if not before_url or not after_url:
        return False, after_url or before_url
    return (
        _control_url_key(before_url) != _control_url_key(after_url),
        after_url,
    )


def _control_click_feedback_payload(
    *,
    tab_id: int,
    navigation_occurred: bool,
    url: str,
    network_metadata: dict[str, Any] | None = None,
    clicked_point: dict[str, Any] | None = None,
    coordinate_space: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async_requests = (
        int(network_metadata.get("async_requests_triggered") or 0)
        if isinstance(network_metadata, dict)
        else 0
    )
    if navigation_occurred:
        message = "Click completed and navigation was detected."
        instruction = (
            "The click changed the current tab. Observe it with snapshot "
            "before taking another action."
        )
    elif async_requests > 0:
        message = (
            "Click completed and asynchronous network activity was detected. "
            "The resulting state is pending verification."
        )
        instruction = (
            "Observe the page before another action. The local page state may "
            "be stale after an asynchronous state-changing request; do not "
            "declare success or failure from an unchanged local badge, "
            "counter, or control. Verify by waiting and observing, reloading "
            "and observing, or reading an authoritative state view."
        )
    elif coordinate_space:
        message = (
            "Raw coordinate click completed, but no navigation was detected."
        )
        instruction = (
            "Observe the page with snapshot before another action. Do not "
            "repeat raw coordinate clicks if the page state did not change; "
            "use a snapshot ref/text/selector target, navigate directly when "
            "the destination URL is known, or report that the page does not "
            "expose a reliable Browser Bridge target."
        )
    else:
        message = (
            "Click completed, but no navigation was detected. If the target "
            "destination is known, use browser(code=...) with the Browser SDK "
            "to navigate directly instead "
            "of repeating the same click."
        )
        instruction = (
            "Observe the page before another action. If this action should "
            "have opened a known URL, navigate directly with that URL; if it "
            "opened a tab asynchronously, the next observation will claim it "
            "instead of repeating the opener action."
        )
    payload: dict[str, Any] = {
        "ok": True,
        "mode": "control",
        "tab_id": tab_id,
        "message": message,
        "navigation_occurred": navigation_occurred,
        "needs_observation": True,
        "ready_for_observation": True,
        "next_action": "snapshot",
        "next_instruction": instruction,
    }
    if url:
        payload["url"] = url
    if clicked_point:
        payload["clicked_point"] = clicked_point
    if coordinate_space:
        payload["coordinate_space"] = coordinate_space
    if isinstance(network_metadata, dict) and async_requests > 0:
        payload["network"] = {
            "async_requests_triggered": async_requests,
            "settled": bool(network_metadata.get("settled")),
            "timed_out": bool(network_metadata.get("timed_out")),
        }
        if not navigation_occurred:
            payload[
                "state_verification"
            ] = _control_state_verification_payload(
                status="pending",
                reason="async_state_change_unverified",
                network_metadata=network_metadata,
            )
    return payload


async def click_control(
    state: ControlState,
    *,
    holder_id: str,
    bridge: Any,
    request_context: dict[str, Any],
    kwargs: dict[str, Any],
):
    canonical_runner = _canonical_runner_request(request_context)
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
    ref = str(kwargs.get("ref") or "").strip()
    selector = str(kwargs.get("selector") or "").strip()
    text = str(kwargs.get("text") or "").strip()
    resolved_ref = _control_current_snapshot_ref(state, tab_id, ref)
    tracking_ref = str(ref or selector or text or "").strip()
    target = (
        state.refs.get(str(tab_id), {}).get(resolved_ref, {}) if ref else {}
    )
    if not target and selector:
        target = await _control_selector_target(session, selector)
    if not target and text:
        target = await _control_text_target(session, text)
    x_param, y_param = kwargs.get("x"), kwargs.get("y")
    coordinate_space: dict[str, Any] | None = None
    clicked_point: dict[str, Any] | None = None
    if (
        not target
        and not any([ref, selector, text])
        and x_param is not None
        and y_param is not None
    ):
        width, height = await _control_viewport_size(session)
        try:
            raw_x = float(x_param)
            raw_y = float(y_param)
        except (TypeError, ValueError) as exc:
            raise TargetResolutionFailed(
                "x/y coordinates must be numeric viewport CSS pixels",
            ) from exc
        _control_validate_viewport_coordinates(
            x=raw_x,
            y=raw_y,
            viewport_width=width,
            viewport_height=height,
        )
        x, y = await _control_snap_to_element(
            session,
            raw_x,
            raw_y,
            width,
            height,
        )
        tracking_ref = _control_point_tracking_ref(x, y)
        clicked_point = {
            "x": x,
            "y": y,
            "input_x": raw_x,
            "input_y": raw_y,
            "tracking_ref": tracking_ref,
        }
        coordinate_space = _control_coordinate_space_payload(
            viewport_width=width,
            viewport_height=height,
        )
    else:
        x, y = await _control_resolve_point(
            session,
            target,
            ref=ref or selector or text,
            fallback_x=x_param,
            fallback_y=y_param,
        )
        clicked_point = {"x": x, "y": y}
    if tracking_ref:
        blocked = _control_visual_coordinate_click_guard(
            state,
            tab_id,
            tracking_ref,
        )
        if blocked is not None:
            return blocked
        blocked = _control_async_write_guard(state, tab_id, tracking_ref)
        if blocked is not None:
            return blocked
        blocked = _control_coordinate_click_loop_guard(
            state,
            tab_id,
            tracking_ref,
        )
        if blocked is not None:
            return blocked
    allow_new_context = bool(kwargs.get("allow_new_context", False))
    before_url = _control_cached_tab_url(state, tab_id)
    before_tabs = await _control_discover_tabs_safe(bridge)
    if not before_url:
        before_url = _control_tab_url_from_tabs(before_tabs, tab_id)
    semantic_link_href = _control_link_href(target, before_url)
    if semantic_link_href and not canonical_runner:
        return await _control_activate_semantic_link(
            state,
            session,
            tab_id,
            semantic_link_href,
        )
    if not allow_new_context:
        await _control_prepare_silent_new_context_at_point(session, x, y)
    if canonical_runner:
        await _control_click_at(session, x, y, "Click")
        return _canonical_raw_command_hint(tab_id, "click")
    network_monitor = await _network_quiescence_monitor_impl(
        session,
        bridge,
        state,
        tab_id,
    )
    try:
        waiter = _control_create_action_transition_waiter(
            bridge,
            before_tabs=before_tabs,
            source_tab_id=tab_id,
        )
        await _control_click_at(session, x, y, "Click")
        transition = await _control_resolve_action_transition(
            state,
            bridge=bridge,
            before_tabs=before_tabs,
            transition_waiter=waiter,
            source_tab_id=tab_id,
            holder_id=holder_id,
            request_context=request_context,
            close_previous_owned_tab=not allow_new_context,
        )
        if transition is not None:
            transition_tab_id = _control_int_tab_id(transition.get("tab_id"))
            _control_mark_observation_required(
                state,
                transition_tab_id or tab_id,
                action="click",
            )
            if "navigation_occurred" not in transition:
                transition["navigation_occurred"] = True
            if "needs_observation" not in transition:
                transition["needs_observation"] = True
            return _json_response(transition)
        after_tabs = (
            await _control_discover_tabs_safe(bridge) if before_url else None
        )
        navigated, current_url = _control_click_navigation_status(
            state,
            tab_id=tab_id,
            before_tabs=before_tabs,
            after_tabs=after_tabs,
            before_url=before_url,
        )
        _control_mark_observation_required(state, tab_id, action="click")
        network = await network_monitor.wait()
        if tracking_ref and not navigated:
            _click_effect_record_click(
                state,
                tab_id,
                tracking_ref,
                _click_effect_last_snapshot_hash(state, tab_id),
                network_metadata=network,
            )
        return _json_response(
            _control_click_feedback_payload(
                tab_id=tab_id,
                navigation_occurred=navigated,
                url=current_url,
                network_metadata=network,
                clicked_point=clicked_point,
                coordinate_space=coordinate_space,
            ),
        )
    finally:
        network_monitor.close()


async def type_control(
    state: ControlState,
    *,
    holder_id: str,
    bridge: Any,
    request_context: dict[str, Any],
    kwargs: dict[str, Any],
):
    canonical_runner = _canonical_runner_request(request_context)
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
    before_tabs = await _control_discover_tabs_safe(bridge)
    waiter = (
        None
        if canonical_runner
        else _control_create_action_transition_waiter(
            bridge,
            before_tabs=before_tabs,
            source_tab_id=tab_id,
        )
    )
    ref = str(kwargs.get("ref") or "").strip()
    selector = str(kwargs.get("selector") or "").strip()
    resolved_ref = _control_current_snapshot_ref(state, tab_id, ref)
    target = (
        state.refs.get(str(tab_id), {}).get(resolved_ref, {}) if ref else {}
    )
    if not target and selector:
        target = await _control_selector_target(session, selector)
    if target:
        x, y = await _control_resolve_point(
            session,
            target,
            ref=ref or selector,
        )
        await _control_click_at(session, x, y, "Focus")
    text_to_type = str(kwargs.get("text", ""))
    await _control_show_keyboard(
        session,
        text=text_to_type,
        status_text="Type",
    )
    await session.send("Input.insertText", {"text": text_to_type})
    if bool(kwargs.get("submit", False)):
        await _control_press_key(session, "Enter")
    if canonical_runner:
        return _canonical_raw_command_hint(tab_id, "type")
    return await _finalize_keyboard_action(
        state,
        bridge,
        before_tabs,
        waiter,
        tab_id,
        holder_id,
        request_context,
        "type",
        (
            "Text was entered. Observe the page before deciding whether to "
            "press Enter, click a submit button, or take another action."
        ),
    )


async def press_key_control(
    state: ControlState,
    *,
    holder_id: str,
    bridge: Any,
    request_context: dict[str, Any],
    kwargs: dict[str, Any],
):
    canonical_runner = _canonical_runner_request(request_context)
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
    before_tabs = await _control_discover_tabs_safe(bridge)
    waiter = (
        None
        if canonical_runner
        else _control_create_action_transition_waiter(
            bridge,
            before_tabs=before_tabs,
            source_tab_id=tab_id,
        )
    )
    await _control_press_key(session, str(kwargs.get("key") or ""))
    if canonical_runner:
        return _canonical_raw_command_hint(tab_id, "press_key")
    return await _finalize_keyboard_action(
        state,
        bridge,
        before_tabs,
        waiter,
        tab_id,
        holder_id,
        request_context,
        "press_key",
        (
            "The key press completed. Observe the page before taking another "
            "action."
        ),
    )


async def _finalize_keyboard_action(
    state,
    bridge,
    before_tabs,
    waiter,
    tab_id,
    holder_id,
    request_context,
    action,
    instruction,
):
    transition = await _control_resolve_action_transition(
        state,
        bridge=bridge,
        before_tabs=before_tabs,
        transition_waiter=waiter,
        source_tab_id=tab_id,
        holder_id=holder_id,
        request_context=request_context,
    )
    if transition is not None:
        transition_tab_id = _control_int_tab_id(transition.get("tab_id"))
        _control_mark_observation_required(
            state,
            transition_tab_id or tab_id,
            action=action,
        )
        return _json_response(transition)
    _control_mark_observation_required(state, tab_id, action=action)
    return _json_response(
        {
            "ok": True,
            "mode": "control",
            "tab_id": tab_id,
            "ready_for_observation": True,
            "next_action": "snapshot",
            "next_instruction": instruction,
        },
    )


__all__ = [
    "click_control",
    "press_key_control",
    "set_network_quiescence_wait",
    "type_control",
]
