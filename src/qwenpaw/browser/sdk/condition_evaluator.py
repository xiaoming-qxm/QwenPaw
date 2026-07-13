# -*- coding: utf-8 -*-
"""Sole Browser-owned evaluator for bounded typed conditions."""
# pylint: disable=protected-access,too-many-branches
# pylint: disable=too-many-return-statements,try-except-raise

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from typing import Literal, Protocol, cast

from .canonical.contracts import (
    BrowserCondition,
    BrowserPrompt,
    CleanupInfo,
    ConditionAtom,
    ContextVersion,
    Coverage,
    EvidenceMeta,
    EvidenceRef,
    Notice,
    OptionChoice,
    PageCondition,
    RegionCondition,
    RegionRef,
    ResourceCondition,
    ResourceHandle,
    SurfaceCondition,
    TabSummary,
    TargetCondition,
    TargetQuery,
    TargetRef,
    TerminalStatus,
    _serialize_browser_condition,
)
from .governance.errors import BrowserSDKError
from .primitives.matching import match_page_url, normalize_visible_text
from .runtime.observation_store import ObservationStore, ObservationStoreError
from .runtime.resources import ResourceStore, ResourceStoreError
from .runtime.session_owner import (
    BrowserRequestBinding,
    BrowserSessionOwnerRegistry,
    OwnerKey,
)


ProbeState = Literal["AVAILABLE", "STALE", "UNAVAILABLE"]
ConditionOutcome = Literal[
    "SATISFIED",
    "TIMED_OUT",
    "STALE",
    "UNAVAILABLE",
    "INVALID_ARGUMENT",
]


class _StaleBaseline(RuntimeError):
    """A once-valid baseline was replaced by a new document generation."""


def _normalize_option_choice(choice: OptionChoice) -> tuple[str, str]:
    """Apply the shared producer/evaluator/dispatcher option rules."""
    if not isinstance(choice, OptionChoice):
        raise TypeError("choice must be an OptionChoice")
    value = (
        normalize_visible_text(choice.value)
        if choice.by == "label"
        else choice.value
    )
    return (choice.by, value)


class MonotonicClock(Protocol):
    """Deterministic monotonic time source owned by Browser Runtime."""

    def now(self) -> float:
        """Return monotonic seconds."""

    async def sleep_until(self, deadline: float) -> None:
        """Yield until a monotonic deadline."""


@dataclass(frozen=True, slots=True)
class ConditionReceiver:
    """Exact owner/session/tab/document receiver for one evaluation."""

    owner_key: OwnerKey
    root_session_id: str
    tab_id: str
    context: ContextVersion
    generation: int
    observation_store: ObservationStore | None = None
    resource_store: ResourceStore | None = None
    target_registry: BrowserSessionOwnerRegistry | None = None
    owner_binding: BrowserRequestBinding | None = None
    target_facts: tuple["TargetFacts", ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.owner_key, tuple)
            or len(self.owner_key) != 2
            or not all(self.owner_key)
        ):
            raise ValueError("receiver owner_key is invalid")
        if not self.root_session_id or not self.tab_id:
            raise ValueError("receiver session and tab are required")
        if not isinstance(self.context, ContextVersion):
            raise TypeError("receiver context must be runtime-issued")
        if self.generation < 1:
            raise ValueError("receiver generation must be positive")

    @property
    def fingerprint(self) -> str:
        """Return a stable private receiver fingerprint."""
        context_fields = self.context.to_dict()
        context_id = context_fields.get("id") or context_fields.get(
            "version_ref",
            "",
        )
        raw = repr(
            (
                self.owner_key,
                self.root_session_id,
                self.tab_id,
                context_id,
                self.generation,
                id(self.resource_store),
            ),
        )
        return sha256(raw.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ConditionBaseline:
    """Trusted baseline identity sealed into an armed watch."""

    label: str = ""
    context: ContextVersion | None = None
    evidence: EvidenceRef | None = None
    region: RegionRef | None = None

    @property
    def fingerprint(self) -> str:
        """Return the identity-only baseline fingerprint."""
        values = (
            self.label,
            _opaque_id(self.context),
            _opaque_id(self.evidence),
            _opaque_id(self.region),
        )
        return sha256(repr(values).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PageFacts:
    """Raw trusted page facts; no condition truth is included."""

    url: str
    title: str
    document_generation: str | int
    ready_state: Literal["loading", "dom_content_loaded", "load"]


@dataclass(frozen=True, slots=True)
class RegionFacts:
    """Raw facts for one exact RegionRef."""

    region: RegionRef
    text: str
    item_count: int
    digest: str
    coverage: Coverage
    baselines: tuple[tuple[EvidenceRef, str], ...] = ()


@dataclass(frozen=True, slots=True)
class TargetFacts:
    """Immutable target evidence; authority remains in the owner registry."""

    ref: TargetRef
    role: str
    name: str
    text: str
    states: tuple[str, ...] = ()
    value: str | None = None
    checked: bool | None = None
    selected: OptionChoice | None = None
    region: RegionRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ref, TargetRef):
            raise TypeError("target facts require a TargetRef")


@dataclass(frozen=True, slots=True)
class MatchedTargetCondition(TargetCondition):
    """Matched Target atom retaining every immutable candidate ref."""

    matched_target_refs: tuple[TargetRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    """One fresh trusted observation from a backend probe."""

    evidence: EvidenceMeta
    context: ContextVersion
    coverage: Coverage
    state: ProbeState
    page: PageFacts | None = None
    regions: tuple[RegionFacts, ...] = ()
    targets: tuple[TargetFacts, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in {"AVAILABLE", "STALE", "UNAVAILABLE"}:
            raise ValueError("invalid probe state")
        if not isinstance(self.evidence, EvidenceMeta):
            raise TypeError("probe evidence is required")
        if self.coverage != self.evidence.coverage:
            raise ValueError("probe coverage must match evidence")


@dataclass(frozen=True, slots=True)
class ResourceOperationBinding:
    """Private PendingAction identity required by `created` atoms."""

    operation_id: str
    operation_fingerprint: str
    command_id: str
    owner_key: OwnerKey
    tab_id: str
    pre_arm_watermark: int | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.operation_id,
                self.operation_fingerprint,
                self.command_id,
                self.tab_id,
            ),
        ):
            raise ValueError("resource operation binding is incomplete")
        if (
            not isinstance(self.owner_key, tuple)
            or len(self.owner_key) != 2
            or not all(self.owner_key)
        ):
            raise ValueError("resource operation owner is invalid")
        if self.pre_arm_watermark is not None and self.pre_arm_watermark < 0:
            raise ValueError("resource operation watermark is invalid")


@dataclass(frozen=True, slots=True)
class ProbeRequest:
    """Exact receiver and closed condition requested from a raw probe."""

    receiver: ConditionReceiver
    condition: BrowserCondition
    baseline: ConditionBaseline | None = None
    operation: ResourceOperationBinding | None = None


@dataclass(frozen=True, slots=True)
class ProbeSubscription:
    """Private backend subscription token and its atomic watermark."""

    token: object
    watermark: int


@dataclass(frozen=True, slots=True)
class ProbeHint:
    """Monotonic change hint; never a truth-bearing event."""

    sequence: int


class ConditionProbe(Protocol):
    """The only explicit backend fact ingress accepted by the evaluator."""

    async def check(self, request: ProbeRequest) -> ProbeObservation:
        """Capture fresh raw facts."""

    async def subscribe(self, request: ProbeRequest) -> ProbeSubscription:
        """Atomically subscribe and return the recorded watermark."""

    async def next_hint(
        self,
        subscription: ProbeSubscription,
        *,
        deadline: float,
    ) -> ProbeHint | None:
        """Wait for a hint or the supplied monotonic deadline."""

    async def unsubscribe(self, subscription: ProbeSubscription) -> None:
        """Release the private subscription."""


@dataclass(frozen=True, slots=True)
class ConditionEvaluation:
    """Internal evidence-bearing terminal facts projected into WaitResult."""

    status: TerminalStatus
    outcome: ConditionOutcome | None
    evidence: EvidenceMeta | None
    matched_atoms: tuple[ConditionAtom, ...]
    last_observed: ContextVersion | None
    elapsed_ms: int
    cleanup: CleanupInfo = CleanupInfo()
    error: str | None = None


@dataclass(slots=True, init=False)
class ConditionWatch:
    """Single-use armed subscription with sealed fingerprints."""

    _receiver_fingerprint: str
    _condition_fingerprint: str
    _baseline_fingerprint: str
    _probe_fingerprint: int
    _request: ProbeRequest
    _probe: ConditionProbe
    _subscription: ProbeSubscription | None
    _observation: ProbeObservation | None
    _startup_error: str | None
    _used: bool
    _armed_at: float

    def __init__(self) -> None:
        raise TypeError(
            "ConditionWatch values are issued by ConditionEvaluator",
        )


class ConditionEvaluator:
    """Evaluate all typed conditions with one bounded state machine."""

    _POLL_SECONDS = 0.1

    def __init__(self, *, clock: MonotonicClock) -> None:
        self._clock = clock

    async def arm(
        self,
        receiver: ConditionReceiver,
        condition: BrowserCondition,
        *,
        probe: ConditionProbe,
        baseline: ConditionBaseline | None = None,
        operation: ResourceOperationBinding | None = None,
    ) -> ConditionWatch:
        """Check immediately, then atomically arm a single-use watch."""
        request = ProbeRequest(receiver, condition, baseline, operation)
        watch = _issue_watch(
            request=request,
            probe=probe,
            receiver_fingerprint=receiver.fingerprint,
            condition_fingerprint=_condition_fingerprint(condition),
            baseline_fingerprint=_baseline_fingerprint(baseline),
            armed_at=self._clock.now(),
        )
        try:
            _validate_resource_operation(receiver, condition, operation)
            _validate_baseline_shape(receiver, condition, baseline)
            watch._observation = await probe.check(request)
        except _StaleBaseline as exc:
            try:
                watch._observation = await probe.check(request)
            # pylint: disable-next=broad-exception-caught
            except Exception as probe_exc:
                watch._startup_error = f"startup:{type(probe_exc).__name__}"
                return watch
            watch._startup_error = f"stale:{exc}"
            return watch
        except (TypeError, ValueError) as exc:
            watch._startup_error = f"invalid:{exc}"
            return watch
        except Exception as exc:  # pylint: disable=broad-exception-caught
            watch._startup_error = f"startup:{type(exc).__name__}"
            return watch
        try:
            if watch._observation.state == "AVAILABLE":
                watch._subscription = await probe.subscribe(request)
                if request.operation is not None:
                    watch._request = replace(
                        request,
                        operation=replace(
                            request.operation,
                            pre_arm_watermark=(watch._subscription.watermark),
                        ),
                    )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            watch._startup_error = f"subscribe:{type(exc).__name__}"
        return watch

    async def evaluate(
        self,
        receiver: ConditionReceiver,
        condition: BrowserCondition,
        *,
        probe: ConditionProbe,
        timeout_ms: int,
        stable_ms: int = 0,
        baseline: ConditionBaseline | None = None,
        armed: ConditionWatch | None = None,
        operation: ResourceOperationBinding | None = None,
    ) -> ConditionEvaluation:
        """Consume one watch through race-close and bounded rechecks."""
        started = self._clock.now()
        if timeout_ms < 1 or stable_ms < 0 or stable_ms > timeout_ms:
            return _invalid_evaluation("invalid wait limits")
        watch = armed or await self.arm(
            receiver,
            condition,
            probe=probe,
            baseline=baseline,
            operation=operation,
        )
        mismatch = _consume_watch(
            watch,
            receiver=receiver,
            condition=condition,
            probe=probe,
            baseline=baseline,
        )
        if mismatch is not None:
            cleanup = await _cleanup_watch(watch)
            return replace(mismatch, cleanup=cleanup)
        result: ConditionEvaluation
        try:
            result = await self._run(
                watch,
                timeout_ms=timeout_ms,
                stable_ms=stable_ms,
                started=started,
            )
        except asyncio.CancelledError:
            await _cleanup_watch(watch)
            raise
        cleanup = await _cleanup_watch(watch)
        return replace(result, cleanup=cleanup)

    async def _run(
        self,
        watch: ConditionWatch,
        *,
        timeout_ms: int,
        stable_ms: int,
        started: float,
    ) -> ConditionEvaluation:
        observation = watch._observation
        if watch._startup_error is not None:
            if watch._startup_error.startswith("invalid:"):
                return _invalid_evaluation(watch._startup_error)
            if watch._startup_error.startswith("stale:"):
                if observation is None:
                    return _startup_failure(watch._startup_error, None)
                return _stale(observation, started, self._clock.now())
            return _startup_failure(watch._startup_error, observation)
        if observation is None:
            return _startup_failure("startup:no_observation", None)
        terminal = _probe_terminal(observation, started, self._clock.now())
        if terminal is not None:
            return terminal
        terminal = _target_terminal(
            watch._request.condition,
            watch._request.receiver,
            observation,
            started,
            self._clock.now(),
        )
        if terminal is not None:
            return terminal
        matched = _matched_atoms(
            watch._request.condition,
            observation,
            watch._request.receiver,
            watch._request.operation,
        )
        if (
            _condition_true(watch._request.condition, matched)
            and stable_ms == 0
        ):
            return _satisfied(observation, matched, started, self._clock.now())
        if watch._subscription is None:
            return _unavailable(observation, started, self._clock.now())

        deadline = started + timeout_ms / 1000
        stable_seconds = stable_ms / 1000
        stable_since: float | None = (
            self._clock.now()
            if _condition_true(watch._request.condition, matched)
            else None
        )
        last_sequence = watch._subscription.watermark
        try:
            observation = await watch._probe.check(watch._request)
        except Exception:  # pylint: disable=broad-exception-caught
            return _backend_failure(observation, started, self._clock.now())

        while True:
            terminal = _probe_terminal(observation, started, self._clock.now())
            if terminal is not None:
                return terminal
            terminal = _target_terminal(
                watch._request.condition,
                watch._request.receiver,
                observation,
                started,
                self._clock.now(),
            )
            if terminal is not None:
                return terminal
            matched = _matched_atoms(
                watch._request.condition,
                observation,
                watch._request.receiver,
                watch._request.operation,
            )
            truth = _condition_true(watch._request.condition, matched)
            now = self._clock.now()
            if truth:
                if stable_since is None:
                    stable_since = now
                if now >= stable_since + stable_seconds:
                    return _satisfied(observation, matched, started, now)
            else:
                stable_since = None
            if now >= deadline:
                return _timed_out(observation, matched, started, now)

            poll_deadline = min(deadline, now + self._POLL_SECONDS)
            if stable_since is not None:
                poll_deadline = min(
                    poll_deadline,
                    stable_since + stable_seconds,
                )
            try:
                hint = await watch._probe.next_hint(
                    watch._subscription,
                    deadline=poll_deadline,
                )
                if hint is not None and hint.sequence <= last_sequence:
                    continue
                if hint is not None:
                    last_sequence = hint.sequence
                observation = await watch._probe.check(watch._request)
            except asyncio.CancelledError:
                raise
            except Exception:  # pylint: disable=broad-exception-caught
                return _backend_failure(
                    observation,
                    started,
                    self._clock.now(),
                )


def _issue_watch(
    *,
    request: ProbeRequest,
    probe: ConditionProbe,
    receiver_fingerprint: str,
    condition_fingerprint: str,
    baseline_fingerprint: str,
    armed_at: float,
) -> ConditionWatch:
    watch = object.__new__(ConditionWatch)
    watch._receiver_fingerprint = receiver_fingerprint
    watch._condition_fingerprint = condition_fingerprint
    watch._baseline_fingerprint = baseline_fingerprint
    watch._probe_fingerprint = id(probe)
    watch._request = request
    watch._probe = probe
    watch._subscription = None
    watch._observation = None
    watch._startup_error = None
    watch._used = False
    watch._armed_at = armed_at
    return watch


def _consume_watch(
    watch: ConditionWatch,
    *,
    receiver: ConditionReceiver,
    condition: BrowserCondition,
    probe: ConditionProbe,
    baseline: ConditionBaseline | None,
) -> ConditionEvaluation | None:
    if not isinstance(watch, ConditionWatch) or watch._used:
        return _invalid_evaluation(
            "condition watch is invalid or already used",
        )
    watch._used = True
    expected = (
        receiver.fingerprint,
        _condition_fingerprint(condition),
        _baseline_fingerprint(baseline),
        id(probe),
    )
    actual = (
        watch._receiver_fingerprint,
        watch._condition_fingerprint,
        watch._baseline_fingerprint,
        watch._probe_fingerprint,
    )
    if actual != expected:
        return _invalid_evaluation("condition watch fingerprint mismatch")
    return None


async def _cleanup_watch(watch: ConditionWatch) -> CleanupInfo:
    if watch._subscription is None:
        return CleanupInfo()
    subscription = watch._subscription
    watch._subscription = None
    try:
        await watch._probe.unsubscribe(subscription)
    except Exception:  # pylint: disable=broad-exception-caught
        return CleanupInfo(
            complete=False,
            warnings=(
                Notice(
                    code="condition_unsubscribe_failed",
                    safe_message=(
                        "Condition subscription cleanup was incomplete."
                    ),
                ),
            ),
        )
    return CleanupInfo()


def _condition_fingerprint(condition: BrowserCondition) -> str:
    payload = _serialize_browser_condition(
        condition,
        max_atoms=max(1, len(condition.atoms)),
    )
    encoded = json.dumps(payload, sort_keys=True, default=str).encode()
    return sha256(encoded).hexdigest()


def _baseline_fingerprint(baseline: ConditionBaseline | None) -> str:
    return baseline.fingerprint if baseline is not None else "none"


def _validate_resource_operation(
    receiver: ConditionReceiver,
    condition: BrowserCondition,
    operation: ResourceOperationBinding | None,
) -> None:
    created = any(
        isinstance(atom, ResourceCondition) and atom.kind == "created"
        for atom in condition.atoms
    )
    if not created:
        if operation is not None:
            raise ValueError("resource operation binding is unexpected")
        return
    if operation is None:
        raise ValueError("resource operation binding required")
    if (
        operation.owner_key != receiver.owner_key
        or operation.tab_id != receiver.tab_id
    ):
        raise ValueError("resource operation receiver mismatch")


def _opaque_id(value: object | None) -> str:
    if value is None:
        return ""
    to_dict = getattr(value, "to_dict", None)
    if not callable(to_dict):
        return "invalid"
    fields = to_dict()
    return str(fields.get("id") or fields.get("version_ref") or "")


def _validate_baseline_shape(
    receiver: ConditionReceiver,
    condition: BrowserCondition,
    baseline: ConditionBaseline | None,
) -> None:
    if baseline is not None:
        if baseline.context is not None and not isinstance(
            baseline.context,
            ContextVersion,
        ):
            raise TypeError("baseline context is invalid")
        if baseline.evidence is not None and not isinstance(
            baseline.evidence,
            EvidenceRef,
        ):
            raise TypeError("baseline evidence is invalid")
        if baseline.region is not None and not isinstance(
            baseline.region,
            RegionRef,
        ):
            raise TypeError("baseline region is invalid")
    for atom in condition.atoms:
        if isinstance(atom, PageCondition) and atom.kind == "document_changed":
            if not isinstance(atom.subject, ContextVersion):
                raise TypeError("document baseline is invalid")
            if receiver.observation_store is not None:
                try:
                    receiver.observation_store.require_context_baseline(
                        atom.subject,
                    )
                except ObservationStoreError as exc:
                    _raise_baseline_error(exc)
        if isinstance(atom, RegionCondition) and atom.kind == "changed":
            if not isinstance(atom.value, EvidenceRef):
                raise TypeError("region evidence baseline is invalid")
            if receiver.observation_store is not None:
                try:
                    store = receiver.observation_store
                    store.require_region_evidence_baseline(
                        atom.region,
                        atom.value,
                    )
                except ObservationStoreError as exc:
                    _raise_baseline_error(exc)


def _raise_baseline_error(error: ObservationStoreError) -> None:
    stale_codes = (
        "_generation_mismatch",
        "_context_mismatch",
        "_expired",
    )
    if error.code.endswith(stale_codes):
        raise _StaleBaseline(error.code) from error
    raise ValueError(error.code) from error


def _matched_atoms(
    condition: BrowserCondition,
    observation: ProbeObservation,
    receiver: ConditionReceiver,
    operation: ResourceOperationBinding | None = None,
) -> tuple[ConditionAtom, ...]:
    matched: list[ConditionAtom] = []
    for atom in condition.atoms:
        if isinstance(atom, ResourceCondition):
            if _resource_condition_matches(atom, receiver, operation):
                matched.append(atom)
            continue
        if isinstance(atom, TargetCondition):
            target_refs = _target_matches(atom, observation, receiver)
            if target_refs is not None:
                matched.append(
                    MatchedTargetCondition(
                        atom.kind,
                        atom.subject,
                        atom.expected,
                        target_refs,
                    ),
                )
            continue
        if isinstance(atom, SurfaceCondition):
            if _surface_condition_matches(atom, receiver):
                matched.append(atom)
            continue
        if _atom_matches(atom, observation):
            matched.append(atom)
    return tuple(matched)


def _resource_condition_matches(
    atom: ResourceCondition,
    receiver: ConditionReceiver | object,
    operation: ResourceOperationBinding | None = None,
) -> bool:
    """Read only fresh complete store facts under the exact binding."""
    store = getattr(receiver, "resource_store", None)
    owner_key = getattr(receiver, "owner_key", None)
    if not isinstance(store, ResourceStore) or owner_key != store.owner_key:
        return False
    if atom.kind == "created":
        if operation is None or operation.owner_key != owner_key:
            return False
        if not isinstance(atom.subject, tuple) or len(atom.subject) != 4:
            return False
        kind, count, media_type, name = atom.subject
        if kind not in {"download", "page_pdf"}:
            return False
        try:
            created_handles = store.created_for(operation)
        except ResourceStoreError:
            return False
        matched = tuple(
            handle
            for handle in created_handles
            if (media_type is None or handle.media_type == media_type)
            and (name is None or handle.name == name)
        )
        return len(matched) == count
    if atom.kind != "available" or not isinstance(
        atom.subject,
        ResourceHandle,
    ):
        return False
    try:
        current = store.require(str(atom.subject.id))
    except ResourceStoreError:
        return False
    return current is atom.subject


def _surface_condition_matches(
    atom: SurfaceCondition,
    receiver: ConditionReceiver | object,
) -> bool:
    """Evaluate only the private T005 exact tab-closed event adapter."""
    registry = getattr(receiver, "target_registry", None)
    owner = getattr(receiver, "owner_binding", None)
    if not isinstance(registry, BrowserSessionOwnerRegistry) or not isinstance(
        owner,
        BrowserRequestBinding,
    ):
        return False
    receiver_tab = str(getattr(receiver, "tab_id", "") or "")
    state = registry._require_current_lease(owner)
    if atom.kind == "tab_closed" and isinstance(atom.subject, TabSummary):
        return registry.is_tab_closed(owner, atom.subject)
    if atom.kind == "tab_selected" and isinstance(atom.subject, TabSummary):
        if state.selected_tab is not atom.subject:
            return False
        bound = state.tabs.get(atom.subject)
        return bound is not None and bound.receiver_tab_key == receiver_tab
    if atom.kind == "prompt_present":
        prompt = state.current_prompt_by_tab.get(receiver_tab)
        if prompt is None:
            return False
        try:
            registry.resolve_browser_prompt(prompt, owner=owner)
        except BrowserSDKError:
            return False
        return atom.subject is None or str(prompt.type) == str(atom.subject)
    if atom.kind == "prompt_absent" and isinstance(
        atom.subject,
        BrowserPrompt,
    ):
        try:
            binding = registry.resolve_browser_prompt(
                atom.subject,
                owner=owner,
            )
        except BrowserSDKError as exc:
            return exc.code == "prompt_expired"
        if binding.receiver_tab_key != receiver_tab:
            return False
        return (
            state.current_prompt_by_tab.get(receiver_tab) is not atom.subject
        )
    if atom.kind == "tab_opened" and isinstance(
        atom.subject,
        ContextVersion,
    ):
        return bool(state.tabs) and atom.subject in state.contexts
    return False


def _condition_true(
    condition: BrowserCondition,
    matched: tuple[ConditionAtom, ...],
) -> bool:
    if condition.combinator == "all":
        return len(matched) == len(condition.atoms)
    return bool(matched)


def _atom_matches(atom: ConditionAtom, observation: ProbeObservation) -> bool:
    if isinstance(atom, PageCondition):
        return _page_matches(atom, observation)
    if isinstance(atom, RegionCondition):
        return _region_matches(atom, observation)
    return False


def _target_terminal(
    condition: BrowserCondition,
    receiver: ConditionReceiver,
    observation: ProbeObservation,
    started: float,
    now: float,
) -> ConditionEvaluation | None:
    registry = receiver.target_registry
    owner = receiver.owner_binding
    for atom in condition.atoms:
        if not isinstance(atom, TargetCondition) or not isinstance(
            atom.subject,
            TargetRef,
        ):
            continue
        if registry is None or owner is None:
            return _unavailable(observation, started, now)
        try:
            status = registry.target_context_status(
                atom.subject,
                current_context=receiver.context,
                receiver_tab=receiver.tab_id,
                owner=owner,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            return _stale(observation, started, now)
        if status == "STALE":
            return _stale(observation, started, now)
    return None


def _target_matches(
    atom: ConditionAtom,
    observation: ProbeObservation,
    receiver: ConditionReceiver,
) -> tuple[TargetRef, ...] | None:
    if not isinstance(atom, TargetCondition):
        return None
    facts = observation.targets or receiver.target_facts
    candidates = _target_candidates(atom, facts, receiver)
    if candidates is None:
        return None
    matching = tuple(
        fact for fact in candidates if _target_fact_matches(atom, fact)
    )
    if atom.kind in {"exists", "visible"}:
        expected = cast(bool, atom.expected)
        truth = bool(matching)
        if truth == expected and (
            expected or observation.coverage == "COMPLETE"
        ):
            return tuple(fact.ref for fact in matching)
        return None
    if atom.kind in {"enabled", "editable", "checked"}:
        expected = cast(bool, atom.expected)
        if not candidates:
            return None
        truth = bool(matching)
        if truth == expected and (
            expected or observation.coverage == "COMPLETE"
        ):
            return tuple(fact.ref for fact in candidates)
        return None
    if matching:
        return tuple(fact.ref for fact in matching)
    return None


def _target_candidates(
    atom: TargetCondition,
    facts: tuple[TargetFacts, ...],
    receiver: ConditionReceiver,
) -> tuple[TargetFacts, ...] | None:
    if isinstance(atom.subject, TargetQuery):
        return tuple(
            fact for fact in facts if _target_query_matches(atom.subject, fact)
        )
    if not isinstance(atom.subject, TargetRef):
        return None
    registry = receiver.target_registry
    owner = receiver.owner_binding
    if registry is None or owner is None:
        return ()
    matches: list[TargetFacts] = []
    for fact in facts:
        try:
            same = registry.same_target_identity(
                atom.subject,
                fact.ref,
                receiver_tab=receiver.tab_id,
                owner=owner,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            continue
        if same:
            matches.append(fact)
    return tuple(matches)


def _target_query_matches(query: TargetQuery, fact: TargetFacts) -> bool:
    if query.region is not None and fact.region is not query.region:
        return False
    if (
        query.role is not None
        and normalize_visible_text(fact.role) != query.role
    ):
        return False
    for expected, actual in (
        (query.name, fact.name),
        (query.text, fact.text),
    ):
        if expected is None:
            continue
        normalized = normalize_visible_text(actual)
        if query.match == "exact":
            if normalized != expected:
                return False
        elif expected not in normalized:
            return False
    return True


def _target_fact_matches(
    atom: TargetCondition,
    fact: TargetFacts,
) -> bool:
    if atom.kind == "exists":
        return True
    if atom.kind in {"visible", "enabled", "editable"}:
        return atom.kind in fact.states
    if atom.kind == "value":
        return fact.value == atom.expected
    if atom.kind == "checked":
        return fact.checked is True or "checked" in fact.states
    if atom.kind == "selected":
        return (
            fact.selected is not None
            and isinstance(atom.expected, OptionChoice)
            and _normalize_option_choice(fact.selected)
            == _normalize_option_choice(atom.expected)
        )
    return False


def _page_matches(atom: PageCondition, observation: ProbeObservation) -> bool:
    page = observation.page
    if page is None:
        return False
    if atom.kind == "url":
        return match_page_url(
            page.url,
            str(atom.subject),
            mode=atom.match,  # type: ignore[arg-type]
        )
    if atom.kind == "title":
        actual = normalize_visible_text(page.title)
        expected = normalize_visible_text(str(atom.subject))
        if atom.match == "exact":
            return actual == expected
        return expected in actual
    if atom.kind == "document_changed":
        return observation.context is not atom.subject
    states = {
        "loading": 0,
        "dom_content_loaded": 1,
        "load": 2,
    }
    return states[page.ready_state] >= states[str(atom.subject)]


def _region_matches(
    atom: RegionCondition,
    observation: ProbeObservation,
) -> bool:
    facts = next(
        (item for item in observation.regions if item.region is atom.region),
        None,
    )
    if facts is None:
        return False
    if atom.kind == "text":
        present, mode = cast(tuple[bool, str], atom.option)
        actual = normalize_visible_text(facts.text)
        expected = normalize_visible_text(str(atom.value))
        found = actual == expected if mode == "exact" else expected in actual
        if present:
            return found
        return not found and facts.coverage == "COMPLETE"
    if atom.kind == "item_count":
        expected_count = cast(int, atom.value)
        if atom.option == "gte":
            return facts.item_count >= expected_count
        if facts.coverage != "COMPLETE":
            return False
        if atom.option == "eq":
            return facts.item_count == expected_count
        return facts.item_count <= expected_count
    baseline = next(
        (digest for ref, digest in facts.baselines if ref is atom.value),
        None,
    )
    return baseline is not None and baseline != facts.digest


def _probe_terminal(
    observation: ProbeObservation,
    started: float,
    now: float,
) -> ConditionEvaluation | None:
    if observation.state == "STALE" or observation.coverage == "STALE":
        return _stale(observation, started, now)
    if (
        observation.state == "UNAVAILABLE"
        or observation.coverage == "UNAVAILABLE"
    ):
        return _unavailable(observation, started, now)
    return None


def _stale(
    observation: ProbeObservation,
    started: float,
    now: float,
) -> ConditionEvaluation:
    return ConditionEvaluation(
        status="PARTIAL",
        outcome="STALE",
        evidence=observation.evidence,
        matched_atoms=(),
        last_observed=observation.context,
        elapsed_ms=_elapsed_ms(started, now),
    )


def _satisfied(
    observation: ProbeObservation,
    matched: tuple[ConditionAtom, ...],
    started: float,
    now: float,
) -> ConditionEvaluation:
    return ConditionEvaluation(
        status="SUCCEEDED",
        outcome="SATISFIED",
        evidence=observation.evidence,
        matched_atoms=matched,
        last_observed=observation.context,
        elapsed_ms=_elapsed_ms(started, now),
    )


def _timed_out(
    observation: ProbeObservation,
    matched: tuple[ConditionAtom, ...],
    started: float,
    now: float,
) -> ConditionEvaluation:
    status: TerminalStatus = (
        "SUCCEEDED" if observation.coverage == "COMPLETE" else "PARTIAL"
    )
    return ConditionEvaluation(
        status=status,
        outcome="TIMED_OUT",
        evidence=observation.evidence,
        matched_atoms=matched,
        last_observed=observation.context,
        elapsed_ms=_elapsed_ms(started, now),
    )


def _unavailable(
    observation: ProbeObservation,
    started: float,
    now: float,
) -> ConditionEvaluation:
    return ConditionEvaluation(
        status="BLOCKED",
        outcome="UNAVAILABLE",
        evidence=observation.evidence,
        matched_atoms=(),
        last_observed=observation.context,
        elapsed_ms=_elapsed_ms(started, now),
    )


def _backend_failure(
    observation: ProbeObservation,
    started: float,
    now: float,
) -> ConditionEvaluation:
    return ConditionEvaluation(
        status="FAILED",
        outcome="UNAVAILABLE",
        evidence=observation.evidence,
        matched_atoms=(),
        last_observed=observation.context,
        elapsed_ms=_elapsed_ms(started, now),
        error="condition probe failed",
    )


def _startup_failure(
    error: str,
    observation: ProbeObservation | None,
) -> ConditionEvaluation:
    if observation is None:
        return ConditionEvaluation(
            status="FAILED",
            outcome=None,
            evidence=None,
            matched_atoms=(),
            last_observed=None,
            elapsed_ms=0,
            error=error,
        )
    return ConditionEvaluation(
        status="FAILED",
        outcome="UNAVAILABLE",
        evidence=observation.evidence,
        matched_atoms=(),
        last_observed=observation.context,
        elapsed_ms=0,
        error=error,
    )


def _invalid_evaluation(error: str) -> ConditionEvaluation:
    return ConditionEvaluation(
        status="FAILED",
        outcome="INVALID_ARGUMENT",
        evidence=None,
        matched_atoms=(),
        last_observed=None,
        elapsed_ms=0,
        error=error,
    )


def _elapsed_ms(started: float, now: float) -> int:
    return max(0, round((now - started) * 1000))


__all__ = [
    "ConditionBaseline",
    "ConditionEvaluation",
    "ConditionEvaluator",
    "ConditionProbe",
    "ConditionReceiver",
    "ConditionWatch",
    "MonotonicClock",
    "PageFacts",
    "ProbeHint",
    "ProbeObservation",
    "ProbeRequest",
    "ProbeState",
    "ProbeSubscription",
    "RegionFacts",
]
