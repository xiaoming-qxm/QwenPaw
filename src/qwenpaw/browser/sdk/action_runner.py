# -*- coding: utf-8 -*-
"""Thin Canonical Browser action preflight and exact binding skeleton."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
import json
import secrets
from time import monotonic
from urllib.parse import urlsplit

from .canonical.contracts import (
    ActionExpectation,
    StateRequirement,
    TabSummary,
    TargetRef,
    _serialize_browser_condition,
    issue_operation_id,
)
from .contracts import BrowserAPIContract
from .governance.boundary import canonical_preflight_handoff_reason
from .governance.effects import (
    UNKNOWN,
    EffectCategory,
    EffectClassification,
    TargetFact,
    classify_effects,
)
from .governance.errors import BrowserSDKError
from .runtime.session_owner import (
    BrowserOwnerRegistryError,
    BrowserRequestBinding,
    BrowserSessionOwnerRegistry,
    StateFactStatus,
    TrustedStateVerifier,
)


class PreflightDecision(StrEnum):
    """Closed S5 preflight outcomes."""

    READY = "READY"
    EXACT_APPROVAL = "EXACT_APPROVAL"
    HANDOFF = "HANDOFF"
    BLOCKED = "BLOCKED"


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


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """Registry-bound trust facts for one dispatch attempt."""

    root_task_id: str
    browser_owner_id: str
    session_id: str
    lease_generation: int
    api_id: str
    operation_id: str
    operation_fingerprint: str
    binding_hash: str
    grant_id: str
    effects: tuple[EffectCategory, ...]
    expectation_digest: str
    _registry: BrowserSessionOwnerRegistry = field(repr=False, compare=False)
    _owner_binding: BrowserRequestBinding = field(repr=False, compare=False)
    _receiver_tab_key: str = field(repr=False, compare=False)

    def is_bound_to(
        self,
        registry: BrowserSessionOwnerRegistry,
        receiver_tab: str,
    ) -> bool:
        """Return exact private registry and receiver binding equality."""
        return self._registry is registry and self._receiver_tab_key == str(
            receiver_tab
        )


@dataclass(frozen=True, slots=True)
class ActionPreflight:
    """Result of the sole S5 action preflight entry."""

    decision: PreflightDecision
    reason: str
    preview: ActionPreview | None = None
    needs_exact_approval: bool = False
    grant_consumed: bool = False

    def dispatch_context(self, grant: ApprovalGrant) -> DispatchContext:
        """Issue and registry-bind the one context for this preflight."""
        if self.preview is None:
            raise BrowserSDKError(
                "preflight has no dispatchable preview",
                code="dispatch_context_invalid",
            )
        return _dispatch_context(self.preview, grant)


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
            tab_ref = str(receiver_tab.ref)
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
        and grant.binding_hash == preview.binding_hash
    )


def _dispatch_context(
    preview: ActionPreview,
    grant: ApprovalGrant,
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
    context = DispatchContext(
        root_task_id=owner.root_task_id,
        browser_owner_id=owner.browser_owner_id,
        session_id=owner.root_session_id,
        lease_generation=owner.lease_generation,
        api_id=preview.api_id,
        operation_id=preview.operation_id,
        operation_fingerprint=preview.operation_fingerprint,
        binding_hash=preview.binding_hash,
        grant_id=grant.grant_id,
        effects=preview.effects,
        expectation_digest=preview.expectation_digest,
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
