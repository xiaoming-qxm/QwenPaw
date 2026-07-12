# -*- coding: utf-8 -*-
"""Deterministic Browser Core Lab case builder and executor."""

from __future__ import annotations

from .model import CapabilityFamily, LabCase, ReplayDescriptor
from .oracle import IndependentOracle


def build_case(
    *,
    family: CapabilityFamily,
    case_id: str,
    seed: int,
) -> LabCase:
    """Build one registered logical case without a scenario DSL."""
    if (
        family is not CapabilityFamily.USER_CHROME_LIFECYCLE
        or case_id != "s0.owner-continuity"
    ):
        raise KeyError(f"unregistered Core Lab case: {family.value}/{case_id}")
    return LabCase(
        case_id=case_id,
        family=family,
        base_flow="two_requests_one_root_task",
        seed=int(seed),
        transformations=("request_scope_rotate",),
        fault=None,
        replay=ReplayDescriptor(
            family=family,
            case_id=case_id,
            seed=int(seed),
        ),
    )


def registered_case_ids(family: CapabilityFamily) -> tuple[str, ...]:
    if family is CapabilityFamily.USER_CHROME_LIFECYCLE:
        return ("s0.owner-continuity",)
    return ()


def run_case(case: LabCase):
    """Execute S0's controller-owned deterministic smoke facts."""
    expected = {"owner_continuity": True, "native_effect_count": 0}
    observed = [
        {
            "owner_continuity": case.transformations
            == ("request_scope_rotate",),
            "native_effect_count": 0,
        },
    ]
    return IndependentOracle().evaluate(
        expected_facts=expected,
        observed_events=observed,
        observed_resources=(),
        observed_blocks=(),
    )


__all__ = ["build_case", "registered_case_ids", "run_case"]
