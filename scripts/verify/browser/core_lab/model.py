# -*- coding: utf-8 -*-
"""Closed data model for Browser Core capability cases."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CapabilityFamily(StrEnum):
    RESULT_DELIVERY = "ResultDelivery"
    CONTEXT_NAVIGATE = "ContextNavigate"
    OBSERVE_READ = "ObserveRead"
    SYNCHRONIZE = "Synchronize"
    TARGET_CONTROL = "TargetControl"
    STATE_APPROVAL_EFFECT = "StateApprovalEffect"
    SURFACES_WIDGETS = "SurfacesWidgets"
    RESOURCE_FILE = "ResourceFile"
    VISUAL_CANVAS = "VisualCanvas"
    USER_CHROME_LIFECYCLE = "UserChromeLifecycle"


class CaseOutcome(StrEnum):
    PASS = "PASS"
    PRODUCT_FAILURE = "PRODUCT_FAILURE"
    EXTERNAL_BLOCKED = "EXTERNAL_BLOCKED"
    TEST_INFRA_FAILURE = "TEST_INFRA_FAILURE"
    NOT_RUN = "NOT_RUN"


class FaultCutPoint(StrEnum):
    BEFORE_DISPATCH = "before_dispatch"
    AFTER_DISPATCH = "after_dispatch"
    BEFORE_NATIVE_EFFECT = "before_native_effect"
    AFTER_NATIVE_EFFECT = "after_native_effect"
    BEFORE_STATE_COMMIT = "before_state_commit"
    AFTER_STATE_COMMIT = "after_state_commit"
    BEFORE_RESULT_PUBLISH = "before_result_publish"
    AFTER_RESULT_PUBLISH = "after_result_publish"
    AFTER_FINAL_TARGET_VALIDATE = "after_final_target_validate"


@dataclass(frozen=True, slots=True)
class ReplayDescriptor:
    family: CapabilityFamily
    case_id: str
    seed: int


@dataclass(frozen=True, slots=True)
class LabCase:
    case_id: str
    family: CapabilityFamily
    base_flow: str
    seed: int
    transformations: tuple[str, ...]
    fault: FaultCutPoint | None
    replay: ReplayDescriptor
    prerequisites: tuple[CapabilityFamily, ...] = ()


@dataclass(frozen=True, slots=True)
class OracleResult:
    outcome: CaseOutcome
    expected: dict[str, Any]
    observed: dict[str, Any]
    diff: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ObserveReadFacts:
    """Controller-owned fixture and native call-log facts."""

    candidate_identity_set: tuple[str, ...]
    coverage_gap_set: tuple[str, ...]
    backend_call_count: int
    invariant_unchanged: bool


@dataclass(frozen=True, slots=True)
class SynchronizeFacts:
    """Raw timeline plus controller logs; no Browser result claims."""

    atom_kind: str
    expected_value: object
    match_mode: str
    timeline: tuple[dict[str, Any], ...]
    observed_truth: tuple[bool, ...]
    observed_summary: dict[str, Any]
    hint_sequences: tuple[int, ...]
    deadline_ms: int
    stable_ms: int
    cleanup_count: int
    evaluator_symbols: tuple[str, str]
    matcher_symbols: tuple[str, str]
    probe_identities: tuple[str, str]


@dataclass(frozen=True, slots=True)
class TargetControlFacts:
    """Controller-only fake native object/command/effect facts."""

    expected_object_id: str | None
    observed_object_id: str | None
    expected_command_count: int
    observed_command_count: int
    expected_effect_count: int
    observed_effect_count: int
    public_dispatch_count: int


__all__ = [
    "CapabilityFamily",
    "CaseOutcome",
    "FaultCutPoint",
    "LabCase",
    "OracleResult",
    "ObserveReadFacts",
    "ReplayDescriptor",
    "SynchronizeFacts",
    "TargetControlFacts",
]
