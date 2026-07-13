# -*- coding: utf-8 -*-
"""Thin Canonical Browser action preflight and exact binding skeleton."""

# pylint: disable=protected-access,too-many-boolean-expressions
# pylint: disable=too-many-return-statements

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
import json
import secrets
from time import monotonic
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from .canonical.contracts import (
    ActionExpectation,
    ActionResult,
    BrowserCondition,
    BrowserPrompt,
    ContextVersion,
    PagePdfResult,
    Problem,
    RetryDirective,
    ResourceCondition,
    ResourceHandle,
    StateRequirement,
    TabSummary,
    TargetRef,
    TerminalStatus,
    UploadItemOutcome,
    UploadOutcome,
    _serialize_browser_condition,
    issue_operation_id,
)
from .contracts import BrowserAPIContract
from .condition_evaluator import (
    ConditionBaseline,
    ConditionEvaluation,
    ConditionEvaluator,
    ConditionProbe,
    ConditionReceiver,
    ConditionWatch,
    ResourceOperationBinding,
    _condition_fingerprint,
)
from .governance.boundary import canonical_preflight_handoff_reason
from .governance.effects import (
    UNKNOWN,
    EffectCategory,
    EffectClassification,
    TargetFact,
    classify_effects,
    minimum_effects,
)
from .governance.errors import BrowserSDKError
from .runtime.session_owner import (
    BrowserOwnerRegistryError,
    BrowserRequestBinding,
    BrowserSessionOwnerRegistry,
    StateFactStatus,
    TrustedStateVerifier,
)
from .runtime.result_delivery import require_artifact_delivery_preflight


class PreflightDecision(StrEnum):
    """Closed S5 preflight outcomes."""

    READY = "READY"
    EXACT_APPROVAL = "EXACT_APPROVAL"
    HANDOFF = "HANDOFF"
    BLOCKED = "BLOCKED"


class DispatchFact(StrEnum):
    """Closed operation-level native dispatch truth."""

    NOT_SENT = "NOT_SENT"
    REJECTED = "REJECTED"
    SENT = "SENT"
    UNKNOWN = "UNKNOWN"


class FactOutcome(StrEnum):
    """Closed commit/effect evidence aggregate."""

    NOT_REQUESTED = "NOT_REQUESTED"
    NOT_OBSERVED = "NOT_OBSERVED"
    NOT_COMMITTED = "NOT_COMMITTED"
    OBSERVED = "OBSERVED"
    CONTRADICTED = "CONTRADICTED"
    UNKNOWN = "UNKNOWN"


class PostconditionFact(StrEnum):
    """Closed typed expectation result."""

    NOT_REQUESTED = "NOT_REQUESTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


def _classify_upload_outcome(
    items: tuple[UploadItemOutcome, ...],
) -> Literal["POSITIVE", "NEGATIVE", "PARTIAL", "UNKNOWN"]:
    """Aggregate only closed per-item facts without optimistic inference."""
    if not items or not all(
        isinstance(item, UploadItemOutcome) for item in items
    ):
        raise TypeError("upload items must be a non-empty closed tuple")
    if any(
        "UNKNOWN" in (item.selection, item.transfer, item.acceptance)
        for item in items
    ):
        return "UNKNOWN"
    positive = {
        ("SELECTED", "COMPLETED", "ACCEPTED"),
    }
    negative = {
        ("NOT_SELECTED", "NOT_COMPLETED", "REJECTED"),
    }
    facts = {
        (item.selection, item.transfer, item.acceptance) for item in items
    }
    if facts <= positive:
        return "POSITIVE"
    if facts <= negative:
        return "NEGATIVE"
    return "PARTIAL"


def _upload_terminal_mapping(
    aggregate: str,
) -> tuple[TerminalStatus, RetryDirective]:
    """Map upload truth without making a possibly disclosed group retryable."""
    mapping: dict[str, tuple[TerminalStatus, RetryDirective]] = {
        "POSITIVE": ("SUCCEEDED", "NONE"),
        "PARTIAL": ("PARTIAL", "FORBIDDEN"),
        "UNKNOWN": ("UNCERTAIN", "RECONCILE_ONLY"),
        "NEGATIVE": ("FAILED", "FORBIDDEN"),
    }
    try:
        return mapping[aggregate]
    except KeyError as exc:
        raise ValueError("invalid upload aggregate") from exc


def _required_resource_expectation(
    api_id: str,
    caller: ActionExpectation | None,
) -> ActionExpectation | None:
    """Add the one operation-created resource atom owned by ActionRunner."""
    resource_kind = {
        "tab.actions.download_file": "download",
        "tab.print_to_pdf": "page_pdf",
    }.get(api_id)
    if resource_kind is None:
        return caller
    required = ResourceCondition.created(
        kind=cast(Literal["download", "page_pdf"], resource_kind),
        count=1,
    )
    atoms = caller.condition.atoms if caller is not None else ()
    if required not in atoms:
        atoms = (*atoms, required)
    return ActionExpectation.transition(
        BrowserCondition.all(*atoms),
        stable_ms=caller.stable_ms if caller is not None else 0,
    )


def _download_terminal_projection(
    expectation: ActionExpectation,
    dispatch: object,
    evaluation_outcome: object,
) -> tuple[TerminalStatus, RetryDirective, tuple[ResourceHandle, ...]]:
    """Project only known correlated resource facts into terminal truth."""
    if not isinstance(dispatch, Mapping):
        return ("UNCERTAIN", "RECONCILE_ONLY", ())
    payload = dispatch.get("download")
    if not isinstance(payload, Mapping):
        return ("UNCERTAIN", "RECONCILE_ONLY", ())
    raw_resources = payload.get("resources")
    if not isinstance(raw_resources, (tuple, list)) or not all(
        isinstance(item, ResourceHandle) for item in raw_resources
    ):
        return ("UNCERTAIN", "RECONCILE_ONLY", ())
    current = tuple(cast(ResourceHandle, item) for item in raw_resources)
    if not current:
        if payload.get("count") == 0:
            return ("FAILED", "FORBIDDEN", ())
        return ("UNCERTAIN", "RECONCILE_ONLY", ())
    required = next(
        (
            atom
            for atom in expectation.condition.atoms
            if isinstance(atom, ResourceCondition)
            and atom.kind == "created"
            and isinstance(atom.subject, tuple)
            and atom.subject[0] == "download"
        ),
        None,
    )
    if required is None:
        return ("UNCERTAIN", "RECONCILE_ONLY", current)
    _, count, media_type, name = cast(
        tuple[object, object, object, object],
        required.subject,
    )
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or not isinstance(media_type, (str, type(None)))
        or not isinstance(name, (str, type(None)))
    ):
        return ("UNCERTAIN", "RECONCILE_ONLY", current)
    exact = len(current) == count and all(
        (media_type is None or item.media_type == media_type)
        and (name is None or item.name == name)
        for item in current
    )
    if not exact:
        return ("PARTIAL", "FORBIDDEN", current)
    if evaluation_outcome == "SATISFIED":
        return ("SUCCEEDED", "NONE", current)
    return ("UNCERTAIN", "RECONCILE_ONLY", current)


def _page_pdf_terminal_projection(
    dispatch: object,
    evaluation_outcome: object,
) -> tuple[
    TerminalStatus,
    RetryDirective,
    ResourceHandle | None,
    ContextVersion | None,
    ContextVersion | None,
    str,
]:
    """Preserve complete PDF facts without claiming one-version truth."""
    if not isinstance(dispatch, Mapping):
        return ("UNCERTAIN", "RECONCILE_ONLY", None, None, None, "UNKNOWN")
    payload = dispatch.get("page_pdf")
    if not isinstance(payload, Mapping):
        return ("UNCERTAIN", "RECONCILE_ONLY", None, None, None, "UNKNOWN")
    resource = payload.get("resource")
    before = payload.get("context_before")
    after = payload.get("context_after")
    if not isinstance(resource, ResourceHandle):
        return ("UNCERTAIN", "RECONCILE_ONLY", None, None, None, "UNKNOWN")
    if not isinstance(before, ContextVersion) or not isinstance(
        after,
        ContextVersion,
    ):
        return (
            "UNCERTAIN",
            "RECONCILE_ONLY",
            resource,
            None,
            None,
            "UNKNOWN",
        )
    if before is not after:
        return ("PARTIAL", "FORBIDDEN", resource, before, after, "CHANGED")
    if evaluation_outcome == "SATISFIED":
        return ("SUCCEEDED", "NONE", resource, before, after, "SAME")
    return (
        "UNCERTAIN",
        "RECONCILE_ONLY",
        resource,
        before,
        after,
        "UNKNOWN",
    )


@dataclass(frozen=True, slots=True)
class EffectFact:
    """Evidence outcome for one concrete classified effect."""

    category: EffectCategory
    outcome: FactOutcome


CommandKind = Literal["INITIAL", "PROMPT_RESPONSE", "STATUS_QUERY"]
CommandObservedState = Literal[
    "NOT_OBSERVED",
    "RECEIVED",
    "RUNNING",
    "COMPLETED",
    "LOST",
    "UNKNOWN",
]


@dataclass(frozen=True, slots=True)
class CommandFact:
    """Pre-send fact proving that observation has not yet occurred."""

    command_id: str
    command_kind: CommandKind
    safe_fingerprint_summary: str
    observed_state: CommandObservedState = "NOT_OBSERVED"


@dataclass(frozen=True, slots=True)
class PendingCommand:
    """One independently identified command under a logical operation."""

    command_id: str
    command_kind: CommandKind
    command_fingerprint: str
    operation_fingerprint: str
    _payload: object = field(repr=False, compare=False)


@dataclass(slots=True)
class PendingAction:
    """Owner-persistent logical mutation and its pre-send command facts."""

    operation_id: str
    operation_fingerprint: str
    revision: int
    logical_api: str
    ordered_target_bindings: tuple[tuple[str, str], ...]
    critical_arguments: tuple[tuple[str, object], ...] = field(repr=False)
    state_binding_digest: str
    expectation_digest: str
    classified_effects: tuple[EffectCategory, ...]
    receiver_tab_ref: str
    context_ref: str
    expires_at: float
    command_fingerprints: dict[str, str] = field(default_factory=dict)
    command_facts: dict[str, CommandFact] = field(default_factory=dict)
    commands: dict[str, PendingCommand] = field(default_factory=dict)
    _status_query: Callable[
        ["PendingAction"],
        Awaitable[object],
    ] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _reconcile_evaluator: ConditionEvaluator | Any | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _reconcile_receiver: ConditionReceiver | Any | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _reconcile_probe: ConditionProbe | Any | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _reconcile_expectation: ActionExpectation | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _reconcile_baseline: ConditionBaseline | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def issue_command(
        self,
        command_kind: CommandKind,
        payload: object,
    ) -> PendingCommand:
        """Persist a fresh command identity and NOT_OBSERVED fact."""
        command_id = f"browser-command-{secrets.token_urlsafe(24)}"
        while command_id in self.commands:
            command_id = f"browser-command-{secrets.token_urlsafe(24)}"
        return self.issue_command_with_id(command_id, command_kind, payload)

    def issue_command_with_id(
        self,
        command_id: str,
        command_kind: CommandKind,
        payload: object,
    ) -> PendingCommand:
        """Idempotently persist the exact command before any send."""
        if command_kind not in {
            "INITIAL",
            "PROMPT_RESPONSE",
            "STATUS_QUERY",
        }:
            raise BrowserSDKError(
                "pending command kind is invalid",
                code="command_kind_invalid",
            )
        normalized_id = str(command_id or "").strip()
        if not normalized_id:
            raise BrowserSDKError(
                "pending command id is invalid",
                code="command_id_invalid",
            )
        fingerprint = _digest(
            {
                "command_id": normalized_id,
                "operation_fingerprint": self.operation_fingerprint,
                "command_kind": command_kind,
                "logical_api": self.logical_api,
                "receiver_tab_ref": self.receiver_tab_ref,
                "context_ref": self.context_ref,
                "expectation_digest": self.expectation_digest,
                "classified_effects": self.classified_effects,
                "payload": payload,
            },
        )
        existing = self.commands.get(normalized_id)
        if existing is not None:
            if existing.command_fingerprint != fingerprint:
                raise BrowserSDKError(
                    "command id is bound to a different fingerprint",
                    code="command_fingerprint_mismatch",
                )
            return existing
        command = PendingCommand(
            command_id=normalized_id,
            command_kind=command_kind,
            command_fingerprint=fingerprint,
            operation_fingerprint=self.operation_fingerprint,
            _payload=payload,
        )
        self.command_fingerprints[normalized_id] = fingerprint
        self.command_facts[normalized_id] = CommandFact(
            command_id=normalized_id,
            command_kind=command_kind,
            safe_fingerprint_summary=fingerprint[:16],
        )
        self.commands[normalized_id] = command
        return command

    def configure_reconcile(
        self,
        *,
        status_query: Callable[["PendingAction"], Awaitable[object]],
        evaluator: ConditionEvaluator | Any | None = None,
        receiver: ConditionReceiver | Any | None = None,
        probe: ConditionProbe | Any | None = None,
        expectation: ActionExpectation | None = None,
        baseline: ConditionBaseline | None = None,
    ) -> None:
        """Bind the private read-only receipt query for this operation."""
        self._status_query = status_query
        self._reconcile_evaluator = evaluator
        self._reconcile_receiver = receiver
        self._reconcile_probe = probe
        self._reconcile_expectation = expectation
        self._reconcile_baseline = baseline


class PendingActionStore:
    """Lease-fenced view over the sole registry owner record."""

    def __init__(
        self,
        *,
        registry: BrowserSessionOwnerRegistry,
        binding: BrowserRequestBinding,
    ) -> None:
        self._registry = registry
        self._binding = binding

    def create(
        self,
        *,
        logical_api: str,
        ordered_target_bindings: tuple[tuple[str, str], ...],
        critical_arguments: tuple[tuple[str, object], ...],
        state_binding_digest: str,
        expectation_digest: str,
        classified_effects: tuple[EffectCategory, ...],
        receiver_tab_ref: str,
        context_ref: str,
        operation_id: str | None = None,
        operation_fingerprint: str | None = None,
    ) -> PendingAction:
        """Create and owner-persist one immutable logical identity."""
        issued_operation_id = operation_id or str(issue_operation_id())
        fingerprint = operation_fingerprint or _digest(
            {
                "owner": self._binding.owner_key,
                "logical_api": logical_api,
                "ordered_target_bindings": ordered_target_bindings,
                "critical_arguments": critical_arguments,
                "state_binding_digest": state_binding_digest,
                "expectation_digest": expectation_digest,
                "classified_effects": classified_effects,
                "receiver_tab_ref": receiver_tab_ref,
                "context_ref": context_ref,
            },
        )
        action = PendingAction(
            operation_id=issued_operation_id,
            operation_fingerprint=fingerprint,
            revision=1,
            logical_api=str(logical_api),
            ordered_target_bindings=tuple(ordered_target_bindings),
            critical_arguments=tuple(critical_arguments),
            state_binding_digest=str(state_binding_digest),
            expectation_digest=str(expectation_digest),
            classified_effects=tuple(classified_effects),
            receiver_tab_ref=str(receiver_tab_ref),
            context_ref=str(context_ref),
            expires_at=self._registry.pending_action_expiry(),
        )
        self._registry.save_pending_action(self._binding, action)
        return action

    def require(self, operation_id: str) -> PendingAction:
        """Return the action through the current owner lease."""
        action = self._registry.require_pending_action(
            self._binding,
            operation_id,
        )
        if not isinstance(action, PendingAction):
            raise BrowserSDKError(
                "pending action has an invalid Runtime type",
                code="pending_action_invalid",
            )
        return action

    def abandon(self, operation_id: str) -> None:
        """Remove the action through the current owner lease."""
        self._registry.abandon_pending_action(self._binding, operation_id)


@dataclass(frozen=True, slots=True)
class ActionPreview:
    """Safe projection plus private canonical material for exact binding."""

    root_task_id: str
    browser_owner_id: str
    operation_id: str
    api_id: str
    session_id: str
    tab_ref: str | None
    origin: str
    ordered_targets: tuple[tuple[str, str], ...]
    state_revision: str
    state_binding_digest: str
    effects: tuple[EffectCategory, ...]
    expectation_digest: str
    safe_arguments: tuple[tuple[str, object], ...]
    expires_at: float
    layout_revision: str
    operation_fingerprint: str
    binding_hash: str
    _critical_arguments: tuple[tuple[str, object], ...] = field(
        repr=False,
        compare=False,
    )
    _registry: BrowserSessionOwnerRegistry | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _owner_binding: BrowserRequestBinding | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _receiver_tab_key: str = field(
        default="",
        repr=False,
        compare=False,
    )

    def with_origin(self, origin: str) -> "ActionPreview":
        return _rehash(replace(self, origin=str(origin)))

    def with_argument(self, name: str, value: object) -> "ActionPreview":
        arguments = dict(self._critical_arguments)
        arguments[str(name)] = value
        critical = tuple(sorted(arguments.items()))
        return _rehash(
            replace(
                self,
                _critical_arguments=critical,
                safe_arguments=_safe_arguments(critical),
            ),
        )

    def with_state_revision(self, revision: str) -> "ActionPreview":
        return _rehash(replace(self, state_revision=str(revision)))

    def swap_ordered_targets(self) -> "ActionPreview":
        return _rehash(
            replace(
                self,
                ordered_targets=tuple(reversed(self.ordered_targets)),
            ),
        )

    def with_layout_revision(self, revision: str) -> "ActionPreview":
        return replace(self, layout_revision=str(revision))

    def with_effects(
        self,
        effects: tuple[EffectCategory, ...],
    ) -> "ActionPreview":
        return _rehash(replace(self, effects=tuple(effects)))

    def with_expectation_digest(self, digest: str) -> "ActionPreview":
        return _rehash(replace(self, expectation_digest=str(digest)))

    def with_operation_id(self, operation_id: str) -> "ActionPreview":
        return _rehash(replace(self, operation_id=str(operation_id)))


@dataclass(slots=True)
class ApprovalGrant:
    """Single-use exact grant; atomic consumption is activated in T005."""

    grant_id: str
    operation_id: str
    operation_fingerprint: str
    binding_hash: str
    expires_at: float
    remaining_uses: int = 1


@dataclass(slots=True)
class PromptResponseGrant:
    """Single-use exact authorization for one prompt continuation delta."""

    grant_id: str
    operation_id: str
    prompt_id: str
    binding_digest: str
    effects: tuple[str, ...]
    expires_at: float
    remaining_uses: int = 1


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """Registry-bound trust facts for one dispatch attempt."""

    root_task_id: str
    browser_owner_id: str
    session_id: str
    owner_lease_generation: int
    api_id: str
    operation_id: str
    operation_fingerprint: str
    command_id: str
    command_kind: CommandKind
    command_fingerprint: str
    receiver_tab_ref: str | None
    context_ref: str | None
    binding_hash: str
    approval_grant_id: str | None
    expectation_digest: str
    classified_effects: tuple[EffectCategory, ...]
    _registry: BrowserSessionOwnerRegistry = field(repr=False, compare=False)
    _owner_binding: BrowserRequestBinding = field(repr=False, compare=False)
    _receiver_tab_key: str = field(repr=False, compare=False)

    @property
    def lease_generation(self) -> int:
        """Return the S5-compatible name for the owner lease generation."""
        return self.owner_lease_generation

    @property
    def grant_id(self) -> str:
        """Return the S5-compatible exact grant id."""
        return self.approval_grant_id or ""

    @property
    def effects(self) -> tuple[EffectCategory, ...]:
        """Return the S5-compatible classified effect tuple."""
        return self.classified_effects

    def is_bound_to(
        self,
        registry: BrowserSessionOwnerRegistry,
        receiver_tab: str,
    ) -> bool:
        """Return exact private registry and receiver binding equality."""
        return self._registry is registry and self._receiver_tab_key == str(
            receiver_tab,
        )


@dataclass(frozen=True, slots=True)
class ActionPreflight:
    """Result of the sole S5 action preflight entry."""

    decision: PreflightDecision
    reason: str
    preview: ActionPreview | None = None
    needs_exact_approval: bool = False
    grant_consumed: bool = False

    def dispatch_context(
        self,
        grant: ApprovalGrant,
        *,
        command: PendingCommand | None = None,
    ) -> DispatchContext:
        """Issue and registry-bind the one context for this preflight."""
        if self.preview is None:
            raise BrowserSDKError(
                "preflight has no dispatchable preview",
                code="dispatch_context_invalid",
            )
        return _dispatch_context(self.preview, grant, command=command)


class ActionRunner:
    """Compose owner, target, state, effect and expectation before dispatch."""

    def __init__(
        self,
        *,
        registry: BrowserSessionOwnerRegistry,
        clock: Callable[[], float] = monotonic,
        verifier_catalog: tuple[TrustedStateVerifier, ...] = (),
    ) -> None:
        self._registry = registry
        self._clock = clock
        self._verifier_catalog = tuple(verifier_catalog)

    @staticmethod
    def prompt_response_effect_delta(
        *,
        prompt_type: str,
        text: str | None,
    ) -> tuple[str, ...]:
        """Return the closed conservative delta for one prompt response."""
        classification = minimum_effects(
            "tab.actions.respond_prompt",
            {
                "prompt_kind": prompt_type,
                "parent_effects": (),
                "prompt_text": text or "",
            },
        )
        return tuple(effect.value for effect in classification)

    async def continue_prompt(
        self,
        *,
        binding: BrowserRequestBinding,
        prompt: BrowserPrompt,
        decision: str,
        text: str | None,
        dispatcher: Callable[..., Awaitable[object]] | None,
        continuation_grant: PromptResponseGrant | None = None,
    ) -> ActionResult:
        """Issue one new prompt-bound command under the immutable parent."""
        prompt_binding = self._registry.resolve_browser_prompt(
            prompt,
            owner=binding,
        )
        prompt_type = str(prompt.type)
        _validate_prompt_response(prompt_type, decision, text)
        parent_id = prompt_binding.parent_operation_id
        if not parent_id:
            return ActionResult(
                operation_id=issue_operation_id(),
                status="BLOCKED",
                retry="FORBIDDEN",
                problem=Problem(
                    code="prompt_parent_unavailable",
                    phase="PREFLIGHT",
                    safe_message="Prompt has no executable parent operation.",
                ),
                dispatch="NOT_SENT",
            )
        pending = self._registry.require_pending_action(binding, parent_id)
        if not isinstance(pending, PendingAction):
            raise BrowserSDKError(
                "prompt parent action is invalid",
                code="prompt_parent_invalid",
            )
        delta = self.prompt_response_effect_delta(
            prompt_type=prompt_type,
            text=text,
        )
        expected_digest = _prompt_response_binding_digest(
            pending=pending,
            prompt=prompt,
            decision=decision,
            text=text,
            effects=delta,
        )
        if continuation_grant is None:
            return ActionResult(
                operation_id=pending.operation_id,
                status="BLOCKED",
                retry="FORBIDDEN",
                problem=Problem(
                    code="prompt_continuation_approval_required",
                    phase="PREFLIGHT",
                    safe_message="Prompt response requires exact approval.",
                ),
                classified_effects=delta,
                dispatch="NOT_SENT",
            )
        if (
            continuation_grant.operation_id != pending.operation_id
            or continuation_grant.prompt_id != str(prompt.prompt_id)
            or continuation_grant.binding_digest != expected_digest
            or continuation_grant.effects != delta
            or continuation_grant.remaining_uses != 1
            or self._clock() > continuation_grant.expires_at
        ):
            raise BrowserSDKError(
                "prompt continuation grant is stale or mismatched",
                code="prompt_continuation_grant_invalid",
            )
        command = pending.issue_command(
            "PROMPT_RESPONSE",
            {
                "prompt_id": str(prompt.prompt_id),
                "native_identity": prompt_binding.native_identity,
                "decision": decision,
                "text_digest": (
                    sha256(text.encode()).hexdigest() if text else ""
                ),
                "state_binding_digest": pending.state_binding_digest,
                "effect_delta": delta,
            },
        )
        if dispatcher is None:
            raise BrowserSDKError(
                "prompt response dispatcher is unavailable",
                code="prompt_dispatcher_missing",
            )
        continuation_grant.remaining_uses = 0
        await dispatcher(command=command, prompt=prompt)
        return ActionResult(
            operation_id=pending.operation_id,
            status="UNCERTAIN",
            retry="RECONCILE_ONLY",
            problem=Problem(
                code="prompt_response_reconcile_required",
                phase="VERIFY",
                safe_message=(
                    "Prompt response requires receipt reconciliation."
                ),
            ),
            classified_effects=delta,
            commands=(pending.command_facts[command.command_id],),
            dispatch="SENT",
        )

    def issue_prompt_response_grant(
        self,
        *,
        binding: BrowserRequestBinding,
        prompt: BrowserPrompt,
        decision: str,
        text: str | None,
        ttl_seconds: float = 60.0,
    ) -> PromptResponseGrant:
        """Issue a testable exact grant after an external approval decision."""
        prompt_binding = self._registry.resolve_browser_prompt(
            prompt,
            owner=binding,
        )
        _validate_prompt_response(str(prompt.type), decision, text)
        if not prompt_binding.parent_operation_id:
            raise BrowserSDKError(
                "prompt has no parent operation",
                code="prompt_parent_unavailable",
            )
        pending = self._registry.require_pending_action(
            binding,
            prompt_binding.parent_operation_id,
        )
        if not isinstance(pending, PendingAction):
            raise BrowserSDKError(
                "prompt parent action is invalid",
                code="prompt_parent_invalid",
            )
        effects = self.prompt_response_effect_delta(
            prompt_type=str(prompt.type),
            text=text,
        )
        return PromptResponseGrant(
            grant_id=f"prompt-grant-{secrets.token_hex(12)}",
            operation_id=pending.operation_id,
            prompt_id=str(prompt.prompt_id),
            binding_digest=_prompt_response_binding_digest(
                pending=pending,
                prompt=prompt,
                decision=decision,
                text=text,
                effects=effects,
            ),
            effects=effects,
            expires_at=self._clock() + float(ttl_seconds),
        )

    async def run(
        self,
        *,
        binding: BrowserRequestBinding,
        receiver_tab: TabSummary | None,
        contract: BrowserAPIContract,
        ordered_targets: tuple[tuple[str, TargetRef], ...],
        arguments: Mapping[str, object],
        expectation: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        deadline: float | None = None,
        condition_evaluator: ConditionEvaluator | Any | None = None,
        condition_receiver: ConditionReceiver | Any | None = None,
        condition_probe: ConditionProbe | Any | None = None,
        condition_baseline: ConditionBaseline | None = None,
        final_revalidator: Callable[..., Awaitable[str]] | None = None,
        approval_grant: ApprovalGrant | None = None,
        dispatcher: Callable[..., Awaitable[object]] | None = None,
        event_hook: Callable[[str], None] | None = None,
        receipt_status_query: (
            Callable[[PendingAction], Awaitable[object]] | None
        ) = None,
    ) -> ActionResult | PagePdfResult:
        """Enter the sole bounded Canonical mutation attempt."""
        if contract.api_id == "tab.print_to_pdf":
            require_artifact_delivery_preflight("application/pdf")
        expectation = _required_resource_expectation(
            contract.api_id,
            expectation,
        )
        preflight = await self.preflight(
            contract=contract,
            binding=binding,
            receiver_tab=receiver_tab,
            ordered_targets=ordered_targets,
            arguments=arguments,
            expectation=expectation,
            state=state,
        )
        if (
            preflight.preview is not None
            and expectation is not None
            and condition_evaluator is not None
            and condition_receiver is not None
            and condition_probe is not None
            and dispatcher is not None
        ):
            return await self._run_armed_attempt(
                preflight=preflight,
                binding=binding,
                receiver_tab=receiver_tab,
                contract=contract,
                ordered_targets=ordered_targets,
                arguments=arguments,
                expectation=expectation,
                state=state,
                deadline=deadline,
                evaluator=condition_evaluator,
                condition_receiver=condition_receiver,
                condition_probe=condition_probe,
                baseline=condition_baseline,
                final_revalidator=final_revalidator,
                approval_grant=approval_grant,
                dispatcher=dispatcher,
                event_hook=event_hook,
                receipt_status_query=receipt_status_query,
            )
        return _blocked_run_result(preflight, contract)

    async def _run_armed_attempt(
        self,
        *,
        preflight: ActionPreflight,
        binding: BrowserRequestBinding,
        receiver_tab: TabSummary | None,
        contract: BrowserAPIContract,
        ordered_targets: tuple[tuple[str, TargetRef], ...],
        arguments: Mapping[str, object],
        expectation: ActionExpectation,
        state: StateRequirement | None,
        deadline: float | None,
        evaluator: ConditionEvaluator | Any,
        condition_receiver: ConditionReceiver | Any,
        condition_probe: ConditionProbe | Any,
        baseline: ConditionBaseline | None,
        final_revalidator: Callable[..., Awaitable[str]] | None,
        approval_grant: ApprovalGrant | None,
        dispatcher: Callable[..., Awaitable[object]],
        event_hook: Callable[[str], None] | None,
        receipt_status_query: Callable[[PendingAction], Awaitable[object]]
        | None,
    ) -> ActionResult | PagePdfResult:
        """Run the pre-armed, final-revalidated single attempt."""
        preview = preflight.preview
        assert preview is not None
        pending = PendingActionStore(
            registry=self._registry,
            binding=binding,
        ).create(
            logical_api=contract.api_id,
            ordered_target_bindings=preview.ordered_targets,
            critical_arguments=preview._critical_arguments,
            state_binding_digest=preview.state_binding_digest,
            expectation_digest=preview.expectation_digest,
            classified_effects=preview.effects,
            receiver_tab_ref=preview.tab_ref or "",
            context_ref=preview.state_revision,
            operation_id=preview.operation_id,
            operation_fingerprint=preview.operation_fingerprint,
        )
        _emit(event_hook, "pending_saved")
        _configure_pending_reconcile(
            pending,
            status_query=receipt_status_query,
            evaluator=evaluator,
            receiver=condition_receiver,
            probe=condition_probe,
            expectation=expectation,
            baseline=baseline,
        )
        resource_operation, watch = await _arm_condition_watch(
            pending=pending,
            evaluator=evaluator,
            receiver=condition_receiver,
            probe=condition_probe,
            expectation=expectation,
            baseline=baseline,
        )
        _emit(event_hook, "watcher_prearmed")
        watch_consumed = False
        timeout_ms = _remaining_timeout_ms(deadline, self._clock())
        try:
            _validate_armed_watch(
                watch,
                pending=pending,
                receiver=condition_receiver,
                expectation=expectation,
                baseline=baseline,
            )
        except Exception:
            await evaluator.evaluate(
                condition_receiver,
                expectation.condition,
                probe=condition_probe,
                timeout_ms=1,
                stable_ms=0,
                baseline=baseline,
                armed=watch,
            )
            raise
        try:
            if final_revalidator is None:
                repeated = await self.preflight(
                    contract=contract,
                    binding=binding,
                    receiver_tab=receiver_tab,
                    ordered_targets=ordered_targets,
                    arguments=arguments,
                    expectation=expectation,
                    state=state,
                )
                decision = (
                    "VALID"
                    if repeated.preview is not None
                    and _preview_material(repeated.preview)
                    == _preview_material(preview)
                    else "DRIFTED"
                )
                _emit(event_hook, "final_revalidation")
            else:
                decision = await final_revalidator(
                    pending=pending,
                    preview=preview,
                    watch=watch,
                )
                _emit(event_hook, "final_revalidation")
            if decision in {"ALREADY_SATISFIED", "DRIFTED"}:
                if approval_grant is not None:
                    approval_grant.remaining_uses = 0
                watch_consumed = True
                await evaluator.evaluate(
                    condition_receiver,
                    expectation.condition,
                    probe=condition_probe,
                    timeout_ms=max(1, timeout_ms),
                    stable_ms=expectation.stable_ms,
                    baseline=baseline,
                    armed=watch,
                )
                if decision == "ALREADY_SATISFIED":
                    return ActionResult(
                        operation_id=pending.operation_id,
                        status="SUCCEEDED",
                        retry="NONE",
                        already_satisfied=True,
                        dispatch="NOT_SENT",
                    )
                return ActionResult(
                    operation_id=pending.operation_id,
                    status="BLOCKED",
                    retry="AFTER_OBSERVATION",
                    problem=Problem(
                        code="final_revalidation_drifted",
                        phase="PREFLIGHT",
                        safe_message=(
                            "Action state changed before native dispatch."
                        ),
                    ),
                    dispatch="NOT_SENT",
                )
            if decision != "VALID":
                raise BrowserSDKError(
                    "final revalidator returned an invalid decision",
                    code="final_revalidation_invalid",
                )
            command_payload: dict[str, object] = {
                "arguments": dict(arguments),
                "root_task_id": binding.root_task_id,
                "browser_owner_id": binding.browser_owner_id,
                "session_id": binding.root_session_id,
                "owner_lease_generation": binding.lease_generation,
                "binding_hash": preview.binding_hash,
                "approval_grant_id": (
                    approval_grant.grant_id
                    if approval_grant is not None
                    else None
                ),
            }
            sealed_operation = getattr(
                getattr(watch, "_request", None),
                "operation",
                None,
            )
            if isinstance(sealed_operation, ResourceOperationBinding):
                command_payload["resource_operation"] = {
                    "operation_id": sealed_operation.operation_id,
                    "operation_fingerprint": (
                        sealed_operation.operation_fingerprint
                    ),
                    "command_id": sealed_operation.command_id,
                    "owner_key": sealed_operation.owner_key,
                    "tab_id": sealed_operation.tab_id,
                    "pre_arm_watermark": (sealed_operation.pre_arm_watermark),
                }
            command = pending.issue_command_with_id(
                (
                    resource_operation.command_id
                    if resource_operation is not None
                    else f"browser-command-{secrets.token_urlsafe(24)}"
                ),
                "INITIAL",
                command_payload,
            )
            _emit(event_hook, "command_fact_persisted")
            dispatch_context = None
            if approval_grant is not None:
                dispatch_context = preflight.dispatch_context(
                    approval_grant,
                    command=command,
                )
                await self._registry.consume_grant_for_dispatch(
                    dispatch_context,
                )
                _emit(event_hook, "grant_consumed")
            _emit(event_hook, "dispatch")
            dispatch_fact = await dispatcher(
                command=command,
                dispatch_context=dispatch_context,
            )
            watch_consumed = True
            evaluation = await evaluator.evaluate(
                condition_receiver,
                expectation.condition,
                probe=condition_probe,
                timeout_ms=max(1, timeout_ms),
                stable_ms=expectation.stable_ms,
                baseline=baseline,
                armed=watch,
            )
            return await _project_armed_terminal(
                registry=self._registry,
                binding=binding,
                pending=pending,
                contract=contract,
                expectation=expectation,
                receiver_tab=receiver_tab,
                dispatch_fact=dispatch_fact,
                evaluation=evaluation,
                command_id=command.command_id,
                deadline=deadline,
            )
        finally:
            if not watch_consumed:
                await evaluator.evaluate(
                    condition_receiver,
                    expectation.condition,
                    probe=condition_probe,
                    timeout_ms=1,
                    stable_ms=0,
                    baseline=baseline,
                    armed=watch,
                )

    async def preflight(
        self,
        *,
        contract: BrowserAPIContract,
        binding: BrowserRequestBinding,
        receiver_tab: TabSummary | None,
        ordered_targets: tuple[tuple[str, TargetRef], ...],
        arguments: Mapping[str, object],
        expectation: ActionExpectation | None,
        state: StateRequirement | None,
    ) -> ActionPreflight:
        """Return one fail-closed outcome without dispatching a command."""
        if (
            not isinstance(contract, BrowserAPIContract)
            or not contract.mutates
        ):
            raise BrowserSDKError(
                "ActionRunner requires a mutating Browser API contract",
                code="action_contract_invalid",
            )
        if not isinstance(binding, BrowserRequestBinding):
            raise BrowserSDKError(
                "ActionRunner owner binding is invalid",
                code="browser_ownership_context_missing",
            )
        unresolved = self._registry.unresolved_pending_action(binding)
        if isinstance(unresolved, PendingAction):
            reconciled = await reconcile_pending(
                binding=binding,
                pending=unresolved,
                deadline=min(unresolved.expires_at, self._clock() + 30.0),
            )
            if reconciled.status == "UNCERTAIN":
                return ActionPreflight(
                    decision=PreflightDecision.HANDOFF,
                    reason="pending_action_reconcile_required",
                )
            self._registry.clear_uncertain_action(
                binding,
                unresolved.operation_id,
            )
        if receiver_tab is None:
            receiver_key = ""
            tab_ref = None
            origin = "about:blank"
            state_revision = f"lease:{binding.lease_generation}"
            layout_revision = "none"
        else:
            try:
                resolved_tab = self._registry.resolve_tab_summary(
                    receiver_tab,
                    owner=binding,
                )
            except BrowserOwnerRegistryError as exc:
                raise BrowserSDKError(
                    "ActionRunner owner binding is not registered",
                    code="browser_ownership_context_missing",
                ) from exc
            receiver_key = resolved_tab.receiver_tab_key
            tab_ref = str(receiver_tab.tab_ref)
            origin = resolved_tab.origin
            state_revision = resolved_tab.state_revision
            layout_revision = resolved_tab.layout_revision

        logical_targets, target_facts = self._resolve_targets(
            ordered_targets,
            receiver_key=receiver_key,
            owner=binding,
        )
        requirement = state or StateRequirement()
        collector = self._registry.state_binding_owner(
            binding,
            runtime_session_id=binding.root_session_id,
            origin=origin,
            generation=state_revision,
            verifier_catalog=self._verifier_catalog,
        )
        state_binding = await collector.collect_state_binding(
            requirement=requirement,
            trusted_floor=StateRequirement(same_session=True),
        )
        if any(
            fact.status is not StateFactStatus.VERIFIED
            for _, fact in state_binding.required_facts
        ):
            return ActionPreflight(
                decision=PreflightDecision.HANDOFF,
                reason="required_state_not_verified",
            )

        classification = classify_effects(
            contract.api_id,
            target_facts=target_facts,
            arguments=arguments,
        )
        expectation_digest = _expectation_digest(expectation)
        preview = _new_preview(
            binding=binding,
            contract=contract,
            tab_ref=tab_ref,
            origin=origin,
            ordered_targets=logical_targets,
            state_revision=state_revision,
            state_binding_digest=state_binding.digest,
            classification=classification,
            expectation_digest=expectation_digest,
            arguments=arguments,
            layout_revision=layout_revision,
            expires_at=self._clock() + 60.0,
            registry=self._registry,
            receiver_tab_key=receiver_key,
        )
        handoff = canonical_preflight_handoff_reason(
            classification,
            arguments,
        )
        if handoff:
            return ActionPreflight(
                decision=PreflightDecision.HANDOFF,
                reason=handoff,
                preview=preview,
            )
        if UNKNOWN in classification.categories:
            if expectation is None:
                return ActionPreflight(
                    decision=PreflightDecision.HANDOFF,
                    reason="unknown_effect_without_expectation",
                    preview=preview,
                )
            return ActionPreflight(
                decision=PreflightDecision.EXACT_APPROVAL,
                reason="single_use_exact_approval_required",
                preview=preview,
                needs_exact_approval=True,
            )
        return ActionPreflight(
            decision=PreflightDecision.READY,
            reason="preflight_ready",
            preview=preview,
        )

    def _resolve_targets(
        self,
        ordered_targets: tuple[tuple[str, TargetRef], ...],
        *,
        receiver_key: str,
        owner: BrowserRequestBinding,
    ) -> tuple[tuple[tuple[str, str], ...], tuple[TargetFact, ...]]:
        logical: list[tuple[str, str]] = []
        facts: list[TargetFact] = []
        labels: set[str] = set()
        for label, target in ordered_targets:
            normalized_label = str(label or "").strip()
            if not normalized_label or normalized_label in labels:
                raise BrowserSDKError(
                    "ordered target label is invalid",
                    code="target_invalid",
                )
            if not isinstance(target, TargetRef) or not receiver_key:
                raise BrowserSDKError(
                    "ordered target is not Runtime-issued",
                    code="runtime_issued_value",
                )
            self._registry.resolve_target(
                target,
                receiver_tab=receiver_key,
                owner=owner,
            )
            labels.add(normalized_label)
            logical.append((normalized_label, str(target.ref)))
            facts.append(
                TargetFact(
                    kind=(
                        "semantic_link"
                        if str(getattr(target, "observed_url", "") or "")
                        else "generic"
                    ),
                ),
            )
        return tuple(logical), tuple(facts)


def _upload_outcome_from_dispatch(value: object) -> UploadOutcome | None:
    """Read only closed trusted upload facts from one dispatcher result."""
    if not isinstance(value, Mapping):
        return None
    payload = value.get("upload", value)
    if not isinstance(payload, Mapping):
        return None
    raw_items = payload.get("items")
    if not isinstance(raw_items, (tuple, list)) or not raw_items:
        return None
    items: list[UploadItemOutcome] = []
    try:
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                return None
            items.append(
                UploadItemOutcome(
                    resource_id=str(raw.get("resource_id") or ""),
                    selection=cast(
                        Literal["SELECTED", "NOT_SELECTED", "UNKNOWN"],
                        str(raw.get("selection") or "UNKNOWN"),
                    ),
                    transfer=cast(
                        Literal["COMPLETED", "NOT_COMPLETED", "UNKNOWN"],
                        str(raw.get("transfer") or "UNKNOWN"),
                    ),
                    acceptance=cast(
                        Literal["ACCEPTED", "REJECTED", "UNKNOWN"],
                        str(raw.get("acceptance") or "UNKNOWN"),
                    ),
                ),
            )
    except (TypeError, ValueError):
        return None
    closed = tuple(items)
    return UploadOutcome(
        items=closed,
        aggregate=_classify_upload_outcome(closed),
    )


async def _project_armed_terminal(
    *,
    registry: BrowserSessionOwnerRegistry,
    binding: BrowserRequestBinding,
    pending: PendingAction,
    contract: BrowserAPIContract,
    expectation: ActionExpectation,
    receiver_tab: TabSummary | None,
    dispatch_fact: object,
    evaluation: ConditionEvaluation,
    command_id: str,
    deadline: float | None,
) -> ActionResult | PagePdfResult:
    """Project a consumed watch outside the dispatch state machine."""
    if contract.api_id == "tab.print_to_pdf":
        (
            status,
            retry,
            resource,
            context_before,
            context_after,
            context_outcome,
        ) = _page_pdf_terminal_projection(dispatch_fact, evaluation.outcome)
        if status in {"SUCCEEDED", "PARTIAL"} and receiver_tab is None:
            status, retry, context_outcome = (
                "UNCERTAIN",
                "RECONCILE_ONLY",
                "UNKNOWN",
            )
        if status == "UNCERTAIN":
            registry.fence_uncertain_action(binding, pending.operation_id)
        return PagePdfResult(
            operation_id=pending.operation_id,
            status=status,
            retry=retry,
            problem=(
                None
                if status == "SUCCEEDED"
                else Problem(
                    code=(
                        "page_pdf_context_changed"
                        if context_outcome == "CHANGED"
                        else "page_pdf_outcome_incomplete"
                    ),
                    phase="VERIFY",
                    safe_message=(
                        "Page PDF context truth could not be fully proven."
                    ),
                )
            ),
            classified_effects=tuple(
                item.value for item in pending.classified_effects
            ),
            effect_facts=(evaluation,),
            commands=(pending.command_facts[command_id],),
            context_before=context_before,
            context_after=context_after,
            context_outcome=context_outcome,
            dispatch=dispatch_fact,
            postcondition=evaluation,
            resource=resource,
            page_info=receiver_tab,
        )
    if contract.api_id == "tab.actions.download_file":
        status, retry, resources = _download_terminal_projection(
            expectation,
            dispatch_fact,
            evaluation.outcome,
        )
        if status == "UNCERTAIN":
            registry.fence_uncertain_action(binding, pending.operation_id)
        return ActionResult(
            operation_id=pending.operation_id,
            status=status,
            retry=retry,
            problem=(
                None
                if status == "SUCCEEDED"
                else Problem(
                    code="download_outcome_incomplete",
                    phase="VERIFY",
                    safe_message=(
                        "Download completion could not be fully proven."
                    ),
                )
            ),
            effect_facts=(evaluation,),
            commands=(pending.command_facts[command_id],),
            dispatch=dispatch_fact,
            postcondition=evaluation,
            resources=resources,
        )
    if evaluation.outcome != "SATISFIED":
        registry.fence_uncertain_action(binding, pending.operation_id)
        return await reconcile_pending(
            binding=binding,
            pending=pending,
            deadline=(deadline or pending.expires_at),
        )
    upload = (
        _upload_outcome_from_dispatch(dispatch_fact)
        if contract.api_id == "tab.actions.upload_file"
        else None
    )
    if upload is not None:
        status, retry = _upload_terminal_mapping(upload.aggregate)
        return ActionResult(
            operation_id=pending.operation_id,
            status=status,
            retry=retry,
            problem=(
                None
                if status == "SUCCEEDED"
                else Problem(
                    code="upload_outcome_incomplete",
                    phase="VERIFY",
                    safe_message=(
                        "Upload acceptance could not be fully proven."
                    ),
                )
            ),
            effect_facts=(evaluation,),
            commands=(pending.command_facts[command_id],),
            dispatch=dispatch_fact,
            postcondition=evaluation,
            upload=upload,
        )
    return ActionResult(
        operation_id=pending.operation_id,
        status="SUCCEEDED",
        retry="NONE",
        effect_facts=(evaluation,),
        commands=(pending.command_facts[command_id],),
        dispatch=dispatch_fact,
        postcondition=evaluation,
    )


def project_action_truth(
    *,
    operation_id: str,
    classified_effects: tuple[EffectCategory, ...],
    commands: tuple[CommandFact, ...],
    dispatch: DispatchFact,
    commit: FactOutcome,
    effect_facts: tuple[EffectFact, ...],
    postcondition: PostconditionFact,
) -> ActionResult:
    """Project four independent facts through a conservative lattice."""
    if any(
        fact.category is UNKNOWN and fact.outcome is FactOutcome.OBSERVED
        for fact in effect_facts
    ):
        raise BrowserSDKError(
            "UNKNOWN classification cannot become observed effect truth",
            code="effect_fact_invalid",
        )
    concrete = tuple(
        category for category in classified_effects if category is not UNKNOWN
    )
    outcomes = tuple(
        fact.outcome for fact in effect_facts if fact.category is not UNKNOWN
    )
    if not concrete:
        effect = FactOutcome.NOT_REQUESTED
    elif len(outcomes) < len(concrete) or FactOutcome.UNKNOWN in outcomes:
        effect = FactOutcome.UNKNOWN
    elif FactOutcome.CONTRADICTED in outcomes:
        effect = FactOutcome.CONTRADICTED
    elif FactOutcome.NOT_OBSERVED in outcomes:
        effect = FactOutcome.NOT_OBSERVED
    elif all(outcome is FactOutcome.OBSERVED for outcome in outcomes):
        effect = FactOutcome.OBSERVED
    else:
        effect = FactOutcome.UNKNOWN

    if postcondition is PostconditionFact.FAILED:
        status: TerminalStatus = "FAILED"
        retry: RetryDirective = "FORBIDDEN"
    elif dispatch in {DispatchFact.NOT_SENT, DispatchFact.REJECTED}:
        status = "BLOCKED"
        retry = "SAFE"
    elif postcondition is PostconditionFact.PASSED and effect in {
        FactOutcome.OBSERVED,
        FactOutcome.NOT_REQUESTED,
    }:
        status = "SUCCEEDED"
        retry = "NONE"
    else:
        status = "UNCERTAIN"
        retry = "RECONCILE_ONLY"
    return ActionResult(
        operation_id=operation_id,
        status=status,
        retry=retry,
        problem=(
            None
            if status == "SUCCEEDED"
            else Problem(
                code=(
                    "action_truth_uncertain"
                    if status == "UNCERTAIN"
                    else (
                        "action_postcondition_failed"
                        if status == "FAILED"
                        else "action_not_dispatched"
                    )
                ),
                phase=(
                    "VERIFY" if dispatch is DispatchFact.SENT else "PREFLIGHT"
                ),
                safe_message=(
                    "Action facts do not prove successful completion."
                ),
            )
        ),
        classified_effects=tuple(item.value for item in classified_effects),
        effect_facts=effect_facts,
        commands=commands,
        dispatch=dispatch,
        commit=commit,
        effect=effect,
        postcondition=postcondition,
    )


async def reconcile_pending(
    *,
    binding: BrowserRequestBinding,
    pending: PendingAction,
    deadline: float,
) -> ActionResult:
    """Query receipt/state only; never resend the original command."""
    del binding
    if pending._status_query is None:
        return project_action_truth(
            operation_id=pending.operation_id,
            classified_effects=pending.classified_effects,
            commands=tuple(pending.command_facts.values()),
            dispatch=DispatchFact.UNKNOWN,
            commit=FactOutcome.UNKNOWN,
            effect_facts=(),
            postcondition=PostconditionFact.UNKNOWN,
        )
    target_id = next(reversed(pending.commands), "")
    target_fingerprint = pending.command_fingerprints.get(target_id, "")
    pending.issue_command(
        "STATUS_QUERY",
        {
            "target_command_id": target_id,
            "target_command_fingerprint": target_fingerprint,
        },
    )
    status_result = await pending._status_query(pending)
    target_receipt = getattr(status_result, "target_receipt", None)
    receipt_state = str(getattr(target_receipt, "state", "") or "")
    if receipt_state in {
        "RECEIVED",
        "RUNNING",
        "COMPLETED",
    }:
        pending.command_facts[target_id] = replace(
            pending.command_facts.get(
                target_id,
                CommandFact(
                    command_id=target_id,
                    command_kind="INITIAL",
                    safe_fingerprint_summary=target_fingerprint[:16],
                ),
            ),
            observed_state=cast(CommandObservedState, receipt_state),
        )
    postcondition = PostconditionFact.UNKNOWN
    if (
        pending._reconcile_evaluator is not None
        and pending._reconcile_receiver is not None
        and pending._reconcile_probe is not None
        and pending._reconcile_expectation is not None
    ):
        expectation = pending._reconcile_expectation
        watch = await pending._reconcile_evaluator.arm(
            pending._reconcile_receiver,
            expectation.condition,
            probe=pending._reconcile_probe,
            baseline=pending._reconcile_baseline,
        )
        evaluation = await pending._reconcile_evaluator.evaluate(
            pending._reconcile_receiver,
            expectation.condition,
            probe=pending._reconcile_probe,
            timeout_ms=max(1, int((deadline - monotonic()) * 1000)),
            stable_ms=expectation.stable_ms,
            baseline=pending._reconcile_baseline,
            armed=watch,
        )
        postcondition = (
            PostconditionFact.PASSED
            if evaluation.outcome == "SATISFIED"
            else (
                PostconditionFact.FAILED
                if evaluation.outcome == "TIMED_OUT"
                else PostconditionFact.UNKNOWN
            )
        )
    return project_action_truth(
        operation_id=pending.operation_id,
        classified_effects=pending.classified_effects,
        commands=tuple(pending.command_facts.values()),
        dispatch=(
            DispatchFact.SENT
            if target_receipt is not None
            else DispatchFact.UNKNOWN
        ),
        commit=FactOutcome.UNKNOWN,
        effect_facts=(),
        postcondition=postcondition,
    )


def _blocked_run_result(
    preflight: ActionPreflight,
    contract: BrowserAPIContract,
) -> ActionResult | PagePdfResult:
    problem = Problem(
        code=(
            preflight.reason
            if preflight.decision is PreflightDecision.BLOCKED
            else "canonical_action_dispatch_not_enabled"
        ),
        phase="PREFLIGHT",
        safe_message="Canonical native mutation is not active in this stage.",
    )
    if contract.api_id == "tab.print_to_pdf":
        return PagePdfResult(
            operation_id=issue_operation_id(),
            status="BLOCKED",
            retry="AFTER_OBSERVATION",
            problem=problem,
        )
    return ActionResult(
        operation_id=(
            preflight.preview.operation_id
            if preflight.preview is not None
            else issue_operation_id()
        ),
        status="BLOCKED",
        retry="AFTER_OBSERVATION",
        problem=problem,
        classified_effects=(
            tuple(item.value for item in preflight.preview.effects)
            if preflight.preview is not None
            else ()
        ),
    )


def _emit(hook: Callable[[str], None] | None, event: str) -> None:
    if hook is not None:
        hook(event)


def _validate_prompt_response(
    prompt_type: str,
    decision: str,
    text: str | None,
) -> None:
    legal = {
        "alert": {"accept"},
        "confirm": {"accept", "dismiss"},
        "prompt": {"accept", "dismiss"},
        "before_unload": {"accept", "dismiss"},
        "permission": {"allow", "deny"},
    }
    if decision not in legal.get(prompt_type, set()):
        raise BrowserSDKError(
            "decision is invalid for this exact prompt",
            code="prompt_decision_invalid",
        )
    if text is not None and (
        not isinstance(text, str)
        or prompt_type != "prompt"
        or decision != "accept"
    ):
        raise BrowserSDKError(
            "prompt text is invalid for this response",
            code="prompt_text_invalid",
        )


def _prompt_response_binding_digest(
    *,
    pending: PendingAction,
    prompt: BrowserPrompt,
    decision: str,
    text: str | None,
    effects: tuple[str, ...],
) -> str:
    return _digest(
        {
            "operation_id": pending.operation_id,
            "operation_fingerprint": pending.operation_fingerprint,
            "prompt_id": str(prompt.prompt_id),
            "decision": decision,
            "text_digest": sha256(text.encode()).hexdigest() if text else "",
            "state_binding_digest": pending.state_binding_digest,
            "effects": effects,
        },
    )


def _remaining_timeout_ms(deadline: float | None, now: float) -> int:
    if deadline is None:
        return 30_000
    return max(1, int((float(deadline) - now) * 1000))


def _preview_material(preview: ActionPreview) -> tuple[object, ...]:
    return (
        preview.root_task_id,
        preview.browser_owner_id,
        preview.api_id,
        preview.session_id,
        preview.tab_ref,
        preview.origin,
        preview.ordered_targets,
        preview.state_revision,
        preview.state_binding_digest,
        preview._critical_arguments,
        preview.effects,
        preview.expectation_digest,
        preview.layout_revision,
        preview._receiver_tab_key,
    )


def _validate_armed_watch(
    watch: ConditionWatch | Any,
    *,
    pending: PendingAction,
    receiver: ConditionReceiver | Any,
    expectation: ActionExpectation,
    baseline: ConditionBaseline | None,
) -> None:
    request = getattr(watch, "_request", None)
    watch_receiver = getattr(request, "receiver", None)
    owner_key = getattr(
        watch,
        "owner_key",
        getattr(watch_receiver, "owner_key", None),
    )
    receiver_fingerprint = getattr(
        watch,
        "receiver_fingerprint",
        getattr(watch, "_receiver_fingerprint", None),
    )
    condition_fingerprint = getattr(
        watch,
        "condition_fingerprint",
        getattr(watch, "_condition_fingerprint", None),
    )
    baseline_fingerprint = getattr(
        watch,
        "baseline_fingerprint",
        getattr(watch, "_baseline_fingerprint", None),
    )
    subscription = getattr(watch, "_subscription", None)
    watermark = getattr(
        watch,
        "watermark",
        getattr(subscription, "watermark", None),
    )
    expected_baseline = (
        baseline.fingerprint if baseline is not None else "none"
    )
    created = any(
        isinstance(atom, ResourceCondition) and atom.kind == "created"
        for atom in expectation.condition.atoms
    )
    operation = getattr(request, "operation", None)
    operation_valid = not created or (
        isinstance(operation, ResourceOperationBinding)
        and operation.operation_id == pending.operation_id
        and operation.operation_fingerprint == pending.operation_fingerprint
        and operation.owner_key == owner_key
        and operation.tab_id == str(getattr(receiver, "tab_id", ""))
        and operation.pre_arm_watermark == watermark
    )
    valid = (
        owner_key == getattr(receiver, "owner_key", None)
        and owner_key is not None
        and receiver_fingerprint == getattr(receiver, "fingerprint", None)
        and condition_fingerprint
        == _condition_fingerprint(expectation.condition)
        and baseline_fingerprint == expected_baseline
        and isinstance(watermark, int)
        and watermark >= 0
        and pending.expectation_digest == _expectation_digest(expectation)
        and operation_valid
    )
    if not valid:
        raise BrowserSDKError(
            "armed condition watch does not match the pending action",
            code="condition_watch_binding_mismatch",
        )


def _resource_operation_binding(
    pending: PendingAction,
    receiver: ConditionReceiver | Any,
    expectation: ActionExpectation,
) -> ResourceOperationBinding | None:
    created = any(
        isinstance(atom, ResourceCondition) and atom.kind == "created"
        for atom in expectation.condition.atoms
    )
    if not created:
        return None
    owner_key = getattr(receiver, "owner_key", None)
    tab_id = str(getattr(receiver, "tab_id", "") or "")
    return ResourceOperationBinding(
        operation_id=pending.operation_id,
        operation_fingerprint=pending.operation_fingerprint,
        command_id=f"browser-command-{secrets.token_urlsafe(24)}",
        owner_key=cast(tuple[str, str], owner_key),
        tab_id=tab_id,
    )


def _configure_pending_reconcile(
    pending: PendingAction,
    *,
    status_query: Callable[[PendingAction], Awaitable[object]] | None,
    evaluator: ConditionEvaluator | Any,
    receiver: ConditionReceiver | Any,
    probe: ConditionProbe | Any,
    expectation: ActionExpectation,
    baseline: ConditionBaseline | None,
) -> None:
    if status_query is not None:
        pending.configure_reconcile(
            status_query=status_query,
            evaluator=evaluator,
            receiver=receiver,
            probe=probe,
            expectation=expectation,
            baseline=baseline,
        )


async def _arm_condition_watch(
    *,
    pending: PendingAction,
    evaluator: ConditionEvaluator | Any,
    receiver: ConditionReceiver | Any,
    probe: ConditionProbe | Any,
    expectation: ActionExpectation,
    baseline: ConditionBaseline | None,
) -> tuple[ResourceOperationBinding | None, ConditionWatch]:
    operation = _resource_operation_binding(pending, receiver, expectation)
    if operation is not None:
        watch = await evaluator.arm(
            receiver,
            expectation.condition,
            probe=probe,
            baseline=baseline,
            operation=operation,
        )
    else:
        watch = await evaluator.arm(
            receiver,
            expectation.condition,
            probe=probe,
            baseline=baseline,
        )
    return operation, watch


def issue_exact_grant(
    preview: ActionPreview,
    *,
    now: float | None = None,
    ttl_seconds: float = 60.0,
) -> ApprovalGrant:
    """Issue one exact grant from an immutable preflight preview."""
    if not isinstance(preview, ActionPreview):
        raise BrowserSDKError(
            "approval preview is invalid",
            code="approval_binding_invalid",
        )
    current = monotonic() if now is None else float(now)
    grant = ApprovalGrant(
        grant_id=f"grant_{secrets.token_urlsafe(24)}",
        operation_id=preview.operation_id,
        operation_fingerprint=preview.operation_fingerprint,
        binding_hash=preview.binding_hash,
        expires_at=min(preview.expires_at, current + float(ttl_seconds)),
    )
    if preview._registry is not None and preview._owner_binding is not None:
        preview._registry.register_exact_grant(
            preview._owner_binding,
            grant_id=grant.grant_id,
            api_id=preview.api_id,
            operation_id=grant.operation_id,
            operation_fingerprint=grant.operation_fingerprint,
            binding_hash=grant.binding_hash,
            effects=tuple(item.value for item in preview.effects),
            expectation_digest=preview.expectation_digest,
            expires_at=grant.expires_at,
            grant_object=grant,
        )
    return grant


def validate_grant(
    grant: ApprovalGrant,
    preview: ActionPreview,
    *,
    now: float | None = None,
) -> bool:
    """Validate exact binding without consuming the grant."""
    if not isinstance(grant, ApprovalGrant) or not isinstance(
        preview,
        ActionPreview,
    ):
        return False
    current = monotonic() if now is None else float(now)
    return bool(
        grant.remaining_uses == 1
        and current <= grant.expires_at
        and grant.operation_id == preview.operation_id
        and grant.operation_fingerprint == preview.operation_fingerprint
        and grant.binding_hash == preview.binding_hash,
    )


def _dispatch_context(
    preview: ActionPreview,
    grant: ApprovalGrant,
    *,
    command: PendingCommand | None = None,
) -> DispatchContext:
    if (
        preview._registry is None
        or preview._owner_binding is None
        or grant.remaining_uses != 1
        or grant.operation_id != preview.operation_id
        or grant.operation_fingerprint != preview.operation_fingerprint
        or grant.binding_hash != preview.binding_hash
    ):
        raise BrowserSDKError(
            "exact grant does not match the preflight preview",
            code="approval_grant_invalid",
        )
    owner = preview._owner_binding
    command_id = (
        command.command_id
        if command is not None
        else f"browser-command-{secrets.token_urlsafe(24)}"
    )
    command_kind: CommandKind = (
        command.command_kind if command is not None else "INITIAL"
    )
    command_fingerprint = (
        command.command_fingerprint
        if command is not None
        else _dispatch_command_fingerprint(
            preview,
            grant,
            owner,
            command_id=command_id,
            command_kind=command_kind,
        )
    )
    context = DispatchContext(
        root_task_id=owner.root_task_id,
        browser_owner_id=owner.browser_owner_id,
        session_id=owner.root_session_id,
        owner_lease_generation=owner.lease_generation,
        api_id=preview.api_id,
        operation_id=preview.operation_id,
        operation_fingerprint=preview.operation_fingerprint,
        command_id=command_id,
        command_kind=command_kind,
        command_fingerprint=command_fingerprint,
        receiver_tab_ref=preview.tab_ref,
        context_ref=None,
        binding_hash=preview.binding_hash,
        approval_grant_id=grant.grant_id,
        expectation_digest=preview.expectation_digest,
        classified_effects=preview.effects,
        _registry=preview._registry,
        _owner_binding=owner,
        _receiver_tab_key=preview._receiver_tab_key,
    )
    preview._registry.bind_dispatch_context(
        owner,
        grant_id=grant.grant_id,
        context=context,
    )
    return context


def _dispatch_command_fingerprint(
    preview: ActionPreview,
    grant: ApprovalGrant,
    owner: BrowserRequestBinding,
    *,
    command_id: str,
    command_kind: CommandKind,
) -> str:
    return _digest(
        {
            "root_task_id": owner.root_task_id,
            "browser_owner_id": owner.browser_owner_id,
            "session_id": owner.root_session_id,
            "owner_lease_generation": owner.lease_generation,
            "api_id": preview.api_id,
            "operation_id": preview.operation_id,
            "operation_fingerprint": preview.operation_fingerprint,
            "command_id": command_id,
            "command_kind": command_kind,
            "receiver_tab_ref": preview.tab_ref,
            "context_ref": None,
            "binding_hash": preview.binding_hash,
            "approval_grant_id": grant.grant_id,
            "expectation_digest": preview.expectation_digest,
            "classified_effects": preview.effects,
        },
    )


def _new_preview(
    *,
    binding: BrowserRequestBinding,
    contract: BrowserAPIContract,
    tab_ref: str | None,
    origin: str,
    ordered_targets: tuple[tuple[str, str], ...],
    state_revision: str,
    state_binding_digest: str,
    classification: EffectClassification,
    expectation_digest: str,
    arguments: Mapping[str, object],
    layout_revision: str,
    expires_at: float,
    registry: BrowserSessionOwnerRegistry,
    receiver_tab_key: str,
) -> ActionPreview:
    critical = tuple(
        sorted((str(key), value) for key, value in arguments.items()),
    )
    preview = ActionPreview(
        root_task_id=binding.root_task_id,
        browser_owner_id=binding.browser_owner_id,
        operation_id=issue_operation_id(),
        api_id=contract.api_id,
        session_id=binding.root_session_id,
        tab_ref=tab_ref,
        origin=origin,
        ordered_targets=ordered_targets,
        state_revision=state_revision,
        state_binding_digest=state_binding_digest,
        effects=classification.categories,
        expectation_digest=expectation_digest,
        safe_arguments=_safe_arguments(critical),
        expires_at=expires_at,
        layout_revision=layout_revision,
        operation_fingerprint="",
        binding_hash="",
        _critical_arguments=critical,
        _registry=registry,
        _owner_binding=binding,
        _receiver_tab_key=receiver_tab_key,
    )
    return _rehash(preview)


def _rehash(preview: ActionPreview) -> ActionPreview:
    operation_payload = {
        "api_id": preview.api_id,
        "session_id": preview.session_id,
        "tab_ref": preview.tab_ref,
        "origin": preview.origin,
        "ordered_targets": preview.ordered_targets,
        "state_revision": preview.state_revision,
        "state_binding_digest": preview.state_binding_digest,
        "critical_arguments": preview._critical_arguments,
        "effects": preview.effects,
        "expectation_digest": preview.expectation_digest,
        "expires_at": preview.expires_at,
    }
    operation_fingerprint = _digest(operation_payload)
    binding_hash = _digest(
        {
            "root_task_id": preview.root_task_id,
            "browser_owner_id": preview.browser_owner_id,
            "operation_id": preview.operation_id,
            "operation_fingerprint": operation_fingerprint,
        },
    )
    return replace(
        preview,
        operation_fingerprint=operation_fingerprint,
        binding_hash=binding_hash,
    )


def _expectation_digest(expectation: ActionExpectation | None) -> str:
    if expectation is None:
        return "none"
    if not isinstance(expectation, ActionExpectation):
        raise BrowserSDKError(
            "action expectation is invalid",
            code="action_expectation_invalid",
        )
    return _digest(
        {
            "timing": expectation.timing,
            "condition": _serialize_browser_condition(
                expectation.condition,
                max_atoms=16,
            ),
            "stable_ms": expectation.stable_ms,
        },
    )


def _safe_arguments(
    arguments: tuple[tuple[str, object], ...],
) -> tuple[tuple[str, object], ...]:
    return tuple(
        (key, _safe_argument_value(key, value)) for key, value in arguments
    )


def _safe_argument_value(key: str, value: object) -> object:
    if _redacted_key(key):
        return "[REDACTED]"
    normalized = key.casefold()
    if normalized in {"url", "origin"} and isinstance(value, str):
        parsed = urlsplit(value)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return "[REDACTED]"
    if normalized in {
        "accept",
        "direction",
        "key",
        "landscape",
        "match",
        "paper",
        "prompt_kind",
        "provenance",
    }:
        return _safe_value(value)
    if isinstance(value, str):
        return "[REDACTED]"
    return _safe_value(value)


def _redacted_key(key: str) -> bool:
    normalized = key.casefold()
    return normalized in {
        "file_path",
        "file_paths",
        "files",
        "prompt_text",
        "text",
        "value",
    } or any(
        token in normalized
        for token in ("credential", "otp", "password", "secret", "token")
    )


def _safe_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:160]
    return "[TYPED]"


def _digest(value: object) -> str:
    serialized = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _canonical_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, EffectCategory):
        return value.value
    if isinstance(value, Mapping):
        return [
            [str(key), _canonical_value(item)]
            for key, item in sorted(
                value.items(),
                key=lambda pair: str(pair[0]),
            )
        ]
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _canonical_value(to_dict())
    raise BrowserSDKError(
        "critical action argument is not canonically serializable",
        code="action_argument_invalid",
    )


__all__ = [
    "ActionPreflight",
    "ActionPreview",
    "ActionRunner",
    "ApprovalGrant",
    "DispatchContext",
    "PreflightDecision",
    "issue_exact_grant",
    "validate_grant",
]
