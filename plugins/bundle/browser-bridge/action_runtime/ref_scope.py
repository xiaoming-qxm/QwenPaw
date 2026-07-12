# -*- coding: utf-8 -*-
"""Snapshot-scoped Browser Bridge ref helpers."""

from __future__ import annotations

import re
from typing import Literal
from uuid import uuid4

from qwenpaw.browser.sdk.governance.errors import BrowserSDKError

from .state import StateMapping

_REF_SCOPE_STATE_KEY = "control_ref_scope_sequences"
_REF_PATTERN = re.compile(r"\[ref=([^\]\s]+)\]")
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
    tab_id: int,
    frame_key: str,
    context: dict[str, int],
    native_identity: tuple[tuple[str, str | int], ...],
    action_state: tuple[tuple[str, bool], ...],
    geometry_digest: str,
    visual_context_ref: str | None,
    allowed_actions: tuple[str, ...],
    effect_ceiling: tuple[str, ...],
) -> str:
    """Store native authority outside the LEGACY ref namespace."""
    if len(owner_key) != 2 or not all(str(item).strip() for item in owner_key):
        raise BrowserSDKError(
            "canonical target owner is invalid",
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
        "tab_id": int(tab_id),
        "frame_key": str(frame_key),
        "context": dict(context),
        "native_identity": tuple(native_identity),
        "action_state": tuple(action_state),
        "geometry_digest": str(geometry_digest),
        "visual_context_ref": visual_context_ref,
        "allowed_actions": tuple(allowed_actions),
        "effect_ceiling": tuple(effect_ceiling),
    }
    return token


def _control_canonical_binding_status(
    state: StateMapping,
    *,
    token: str,
    owner_key: tuple[str, str],
    receiver_tab: int,
    current_native_identity: tuple[tuple[str, str | int], ...],
    visual: bool = False,
) -> CanonicalBindingStatus:
    """Compare exact owner/receiver/native generations without rebinding."""
    binding = _require_canonical_binding(state, token)
    if tuple(binding.get("owner_key", ())) != tuple(owner_key):
        raise BrowserSDKError(
            "canonical target owner mismatch",
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


def _control_scope_snapshot_refs(
    state: StateMapping,
    tab_id: int,
    snapshot: str,
    refs: dict[str, dict],
) -> tuple[str, dict[str, dict], str]:
    """Return snapshot text and refs whose public ids are snapshot-scoped."""
    if not refs:
        return snapshot, refs, ""

    scope = _next_ref_scope(state, tab_id)
    ref_map = {str(ref): f"{scope}_{ref}" for ref in refs}
    scoped_refs: dict[str, dict] = {}
    for ref, target in refs.items():
        ref_key = str(ref)
        scoped_ref = ref_map[ref_key]
        target_payload = dict(target) if isinstance(target, dict) else {}
        target_payload["source_ref"] = ref_key
        target_payload["snapshot_scope"] = scope
        scoped_refs[scoped_ref] = target_payload

    def replace_ref(match: re.Match[str]) -> str:
        public_ref = ref_map.get(match.group(1), match.group(1))
        return f"[ref={public_ref}]"

    return _REF_PATTERN.sub(replace_ref, snapshot), scoped_refs, scope


def _control_snapshot_payload_refs(
    refs: dict[str, dict],
) -> dict[str, dict]:
    """Return response refs with legacy source-ref aliases.

    Runtime state keeps only snapshot-scoped refs so later browser actions
    cannot accidentally reuse stale unscoped ids. The response payload keeps
    read-only aliases for callers that inspect refs by the original AX ids.
    """
    payload_refs = dict(refs)
    for scoped_ref, target in refs.items():
        if not isinstance(target, dict):
            continue
        source_ref = str(target.get("source_ref") or "").strip()
        if not source_ref or source_ref in payload_refs:
            continue
        alias_payload = dict(target)
        alias_payload["scoped_ref"] = str(scoped_ref)
        payload_refs[source_ref] = alias_payload
    return payload_refs


def _control_current_snapshot_ref(
    state: StateMapping,
    tab_id: int,
    ref: str,
) -> str:
    """Return the current scoped ref for a legacy source ref."""
    ref = str(ref or "").strip()
    if not ref:
        return ref

    tab_refs_by_id = getattr(state, "refs", None)
    if not isinstance(tab_refs_by_id, dict):
        tab_refs_by_id = state.get("refs", {})
    tab_refs = tab_refs_by_id.get(str(tab_id), {})
    if not isinstance(tab_refs, dict) or ref in tab_refs:
        return ref

    sequences = state.get(_REF_SCOPE_STATE_KEY)
    if not isinstance(sequences, dict):
        return ref
    current_scope = f"r{int(sequences.get(str(tab_id)) or 0)}"
    if current_scope == "r0":
        return ref

    for scoped_ref, target in tab_refs.items():
        if not isinstance(target, dict):
            continue
        if str(target.get("source_ref") or "") != ref:
            continue
        if str(target.get("snapshot_scope") or "") == current_scope:
            return str(scoped_ref)
    return ref


def _next_ref_scope(state: StateMapping, tab_id: int) -> str:
    sequences = state.get(_REF_SCOPE_STATE_KEY)
    if not isinstance(sequences, dict):
        sequences = {}
        state[_REF_SCOPE_STATE_KEY] = sequences
    tab_key = str(tab_id)
    sequence = int(sequences.get(tab_key) or 0) + 1
    sequences[tab_key] = sequence
    return f"r{sequence}"


__all__ = [
    "CanonicalRefScopeError",
    "_control_bind_canonical_ref",
    "_control_current_snapshot_ref",
    "_control_require_canonical_ref",
    "_control_scope_snapshot_refs",
    "_control_snapshot_payload_refs",
]
