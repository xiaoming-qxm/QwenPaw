# -*- coding: utf-8 -*-
"""Snapshot-scoped Browser Bridge ref helpers."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from qwenpaw.browser.governance.errors import BrowserSDKError

from .state import StateMapping

_CANONICAL_REF_STATE_KEY = "canonical_ref_bindings"
_CANONICAL_CONTEXT_STATE_KEY = "canonical_context_generations"
_CANONICAL_TARGET_STATE_KEY = "canonical_target_bindings"
_CANONICAL_DOCUMENT_TOKENS_KEY = "canonical_document_tokens"

CanonicalGenerationChange = Literal[
    "CONNECTION",
    "TAB",
    "FRAME",
    "DOCUMENT",
    "SPA",
    "LAYOUT",
    "SCREENSHOT",
]
CanonicalBindingStatus = Literal["VALID", "REVALIDATE", "STALE"]
_HARD_GENERATIONS = (
    "connection_generation",
    "tab_generation",
    "frame_generation",
    "document_generation",
)


def _control_canonical_context(
    state: StateMapping,
    *,
    tab_id: int,
) -> dict[str, int]:
    """Return the sole private generation record for one receiver tab."""
    contexts = state.setdefault(_CANONICAL_CONTEXT_STATE_KEY, {})
    key = str(int(tab_id))
    current = contexts.get(key)
    if not isinstance(current, dict):
        current = {
            "connection_generation": 1,
            "tab_generation": 1,
            "frame_generation": 1,
            "document_generation": 1,
            "spa_route_generation": 0,
            "layout_generation": 0,
        }
        contexts[key] = current
    return {name: int(value) for name, value in current.items()}


def _control_advance_canonical_generation(
    state: StateMapping,
    *,
    tab_id: int,
    change: str,
) -> dict[str, int]:
    """Advance one exact lifecycle dimension; screenshots are read-only."""
    normalized = str(change).upper()
    if normalized not in {
        "CONNECTION",
        "TAB",
        "FRAME",
        "DOCUMENT",
        "SPA",
        "LAYOUT",
        "SCREENSHOT",
    }:
        raise ValueError(f"unsupported canonical generation change: {change}")
    current = _control_canonical_context(state, tab_id=tab_id)
    if normalized != "SCREENSHOT":
        field = {
            "CONNECTION": "connection_generation",
            "TAB": "tab_generation",
            "FRAME": "frame_generation",
            "DOCUMENT": "document_generation",
            "SPA": "spa_route_generation",
            "LAYOUT": "layout_generation",
        }[normalized]
        current[field] += 1
        contexts = state.setdefault(_CANONICAL_CONTEXT_STATE_KEY, {})
        contexts[str(int(tab_id))] = current
        from .source_traversal import invalidate_source_traversals

        invalidate_source_traversals(state, tab_id=tab_id)
    return dict(current)


def _control_note_canonical_document(
    state: StateMapping,
    *,
    tab_id: int,
    document_token: str,
) -> dict[str, int]:
    """Close missed-event races by comparing the trusted loader token."""
    token = str(document_token or "").strip()
    if not token:
        raise ValueError("canonical document token is missing")
    tokens = state.setdefault(_CANONICAL_DOCUMENT_TOKENS_KEY, {})
    key = str(int(tab_id))
    previous = str(tokens.get(key) or "")
    if previous and previous != token:
        _control_advance_canonical_generation(
            state,
            tab_id=tab_id,
            change="DOCUMENT",
        )
    tokens[key] = token
    return _control_canonical_context(state, tab_id=tab_id)


def _control_bind_canonical_target(
    state: StateMapping,
    *,
    owner_key: tuple[str, str],
    root_session_id: str,
    tab_id: int,
    frame_key: str,
    context: dict[str, int],
    native_identity: tuple[tuple[str, str | int], ...],
    action_state: tuple[tuple[str, bool], ...],
    geometry_digest: str,
    visual_context_ref: str | None,
    allowed_actions: tuple[str, ...],
    effect_ceiling: tuple[str, ...],
    single_use: bool = False,
) -> str:
    """Store native authority outside the LEGACY ref namespace."""
    if len(owner_key) != 2 or not all(str(item).strip() for item in owner_key):
        raise BrowserSDKError(
            "canonical target owner is invalid",
            code="target_wrong_owner",
        )
    session_owner = str(root_session_id or "").strip()
    if not session_owner:
        raise BrowserSDKError(
            "canonical target session owner is invalid",
            code="target_wrong_owner",
        )
    if not native_identity:
        raise BrowserSDKError(
            "canonical native identity is missing",
            code="target_binding_invalid",
        )
    token = f"target_{uuid4().hex}"
    bindings = state.setdefault(_CANONICAL_TARGET_STATE_KEY, {})
    bindings[token] = {
        "owner_key": tuple(owner_key),
        "root_session_id": session_owner,
        "tab_id": int(tab_id),
        "frame_key": str(frame_key),
        "context": dict(context),
        "native_identity": tuple(native_identity),
        "action_state": tuple(action_state),
        "geometry_digest": str(geometry_digest),
        "visual_context_ref": visual_context_ref,
        "allowed_actions": tuple(allowed_actions),
        "effect_ceiling": tuple(effect_ceiling),
        "single_use": bool(single_use),
        "use_state": "FRESH",
    }
    return token


def _control_canonical_binding_status(
    state: StateMapping,
    *,
    token: str,
    owner_key: tuple[str, str],
    root_session_id: str,
    receiver_tab: int,
    current_native_identity: tuple[tuple[str, str | int], ...],
    visual: bool = False,
) -> CanonicalBindingStatus:
    """Compare exact owner/receiver/native generations without rebinding."""
    binding = _require_canonical_binding(state, token)
    if bool(binding.get("single_use")) and binding.get("use_state") != "FRESH":
        return "STALE"
    if tuple(binding.get("owner_key", ())) != tuple(owner_key):
        raise BrowserSDKError(
            "canonical target owner mismatch",
            code="target_wrong_owner",
        )
    if str(binding.get("root_session_id") or "") != str(
        root_session_id or "",
    ):
        raise BrowserSDKError(
            "canonical target session owner mismatch",
            code="target_wrong_owner",
        )
    if int(binding.get("tab_id", -1)) != int(receiver_tab):
        raise BrowserSDKError(
            "canonical target receiver mismatch",
            code="target_wrong_receiver",
        )
    bound = binding.get("context")
    if not isinstance(bound, dict):
        raise BrowserSDKError(
            "canonical target context is invalid",
            code="target_binding_invalid",
        )
    current = _control_canonical_context(state, tab_id=receiver_tab)
    if any(
        int(bound.get(key, -1)) != current[key] for key in _HARD_GENERATIONS
    ):
        return "STALE"
    native = tuple(binding.get("native_identity", ()))
    if native != tuple(current_native_identity):
        return "STALE"
    if (
        int(bound.get("spa_route_generation", -1))
        != current["spa_route_generation"]
    ):
        return "REVALIDATE"
    if (
        visual
        and int(bound.get("layout_generation", -1))
        != current["layout_generation"]
    ):
        return "STALE"
    return "VALID"


def _control_revalidate_canonical_target(
    state: StateMapping,
    *,
    token: str,
    current_native_identity: tuple[tuple[str, str | int], ...],
) -> None:
    """Refresh only semantic SPA generation for the proven same native id."""
    binding = _require_canonical_binding(state, token)
    if tuple(binding.get("native_identity", ())) != tuple(
        current_native_identity,
    ):
        raise BrowserSDKError(
            "canonical target native identity changed",
            code="target_stale",
        )
    tab_id = int(binding.get("tab_id", -1))
    current = _control_canonical_context(state, tab_id=tab_id)
    context = binding.get("context")
    if not isinstance(context, dict) or any(
        int(context.get(key, -1)) != current[key] for key in _HARD_GENERATIONS
    ):
        raise BrowserSDKError(
            "canonical target context replaced",
            code="target_stale",
        )
    context["spa_route_generation"] = current["spa_route_generation"]


def _require_canonical_binding(
    state: StateMapping,
    token: str,
) -> dict:
    if not str(token).startswith("target_"):
        raise BrowserSDKError(
            "canonical target token is invalid",
            code="runtime_issued_value",
        )
    bindings = state.get(_CANONICAL_TARGET_STATE_KEY)
    binding = bindings.get(token) if isinstance(bindings, dict) else None
    if not isinstance(binding, dict):
        raise BrowserSDKError(
            "canonical target token is unknown",
            code="runtime_issued_value",
        )
    return binding


class CanonicalRefScopeError(RuntimeError):
    """Typed fail-closed canonical surface reference error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _control_bind_canonical_ref(
    state: StateMapping,
    *,
    tab_id: int,
    generation: str,
    source_ref: str,
    target: dict,
    owner_chain: tuple[str, ...],
    kind: str,
) -> str:
    """Bind a private target to exact tab/document/owner identity."""
    bindings = state.get(_CANONICAL_REF_STATE_KEY)
    if not isinstance(bindings, dict):
        bindings = {}
        state[_CANONICAL_REF_STATE_KEY] = bindings
    sequence = len(bindings) + 1
    public_ref = f"canonical-{sequence}"
    bindings[public_ref] = {
        "tab_id": int(tab_id),
        "generation": str(generation),
        "source_ref": str(source_ref),
        "target": dict(target),
        "owner_chain": tuple(owner_chain),
        "kind": str(kind),
    }
    return public_ref


def _control_require_canonical_ref(
    state: StateMapping,
    *,
    tab_id: int,
    generation: str,
    ref: str,
    kind: str,
) -> dict:
    """Resolve only the exact original surface; never rebind heuristically."""
    bindings = state.get(_CANONICAL_REF_STATE_KEY)
    binding = bindings.get(ref) if isinstance(bindings, dict) else None
    if not isinstance(binding, dict):
        raise CanonicalRefScopeError("canonical_ref_invalid")
    if int(binding.get("tab_id", -1)) != int(tab_id):
        raise CanonicalRefScopeError("canonical_ref_tab_mismatch")
    if str(binding.get("generation") or "") != str(generation):
        raise CanonicalRefScopeError("canonical_ref_stale")
    if str(binding.get("kind") or "") != str(kind):
        raise CanonicalRefScopeError("canonical_ref_type_mismatch")
    target = binding.get("target")
    if not isinstance(target, dict):
        raise CanonicalRefScopeError("canonical_ref_invalid")
    return dict(target)


__all__ = [
    "CanonicalRefScopeError",
    "_control_bind_canonical_ref",
    "_control_require_canonical_ref",
]
