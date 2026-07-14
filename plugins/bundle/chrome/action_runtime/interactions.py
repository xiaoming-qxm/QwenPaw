# -*- coding: utf-8 -*-
"""Interaction helpers for Chrome typed handlers."""
# pylint: disable=too-many-branches,too-many-statements
# pylint: disable=too-many-return-statements,protected-access
# pylint: disable=too-many-boolean-expressions

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from qwenpaw.browser.action_runner import DispatchContext
from qwenpaw.browser.governance.errors import BrowserSDKError
from qwenpaw.browser.governance.policy import (
    trusted_surface_rule_fingerprint,
)
from qwenpaw.browser.runtime.responses import _tool_response
from .network_settle import _network_quiescence_wait as _default_network_wait
from .ref_scope import (
    _control_canonical_binding_status,
    _require_canonical_binding,
)
from .session_manager import _control_get_session
from .state import ControlState, StateMapping
from .tab_manager import _control_ensure_tab_available
from .targets import canonical_live_target_point

_network_quiescence_wait_impl: Any = _default_network_wait


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


_CANONICAL_FORBIDDEN_TARGET_KEYS = {
    "selector",
    "x",
    "y",
    "native_id",
    "nativeId",
    "backendNodeId",
    "nodeId",
}


async def _bring_tab_to_front_for_native_input(session: Any) -> None:
    """Use the existing CDP relay to foreground the controlled page."""
    try:
        await session.send("Page.bringToFront")
    except Exception as exc:
        raise BrowserSDKError(
            "Cannot foreground the controlled tab for native input",
            code="native_input_activation_failed",
        ) from exc


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
    if (
        not isinstance(target_tokens, Mapping)
        or not isinstance(
            native_facts,
            Mapping,
        )
        or not isinstance(surface_policy_facts, Mapping)
    ):
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
            root_session_id=context.session_id,
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
        item for item in str(context.effect_proof_ref or "").split("|") if item
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
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, (int, float))
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
        await _bring_tab_to_front_for_native_input(session)
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
        native_receipt = await _dispatch_canonical_pointer(
            session,
            action=action,
            points=tuple(points),
            arguments=arguments,
        )
        return {
            "tab_id": tab_id,
            **(
                native_receipt
                if isinstance(native_receipt, Mapping)
                else {}
            ),
        }

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
) -> dict[str, object] | None:
    if action == "scroll":
        return await _dispatch_canonical_scroll(
            session,
            points=points,
            arguments=arguments,
        )
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
        return None
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
        return None
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
    return None


async def _dispatch_canonical_scroll(
    session: Any,
    *,
    points: tuple[tuple[float, float], ...],
    arguments: dict[str, object],
) -> dict[str, object]:
    """Inject one wheel event and return its native viewport receipt."""
    if len(points) > 1:
        raise BrowserSDKError(
            "Canonical scroll accepts at most one target",
            code="interaction_action_invalid",
        )
    direction = str(arguments.get("direction") or "down")
    amount = str(arguments.get("amount") or "page")
    if direction not in {"up", "down", "left", "right"}:
        raise BrowserSDKError(
            "Canonical scroll direction is invalid",
            code="interaction_action_invalid",
        )
    if amount not in {"line", "page", "start", "end"}:
        raise BrowserSDKError(
            "Canonical scroll amount is invalid",
            code="interaction_action_invalid",
        )
    before = await _canonical_scroll_position(session)
    if amount == "line":
        magnitude = 120.0
    elif amount == "page":
        magnitude = 640.0
    else:
        magnitude = 1_000_000.0
    sign = -1.0 if direction in {"up", "left"} else 1.0
    delta_x = sign * magnitude if direction in {"left", "right"} else 0.0
    delta_y = sign * magnitude if direction in {"up", "down"} else 0.0
    x, y = (
        points[0]
        if points
        else await _canonical_scroll_viewport_center(session)
    )
    await session.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseWheel",
            "x": x,
            "y": y,
            "deltaX": delta_x,
            "deltaY": delta_y,
        },
    )
    await asyncio.sleep(0)
    after = await _canonical_scroll_position(session)
    return {
        "scroll_receipt": {
            "before": before,
            "after": after,
            "moved": before != after,
        },
    }


async def _canonical_scroll_viewport_center(
    session: Any,
) -> tuple[float, float]:
    """Choose a neutral viewport point when scroll has no bound target."""
    payload = await session.send("Page.getLayoutMetrics")
    if not isinstance(payload, Mapping):
        return (1.0, 1.0)
    for key in ("cssVisualViewport", "visualViewport"):
        viewport = payload.get(key)
        if not isinstance(viewport, Mapping):
            continue
        width = viewport.get("clientWidth")
        height = viewport.get("clientHeight")
        if (
            isinstance(width, (int, float))
            and isinstance(height, (int, float))
            and width > 0
            and height > 0
        ):
            return (float(width) / 2.0, float(height) / 2.0)
    return (1.0, 1.0)


async def _canonical_scroll_position(
    session: Any,
) -> tuple[float, float]:
    """Read the current scroll from trusted layout metrics, not page script."""
    payload = await session.send("Page.getLayoutMetrics")
    if not isinstance(payload, Mapping):
        raise BrowserSDKError(
            "Canonical scroll receipt is unavailable",
            code="scroll_receipt_unavailable",
        )
    for key in (
        "cssVisualViewport",
        "visualViewport",
        "cssLayoutViewport",
        "layoutViewport",
    ):
        viewport = payload.get(key)
        if not isinstance(viewport, Mapping):
            continue
        x = viewport.get("pageX")
        y = viewport.get("pageY")
        if (
            isinstance(x, (int, float))
            and not isinstance(x, bool)
            and isinstance(y, (int, float))
            and not isinstance(y, bool)
        ):
            return float(x), float(y)
    raise BrowserSDKError(
        "Canonical scroll receipt is unavailable",
        code="scroll_receipt_unavailable",
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


def set_network_quiescence_wait(func: Any) -> None:
    global _network_quiescence_wait_impl
    _network_quiescence_wait_impl = func


__all__ = [
    "set_network_quiescence_wait",
]
