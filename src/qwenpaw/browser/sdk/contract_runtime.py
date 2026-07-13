# -*- coding: utf-8 -*-
"""Canonical Browser action-contract materialization."""

from __future__ import annotations

from .canonical.action_contract import (
    BrowserAPIContract,
    BrowserTargetContract,
)
from .canonical.contracts import canonical_api_catalog
from .governance.errors import BrowserSDKError


def canonical_mutation_contract(api_id: str) -> BrowserAPIContract:
    """Materialize one reviewed Canonical mutation catalog row."""
    for entry in canonical_api_catalog()["apis"]:
        if entry["api_id"] != api_id:
            continue
        if not entry["mutates"] or api_id == "browser.close":
            break
        target_names = tuple(
            parameter["name"]
            for parameter in entry["parameters"]
            if parameter.get("annotation") == "TargetRef"
        )
        return BrowserAPIContract(
            api_id=api_id,
            kind=str(entry["kind"]),
            visibility="default",
            mutates=True,
            requires_observation=bool(target_names),
            satisfies_observation=False,
            invalidates_observation=True,
            public_name=api_id,
            target=(
                BrowserTargetContract(
                    required=True,
                    methods=("runtime_ref",),
                    snapshot_bound=True,
                )
                if target_names
                else None
            ),
            backend_op=api_id.rsplit(".", 1)[-1],
            callable_path=str(entry["callable_path"]),
        )
    raise BrowserSDKError(
        "Canonical mutation is not present in the reviewed catalog",
        code="browser_contract_missing",
        action=api_id,
    )


__all__ = ["canonical_mutation_contract"]
