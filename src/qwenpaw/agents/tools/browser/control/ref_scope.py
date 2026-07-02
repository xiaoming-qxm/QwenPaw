# -*- coding: utf-8 -*-
"""Snapshot-scoped Browser Control ref helpers."""

from __future__ import annotations

import re
from typing import Any

_REF_SCOPE_STATE_KEY = "control_ref_scope_sequences"
_REF_PATTERN = re.compile(r"\[ref=([^\]\s]+)\]")


def _control_scope_snapshot_refs(
    state: dict[str, Any],
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


def _next_ref_scope(state: dict[str, Any], tab_id: int) -> str:
    sequences = state.get(_REF_SCOPE_STATE_KEY)
    if not isinstance(sequences, dict):
        sequences = {}
        state[_REF_SCOPE_STATE_KEY] = sequences
    tab_key = str(tab_id)
    sequence = int(sequences.get(tab_key) or 0) + 1
    sequences[tab_key] = sequence
    return f"r{sequence}"


__all__ = ["_control_scope_snapshot_refs"]
