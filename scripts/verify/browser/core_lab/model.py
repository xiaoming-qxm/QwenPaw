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
    ACTION_BEFORE_DISPATCH = "BEFORE_DISPATCH"
    AFTER_SEND_BEFORE_ACK = "AFTER_SEND_BEFORE_ACK"
    AFTER_ACK_BEFORE_EFFECT = "AFTER_ACK_BEFORE_EFFECT"
    AFTER_EFFECT_BEFORE_VERIFY = "AFTER_EFFECT_BEFORE_VERIFY"
    DURING_RESULT_MAPPING = "DURING_RESULT_MAPPING"
    DROP_REQUIRED_RESOURCE_BLOCK = "DROP_REQUIRED_RESOURCE_BLOCK"
    BRIDGE_OR_EXTENSION_LOSS = "BRIDGE_OR_EXTENSION_LOSS"
    CLEANUP_FAILURE = "CLEANUP_FAILURE"
    AFTER_PRE_ARM = "AFTER_PRE_ARM"
    DOWNLOAD_PROGRESS_PARTIAL = "DOWNLOAD_PROGRESS_PARTIAL"
    DOWNLOAD_PROGRESS_COMPLETED = "DOWNLOAD_PROGRESS_COMPLETED"
    BEFORE_BYTE_STABILITY = "BEFORE_BYTE_STABILITY"
    DURING_HASH = "DURING_HASH"
    DURING_INGEST = "DURING_INGEST"
    DURING_PROMOTION = "DURING_PROMOTION"
    DURING_FORMATTER_PREPARE = "DURING_FORMATTER_PREPARE"
    DURING_FINAL_ENVELOPE = "DURING_FINAL_ENVELOPE"
    DURING_TRANSIENT_CLEANUP = "DURING_TRANSIENT_CLEANUP"
    DURING_ARTIFACT_EXPIRY = "DURING_ARTIFACT_EXPIRY"


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


@dataclass(frozen=True, slots=True)
class StateApprovalFacts:
    """Controller-owned state and approval request/grant/attempt facts."""

    expected_decision: str
    observed_decision: str
    expected_state_status: str
    observed_state_status: str
    expected_effect_floor_preserved: bool
    observed_effect_floor_preserved: bool
    expected_request_count: int
    observed_request_count: int
    expected_grant_count: int
    observed_grant_count: int
    expected_attempt_count: int
    observed_attempt_count: int
    expected_remaining_uses: int
    observed_remaining_uses: int
    native_effect_count: int


@dataclass(frozen=True, slots=True)
class ActionFaultFacts:
    """Independent logs for one S6 command/effect fault cut point."""

    fault: FaultCutPoint
    native_dispatch_count: int
    native_effect_count: int
    blind_resend_count: int
    receipt_state: str
    terminal_status: str
    retry: str
    command_identity_visible: bool
    failure_or_cleanup_visible: bool
    false_success: bool


@dataclass(frozen=True, slots=True)
class S7FamilyFacts:
    """Controller/native facts for one S7 primary-family case."""

    primary_family: CapabilityFamily
    observed_family: CapabilityFamily
    expected_native_effect_count: int
    observed_native_effect_count: int
    expected_native_event_count: int
    observed_native_event_count: int
    exact_identity_bound: bool
    owner_bound: bool
    public_bypass_count: int
    false_success: bool


@dataclass(frozen=True, slots=True)
class ResourceFileFacts:
    """Controller/native/resource facts independent of SDK result claims."""

    operation_kind: str
    expected_native_effect_count: int
    observed_native_effect_count: int
    selected_count: int
    transferred_count: int
    accepted_count: int | None
    owner_bound: bool
    operation_bound: bool
    command_bound: bool
    native_transfer_bound: bool
    byte_stable: bool
    expected_sha256: str
    stored_sha256: str
    exact_metadata: bool
    context_unchanged: bool
    path_free: bool
    clipboard_access_count: int
    cleanup_failure_visible: bool
    false_success: bool


__all__ = [
    "CapabilityFamily",
    "ActionFaultFacts",
    "CaseOutcome",
    "FaultCutPoint",
    "LabCase",
    "OracleResult",
    "ObserveReadFacts",
    "ReplayDescriptor",
    "ResourceFileFacts",
    "S7FamilyFacts",
    "SynchronizeFacts",
    "StateApprovalFacts",
    "TargetControlFacts",
]
