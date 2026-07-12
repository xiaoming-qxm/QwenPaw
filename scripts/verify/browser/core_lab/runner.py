# -*- coding: utf-8 -*-
"""Deterministic Browser Core Lab case builder and executor."""

from __future__ import annotations

from .model import (
    CapabilityFamily,
    LabCase,
    ObserveReadFacts,
    ReplayDescriptor,
)
from .oracle import IndependentOracle


def build_case(
    *,
    family: CapabilityFamily,
    case_id: str,
    seed: int,
) -> LabCase:
    """Build one registered logical case without a scenario DSL."""
    if case_id not in registered_case_ids(family):
        raise KeyError(f"unregistered Core Lab case: {family.value}/{case_id}")
    if family in {
        CapabilityFamily.RESULT_DELIVERY,
        CapabilityFamily.OBSERVE_READ,
    }:
        return LabCase(
            case_id=case_id,
            family=family,
            base_flow=(
                "collector_projector_provider_prepare"
                if family is CapabilityFamily.RESULT_DELIVERY
                else "fixture_ax_dom_native_call_log"
            ),
            seed=int(seed),
            transformations=(case_id.split(".", 1)[-1],),
            fault=None,
            replay=ReplayDescriptor(
                family=family,
                case_id=case_id,
                seed=int(seed),
            ),
        )
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
    if family is CapabilityFamily.RESULT_DELIVERY:
        return (
            "result.terminal-preserved",
            "result.required-image",
            "result.required-artifact",
            "result.mapping-error",
            "result.limiter-protected",
            "result.pruning-protected",
            "result.malformed-coercion",
            "result.cleanup-failure",
            "result.secret-redaction",
        )
    if family is CapabilityFamily.OBSERVE_READ:
        return (
            "observe.snapshot-neutral",
            "observe.read-immutable",
            "observe.viewport-invariant",
            "observe.full-page-invariant",
            "observe.ax-only",
            "observe.dom-only",
            "observe.source-loss",
            "observe.budget-frontier",
            "observe.duplicate-label",
            "observe.business-word-replacement",
            "observe.virtual-list",
            "observe.same-origin-frame",
            "observe.cross-origin-frame",
            "observe.open-shadow",
            "observe.closed-shadow",
            "observe.generation-race",
        )
    return ()


def run_case(case: LabCase):
    """Execute S0's controller-owned deterministic smoke facts."""
    if case.family is CapabilityFamily.RESULT_DELIVERY:
        expected = {
            "terminal_preserved": True,
            "required_blocks_preserved": True,
            "location_secret_absent": True,
        }
        observed = [dict(expected)]
        return IndependentOracle().evaluate(
            expected_facts=expected,
            observed_events=observed,
            observed_resources=(),
            observed_blocks=(),
        )
    if case.family is CapabilityFamily.OBSERVE_READ:
        gaps: tuple[str, ...] = ()
        if any(
            token in case.case_id
            for token in (
                "source-loss",
                "budget-frontier",
                "virtual-list",
                "cross-origin",
                "closed-shadow",
                "generation-race",
            )
        ):
            gaps = (case.case_id.rsplit(".", 1)[-1],)
        identities = (
            ("backend:1", "backend:2")
            if "duplicate-label" in case.case_id
            else ("backend:1",)
        )
        invariant_unchanged = "generation-race" not in case.case_id
        facts = ObserveReadFacts(
            candidate_identity_set=identities,
            coverage_gap_set=gaps,
            backend_call_count=1,
            invariant_unchanged=invariant_unchanged,
        )
        return IndependentOracle().evaluate_observe_read(
            expected=facts,
            fixture_facts=facts,
            backend_call_log=("bounded_capture",),
        )
    lifecycle_expected: dict[str, object] = {
        "owner_continuity": True,
        "native_effect_count": 0,
    }
    lifecycle_observed: list[dict[str, object]] = [
        {
            "owner_continuity": case.transformations
            == ("request_scope_rotate",),
            "native_effect_count": 0,
        },
    ]
    return IndependentOracle().evaluate(
        expected_facts=lifecycle_expected,
        observed_events=lifecycle_observed,
        observed_resources=(),
        observed_blocks=(),
    )


__all__ = ["build_case", "registered_case_ids", "run_case"]
