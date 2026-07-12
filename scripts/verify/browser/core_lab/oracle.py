# -*- coding: utf-8 -*-
"""Independent oracle over controller-owned observed facts."""

from __future__ import annotations

from typing import Any, Iterable

from .model import CaseOutcome, ObserveReadFacts, OracleResult


class IndependentOracle:
    """Compare expected facts without trusting product success claims."""

    def evaluate(
        self,
        *,
        expected_facts: dict[str, Any],
        observed_events: Iterable[dict[str, Any]],
        observed_resources: Iterable[dict[str, Any]],
        observed_blocks: Iterable[dict[str, Any]],
        product_result: dict[str, Any] | None = None,
        agent_text: str = "",
    ) -> OracleResult:
        del product_result, agent_text
        observed: dict[str, Any] = {}
        for record in (
            *tuple(observed_events),
            *tuple(observed_resources),
            *tuple(observed_blocks),
        ):
            observed.update(record)
        selected = {key: observed.get(key) for key in expected_facts}
        diff = {
            key: {"expected": expected, "observed": selected.get(key)}
            for key, expected in expected_facts.items()
            if selected.get(key) != expected
        }
        return OracleResult(
            outcome=(
                CaseOutcome.PASS if not diff else CaseOutcome.PRODUCT_FAILURE
            ),
            expected=dict(expected_facts),
            observed=selected,
            diff=diff,
        )

    def evaluate_observe_read(
        self,
        *,
        expected: ObserveReadFacts,
        fixture_facts: ObserveReadFacts,
        backend_call_log: tuple[str, ...],
    ) -> OracleResult:
        """Evaluate fixture/native facts without reading Browser result claims."""
        expected_facts = {
            "candidate_identity_set": list(expected.candidate_identity_set),
            "coverage_gap_set": list(expected.coverage_gap_set),
            "backend_call_count": expected.backend_call_count,
            "invariant_unchanged": expected.invariant_unchanged,
        }
        observed_events = (
            {
                "candidate_identity_set": list(
                    fixture_facts.candidate_identity_set,
                ),
                "coverage_gap_set": list(fixture_facts.coverage_gap_set),
                "backend_call_count": len(backend_call_log),
                "invariant_unchanged": fixture_facts.invariant_unchanged,
            },
        )
        return self.evaluate(
            expected_facts=expected_facts,
            observed_events=observed_events,
            observed_resources=(),
            observed_blocks=(),
        )


__all__ = ["IndependentOracle"]
