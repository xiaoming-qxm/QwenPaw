# -*- coding: utf-8 -*-
"""Trusted session-mode and root-task ownership registries."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import Callable, Literal, TypeAlias
from uuid import uuid4

from ..canonical.contracts import (
    ContextVersion,
    TargetRef,
    _issue_context_version,
    _issue_target_ref,
)
from ..governance.errors import BrowserSDKError


class ContractMode(StrEnum):
    """Browser public contract selected for one trusted root session."""

    LEGACY = "LEGACY"
    CANONICAL = "CANONICAL"


class RootTaskOutcome(StrEnum):
    """Trusted terminal or retained outcome for a root task."""

    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    HANDOFF = "HANDOFF"
    RETAINED_PROMPT = "RETAINED_PROMPT"
    RETAINED_UNCERTAIN = "RETAINED_UNCERTAIN"


OwnerKey: TypeAlias = tuple[str, str]


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


@dataclass(frozen=True, slots=True)
class BrowserRequestBinding:
    """Registry-issued identity and lease for one Browser request."""

    root_session_id: str
    root_task_id: str
    browser_owner_id: str
    contract_mode: ContractMode
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
    lease_active: bool = True
    retained_until: float | None = None
    attachment: BrowserOwnerAttachment | None = None
    contexts: dict[ContextVersion, "_ContextState"] = field(
        default_factory=dict,
    )
    targets: dict[TargetRef, TargetBinding] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _ContextState:
    native: NativeContextVersion
    receiver_tab_key: str
    expires_at: float


@dataclass(slots=True)
class _TokenState:
    owner_key: OwnerKey
    root_session_id: str
    expires_at: float
    consumed: bool = False


class SessionContractModeRegistry:
    """Atomically bind a contract mode once per trusted root session."""

    def __init__(self) -> None:
        self._modes: dict[str, ContractMode] = {}
        self._lock = asyncio.Lock()

    async def bind(
        self,
        *,
        root_session_id: str,
        rollout_default: ContractMode,
    ) -> ContractMode:
        """Return the session's first process-trusted rollout decision."""
        session_key = _require_identity(root_session_id, "root_session_id")
        async with self._lock:
            mode = self._modes.get(session_key)
            if mode is None:
                mode = ContractMode(rollout_default)
                self._modes[session_key] = mode
            return mode

    async def require(self, root_session_id: str) -> ContractMode:
        """Return an existing trusted binding, failing closed if absent."""
        session_key = _require_identity(root_session_id, "root_session_id")
        async with self._lock:
            try:
                return self._modes[session_key]
            except KeyError as exc:
                raise BrowserOwnerRegistryError(
                    "contract_mode_missing",
                ) from exc


class BrowserSessionOwnerRegistry:
    """Manage main-process owners, fenced leases, and opaque resumes."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        modes: SessionContractModeRegistry | None = None,
    ) -> None:
        self._clock = clock
        self._modes = modes or SessionContractModeRegistry()
        self._owners: dict[tuple[str, str], _OwnerState] = {}
        self._tokens: dict[str, _TokenState] = {}
        self._lock = asyncio.Lock()

    async def begin_request(
        self,
        *,
        root_session_id: str,
        source: str,
        rollout_default: ContractMode | None = None,
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

        mode = await self._modes.bind(
            root_session_id=session_key,
            rollout_default=rollout_default or ContractMode.LEGACY,
        )
        binding = BrowserRequestBinding(
            root_session_id=session_key,
            root_task_id=f"root_task_{uuid4().hex}",
            browser_owner_id=f"browser_owner_{uuid4().hex}",
            contract_mode=mode,
            lease_generation=1,
        )
        async with self._lock:
            self._owners[binding.owner_key] = _OwnerState(binding=binding)
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

    @property
    def target_issue_count(self) -> int:
        """Return issuance count for no-authority query assertions."""
        return sum(len(state.targets) for state in self._owners.values())

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
        expiry = float(expires_at)
        context = _issue_context_version(
            version_ref=_new_handle_token("context"),
            safe_receiver=str(safe_receiver or receiver),
        )
        state.contexts[context] = _ContextState(
            native=native,
            receiver_tab_key=receiver,
            expires_at=expiry,
        )
        return context

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
        if self._clock() > stored.expires_at:
            raise BrowserSDKError(
                "context binding expired",
                code="context_expired",
            )
        return stored.native

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
        if self._clock() > binding.expires_at:
            raise BrowserSDKError(
                "target binding expired",
                code="target_expired",
            )
        return binding

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
            contract_mode=current.contract_mode,
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
        if (
            state.binding.root_session_id != binding.root_session_id
            or state.binding.contract_mode is not binding.contract_mode
        ):
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
