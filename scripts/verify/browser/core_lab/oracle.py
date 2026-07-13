# -*- coding: utf-8 -*-
"""Independent oracle over controller-owned observed facts."""

# pylint: disable=too-many-boolean-expressions

from __future__ import annotations

import posixpath
import unicodedata
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from .model import (
    ActionFaultFacts,
    CaseOutcome,
    FaultCutPoint,
    ObserveReadFacts,
    OracleResult,
    S7FamilyFacts,
    StateApprovalFacts,
    SynchronizeFacts,
    TargetControlFacts,
)


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

    def evaluate_synchronize(self, facts: SynchronizeFacts) -> OracleResult:
        """Recompute timeline truth without reading Browser result claims."""
        truth = tuple(
            _oracle_atom_truth(
                facts.atom_kind,
                item,
                facts.expected_value,
                facts.match_mode,
            )
            for item in facts.timeline
        )
        expected = _oracle_timeline_summary(
            facts.timeline,
            truth,
            deadline_ms=facts.deadline_ms,
            stable_ms=facts.stable_ms,
        )
        expected.update(
            cleanup_count=1,
            hint_count=len(facts.hint_sequences),
            same_evaluator=(len(set(facts.evaluator_symbols)) == 1),
            same_matcher=len(set(facts.matcher_symbols)) == 1,
            same_probe=len(set(facts.probe_identities)) == 1,
        )
        observed = dict(facts.observed_summary)
        observed.update(
            cleanup_count=facts.cleanup_count,
            hint_count=len(facts.hint_sequences),
            same_evaluator=(len(set(facts.evaluator_symbols)) == 1),
            same_matcher=len(set(facts.matcher_symbols)) == 1,
            same_probe=len(set(facts.probe_identities)) == 1,
        )
        return self.evaluate(
            expected_facts=expected,
            observed_events=(observed,),
            observed_resources=(),
            observed_blocks=(),
        )

    def evaluate_target_control(
        self,
        facts: TargetControlFacts,
    ) -> OracleResult:
        """Compare only fake-native object/command/effect controller logs."""
        return self.evaluate(
            expected_facts={
                "native_object_id": facts.expected_object_id,
                "native_command_count": facts.expected_command_count,
                "native_effect_count": facts.expected_effect_count,
                "public_dispatch_count": 0,
            },
            observed_events=(
                {
                    "native_object_id": facts.observed_object_id,
                    "native_command_count": facts.observed_command_count,
                    "native_effect_count": facts.observed_effect_count,
                    "public_dispatch_count": facts.public_dispatch_count,
                },
            ),
            observed_resources=(),
            observed_blocks=(),
        )

    def evaluate_state_approval(
        self,
        facts: StateApprovalFacts,
    ) -> OracleResult:
        """Compare controller state plus request/grant/attempt counters."""
        return self.evaluate(
            expected_facts={
                "decision": facts.expected_decision,
                "state_status": facts.expected_state_status,
                "effect_floor_preserved": (
                    facts.expected_effect_floor_preserved
                ),
                "approval_request_count": facts.expected_request_count,
                "approval_grant_count": facts.expected_grant_count,
                "dispatch_attempt_count": facts.expected_attempt_count,
                "remaining_uses": facts.expected_remaining_uses,
                "native_effect_count": 0,
            },
            observed_events=(
                {
                    "decision": facts.observed_decision,
                    "state_status": facts.observed_state_status,
                    "effect_floor_preserved": (
                        facts.observed_effect_floor_preserved
                    ),
                    "approval_request_count": facts.observed_request_count,
                    "approval_grant_count": facts.observed_grant_count,
                    "dispatch_attempt_count": facts.observed_attempt_count,
                    "remaining_uses": facts.observed_remaining_uses,
                    "native_effect_count": facts.native_effect_count,
                },
            ),
            observed_resources=(),
            observed_blocks=(),
        )

    def evaluate_action_fault(
        self,
        facts: ActionFaultFacts,
    ) -> OracleResult:
        """Check controller/native logs without trusting ActionResult."""
        expected_effect_count = (
            0
            if facts.fault
            in {
                FaultCutPoint.ACTION_BEFORE_DISPATCH,
                FaultCutPoint.AFTER_SEND_BEFORE_ACK,
                FaultCutPoint.AFTER_ACK_BEFORE_EFFECT,
            }
            else 1
        )
        return self.evaluate(
            expected_facts={
                "native_effect_count": expected_effect_count,
                "effect_count_at_most_one": True,
                "blind_resend_count": 0,
                "terminal_status": facts.terminal_status,
                "retry": facts.retry,
                "receipt_state": facts.receipt_state,
                "false_success": False,
                "command_identity_visible": True,
                "failure_or_cleanup_visible": True,
            },
            observed_events=(
                {
                    "native_effect_count": facts.native_effect_count,
                    "effect_count_at_most_one": (
                        facts.native_effect_count <= 1
                    ),
                    "blind_resend_count": facts.blind_resend_count,
                    "terminal_status": facts.terminal_status,
                    "retry": facts.retry,
                    "receipt_state": facts.receipt_state,
                    "false_success": facts.false_success,
                    "command_identity_visible": (
                        facts.command_identity_visible
                    ),
                    "failure_or_cleanup_visible": (
                        facts.failure_or_cleanup_visible
                    ),
                },
            ),
            observed_resources=(),
            observed_blocks=(),
        )

    def evaluate_s7_family(self, facts: S7FamilyFacts) -> OracleResult:
        """Evaluate only controller/native logs for an S7 primary case."""
        return self.evaluate(
            expected_facts={
                "primary_family": facts.primary_family.value,
                "native_effect_count": facts.expected_native_effect_count,
                "native_event_count": facts.expected_native_event_count,
                "exact_identity_bound": True,
                "owner_bound": True,
                "public_bypass_count": 0,
                "false_success": False,
            },
            observed_events=(
                {
                    "primary_family": facts.observed_family.value,
                    "native_effect_count": facts.observed_native_effect_count,
                    "native_event_count": facts.observed_native_event_count,
                    "exact_identity_bound": facts.exact_identity_bound,
                    "owner_bound": facts.owner_bound,
                    "public_bypass_count": facts.public_bypass_count,
                    "false_success": facts.false_success,
                },
            ),
            observed_resources=(),
            observed_blocks=(),
        )


# pylint: disable-next=too-many-return-statements
def _oracle_atom_truth(
    kind: str,
    item: dict[str, Any],
    expected: object,
    mode: str,
) -> bool:
    actual = item.get("actual")
    if kind == "page.url":
        return _oracle_url_match(str(actual), str(expected), mode)
    if kind in {"page.title", "region.text"}:
        actual_text = _oracle_visible_text(str(actual))
        expected_text = _oracle_visible_text(str(expected))
        found = (
            actual_text == expected_text
            if mode == "exact"
            else expected_text in actual_text
        )
        present = bool(item.get("present", True))
        if present:
            return found
        return not found and item.get("coverage") == "COMPLETE"
    if kind == "page.document_changed":
        return actual != expected
    if kind == "page.ready":
        ranks = {"loading": 0, "dom_content_loaded": 1, "load": 2}
        return ranks.get(str(actual), -1) >= ranks.get(str(expected), 99)
    if kind == "region.item_count":
        count = int(str(actual or 0))
        value = int(str(expected))
        if mode == "gte":
            return count >= value
        if item.get("coverage") != "COMPLETE":
            return False
        return count == value if mode == "eq" else count <= value
    if kind == "region.changed":
        return str(actual) != str(expected)
    if kind == "target.exists":
        present = bool(actual)
        expected_present = bool(expected)
        return present == expected_present and (
            expected_present or item.get("coverage") == "COMPLETE"
        )
    return False


def _oracle_timeline_summary(
    timeline: tuple[dict[str, Any], ...],
    truth: tuple[bool, ...],
    *,
    deadline_ms: int,
    stable_ms: int,
) -> dict[str, Any]:
    stable_since: int | None = None
    last_truth = False
    last_coverage = "COMPLETE"
    for item, matched in zip(timeline, truth, strict=True):
        at_ms = int(item["at_ms"])
        state = str(item.get("state") or "AVAILABLE")
        last_coverage = str(item.get("coverage") or "COMPLETE")
        if state in {"STALE", "UNAVAILABLE", "CANCELLED"}:
            status = {
                "STALE": "PARTIAL",
                "UNAVAILABLE": "BLOCKED",
                "CANCELLED": "CANCELLED",
            }[state]
            return {
                "status": status,
                "outcome": state,
                "elapsed_ms": at_ms,
                "matched_count": 0,
                "stable_interval_ms": 0,
            }
        last_truth = matched
        if matched:
            if stable_since is None:
                stable_since = at_ms
            if at_ms >= stable_since + stable_ms:
                return {
                    "status": "SUCCEEDED",
                    "outcome": "SATISFIED",
                    "elapsed_ms": at_ms,
                    "matched_count": 1,
                    "stable_interval_ms": at_ms - stable_since,
                }
        else:
            stable_since = None
    return {
        "status": "SUCCEEDED" if last_coverage == "COMPLETE" else "PARTIAL",
        "outcome": "TIMED_OUT",
        "elapsed_ms": deadline_ms,
        "matched_count": 1 if last_truth else 0,
        "stable_interval_ms": 0,
    }


def _oracle_visible_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _oracle_url_match(actual: str, expected: str, mode: str) -> bool:
    actual_raw = urlsplit(actual)
    expected_raw = urlsplit(expected)
    # Closed safety checks are intentionally visible in one audit point.
    if (
        actual_raw.scheme.lower() not in {"http", "https"}
        or expected_raw.scheme.lower() not in {"http", "https"}
        or actual_raw.username is not None
        or actual_raw.password is not None
        or expected_raw.username is not None
        or expected_raw.password is not None
    ):
        return False
    actual_parts = _oracle_url(actual)
    expected_parts = _oracle_url(expected)
    if mode == "exact":
        return actual_parts == expected_parts
    if expected_parts[3] or expected_parts[4]:
        return False
    if actual_parts[:2] != expected_parts[:2]:
        return False
    actual_path = actual_parts[2]
    expected_path = expected_parts[2]
    return actual_path == expected_path or actual_path.startswith(
        expected_path.rstrip("/") + "/",
    )


def _oracle_url(value: str) -> tuple[str, str, str, str, str]:
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").encode("idna").decode().lower()
    port = parsed.port
    if port == (80 if scheme == "http" else 443):
        port = None
    authority = host if port is None else f"{host}:{port}"
    path = posixpath.normpath(parsed.path or "/")
    if not path.startswith("/"):
        path = f"/{path}"
    normalized = urlsplit(
        urlunsplit((scheme, authority, path, parsed.query, parsed.fragment)),
    )
    return (
        normalized.scheme,
        normalized.netloc,
        normalized.path,
        normalized.query,
        normalized.fragment,
    )


__all__ = ["IndependentOracle"]
