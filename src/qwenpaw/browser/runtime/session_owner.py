# -*- coding: utf-8 -*-
"""Trusted session-mode and root-task ownership registries."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import secrets
from dataclasses import dataclass, field, replace
from enum import StrEnum
from time import monotonic
from typing import Callable, Literal, Protocol, TypeAlias
from uuid import uuid4

from ..canonical.contracts import (
    ActionExpectation,
    BrowserPrompt,
    ContextVersion,
    EvidenceRef,
    StateRequirement,
    TabSummary,
    TargetRef,
    VisualContextRef,
    _issue_context_version,
    _issue_opaque_value,
    _issue_target_ref,
    _RUNTIME_VALUE_ISSUER,
)
from ..governance.errors import BrowserSDKError
from ..governance.policy import (
    TrustedSurfacePolicy,
    trusted_surface_rule_fingerprint,
)
from ..primitives.matching import canonicalize_http_url

MAX_RETAINED_STATE_TTL_SECONDS = 3600
MAX_LEGACY_TOKEN_TTL_SECONDS = 3600


class RootTaskOutcome(StrEnum):
    """Trusted terminal or retained outcome for a root task."""

    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    HANDOFF = "HANDOFF"
    RETAINED_PROMPT = "RETAINED_PROMPT"
    RETAINED_UNCERTAIN = "RETAINED_UNCERTAIN"


OwnerKey: TypeAlias = tuple[str, str]


class StateFactStatus(StrEnum):
    """Closed trust state for one action-required fact."""

    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    MISMATCH = "MISMATCH"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class StateVerificationRequest:
    """Finite trusted input supplied to a state verifier."""

    fact_name: str
    expected: str | bool | int | None
    owner_key: OwnerKey
    origin: str
    generation: str


@dataclass(frozen=True, slots=True)
class StateVerification:
    """Typed result returned by a site-independent trusted verifier."""

    status: Literal["VERIFIED", "UNKNOWN", "MISMATCH", "STALE"]
    safe_summary: str
    evidence_ref: EvidenceRef | None
    revision: str
    fresh_until: float | None


class TrustedStateVerifier(Protocol):
    """Minimal closed verifier hook exposed by a reviewed backend profile."""

    key: str

    async def verify(
        self,
        request: StateVerificationRequest,
    ) -> StateVerification:
        """Verify one cataloged fact without page or browser metadata."""


@dataclass(frozen=True, slots=True)
class StateFact:
    """Safe action-scoped projection of one required fact."""

    status: StateFactStatus
    safe_summary: str
    evidence_ref: EvidenceRef | None
    revision: str
    fresh_until: float | None


@dataclass(frozen=True, slots=True)
class StateBinding:
    """Ordered required facts and their trusted action-scoped digest."""

    required_facts: tuple[tuple[str, StateFact], ...]
    digest: str

    def fact(self, name: str) -> StateFact:
        """Return one required fact, failing closed when it was not bound."""
        for fact_name, fact in self.required_facts:
            if fact_name == name:
                return fact
        raise BrowserSDKError(
            f"state fact {name!r} was not required",
            code="state_fact_not_required",
        )


@dataclass(frozen=True)
class NativeContextVersion:
    """Private browser generations behind one public ContextVersion."""

    connection_generation: int
    tab_generation: int
    frame_generation: int
    document_generation: int
    spa_route_generation: int
    layout_generation: int


@dataclass(frozen=True)
class TargetBinding:
    """Private exact native authority behind one public TargetRef."""

    root_task_id: str
    browser_owner_id: str
    session_id: str
    backend_id: str
    receiver_tab_key: str
    frame_key: str
    context_ref: str
    native_identity: tuple[tuple[str, str | int], ...]
    action_state: tuple[tuple[str, bool], ...]
    geometry_digest: str
    visual_context_ref: str | None
    allowed_actions: tuple[str, ...]
    effect_ceiling: tuple[str, ...]
    use_state: str
    expires_at: float
    bridge_token: str = ""
    surface_origin: str = ""
    surface_identity: str = ""
    surface_policy_revision: str = ""
    surface_policy_evidence: str = ""
    surface_policy_proof: str = ""
    surface_policy_expires_at: float = 0.0


@dataclass(frozen=True)
class VisualContextBinding:
    """Private same-epoch facts behind one opaque visual context."""

    root_task_id: str
    browser_owner_id: str
    session_id: str
    backend_id: str
    receiver_tab_key: str
    context: ContextVersion
    viewport: tuple[int, int]
    scroll: tuple[float, float]
    zoom: float
    device_pixel_ratio: float
    layout: tuple[int, int]
    capture_epoch: int
    image_sha256: str
    resource_id: str
    generation: str
    expires_at: float
    actionable: bool


@dataclass(frozen=True, slots=True)
class BrowserRequestBinding:
    """Registry-issued identity and lease for one Browser request."""

    root_session_id: str
    root_task_id: str
    browser_owner_id: str
    lease_generation: int

    @property
    def owner_key(self) -> OwnerKey:
        """Return the durable root-task and Browser-owner namespace."""
        return (self.root_task_id, self.browser_owner_id)


@dataclass(frozen=True, slots=True)
class BrowserOwnerAttachment:
    """First trusted backend-context decision for one owner."""

    binding: BrowserRequestBinding
    resolved_context: Literal["user", "isolated"]
    retention_policy: Literal["KEEP", "CLOSE_TASK_CREATED"]


@dataclass(frozen=True, slots=True)
class ResumeToken:
    """Opaque handle whose facts remain private to the registry."""

    value: str


class BrowserOwnerRegistryError(RuntimeError):
    """Typed fail-closed ownership error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class _OwnerState:
    binding: BrowserRequestBinding
    trusted_surface_policy: TrustedSurfacePolicy | None = None
    lease_active: bool = True
    retained_until: float | None = None
    attachment: BrowserOwnerAttachment | None = None
    contexts: dict[ContextVersion, "_ContextState"] = field(
        default_factory=dict,
    )
    targets: dict[TargetRef, TargetBinding] = field(default_factory=dict)
    visual_contexts: dict[VisualContextRef, VisualContextBinding] = field(
        default_factory=dict,
    )
    tabs: dict[TabSummary, "_TabState"] = field(default_factory=dict)
    selected_tab: TabSummary | None = None
    initial_selection_captured: bool = False
    closed_tab_refs: set[str] = field(default_factory=set)
    prompts: dict[BrowserPrompt, "_PromptState"] = field(default_factory=dict)
    current_prompt_by_tab: dict[str, BrowserPrompt] = field(
        default_factory=dict,
    )
    grants: dict[str, "_GrantState"] = field(default_factory=dict)
    pending_actions: dict[str, object] = field(default_factory=dict)
    unresolved_operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class _ContextState:
    native: NativeContextVersion
    receiver_tab_key: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class _TabState:
    receiver_tab_key: str
    origin: str
    state_revision: str
    layout_revision: str
    provenance: Literal["BORROWED", "TASK_CREATED", "UNKNOWN"]
    expires_at: float


@dataclass(frozen=True, slots=True)
class _PromptState:
    tab: TabSummary
    receiver_tab_key: str
    native_identity: str
    parent_operation_id: str | None
    expires_at: float


@dataclass(slots=True)
class _GrantState:
    api_id: str
    operation_id: str
    operation_fingerprint: str
    binding_hash: str
    effects: tuple[str, ...]
    expectation_digest: str
    expires_at: float
    grant_object: object
    remaining_uses: int = 1
    dispatch_context_identity: int | None = None


@dataclass(slots=True)
class _TokenState:
    owner_key: OwnerKey
    root_session_id: str
    expires_at: float
    consumed: bool = False


@dataclass(frozen=True, slots=True)
class _ActionStateOwner:
    """Owner-scoped action fact collector with a closed verifier catalog."""

    registry: "BrowserSessionOwnerRegistry"
    binding: BrowserRequestBinding
    runtime_session_id: str
    origin: str
    generation: str
    verifier_catalog: tuple[TrustedStateVerifier, ...]

    async def collect_state_binding(
        self,
        *,
        requirement: StateRequirement,
        trusted_floor: StateRequirement,
    ) -> StateBinding:
        """Collect only facts required by the caller or trusted floor."""
        self.registry._require_owner(self.binding)
        merged = _merge_state_requirements(requirement, trusted_floor)
        verifiers = _index_verifiers(self.verifier_catalog)
        expected_facts = _required_state_facts(merged)
        workflow = merged.workflow
        if workflow is not None and workflow.key not in verifiers:
            raise BrowserSDKError(
                "workflow state verifier is not in the trusted catalog",
                code="state_verifier_unknown",
            )

        facts: list[tuple[str, StateFact]] = []
        digest_facts: list[dict[str, object]] = []
        for fact_name, verifier_key, expected in expected_facts:
            if fact_name == "same_session":
                fact = _runtime_session_fact(
                    matches=(
                        self.runtime_session_id == self.binding.root_session_id
                    ),
                    generation=self.generation,
                )
            else:
                verifier = verifiers.get(verifier_key)
                fact = await self._verified_fact(
                    verifier=verifier,
                    fact_name=fact_name,
                    expected=expected,
                )
            facts.append((fact_name, fact))
            digest_facts.append(
                {
                    "name": fact_name,
                    "expected": expected,
                    "status": fact.status.value,
                    "revision": fact.revision,
                    "fresh_until": fact.fresh_until,
                    "evidence": (
                        fact.evidence_ref.to_dict()
                        if fact.evidence_ref is not None
                        else None
                    ),
                },
            )

        digest_payload = {
            "root_task_id": self.binding.root_task_id,
            "browser_owner_id": self.binding.browser_owner_id,
            "runtime_session_id": self.runtime_session_id,
            "origin": self.origin,
            "generation": self.generation,
            "facts": digest_facts,
        }
        digest = sha256(
            json.dumps(
                digest_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=False,
            ).encode("utf-8"),
        ).hexdigest()
        return StateBinding(required_facts=tuple(facts), digest=digest)

    async def _verified_fact(
        self,
        *,
        verifier: TrustedStateVerifier | None,
        fact_name: str,
        expected: str | bool | int | None,
    ) -> StateFact:
        if verifier is None:
            return StateFact(
                status=StateFactStatus.UNKNOWN,
                safe_summary="required fact has no trusted evidence",
                evidence_ref=None,
                revision="unverified",
                fresh_until=None,
            )
        result = await verifier.verify(
            StateVerificationRequest(
                fact_name=fact_name,
                expected=expected,
                owner_key=self.binding.owner_key,
                origin=self.origin,
                generation=self.generation,
            ),
        )
        if not isinstance(result, StateVerification):
            raise BrowserSDKError(
                "trusted state verifier returned an invalid result",
                code="state_verifier_invalid",
            )
        try:
            status = StateFactStatus(result.status)
        except ValueError as exc:
            raise BrowserSDKError(
                "trusted state verifier returned an invalid status",
                code="state_verifier_invalid",
            ) from exc
        evidence = result.evidence_ref
        if status is StateFactStatus.VERIFIED and not isinstance(
            evidence,
            EvidenceRef,
        ):
            status = StateFactStatus.UNKNOWN
            evidence = None
        if (
            result.fresh_until is not None
            and self.registry._clock() > result.fresh_until
        ):
            status = StateFactStatus.STALE
        return StateFact(
            status=status,
            safe_summary=_safe_fact_summary(result.safe_summary),
            evidence_ref=evidence,
            revision=_require_verifier_text(result.revision, "revision"),
            fresh_until=result.fresh_until,
        )


# pylint: disable-next=too-many-public-methods
class BrowserSessionOwnerRegistry:
    """Manage main-process owners, fenced leases, and opaque resumes."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        trusted_surface_policy: TrustedSurfacePolicy | None = None,
        pending_action_capacity: int = 128,
        pending_action_ttl_seconds: float = 300.0,
    ) -> None:
        if pending_action_capacity <= 0:
            raise ValueError("pending_action_capacity must be positive")
        if pending_action_ttl_seconds <= 0:
            raise ValueError("pending_action_ttl_seconds must be positive")
        self._clock = clock
        self._default_trusted_surface_policy = trusted_surface_policy
        self._pending_action_capacity = int(pending_action_capacity)
        self._pending_action_ttl_seconds = float(
            pending_action_ttl_seconds,
        )
        self._owners: dict[tuple[str, str], _OwnerState] = {}
        self._tokens: dict[str, _TokenState] = {}
        self._lock = asyncio.Lock()

    def install_trusted_surface_policy(
        self,
        owner: BrowserRequestBinding,
        policy: TrustedSurfacePolicy,
    ) -> None:
        """Bind one immutable host-reviewed policy to an exact owner."""
        if not isinstance(policy, TrustedSurfacePolicy):
            raise BrowserSDKError(
                "trusted surface policy is invalid",
                code="surface_policy_invalid",
            )
        state = self._require_owner(owner)
        if state.trusted_surface_policy is None:
            state.trusted_surface_policy = policy
            return
        if state.trusted_surface_policy is not policy:
            raise BrowserSDKError(
                "trusted surface policy is already installed",
                code="surface_policy_invalid",
            )

    async def begin_request(
        self,
        *,
        root_session_id: str,
        source: str,
        resume_token: str | None = None,
        inherited_binding: BrowserRequestBinding | None = None,
    ) -> BrowserRequestBinding:
        """Issue a new root owner or acquire a fenced continuation lease."""
        del source
        session_key = _require_identity(root_session_id, "root_session_id")
        if resume_token is not None and inherited_binding is not None:
            raise BrowserOwnerRegistryError("ambiguous_continuation")
        if resume_token is not None:
            return await self._resume(session_key, resume_token)
        if inherited_binding is not None:
            return await self._inherit(session_key, inherited_binding)

        binding = BrowserRequestBinding(
            root_session_id=session_key,
            root_task_id=f"root_task_{uuid4().hex}",
            browser_owner_id=f"browser_owner_{uuid4().hex}",
            lease_generation=1,
        )
        async with self._lock:
            self._owners[binding.owner_key] = _OwnerState(
                binding=binding,
                trusted_surface_policy=self._default_trusted_surface_policy,
            )
        return binding

    async def bind_owner_attachment(
        self,
        binding: BrowserRequestBinding,
        *,
        resolved_context: Literal["user", "isolated"],
    ) -> BrowserOwnerAttachment:
        """Persist the first host-selected context and retention policy."""
        async with self._lock:
            state = self._require_owner(binding)
            if state.attachment is None:
                state.attachment = BrowserOwnerAttachment(
                    binding=state.binding,
                    resolved_context=resolved_context,
                    retention_policy=(
                        "KEEP"
                        if resolved_context == "user"
                        else "CLOSE_TASK_CREATED"
                    ),
                )
            return state.attachment

    async def release_request_lease(
        self,
        binding: BrowserRequestBinding,
    ) -> None:
        """Release only the current generation's request lease."""
        async with self._lock:
            state = self._require_current_lease(binding)
            state.lease_active = False

    async def finish_root_task(
        self,
        binding: BrowserRequestBinding,
        outcome: RootTaskOutcome,
    ) -> None:
        """Clear terminal owners while preserving trusted retained states."""
        terminal = False
        async with self._lock:
            state = self._require_owner(binding)
            if state.binding.lease_generation != binding.lease_generation:
                raise BrowserOwnerRegistryError("stale_lease")
            if outcome in {
                RootTaskOutcome.HANDOFF,
                RootTaskOutcome.RETAINED_PROMPT,
                RootTaskOutcome.RETAINED_UNCERTAIN,
            }:
                state.lease_active = False
                return
            self._drop_owner(binding.owner_key)
            terminal = True
        if terminal:
            from .observation_store import cleanup_observation_store
            from .resources import cleanup_resource_store

            cleanup_observation_store(binding.owner_key)
            await cleanup_resource_store(binding.owner_key)

    async def retain(
        self,
        binding: BrowserRequestBinding,
        *,
        reason: str,
        ttl_seconds: float,
    ) -> ResumeToken:
        """Release the lease and issue an opaque single-use resume handle."""
        del reason
        ttl = float(ttl_seconds)
        if ttl <= 0:
            raise BrowserOwnerRegistryError("resume_token_expired")
        if ttl > min(
            MAX_RETAINED_STATE_TTL_SECONDS,
            MAX_LEGACY_TOKEN_TTL_SECONDS,
        ):
            raise BrowserOwnerRegistryError(
                "retained_ttl_exceeds_maximum",
            )
        async with self._lock:
            state = self._require_current_lease(binding)
            expires_at = self._clock() + ttl
            value = secrets.token_urlsafe(32)
            while value in self._tokens:
                value = secrets.token_urlsafe(32)
            self._tokens[value] = _TokenState(
                owner_key=binding.owner_key,
                root_session_id=binding.root_session_id,
                expires_at=expires_at,
            )
            state.lease_active = False
            state.retained_until = expires_at
            return ResumeToken(value=value)

    async def sweep_expired(self) -> tuple[OwnerKey, ...]:
        """Remove retained owners only after their trusted TTL expires."""
        now = self._clock()
        async with self._lock:
            expired = tuple(
                owner_key
                for owner_key, state in self._owners.items()
                if state.retained_until is not None
                and now > state.retained_until
            )
            for owner_key in expired:
                self._drop_owner(owner_key)
        from .observation_store import cleanup_observation_store

        for owner_key in expired:
            cleanup_observation_store(owner_key)
        return expired

    def has_owner(self, owner_key: OwnerKey) -> bool:
        """Return whether an owner remains registered."""
        return owner_key in self._owners

    def active_lease_count(self, owner_key: OwnerKey) -> int:
        """Return the binary active lease count for contract assertions."""
        state = self._owners.get(owner_key)
        return int(state is not None and state.lease_active)

    def pending_action_expiry(self) -> float:
        """Return the owner-store expiry for a newly admitted action."""
        return self._clock() + self._pending_action_ttl_seconds

    def save_pending_action(
        self,
        owner: BrowserRequestBinding,
        action: object,
    ) -> None:
        """Persist one action in the sole durable owner record."""
        state = self._require_current_lease(owner)
        operation_id = _require_identity(
            str(getattr(action, "operation_id", "")),
            "operation_id",
        )
        if operation_id in state.pending_actions:
            raise BrowserSDKError(
                "pending action is already registered",
                code="pending_action_duplicate",
            )
        while len(state.pending_actions) >= self._pending_action_capacity:
            oldest = next(iter(state.pending_actions))
            del state.pending_actions[oldest]
        state.pending_actions[operation_id] = action

    def require_pending_action(
        self,
        owner: BrowserRequestBinding,
        operation_id: str,
    ) -> object:
        """Resolve one live action through the current fenced lease."""
        state = self._require_current_lease(owner)
        key = _require_identity(operation_id, "operation_id")
        action = state.pending_actions.get(key)
        if action is None:
            raise BrowserSDKError(
                "pending action is not registered",
                code="pending_action_missing",
            )
        expires_at = float(getattr(action, "expires_at", 0.0))
        if self._clock() > expires_at:
            del state.pending_actions[key]
            raise BrowserSDKError(
                "pending action expired; execution state is unknown",
                code="pending_action_expired",
            )
        return action

    def abandon_pending_action(
        self,
        owner: BrowserRequestBinding,
        operation_id: str,
    ) -> None:
        """Drop an action only through its current fenced owner lease."""
        state = self._require_current_lease(owner)
        state.pending_actions.pop(str(operation_id), None)
        if state.unresolved_operation_id == str(operation_id):
            state.unresolved_operation_id = None

    def fence_uncertain_action(
        self,
        owner: BrowserRequestBinding,
        operation_id: str,
    ) -> None:
        """Fence later mutations behind read-only reconciliation."""
        state = self._require_current_lease(owner)
        key = _require_identity(operation_id, "operation_id")
        if key not in state.pending_actions:
            raise BrowserSDKError(
                "uncertain action is not registered",
                code="pending_action_missing",
            )
        state.unresolved_operation_id = key

    def clear_uncertain_action(
        self,
        owner: BrowserRequestBinding,
        operation_id: str,
    ) -> None:
        """Clear only the exact reconciled operation fence."""
        state = self._require_current_lease(owner)
        if state.unresolved_operation_id == str(operation_id):
            state.unresolved_operation_id = None

    def require_mutation_unfenced(
        self,
        owner: BrowserRequestBinding,
    ) -> None:
        """Fail closed while a prior mutation remains unresolved."""
        state = self._require_current_lease(owner)
        if state.unresolved_operation_id is not None:
            raise BrowserSDKError(
                "prior mutation requires read-only reconciliation",
                code="pending_action_reconcile_required",
            )

    def unresolved_pending_action(
        self,
        owner: BrowserRequestBinding,
    ) -> object | None:
        """Return the exact fenced action for automatic reconciliation."""
        state = self._require_current_lease(owner)
        if state.unresolved_operation_id is None:
            return None
        return state.pending_actions.get(state.unresolved_operation_id)

    @property
    def target_issue_count(self) -> int:
        """Return issuance count for no-authority query assertions."""
        return sum(len(state.targets) for state in self._owners.values())

    def state_binding_owner(
        self,
        binding: BrowserRequestBinding,
        *,
        runtime_session_id: str,
        origin: str,
        generation: str,
        verifier_catalog: tuple[TrustedStateVerifier, ...],
    ) -> _ActionStateOwner:
        """Bind finite Runtime facts and trusted verifiers to one owner."""
        self._require_owner(binding)
        session_id = _require_identity(
            runtime_session_id,
            "runtime_session_id",
        )
        normalized_origin = _require_identity(origin, "origin")
        normalized_generation = _require_identity(generation, "generation")
        catalog = tuple(verifier_catalog)
        _index_verifiers(catalog)
        return _ActionStateOwner(
            registry=self,
            binding=binding,
            runtime_session_id=session_id,
            origin=normalized_origin,
            generation=normalized_generation,
            verifier_catalog=catalog,
        )

    def issue_tab_summary(
        self,
        owner: BrowserRequestBinding,
        *,
        receiver_tab: str,
        origin: str,
        state_revision: str,
        layout_revision: str,
        safe_title: str = "",
        safe_url: str = "",
        selected: bool = False,
        provenance: Literal["BORROWED", "TASK_CREATED", "UNKNOWN"] = "UNKNOWN",
        expires_at: float | None = None,
    ) -> TabSummary:
        """Issue a safe logical tab backed by private receiver authority."""
        state = self._require_owner(owner)
        receiver = _require_handle_text(receiver_tab, "receiver_tab")
        normalized_origin = _require_identity(origin, "origin")
        revision = _require_identity(state_revision, "state_revision")
        layout = _require_identity(layout_revision, "layout_revision")
        if provenance not in {"BORROWED", "TASK_CREATED", "UNKNOWN"}:
            raise BrowserSDKError(
                "tab provenance is invalid",
                code="tab_binding_invalid",
            )
        url = canonicalize_http_url(safe_url).value if safe_url else ""
        safe_origin = canonicalize_http_url(
            normalized_origin,
        ).value.rstrip("/")
        expiry = (
            self._clock() + self._pending_action_ttl_seconds
            if expires_at is None
            else float(expires_at)
        )
        tab_ref = _new_handle_token("tab")
        issued = _issue_opaque_value(
            TabSummary,
            _RUNTIME_VALUE_ISSUER,
            tab_ref=tab_ref,
            title=" ".join(str(safe_title or "").split())[:120],
            url=url,
            origin=safe_origin,
            selected=bool(selected),
            provenance=provenance,
        )
        assert isinstance(issued, TabSummary)
        state.tabs[issued] = _TabState(
            receiver_tab_key=receiver,
            origin=normalized_origin,
            state_revision=revision,
            layout_revision=layout,
            provenance=provenance,
            expires_at=expiry,
        )
        return issued

    def resolve_tab_summary(
        self,
        tab: TabSummary,
        *,
        owner: BrowserRequestBinding,
    ) -> _TabState:
        """Resolve only a TabSummary issued for the exact owner."""
        if not isinstance(tab, TabSummary):
            raise BrowserSDKError(
                "runtime_issued_value: tab has the wrong type",
                code="runtime_issued_value",
            )
        state = self._require_owner(owner)
        resolved = state.tabs.get(tab)
        if resolved is None:
            raise BrowserSDKError(
                "runtime_issued_value: tab is not registered to this owner",
                code="runtime_issued_value",
            )
        if self._clock() > resolved.expires_at:
            raise BrowserSDKError(
                "tab summary expired",
                code="tab_expired",
            )
        return resolved

    def list_tab_summaries(
        self,
        owner: BrowserRequestBinding,
        *,
        max_visible_tabs: int,
    ) -> list[TabSummary]:
        """Return the complete owner set or one typed limit error."""
        state = self._require_current_lease(owner)
        current = [
            tab
            for tab, binding in state.tabs.items()
            if self._clock() <= binding.expires_at
        ]
        if len(current) > max_visible_tabs:
            raise BrowserSDKError(
                "visible tab collection exceeds the profile limit",
                code="tab_limit_exceeded",
            )
        return current

    def capture_initial_tab_selection(
        self,
        owner: BrowserRequestBinding,
        tab: TabSummary,
    ) -> TabSummary:
        """Capture host-active state once; never rebind from ambient focus."""
        state = self._require_current_lease(owner)
        self.resolve_tab_summary(tab, owner=owner)
        if not state.initial_selection_captured:
            state.selected_tab = tab
            state.initial_selection_captured = True
        return state.selected_tab or tab

    def select_tab_summary(
        self,
        owner: BrowserRequestBinding,
        tab: TabSummary,
    ) -> None:
        """Move only the explicit SDK selection pointer."""
        state = self._require_current_lease(owner)
        self.resolve_tab_summary(tab, owner=owner)
        state.selected_tab = tab
        state.initial_selection_captured = True

    def selected_tab_summary(
        self,
        owner: BrowserRequestBinding,
    ) -> TabSummary | None:
        return self._require_current_lease(owner).selected_tab

    def task_created_tab_count(self, owner: BrowserRequestBinding) -> int:
        state = self._require_current_lease(owner)
        return sum(
            binding.provenance == "TASK_CREATED"
            and self._clock() <= binding.expires_at
            for binding in state.tabs.values()
        )

    def prove_tab_closed(
        self,
        owner: BrowserRequestBinding,
        tab: TabSummary,
    ) -> None:
        """Apply an owner close fact without fallback selection."""
        state = self._require_current_lease(owner)
        tab_state = self.resolve_tab_summary(tab, owner=owner)
        self._revoke_tab_observation_state(
            state,
            receiver_tab=tab_state.receiver_tab_key,
        )
        state.tabs.pop(tab, None)
        state.closed_tab_refs.add(str(tab.tab_ref))
        if state.selected_tab is tab:
            state.selected_tab = None

    def is_tab_closed(
        self,
        owner: BrowserRequestBinding,
        tab: TabSummary,
    ) -> bool:
        """Read one exact owner-bound proven close event fact."""
        if not isinstance(tab, TabSummary):
            return False
        state = self._require_current_lease(owner)
        return str(tab.tab_ref) in state.closed_tab_refs

    def capture_browser_prompt(
        self,
        owner: BrowserRequestBinding,
        *,
        tab: TabSummary,
        prompt_type: Literal[
            "alert",
            "confirm",
            "prompt",
            "before_unload",
            "permission",
        ],
        origin: str,
        safe_message: str,
        allows_text: bool,
        native_identity: str,
        parent_operation_id: str | None,
        expires_at: float,
    ) -> BrowserPrompt:
        """Capture one exact native prompt in the existing owner state."""
        state = self._require_current_lease(owner)
        tab_state = self.resolve_tab_summary(tab, owner=owner)
        if prompt_type not in {
            "alert",
            "confirm",
            "prompt",
            "before_unload",
            "permission",
        }:
            raise BrowserSDKError(
                "browser prompt type is invalid",
                code="prompt_type_invalid",
            )
        native = _require_identity(native_identity, "native_identity")
        expiry = float(expires_at)
        if expiry <= self._clock():
            raise BrowserSDKError(
                "browser prompt is already expired",
                code="prompt_expired",
            )
        prompt_id = _new_handle_token("prompt")
        prompt = _issue_opaque_value(
            BrowserPrompt,
            _RUNTIME_VALUE_ISSUER,
            prompt_id=prompt_id,
            tab=tab,
            origin=canonicalize_http_url(origin).value.rstrip("/"),
            type=prompt_type,
            safe_message=" ".join(str(safe_message).split())[:512],
            allows_text=bool(allows_text),
            parent_operation_id=parent_operation_id,
            expires_at=expiry,
        )
        assert isinstance(prompt, BrowserPrompt)
        state.prompts[prompt] = _PromptState(
            tab=tab,
            receiver_tab_key=tab_state.receiver_tab_key,
            native_identity=native,
            parent_operation_id=parent_operation_id,
            expires_at=expiry,
        )
        state.current_prompt_by_tab[tab_state.receiver_tab_key] = prompt
        return prompt

    def resolve_browser_prompt(
        self,
        prompt: BrowserPrompt,
        *,
        owner: BrowserRequestBinding,
    ) -> _PromptState:
        """Resolve only the exact unexpired owner-issued prompt token."""
        if not isinstance(prompt, BrowserPrompt):
            raise BrowserSDKError(
                "browser prompt is not Runtime-issued",
                code="runtime_issued_value",
            )
        state = self._require_current_lease(owner)
        binding = state.prompts.get(prompt)
        if binding is None:
            raise BrowserSDKError(
                "browser prompt belongs to another owner",
                code="prompt_wrong_owner",
            )
        if self._clock() > binding.expires_at:
            state.prompts.pop(prompt, None)
            if (
                state.current_prompt_by_tab.get(binding.receiver_tab_key)
                is prompt
            ):
                state.current_prompt_by_tab.pop(binding.receiver_tab_key, None)
            raise BrowserSDKError(
                "browser prompt expired",
                code="prompt_expired",
            )
        return binding

    def current_browser_prompt(
        self,
        owner: BrowserRequestBinding,
        *,
        tab: TabSummary,
    ) -> BrowserPrompt | None:
        """Return only the exact currently waiting prompt for this tab."""
        state = self._require_current_lease(owner)
        tab_state = self.resolve_tab_summary(tab, owner=owner)
        prompt = state.current_prompt_by_tab.get(tab_state.receiver_tab_key)
        if prompt is None:
            return None
        try:
            self.resolve_browser_prompt(prompt, owner=owner)
        except BrowserSDKError as exc:
            if exc.code == "prompt_expired":
                return None
            raise
        return prompt

    @staticmethod
    def close_effect_floor(
        provenance: str,
    ) -> tuple[str, ...]:
        """Return the closed provenance-dependent explicit-close floor."""
        base = ("PRESENTATION", "SESSION_STATE")
        if provenance == "TASK_CREATED":
            return base
        if provenance in {"BORROWED", "UNKNOWN"}:
            return (*base, "DELETE", "UNKNOWN")
        raise BrowserSDKError(
            "tab provenance is invalid",
            code="tab_binding_invalid",
        )

    def register_exact_grant(
        self,
        owner: BrowserRequestBinding,
        *,
        grant_id: str,
        api_id: str,
        operation_id: str,
        operation_fingerprint: str,
        binding_hash: str,
        effects: tuple[str, ...],
        expectation_digest: str,
        expires_at: float,
        grant_object: object,
    ) -> None:
        """Register one exact grant before any dispatch context is issued."""
        state = self._require_current_lease(owner)
        key = _require_identity(grant_id, "grant_id")
        if key in state.grants:
            raise BrowserSDKError(
                "exact approval grant is already registered",
                code="approval_grant_replayed",
            )
        state.grants[key] = _GrantState(
            api_id=_require_identity(api_id, "api_id"),
            operation_id=_require_identity(operation_id, "operation_id"),
            operation_fingerprint=_require_identity(
                operation_fingerprint,
                "operation_fingerprint",
            ),
            binding_hash=_require_identity(binding_hash, "binding_hash"),
            effects=tuple(str(item) for item in effects),
            expectation_digest=_require_identity(
                expectation_digest,
                "expectation_digest",
            ),
            expires_at=float(expires_at),
            grant_object=grant_object,
        )

    def bind_dispatch_context(
        self,
        owner: BrowserRequestBinding,
        *,
        grant_id: str,
        context: object,
    ) -> None:
        """Bind the one registry-issued context object to a grant."""
        state = self._require_current_lease(owner)
        grant = state.grants.get(str(grant_id))
        if grant is None:
            raise BrowserSDKError(
                "exact approval grant is not registered",
                code="approval_grant_invalid",
            )
        identity = id(context)
        if (
            grant.dispatch_context_identity is not None
            and grant.dispatch_context_identity != identity
        ):
            raise BrowserSDKError(
                "dispatch context has already been issued",
                code="approval_grant_replayed",
            )
        grant.dispatch_context_identity = identity

    async def consume_grant_for_dispatch(self, context: object) -> None:
        """Atomically verify and consume at the unique attempt boundary."""
        owner = getattr(context, "_owner_binding", None)
        if not isinstance(owner, BrowserRequestBinding):
            raise BrowserSDKError(
                "dispatch context owner is not Runtime-issued",
                code="dispatch_context_invalid",
            )
        async with self._lock:
            state = self._require_current_lease(owner)
            grant_id = str(getattr(context, "grant_id", "") or "")
            grant = state.grants.get(grant_id)
            if grant is None:
                raise BrowserSDKError(
                    "dispatch grant is not registered",
                    code="approval_grant_invalid",
                )
            expected = (
                owner.root_task_id,
                owner.browser_owner_id,
                owner.root_session_id,
                owner.lease_generation,
                grant.api_id,
                grant.operation_id,
                grant.operation_fingerprint,
                grant.binding_hash,
                grant.effects,
                grant.expectation_digest,
            )
            observed = (
                getattr(context, "root_task_id", None),
                getattr(context, "browser_owner_id", None),
                getattr(context, "session_id", None),
                getattr(context, "lease_generation", None),
                getattr(context, "api_id", None),
                getattr(context, "operation_id", None),
                getattr(context, "operation_fingerprint", None),
                getattr(context, "binding_hash", None),
                tuple(str(item) for item in getattr(context, "effects", ())),
                getattr(context, "expectation_digest", None),
            )
            grant_object_remaining = getattr(
                grant.grant_object,
                "remaining_uses",
                None,
            )
            binding_invalid = (
                getattr(context, "_registry", None) is not self
                or grant.dispatch_context_identity != id(context)
                or expected != observed
            )
            grant_invalid = (
                self._clock() > grant.expires_at
                or grant.remaining_uses != 1
                or grant_object_remaining != 1
            )
            if binding_invalid or grant_invalid:
                raise BrowserSDKError(
                    "dispatch grant is expired, replayed, or mismatched",
                    code="approval_grant_invalid",
                )
            grant.remaining_uses = 0
            setattr(grant.grant_object, "remaining_uses", 0)

    def issue_context(
        self,
        owner: BrowserRequestBinding,
        *,
        receiver_tab: str,
        native: NativeContextVersion,
        expires_at: float,
        safe_receiver: str = "",
    ) -> ContextVersion:
        """Issue an opaque context whose private facts remain owner-scoped."""
        state = self._require_owner(owner)
        receiver = _require_handle_text(receiver_tab, "receiver_tab")
        if not isinstance(native, NativeContextVersion):
            raise BrowserSDKError(
                "context native version is invalid",
                code="runtime_issued_value",
            )
        existing = next(
            (
                context
                for context, binding in state.contexts.items()
                if binding.receiver_tab_key == receiver
                and binding.native == native
            ),
            None,
        )
        if existing is not None:
            return existing
        expiry = float(expires_at)
        context = _issue_context_version(
            version_ref=_new_handle_token("context"),
            safe_receiver=str(safe_receiver or receiver),
        )
        self._revoke_tab_observation_state(state, receiver_tab=receiver)
        state.contexts[context] = _ContextState(
            native=native,
            receiver_tab_key=receiver,
            expires_at=expiry,
        )
        return context

    def invalidate_tab_observation(
        self,
        owner: BrowserRequestBinding,
        *,
        receiver_tab: str,
    ) -> None:
        """Revoke all observation-derived values after a page mutation."""
        state = self._require_current_lease(owner)
        self._revoke_tab_observation_state(
            state,
            receiver_tab=_require_handle_text(receiver_tab, "receiver_tab"),
        )

    @staticmethod
    def _revoke_tab_observation_state(
        state: _OwnerState,
        *,
        receiver_tab: str,
    ) -> None:
        """Drop context, target, and visual facts tied to one native tab."""
        state.contexts = {
            context: binding
            for context, binding in state.contexts.items()
            if binding.receiver_tab_key != receiver_tab
        }
        state.targets = {
            target: binding
            for target, binding in state.targets.items()
            if binding.receiver_tab_key != receiver_tab
        }
        state.visual_contexts = {
            visual: binding
            for visual, binding in state.visual_contexts.items()
            if binding.receiver_tab_key != receiver_tab
        }
        from .observation_store import cleanup_observation_tab

        cleanup_observation_tab(state.binding.owner_key, receiver_tab)

    def resolve_context(
        self,
        context: ContextVersion,
        *,
        owner: BrowserRequestBinding,
        receiver_tab: str,
    ) -> NativeContextVersion:
        """Resolve a context only for its issuing owner and receiver."""
        if not isinstance(context, ContextVersion):
            raise BrowserSDKError(
                "runtime_issued_value: context has the wrong type",
                code="runtime_issued_value",
            )
        state = self._require_owner(owner)
        stored = state.contexts.get(context)
        if stored is None:
            raise BrowserSDKError(
                "runtime_issued_value: context is not registered "
                "to this owner",
                code="runtime_issued_value",
            )
        receiver = _require_handle_text(receiver_tab, "receiver_tab")
        if stored.receiver_tab_key != receiver:
            raise BrowserSDKError(
                "context receiver mismatch",
                code="context_wrong_receiver",
            )
        return stored.native

    def issue_visual_context(
        self,
        owner: BrowserRequestBinding,
        *,
        receiver_tab: str,
        backend_id: str,
        context: ContextVersion,
        viewport: tuple[int, int],
        scroll: tuple[float, float],
        zoom: float,
        device_pixel_ratio: float,
        layout: tuple[int, int],
        capture_epoch: int,
        image_sha256: str,
        resource_id: str,
        generation: str,
        expires_at: float,
        actionable: bool,
    ) -> VisualContextRef:
        """Issue one owner-scoped same-epoch viewport binding."""
        receiver = _require_handle_text(receiver_tab, "receiver_tab")
        self.resolve_context(context, owner=owner, receiver_tab=receiver)
        if (
            min(*viewport, *layout) <= 0
            or zoom <= 0
            or device_pixel_ratio <= 0
            or capture_epoch < 0
            or len(image_sha256) != 64
        ):
            raise BrowserSDKError(
                "visual context invariant is invalid",
                code="visual_context_invalid",
            )
        state = self._require_owner(owner)
        visual = _issue_opaque_value(
            VisualContextRef,
            _RUNTIME_VALUE_ISSUER,
            id=_new_handle_token("visual"),
        )
        assert isinstance(visual, VisualContextRef)
        state.visual_contexts[visual] = VisualContextBinding(
            root_task_id=owner.root_task_id,
            browser_owner_id=owner.browser_owner_id,
            session_id=owner.root_session_id,
            backend_id=_require_handle_text(backend_id, "backend_id"),
            receiver_tab_key=receiver,
            context=context,
            viewport=(int(viewport[0]), int(viewport[1])),
            scroll=(float(scroll[0]), float(scroll[1])),
            zoom=float(zoom),
            device_pixel_ratio=float(device_pixel_ratio),
            layout=(int(layout[0]), int(layout[1])),
            capture_epoch=int(capture_epoch),
            image_sha256=str(image_sha256),
            resource_id=_require_handle_text(resource_id, "resource_id"),
            generation=_require_handle_text(generation, "generation"),
            expires_at=float(expires_at),
            actionable=bool(actionable),
        )
        return visual

    def resolve_visual_context(
        self,
        visual: VisualContextRef,
        *,
        owner: BrowserRequestBinding,
        receiver_tab: str,
    ) -> VisualContextBinding:
        """Resolve one fresh visual binding for its exact owner and tab."""
        if not isinstance(visual, VisualContextRef):
            raise BrowserSDKError(
                "visual context has the wrong type",
                code="runtime_issued_value",
            )
        state = self._require_owner(owner)
        binding = state.visual_contexts.get(visual)
        if binding is None:
            raise BrowserSDKError(
                "visual context is not registered to this owner",
                code="runtime_issued_value",
            )
        receiver = _require_handle_text(receiver_tab, "receiver_tab")
        if binding.receiver_tab_key != receiver:
            raise BrowserSDKError(
                "visual context receiver mismatch",
                code="visual_context_wrong_receiver",
            )
        return binding

    def issue_target(
        self,
        binding: TargetBinding,
        *,
        safe_role: str = "",
        safe_name: str = "",
        observed_url: str | None = None,
        single_use: bool = False,
    ) -> TargetRef:
        """Issue a public target backed only by the existing owner record."""
        if not isinstance(binding, TargetBinding):
            raise BrowserSDKError(
                "target binding is invalid",
                code="runtime_issued_value",
            )
        owner_key = (binding.root_task_id, binding.browser_owner_id)
        state = self._owners.get(owner_key)
        if (
            state is None
            or state.binding.root_session_id != binding.session_id
        ):
            raise BrowserSDKError(
                "target owner binding is invalid",
                code="target_wrong_owner",
            )
        _require_handle_text(binding.receiver_tab_key, "receiver_tab_key")
        _require_handle_text(binding.context_ref, "context_ref")
        if not binding.native_identity:
            raise BrowserSDKError(
                "target native identity is missing",
                code="target_binding_invalid",
            )
        target = _issue_target_ref(
            ref=_new_handle_token("target"),
            safe_role=str(safe_role),
            safe_name=str(safe_name),
            observed_url=observed_url,
            allowed_actions=tuple(binding.allowed_actions),
            single_use=bool(single_use),
        )
        state.targets[target] = binding
        return target

    def issue_trusted_surface_target(
        self,
        owner: BrowserRequestBinding,
        *,
        candidate: TargetBinding,
        receiver_tab: str,
        origin: str,
        surface_identity: str,
        action: str,
        expectation: ActionExpectation | None,
        policy: TrustedSurfacePolicy | None,
    ) -> TargetRef | None:
        """Issue one exact low-risk surface target or preserve handoff."""
        if policy is None:
            return None
        if not isinstance(expectation, ActionExpectation):
            raise BrowserSDKError(
                "trusted surface action requires a typed expectation",
                code="surface_expectation_required",
            )
        if not isinstance(candidate, TargetBinding):
            raise BrowserSDKError(
                "trusted surface binding is invalid",
                code="target_binding_invalid",
            )
        receiver = _require_handle_text(receiver_tab, "receiver_tab")
        if (
            candidate.root_task_id != owner.root_task_id
            or candidate.browser_owner_id != owner.browser_owner_id
            or candidate.session_id != owner.root_session_id
            or candidate.receiver_tab_key != receiver
        ):
            raise BrowserSDKError(
                "trusted surface owner binding is invalid",
                code="target_wrong_owner",
            )
        if (
            candidate.use_state != "FRESH"
            or not candidate.visual_context_ref
            or not candidate.geometry_digest
            or not candidate.native_identity
        ):
            raise BrowserSDKError(
                "trusted surface binding is stale",
                code="target_stale",
            )
        state = self._require_owner(owner)
        tab_binding = next(
            (
                item
                for item in state.tabs.values()
                if item.receiver_tab_key == receiver
                and self._clock() <= item.expires_at
            ),
            None,
        )
        normalized_origin = canonicalize_http_url(origin).value.rstrip("/")
        if (
            tab_binding is None
            or canonicalize_http_url(tab_binding.origin).value.rstrip("/")
            != normalized_origin
        ):
            return None
        context_current = any(
            context_state.receiver_tab_key == receiver
            and str(context.version_ref) == candidate.context_ref
            for context, context_state in state.contexts.items()
        )
        if not context_current:
            raise BrowserSDKError(
                "trusted surface context is stale",
                code="target_stale",
            )
        rule = policy.authorize(
            origin=normalized_origin,
            surface_identity=surface_identity,
            action=action,
            now=self._clock(),
        )
        if rule is None:
            return None
        policy_proof = trusted_surface_rule_fingerprint(
            origin=rule.origin,
            surface_identity=rule.surface_identity,
            action=str(action),
            revision=rule.revision,
            evidence_ref=rule.evidence_ref,
            effect_ceiling=rule.effect_ceiling,
            expires_at=rule.expires_at,
        )
        binding = replace(
            candidate,
            allowed_actions=(str(action),),
            effect_ceiling=tuple(str(item) for item in rule.effect_ceiling),
            use_state="FRESH",
            surface_origin=rule.origin,
            surface_identity=rule.surface_identity,
            surface_policy_revision=rule.revision,
            surface_policy_evidence=rule.evidence_ref,
            surface_policy_proof=policy_proof,
            surface_policy_expires_at=float(rule.expires_at),
        )
        return self.issue_target(
            binding,
            safe_role="canvas",
            safe_name="Reviewed visual surface",
            single_use=True,
        )

    def issue_trusted_surface_candidate(
        self,
        owner: BrowserRequestBinding,
        *,
        candidate: TargetBinding,
        receiver_tab: str,
        origin: str,
        surface_identity: str,
    ) -> TargetRef | None:
        """Issue a reviewed candidate whose exact action is sealed later."""
        state = self._require_owner(owner)
        policy = state.trusted_surface_policy
        if policy is None:
            return None
        if not isinstance(candidate, TargetBinding):
            raise BrowserSDKError(
                "trusted surface binding is invalid",
                code="target_binding_invalid",
            )
        receiver = _require_handle_text(receiver_tab, "receiver_tab")
        if (
            candidate.root_task_id != owner.root_task_id
            or candidate.browser_owner_id != owner.browser_owner_id
            or candidate.session_id != owner.root_session_id
            or candidate.receiver_tab_key != receiver
        ):
            raise BrowserSDKError(
                "trusted surface owner binding is invalid",
                code="target_wrong_owner",
            )
        if (
            candidate.use_state != "FRESH"
            or not candidate.visual_context_ref
            or not candidate.geometry_digest
            or not candidate.native_identity
        ):
            raise BrowserSDKError(
                "trusted surface binding is stale",
                code="target_stale",
            )
        tab_binding = next(
            (
                item
                for item in state.tabs.values()
                if item.receiver_tab_key == receiver
                and self._clock() <= item.expires_at
            ),
            None,
        )
        normalized_origin = canonicalize_http_url(origin).value.rstrip("/")
        if (
            tab_binding is None
            or canonicalize_http_url(tab_binding.origin).value.rstrip("/")
            != normalized_origin
        ):
            return None
        context_current = any(
            context_state.receiver_tab_key == receiver
            and str(context.version_ref) == candidate.context_ref
            for context, context_state in state.contexts.items()
        )
        if not context_current:
            raise BrowserSDKError(
                "trusted surface context is stale",
                code="target_stale",
            )
        rule = policy.match(
            origin=normalized_origin,
            surface_identity=surface_identity,
            now=self._clock(),
        )
        if rule is None:
            return None
        binding = replace(
            candidate,
            allowed_actions=tuple(rule.allowed_actions),
            effect_ceiling=tuple(str(item) for item in rule.effect_ceiling),
            use_state="FRESH",
            surface_origin=rule.origin,
            surface_identity=rule.surface_identity,
            surface_policy_revision=rule.revision,
            surface_policy_evidence=rule.evidence_ref,
            surface_policy_proof="",
            surface_policy_expires_at=float(rule.expires_at),
        )
        return self.issue_target(
            binding,
            safe_role="canvas",
            safe_name="Reviewed visual surface",
            single_use=True,
        )

    def bind_trusted_surface_action(
        self,
        target: TargetRef,
        *,
        receiver_tab: str,
        owner: BrowserRequestBinding,
        action: str,
        expectation: ActionExpectation,
    ) -> TargetBinding:
        """Seal one staged surface candidate to a typed expected action."""
        if not isinstance(expectation, ActionExpectation):
            raise BrowserSDKError(
                "trusted surface action requires a typed expectation",
                code="surface_expectation_required",
            )
        binding = self.resolve_target(
            target,
            receiver_tab=receiver_tab,
            owner=owner,
        )
        if binding.surface_policy_proof:
            if binding.allowed_actions != (str(action),):
                raise BrowserSDKError(
                    "trusted surface target is sealed to another action",
                    code="target_action_forbidden",
                )
            return binding
        if not binding.surface_identity or not binding.surface_origin:
            return binding
        state = self._require_owner(owner)
        policy = state.trusted_surface_policy
        rule = (
            policy.authorize(
                origin=binding.surface_origin,
                surface_identity=binding.surface_identity,
                action=action,
                now=self._clock(),
            )
            if policy is not None
            else None
        )
        if (
            rule is None
            or rule.revision != binding.surface_policy_revision
            or rule.evidence_ref != binding.surface_policy_evidence
            or tuple(str(item) for item in rule.effect_ceiling)
            != binding.effect_ceiling
            or float(rule.expires_at) != binding.surface_policy_expires_at
        ):
            raise BrowserSDKError(
                "trusted surface policy no longer matches",
                code="surface_policy_invalid",
            )
        proof = trusted_surface_rule_fingerprint(
            origin=rule.origin,
            surface_identity=rule.surface_identity,
            action=str(action),
            revision=rule.revision,
            evidence_ref=rule.evidence_ref,
            effect_ceiling=rule.effect_ceiling,
            expires_at=rule.expires_at,
        )
        sealed = replace(
            binding,
            allowed_actions=(str(action),),
            surface_policy_proof=proof,
        )
        state.targets[target] = sealed
        return sealed

    def resolve_target(
        self,
        target: TargetRef,
        *,
        receiver_tab: str,
        owner: BrowserRequestBinding | None = None,
    ) -> TargetBinding:
        """Resolve exact target authority without trusting public fields."""
        if not isinstance(target, TargetRef):
            raise BrowserSDKError(
                "runtime_issued_value: target has the wrong type",
                code="runtime_issued_value",
            )
        found_owner: _OwnerState | None = None
        binding: TargetBinding | None = None
        for state in self._owners.values():
            candidate = state.targets.get(target)
            if candidate is not None:
                found_owner = state
                binding = candidate
                break
        if found_owner is None or binding is None:
            raise BrowserSDKError(
                "runtime_issued_value: target is not registered "
                "to this Runtime",
                code="runtime_issued_value",
            )
        if (
            owner is not None
            and found_owner.binding.owner_key != owner.owner_key
        ):
            raise BrowserSDKError(
                "target owner mismatch",
                code="target_wrong_owner",
            )
        receiver = _require_handle_text(receiver_tab, "receiver_tab")
        if binding.receiver_tab_key != receiver:
            raise BrowserSDKError(
                "target receiver mismatch",
                code="target_wrong_receiver",
            )
        if (
            binding.surface_policy_expires_at > 0
            and self._clock() >= binding.surface_policy_expires_at
        ):
            raise BrowserSDKError(
                "trusted surface policy expired",
                code="surface_policy_expired",
            )
        return binding

    def consume_single_use_target(
        self,
        target: TargetRef,
        *,
        receiver_tab: str,
        owner: BrowserRequestBinding,
    ) -> None:
        """Consume visual/canvas authority once immediately before send."""
        binding = self.resolve_target(
            target,
            receiver_tab=receiver_tab,
            owner=owner,
        )
        if not bool(getattr(target, "single_use", False)):
            return
        if binding.use_state != "FRESH":
            raise BrowserSDKError(
                "single-use target was already consumed",
                code="target_consumed",
            )
        state = self._require_owner(owner)
        state.targets[target] = replace(binding, use_state="CONSUMED")

    def target_context_status(
        self,
        target: TargetRef,
        *,
        current_context: ContextVersion,
        receiver_tab: str,
        owner: BrowserRequestBinding,
    ) -> Literal["VALID", "REVALIDATE", "STALE"]:
        """Compare target and current context generations semantically."""
        binding = self.resolve_target(
            target,
            receiver_tab=receiver_tab,
            owner=owner,
        )
        state = self._require_owner(owner)
        current = state.contexts.get(current_context)
        if current is None:
            raise BrowserSDKError(
                "runtime_issued_value: current context is not registered",
                code="runtime_issued_value",
            )
        bound = next(
            (
                entry
                for context, entry in state.contexts.items()
                if str(context.version_ref) == binding.context_ref
            ),
            None,
        )
        if bound is None:
            return "STALE"
        hard_fields = (
            "connection_generation",
            "tab_generation",
            "frame_generation",
            "document_generation",
        )
        if any(
            getattr(bound.native, field_name)
            != getattr(current.native, field_name)
            for field_name in hard_fields
        ):
            return "STALE"
        if (
            bound.native.spa_route_generation
            != current.native.spa_route_generation
        ):
            return "REVALIDATE"
        return "VALID"

    def same_target_identity(
        self,
        first: TargetRef,
        second: TargetRef,
        *,
        receiver_tab: str,
        owner: BrowserRequestBinding,
    ) -> bool:
        """Return exact private identity equality for two resolved refs."""
        first_binding = self.resolve_target(
            first,
            receiver_tab=receiver_tab,
            owner=owner,
        )
        second_binding = self.resolve_target(
            second,
            receiver_tab=receiver_tab,
            owner=owner,
        )
        return (
            first_binding.frame_key == second_binding.frame_key
            and first_binding.native_identity == second_binding.native_identity
        )

    async def _resume(
        self,
        root_session_id: str,
        resume_token: str,
    ) -> BrowserRequestBinding:
        async with self._lock:
            token = self._tokens.get(resume_token)
            if token is None:
                raise BrowserOwnerRegistryError("resume_token_invalid")
            if token.root_session_id != root_session_id:
                raise BrowserOwnerRegistryError("resume_token_wrong_owner")
            if token.consumed:
                raise BrowserOwnerRegistryError("resume_token_replayed")
            if self._clock() > token.expires_at:
                raise BrowserOwnerRegistryError("resume_token_expired")
            state = self._owners.get(token.owner_key)
            if state is None:
                raise BrowserOwnerRegistryError("resume_owner_missing")
            if state.lease_active:
                raise BrowserOwnerRegistryError("owner_busy")
            token.consumed = True
            return self._acquire_next_generation(state)

    async def _inherit(
        self,
        root_session_id: str,
        inherited_binding: BrowserRequestBinding,
    ) -> BrowserRequestBinding:
        if inherited_binding.root_session_id != root_session_id:
            raise BrowserOwnerRegistryError("inherited_binding_wrong_owner")
        async with self._lock:
            state = self._require_owner(inherited_binding)
            if (
                state.binding.lease_generation
                != inherited_binding.lease_generation
            ):
                raise BrowserOwnerRegistryError("stale_lease")
            if state.lease_active:
                raise BrowserOwnerRegistryError("owner_busy")
            return self._acquire_next_generation(state)

    @staticmethod
    def _acquire_next_generation(
        state: _OwnerState,
    ) -> BrowserRequestBinding:
        current = state.binding
        binding = BrowserRequestBinding(
            root_session_id=current.root_session_id,
            root_task_id=current.root_task_id,
            browser_owner_id=current.browser_owner_id,
            lease_generation=current.lease_generation + 1,
        )
        state.binding = binding
        state.lease_active = True
        state.retained_until = None
        return binding

    def _require_owner(self, binding: BrowserRequestBinding) -> _OwnerState:
        state = self._owners.get(binding.owner_key)
        if state is None:
            raise BrowserOwnerRegistryError("owner_missing")
        if state.binding.root_session_id != binding.root_session_id:
            raise BrowserOwnerRegistryError("owner_binding_mismatch")
        return state

    def _require_current_lease(
        self,
        binding: BrowserRequestBinding,
    ) -> _OwnerState:
        state = self._require_owner(binding)
        if (
            state.binding.lease_generation != binding.lease_generation
            or not state.lease_active
        ):
            raise BrowserOwnerRegistryError("stale_lease")
        return state

    def _drop_owner(self, owner_key: OwnerKey) -> None:
        self._owners.pop(owner_key, None)
        for value, token in tuple(self._tokens.items()):
            if token.owner_key == owner_key:
                self._tokens.pop(value, None)


def _pending_action_is_live(action: object, now: float) -> bool:
    expires_at = getattr(action, "expires_at", None)
    if expires_at is None:
        return True
    try:
        return float(expires_at) >= now
    except (TypeError, ValueError):
        return True


def _require_identity(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise BrowserOwnerRegistryError(f"{field_name}_missing")
    return normalized


def _require_handle_text(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise BrowserSDKError(
            f"{field_name} is missing",
            code="runtime_issued_value",
        )
    return normalized


def _new_handle_token(kind: str) -> str:
    return f"{kind}_{secrets.token_urlsafe(32)}"


def _merge_state_requirements(
    requirement: StateRequirement,
    trusted_floor: StateRequirement,
) -> StateRequirement:
    if not isinstance(requirement, StateRequirement) or not isinstance(
        trusted_floor,
        StateRequirement,
    ):
        raise BrowserSDKError(
            "state requirement is invalid",
            code="state_requirement_invalid",
        )
    caller_workflow = requirement.workflow
    floor_workflow = trusted_floor.workflow
    if (
        caller_workflow is not None
        and floor_workflow is not None
        and caller_workflow.key != floor_workflow.key
    ):
        raise BrowserSDKError(
            "trusted state workflow floor conflicts with the request",
            code="state_requirement_conflict",
        )
    return StateRequirement(
        same_session=requirement.same_session or trusted_floor.same_session,
        authenticated=(
            trusted_floor.authenticated
            if trusted_floor.authenticated is not None
            else requirement.authenticated
        ),
        account_hint=(
            trusted_floor.account_hint
            if trusted_floor.account_hint is not None
            else requirement.account_hint
        ),
        tenant_hint=(
            trusted_floor.tenant_hint
            if trusted_floor.tenant_hint is not None
            else requirement.tenant_hint
        ),
        workspace_hint=(
            trusted_floor.workspace_hint
            if trusted_floor.workspace_hint is not None
            else requirement.workspace_hint
        ),
        role_hint=(
            trusted_floor.role_hint
            if trusted_floor.role_hint is not None
            else requirement.role_hint
        ),
        workflow=floor_workflow or caller_workflow,
    )


def _required_state_facts(
    requirement: StateRequirement,
) -> tuple[tuple[str, str, str | bool | int | None], ...]:
    facts: list[tuple[str, str, str | bool | int | None]] = []
    if requirement.same_session:
        facts.append(("same_session", "same_session", True))
    if requirement.authenticated is not None:
        facts.append(
            ("authenticated", "authenticated", requirement.authenticated),
        )
    for fact_name, expected in (
        ("account", requirement.account_hint),
        ("tenant", requirement.tenant_hint),
        ("workspace", requirement.workspace_hint),
        ("role", requirement.role_hint),
    ):
        if expected is not None:
            facts.append((fact_name, fact_name, expected))
    if requirement.workflow is not None:
        workflow = requirement.workflow
        facts.append(
            (
                f"workflow:{workflow.key}",
                workflow.key,
                workflow.expected,
            ),
        )
    return tuple(facts)


def _runtime_session_fact(*, matches: bool, generation: str) -> StateFact:
    return StateFact(
        status=(
            StateFactStatus.VERIFIED if matches else StateFactStatus.MISMATCH
        ),
        safe_summary=(
            "Runtime session matches the owner"
            if matches
            else "Runtime session does not match the owner"
        ),
        evidence_ref=None,
        revision=f"runtime:{generation}",
        fresh_until=None,
    )


def _index_verifiers(
    catalog: tuple[TrustedStateVerifier, ...],
) -> dict[str, TrustedStateVerifier]:
    indexed: dict[str, TrustedStateVerifier] = {}
    for verifier in catalog:
        key = _require_verifier_text(
            getattr(verifier, "key", ""),
            "verifier key",
        )
        if not callable(getattr(verifier, "verify", None)):
            raise BrowserSDKError(
                "trusted state verifier is invalid",
                code="state_verifier_invalid",
            )
        if key in indexed:
            raise BrowserSDKError(
                "trusted state verifier key is duplicated",
                code="state_verifier_invalid",
            )
        indexed[key] = verifier
    return indexed


def _require_verifier_text(value: object, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise BrowserSDKError(
            f"trusted state verifier {field_name} is missing",
            code="state_verifier_invalid",
        )
    return normalized


def _safe_fact_summary(value: str) -> str:
    summary = " ".join(str(value or "").split())[:160]
    return summary or "trusted verifier supplied no safe summary"
