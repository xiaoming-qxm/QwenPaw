# -*- coding: utf-8 -*-
"""Snapshot-scoped Browser Bridge ref helpers."""

from __future__ import annotations

import re

from .state import StateMapping

_REF_SCOPE_STATE_KEY = "control_ref_scope_sequences"
_REF_PATTERN = re.compile(r"\[ref=([^\]\s]+)\]")
_CANONICAL_REF_STATE_KEY = "canonical_ref_bindings"


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
