# -*- coding: utf-8 -*-
"""Canonical Tab, BrowserTabs, and TabActions public surface."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from hashlib import sha256
from time import monotonic
from typing import Any, Awaitable, Callable, Literal, cast
from urllib.parse import urlsplit
from uuid import uuid4

from ..action_runner import ActionRunner
from ..backends.protocols import BackendProfile
from ..condition_evaluator import (
    ConditionEvaluation,
    ConditionEvaluator,
    ConditionReceiver,
    ResourceOperationBinding,
    TargetFacts,
)
from ..contract_runtime import canonical_mutation_contract
from ..governance.errors import BrowserSDKError, BrowserSDKGap
from ..primitives.matching import normalize_visible_text
from ..runtime.resources import (
    DownloadCapture,
    PagePdfCapture,
    ResourceStore,
    ResourceStoreError,
    ScreenshotCapture,
    TrustedOutputSource,
)
from ..runtime.result_delivery import RequiredBlock, record_browser_result
from ..runtime.observation_store import (
    ObservationStore,
    ObservationStoreError,
    cleanup_observation_tab,
)
from ..runtime.snapshot import (
    SnapshotCapture,
    SnapshotTarget,
    SourceTraversalCapture,
)
from ..runtime.session_owner import (
    BrowserRequestBinding,
    BrowserSessionOwnerRegistry,
)
from .contracts import (
    ActionResult,
    ActionExpectation,
    CapabilityProblemDetails,
    BrowserCondition,
    BrowserPrompt,
    CaptureGap,
    Coverage,
    CoverageGap,
    CurrentSurface,
    EvidenceRef,
    FrameScope,
    Grounding,
    ObservationScope,
    OptionChoice,
    PagePdfOptions,
    PagePdfResult,
    Problem,
    ReadCursor,
    ReadResult,
    ReadSegment,
    RegionScope,
    RegionSummary,
    ResourceCondition,
    ResourceHandle,
    ScreenshotResult,
    SnapshotCursor,
    SnapshotResult,
    SurfaceCondition,
    StateRequirement,
    TabSummary,
    RetryDirective,
    TargetQuery,
    TargetCondition,
    TargetRef,
    TargetSummary,
    TerminalStatus,
    VisualRegion,
    VisualContextRef,
    WaitResult,
    _condition_usage,
    _RUNTIME_VALUE_ISSUER,
    _issue_opaque_value,
    issue_operation_id,
)

Dispatch = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class _SourceContinuation:
    """Private binding for one bridge-owned observation continuation."""

    bridge_cursor: str
    scope: ObservationScope
    query: TargetQuery | None
    region_owner_chain: tuple[str, ...]
    context: Any
    generation: int
    visual: bool = False
    visual_witnesses: tuple[SnapshotTarget, ...] = ()


async def _invoke_async(
    callback: Callable[..., Awaitable[object]],
    *args: object,
    **kwargs: object,
) -> object:
    return await callback(*args, **kwargs)


@dataclass(slots=True)
class TabActions:
    """S0 action surface; later stages activate individual capabilities."""

    dispatch: Dispatch | None = field(default=None, repr=False)
    _target_registry: BrowserSessionOwnerRegistry | None = field(
        default=None,
        repr=False,
    )
    _owner_binding: BrowserRequestBinding | None = field(
        default=None,
        repr=False,
    )
    _receiver_tab: str = field(default="", repr=False)
    _receiver_summary: TabSummary | None = field(default=None, repr=False)
    _action_runner: ActionRunner | Any | None = field(
        default=None,
        repr=False,
    )
    _resources: ResourceStore | None = field(default=None, repr=False)
    _session: Any = field(default=None, repr=False)
    _condition_evaluator: ConditionEvaluator | Any | None = field(
        default=None,
        repr=False,
    )
    _condition_receiver: ConditionReceiver | None = field(
        default=None,
        repr=False,
    )
    _invalidate_observation: Callable[[], None] | None = field(
        default=None,
        repr=False,
    )
    _max_paste_chars: int = field(default=100_000, repr=False)

    async def navigate(
        self,
        url: str,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Navigate this exact receiver to one safe HTTP(S) URL."""
        _require_safe_http_url(url)
        return await self._run_mutation(
            "tab.actions.navigate",
            ordered_targets=(),
            arguments={"url": url},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    def _download_dispatcher(self, target: TargetRef) -> Dispatch:
        async def dispatch_download(
            *,
            command: object,
            dispatch_context: object,
        ) -> object:
            if self._resources is None:
                raise BrowserSDKError(
                    "Canonical ResourceStore is unavailable",
                    code="resource_store_unavailable",
                )
            download = getattr(self._session, "download_resource", None)
            if not callable(download):
                raise BrowserSDKError(
                    "Canonical download dispatcher is unavailable",
                    code="download_dispatcher_missing",
                )
            download_call = cast(Callable[..., Awaitable[object]], download)
            raw_command_payload = getattr(command, "_payload", None)
            operation = _resource_operation_from_payload(raw_command_payload)
            if getattr(command, "command_id", "") != operation.command_id:
                raise BrowserSDKError(
                    "Canonical download command identity is invalid",
                    code="download_command_invalid",
                )
            command_payload = _command_arguments(
                command,
                code="download_command_invalid",
                message="Canonical download command is invalid",
            )
            capture = await _invoke_async(
                download_call,
                self._receiver_tab,
                target,
                operation=operation,
                dispatch_context=dispatch_context,
                command_payload=command_payload,
            )
            if not isinstance(capture, DownloadCapture):
                raise BrowserSDKError(
                    "Canonical download capture is invalid",
                    code="download_capture_invalid",
                )
            handle = await self._resources.ingest_correlated_download(
                capture,
                operation,
            )
            return {"download": {"resources": (handle,), "count": 1}}

        return dispatch_download

    async def back(
        self,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Navigate backward in this receiver's history."""
        return await self._run_mutation(
            "tab.actions.back",
            ordered_targets=(),
            arguments={},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def forward(
        self,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Navigate forward in this receiver's history."""
        return await self._run_mutation(
            "tab.actions.forward",
            ordered_targets=(),
            arguments={},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def reload(
        self,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Reload this exact receiver."""
        return await self._run_mutation(
            "tab.actions.reload",
            ordered_targets=(),
            arguments={},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def click(
        self,
        target: TargetRef,
        *,
        button: Literal["primary", "secondary", "middle"] = "primary",
        count: Literal[1, 2] = 1,
        modifiers: tuple[
            Literal["alt", "control", "meta", "shift"],
            ...,
        ] = (),
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Click one Runtime-issued target with closed input values."""
        _require_choice(button, {"primary", "secondary", "middle"}, "button")
        _require_choice(count, {1, 2}, "count")
        _require_modifiers(
            modifiers,
            allowed={"alt", "control", "meta", "shift"},
        )
        if isinstance(target, str):
            # Preserve the frozen S0 characterization while rejecting all
            # string/native-id authority before the runner or backend.
            raise _capability_blocked("tab.actions.click")
        self._require_target(target)
        if self._action_runner is None:
            return _blocked_canonical_action(
                "tab.actions.click",
                target=target,
            )
        return await self._run_mutation(
            "tab.actions.click",
            ordered_targets=(("target", target),),
            arguments={
                "button": button,
                "count": count,
                "modifiers": modifiers,
            },
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
            dispatcher=self._interaction_dispatcher(
                "click",
                (("target", target),),
            ),
        )

    async def hover(
        self,
        target: TargetRef,
        *,
        expect: ActionExpectation | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Hover one Runtime-issued target."""
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.hover",
            ordered_targets=(("target", target),),
            arguments={},
            expectation=expect,
            timeout_ms=timeout_ms,
            dispatcher=self._interaction_dispatcher(
                "hover",
                (("target", target),),
            ),
        )

    async def drag(
        self,
        source: TargetRef,
        destination: TargetRef,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Drag between two ordered Runtime-issued endpoints."""
        self._require_target(source)
        self._require_target(destination)
        return await self._run_mutation(
            "tab.actions.drag",
            ordered_targets=(
                ("source", source),
                ("destination", destination),
            ),
            arguments={},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
            dispatcher=self._interaction_dispatcher(
                "drag",
                (
                    ("source", source),
                    ("destination", destination),
                ),
            ),
        )

    def _interaction_dispatcher(
        self,
        action: Literal["click", "hover", "drag"],
        targets: tuple[tuple[str, TargetRef], ...],
    ) -> Dispatch:
        async def dispatch_interaction(
            *,
            command: object,
            dispatch_context: object,
        ) -> object:
            dispatch = getattr(
                self._session,
                "dispatch_targeted_interaction",
                None,
            )
            if not callable(dispatch):
                raise BrowserSDKError(
                    "Canonical interaction dispatcher is unavailable",
                    code="interaction_dispatcher_missing",
                )
            command_payload = _command_arguments(
                command,
                code="interaction_command_invalid",
                message="Canonical interaction command is invalid",
            )
            dispatch_call = cast(Callable[..., Awaitable[object]], dispatch)
            return await _invoke_async(
                dispatch_call,
                self._receiver_tab,
                action=action,
                targets=targets,
                dispatch_context=dispatch_context,
                command_payload=command_payload,
            )

        return dispatch_interaction

    async def scroll(
        self,
        *,
        target: TargetRef | None = None,
        direction: Literal["up", "down", "left", "right"] = "down",
        amount: Literal["line", "page", "start", "end"] = "page",
        expect: ActionExpectation | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Scroll the receiver or one explicit Runtime-issued target."""
        _require_choice(
            direction,
            {"up", "down", "left", "right"},
            "direction",
        )
        _require_choice(amount, {"line", "page", "start", "end"}, "amount")
        if target is not None:
            self._require_target(target)
        ordered_targets = () if target is None else (("target", target),)
        return await self._run_mutation(
            "tab.actions.scroll",
            ordered_targets=ordered_targets,
            arguments={"direction": direction, "amount": amount},
            expectation=expect,
            timeout_ms=timeout_ms,
            dispatcher=self._scroll_dispatcher(target),
        )

    def _scroll_dispatcher(self, target: TargetRef | None) -> Dispatch:
        async def dispatch_scroll(
            *,
            command: object,
            dispatch_context: object,
        ) -> object:
            dispatch = getattr(self._session, "dispatch_scroll", None)
            if not callable(dispatch):
                raise BrowserSDKError(
                    "Canonical scroll dispatcher is unavailable",
                    code="scroll_dispatcher_missing",
                )
            command_payload = _command_arguments(
                command,
                code="scroll_command_invalid",
                message="Canonical scroll command is invalid",
            )
            dispatch_call = cast(Callable[..., Awaitable[object]], dispatch)
            return await _invoke_async(
                dispatch_call,
                self._receiver_tab,
                target=target,
                dispatch_context=dispatch_context,
                command_payload=command_payload,
            )

        return dispatch_scroll

    async def fill(
        self,
        target: TargetRef,
        value: str,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Replace the complete value of one Runtime-issued target."""
        _require_string(value, "value")
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.fill",
            ordered_targets=(("target", target),),
            arguments={"value": value},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def type_text(
        self,
        target: TargetRef,
        text: str,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Append browser input events to one Runtime-issued target."""
        _require_string(text, "text")
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.type_text",
            ordered_targets=(("target", target),),
            arguments={"text": text},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def press_key(
        self,
        target: TargetRef,
        key: str,
        *,
        modifiers: tuple[Literal["shift"], ...] = (),
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Press one closed key value on an explicit target."""
        _require_key(key)
        _require_modifiers(modifiers, allowed={"shift"})
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.press_key",
            ordered_targets=(("target", target),),
            arguments={"key": key, "modifiers": modifiers},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def set_checked(
        self,
        target: TargetRef,
        checked: bool,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Ensure one target has the exact checked state."""
        if not isinstance(checked, bool):
            raise TypeError("checked must be a bool")
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.set_checked",
            ordered_targets=(("target", target),),
            arguments={"checked": checked},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def select_option(
        self,
        target: TargetRef,
        option: OptionChoice,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Select one exact option choice on a Runtime-issued target."""
        if not isinstance(option, OptionChoice):
            raise TypeError("option must be an OptionChoice")
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.select_option",
            ordered_targets=(("target", target),),
            arguments={"option": option},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
        )

    async def upload_file(
        self,
        target: TargetRef,
        resources: ResourceHandle | Sequence[ResourceHandle],
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Select an exact ordered group of current owner resources."""
        self._require_target(target)
        if self._resources is None:
            raise BrowserSDKError(
                "Canonical ResourceStore is unavailable",
                code="resource_store_unavailable",
            )
        requested: tuple[ResourceHandle, ...]
        if isinstance(resources, ResourceHandle):
            requested = (resources,)
        elif isinstance(resources, Sequence) and not isinstance(
            resources,
            (str, bytes, bytearray),
        ):
            requested = tuple(resources)
        else:
            raise TypeError("resources must contain ResourceHandle values")
        if not requested:
            raise ValueError("at least one upload resource is required")
        if not all(isinstance(item, ResourceHandle) for item in requested):
            raise TypeError("resources must contain ResourceHandle values")
        resource_ids = tuple(str(item.id) for item in requested)
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("duplicate upload resource id")
        validated = tuple(
            self._resources.require(resource_id)
            for resource_id in resource_ids
        )
        return await self._run_mutation(
            "tab.actions.upload_file",
            ordered_targets=(("target", target),),
            arguments={"resources": validated},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
            dispatcher=self._upload_dispatcher(
                target=target,
                resources=validated,
            ),
        )

    def _upload_dispatcher(
        self,
        *,
        target: TargetRef,
        resources: tuple[ResourceHandle, ...],
    ) -> Dispatch:
        async def dispatch_upload(
            *,
            command: object,
            dispatch_context: object,
        ) -> object:
            if self._resources is None:
                raise BrowserSDKError(
                    "Canonical ResourceStore is unavailable",
                    code="resource_store_unavailable",
                )
            upload = getattr(self._session, "upload_resources", None)
            if not callable(upload):
                raise BrowserSDKError(
                    "Canonical upload dispatcher is unavailable",
                    code="upload_dispatcher_missing",
                )
            upload_call = cast(Callable[..., Awaitable[object]], upload)
            command_payload = _command_arguments(
                command,
                code="upload_command_invalid",
                message="Canonical upload command payload is invalid",
            )
            private_paths = self._resources.resolve_upload_paths(resources)
            return await _invoke_async(
                upload_call,
                self._receiver_tab,
                target,
                resource_ids=tuple(str(handle.id) for handle in resources),
                private_paths=private_paths,
                dispatch_context=dispatch_context,
                command_payload=command_payload,
            )

        return dispatch_upload

    async def download_file(
        self,
        target: TargetRef,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Download once from one exact target into ResourceStore."""
        self._require_target(target)
        return await self._run_mutation(
            "tab.actions.download_file",
            ordered_targets=(("target", target),),
            arguments={},
            expectation=expect,
            state=state,
            timeout_ms=timeout_ms,
            dispatcher=self._download_dispatcher(target),
        )

    async def paste(
        self,
        target: TargetRef,
        content: str,
        *,
        expect: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Insert bounded caller-provided content into one exact target."""
        self._require_target(target)
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        if not content:
            raise ValueError("content must not be empty")
        if len(content) > self._max_paste_chars:
            raise ValueError("content exceeds the paste limit")
        expectation = expect or ActionExpectation.final(
            BrowserCondition.all(TargetCondition.value(target, content)),
        )
        return await self._run_mutation(
            "tab.actions.paste",
            ordered_targets=(("target", target),),
            arguments={"content": content},
            expectation=expectation,
            state=state,
            timeout_ms=timeout_ms,
            dispatcher=self._paste_dispatcher(target, content),
        )

    def _paste_dispatcher(self, target: TargetRef, content: str) -> Dispatch:
        async def dispatch_paste(
            *,
            command: object,
            dispatch_context: object,
        ) -> object:
            paste = getattr(self._session, "paste_controlled", None)
            if not callable(paste):
                raise BrowserSDKError(
                    "Canonical paste dispatcher is unavailable",
                    code="paste_dispatcher_missing",
                )
            paste_call = cast(Callable[..., Awaitable[object]], paste)
            command_payload = _command_arguments(
                command,
                code="paste_command_invalid",
                message="Canonical paste command payload is invalid",
            )
            return await _invoke_async(
                paste_call,
                self._receiver_tab,
                target,
                content=content,
                dispatch_context=dispatch_context,
                command_payload=command_payload,
            )

        return dispatch_paste

    async def respond_prompt(
        self,
        prompt: BrowserPrompt,
        decision: Literal["accept", "dismiss", "allow", "deny"],
        *,
        text: str | None = None,
        timeout_ms: int | None = None,
    ) -> ActionResult:
        """Continue one exact prompt under its parent PendingAction."""
        if not isinstance(prompt, BrowserPrompt):
            raise TypeError("prompt must be a Runtime-issued BrowserPrompt")
        if decision not in {"accept", "dismiss", "allow", "deny"}:
            raise ValueError("invalid prompt decision")
        _deadline(timeout_ms)
        if self._action_runner is None or self._owner_binding is None:
            raise BrowserSDKError(
                "Canonical ActionRunner is unavailable",
                code="action_runner_missing",
                action="tab.actions.respond_prompt",
            )
        dispatcher = getattr(self.dispatch, "respond_prompt", None)
        if dispatcher is None and callable(self.dispatch):
            dispatcher = self.dispatch
        result = await self._action_runner.continue_prompt(
            binding=self._owner_binding,
            prompt=prompt,
            decision=decision,
            text=text,
            dispatcher=dispatcher,
        )
        if result.status not in {"BLOCKED", "CANCELLED"}:
            if self._invalidate_observation is not None:
                self._invalidate_observation()
        return result

    async def _run_mutation(
        self,
        api_id: str,
        *,
        ordered_targets: tuple[tuple[str, TargetRef], ...],
        arguments: dict[str, object],
        expectation: ActionExpectation | None = None,
        state: StateRequirement | None = None,
        timeout_ms: int | None = None,
        dispatcher: Dispatch | None = None,
    ) -> ActionResult:
        if self._action_runner is None:
            raise BrowserSDKError(
                "Canonical ActionRunner is unavailable",
                code="action_runner_missing",
                action=api_id,
            )
        result = await self._action_runner.run(
            binding=cast(BrowserRequestBinding, self._owner_binding),
            receiver_tab=self._receiver_summary,
            contract=canonical_mutation_contract(api_id),
            ordered_targets=ordered_targets,
            arguments=arguments,
            expectation=expectation,
            state=state,
            deadline=_deadline(timeout_ms),
            dispatcher=dispatcher,
            condition_evaluator=self._condition_evaluator,
            condition_receiver=self._condition_receiver,
            condition_probe=(
                self._session.condition_probe(self._receiver_tab)
                if self._condition_evaluator is not None
                and self._condition_receiver is not None
                and callable(getattr(self._session, "condition_probe", None))
                else None
            ),
        )
        typed = cast(ActionResult, result)
        if typed.status not in {"BLOCKED", "CANCELLED"}:
            if self._invalidate_observation is not None:
                self._invalidate_observation()
        record_browser_result(typed)
        return typed

    def _require_target(self, target: TargetRef) -> None:
        if not isinstance(target, TargetRef):
            raise BrowserSDKError(
                "Canonical mutation target must be a TargetRef.",
                code="target_invalid",
                action="tab.actions",
            )
        if (
            self._target_registry is None
            or self._owner_binding is None
            or not self._receiver_tab
        ):
            raise BrowserSDKError(
                "runtime_issued_value: target authority is unavailable",
                code="runtime_issued_value",
                action="tab.actions",
            )
        self._target_registry.resolve_target(
            target,
            receiver_tab=self._receiver_tab,
            owner=self._owner_binding,
        )


@dataclass(slots=True)
class Tab:
    """Canonical tab shell owned by this module."""

    id: str
    actions: TabActions = field(default_factory=TabActions)
    _session: Any = field(default=None, repr=False)
    _resources: ResourceStore | None = field(default=None, repr=False)
    _observations: ObservationStore | None = field(default=None, repr=False)
    _condition_evaluator: ConditionEvaluator | Any = field(
        default=None,
        repr=False,
    )
    _profile: BackendProfile | None = field(default=None, repr=False)
    _target_registry: BrowserSessionOwnerRegistry | None = field(
        default=None,
        repr=False,
    )
    _owner_binding: BrowserRequestBinding | None = field(
        default=None,
        repr=False,
    )
    _target_facts: tuple[TargetFacts, ...] = field(
        default=(),
        repr=False,
    )
    _tab_summary: TabSummary | None = field(default=None, repr=False)
    _action_runner: ActionRunner | Any | None = field(
        default=None,
        repr=False,
    )
    _observation_generation: int = field(default=0, repr=False)
    _snapshot_continuations: dict[str, _SourceContinuation] = field(
        default_factory=dict,
        repr=False,
    )
    _read_continuations: dict[str, _SourceContinuation] = field(
        default_factory=dict,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self._observations is not None:
            self._observation_generation = self._observations.generation
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        """Bind actions to the latest owner-scoped observation state."""
        condition_receiver = None
        if self._observations is not None and self._resources is not None:
            condition_receiver = ConditionReceiver(
                owner_key=self._observations.owner_key,
                root_session_id=self._observations.root_session_id,
                tab_id=self.id,
                context=self._observations.context,
                generation=self._observations.generation,
                observation_store=self._observations,
                resource_store=self._resources,
                target_registry=self._target_registry,
                owner_binding=self._owner_binding,
                target_facts=self._target_facts,
            )
        self.actions = TabActions(
            dispatch=self.actions.dispatch,
            _target_registry=self._target_registry,
            _owner_binding=self._owner_binding,
            _receiver_tab=self.id,
            _receiver_summary=self._tab_summary,
            _action_runner=self._action_runner,
            _resources=self._resources,
            _session=self._session,
            _condition_evaluator=self._condition_evaluator,
            _condition_receiver=condition_receiver,
            _invalidate_observation=self._invalidate_observation,
            _max_paste_chars=int(
                (self._profile.hard_limits if self._profile else {}).get(
                    "max_paste_chars",
                    100_000,
                ),
            ),
        )

    def _replace_observation_store(self, capture: SnapshotCapture) -> None:
        if self._owner_binding is None:
            raise _capability_blocked("tab.snapshot")
        cleanup_observation_tab(self._owner_binding.owner_key, self.id)
        self._clear_source_continuations()
        self._target_facts = ()
        self._observation_generation += 1
        self._observations = ObservationStore(
            owner_key=self._owner_binding.owner_key,
            root_session_id=self._owner_binding.root_session_id,
            tab_id=self.id,
            context=capture.context,
            generation=self._observation_generation,
        )
        self._refresh_actions()

    def _invalidate_observation(self) -> None:
        """Revoke values captured before an action may have changed the page."""
        self._clear_source_continuations()
        if self._owner_binding is not None and self._target_registry is not None:
            self._target_registry.invalidate_tab_observation(
                self._owner_binding,
                receiver_tab=self.id,
            )
        elif self._observations is not None:
            cleanup_observation_tab(self._observations.owner_key, self.id)
        self._observations = None
        self._target_facts = ()
        self._refresh_actions()

    def _clear_source_continuations(self) -> None:
        """Forget public cursors when their observation chain is revoked."""
        self._snapshot_continuations.clear()
        self._read_continuations.clear()

    async def _capture_source_page(
        self,
        tab_id: str,
        *,
        limit: int,
        query: TargetQuery | None,
        cursor: str | None,
        region_owner_chain: tuple[str, ...],
        visual_scope: VisualRegion | None = None,
    ) -> SourceTraversalCapture:
        """Invoke the only canonical source-owned observation page path."""
        if visual_scope is not None:
            capture_visual_page = getattr(
                self._session,
                "capture_visual_source_page",
                None,
            )
            if callable(capture_visual_page):
                capture = await capture_visual_page(  # pylint: disable=not-callable
                    tab_id,
                    scope=visual_scope,
                    limit=limit,
                    query=query,
                    cursor=cursor,
                    region_owner_chain=region_owner_chain,
                )
                if not isinstance(capture, SourceTraversalCapture):
                    raise BrowserSDKGap(
                        "Canonical visual source traversal returned invalid "
                        "evidence.",
                        action="tab.snapshot.visual_region",
                    )
                return capture
        capture_page = getattr(self._session, "capture_source_page", None)
        if not callable(capture_page):
            raise _capability_blocked("tab.snapshot.source_continuation")
        capture = await capture_page(  # pylint: disable=not-callable
            tab_id,
            limit=limit,
            query=query,
            cursor=cursor,
            region_owner_chain=region_owner_chain,
        )
        if not isinstance(capture, SourceTraversalCapture):
            raise BrowserSDKGap(
                "Canonical source traversal returned invalid evidence.",
                action="tab.snapshot",
            )
        return capture

    def _source_owner_chain(
        self,
        scope: ObservationScope,
        query: TargetQuery | None,
    ) -> tuple[str, ...]:
        """Resolve the one narrowest region chain before starting a cursor."""
        if self._observations is None:
            if not isinstance(scope, CurrentSurface) or (
                query is not None and query.region is not None
            ):
                raise _capability_blocked("tab.snapshot")
            return ()
        scope_chain = _scope_owner_chain(self._observations, scope) or ()
        query_chain = (
            _region_owner_chain(self._observations, query.region)
            if query is not None and query.region is not None
            else ()
        )
        if not scope_chain:
            return query_chain
        if not query_chain:
            return scope_chain
        if query_chain[: len(scope_chain)] == scope_chain:
            return query_chain
        if scope_chain[: len(query_chain)] == query_chain:
            return scope_chain
        raise ObservationStoreError("query_scope_mismatch")

    def _require_source_continuation(
        self,
        cursor: object,
        *,
        kind: Literal["SNAPSHOT", "READ"],
    ) -> _SourceContinuation:
        expected = SnapshotCursor if kind == "SNAPSHOT" else ReadCursor
        if not isinstance(cursor, expected):
            raise ObservationStoreError("cursor_invalid")
        cursor_id = str(cursor.to_dict().get("id") or "")
        records = (
            self._snapshot_continuations
            if kind == "SNAPSHOT"
            else self._read_continuations
        )
        continuation = records.get(cursor_id)
        if continuation is None:
            raise ObservationStoreError("cursor_invalid")
        if self._observations is None:
            raise ObservationStoreError("cursor_generation_mismatch")
        if (
            continuation.context is not self._observations.context
            or continuation.generation != self._observations.generation
        ):
            raise ObservationStoreError("cursor_generation_mismatch")
        return continuation

    def _consume_source_continuation(
        self,
        cursor: object,
        *,
        kind: Literal["SNAPSHOT", "READ"],
    ) -> None:
        cursor_id = str(getattr(cursor, "to_dict")().get("id") or "")
        records = (
            self._snapshot_continuations
            if kind == "SNAPSHOT"
            else self._read_continuations
        )
        records.pop(cursor_id, None)

    def _issue_source_continuation(
        self,
        *,
        kind: Literal["SNAPSHOT", "READ"],
        source: SourceTraversalCapture,
        scope: ObservationScope,
        query: TargetQuery | None,
        region_owner_chain: tuple[str, ...],
        visual: bool = False,
        visual_witnesses: tuple[SnapshotTarget, ...] = (),
    ) -> SnapshotCursor | ReadCursor | None:
        if source.end_of_collection:
            return None
        assert source.cursor is not None
        assert self._observations is not None
        cursor_type = SnapshotCursor if kind == "SNAPSHOT" else ReadCursor
        issued = _issue_opaque_value(
            cursor_type,
            _RUNTIME_VALUE_ISSUER,
            id=f"{kind.lower()}-cursor-{uuid4().hex}",
        )
        cursor_id = str(issued.to_dict().get("id") or "")
        record = _SourceContinuation(
            bridge_cursor=source.cursor,
            scope=scope,
            query=query,
            region_owner_chain=region_owner_chain,
            context=self._observations.context,
            generation=self._observations.generation,
            visual=visual,
            visual_witnesses=visual_witnesses,
        )
        records = (
            self._snapshot_continuations
            if kind == "SNAPSHOT"
            else self._read_continuations
        )
        records[cursor_id] = record
        return cast(SnapshotCursor | ReadCursor, issued)

    def _source_context_is_current(
        self,
        continuation: _SourceContinuation,
        capture: SnapshotCapture,
    ) -> bool:
        return (
            self._observations is not None
            and continuation.context is self._observations.context
            and continuation.generation == self._observations.generation
            and capture.context is self._observations.context
        )

    def _stale_snapshot_result(
        self,
        scope: ObservationScope,
        capture: SnapshotCapture,
    ) -> SnapshotResult:
        status, retry, problem = _snapshot_terminal("STALE")
        return _record_snapshot_result(
            SnapshotResult(
                operation_id=issue_operation_id(),
                status=status,
                retry=retry,
                problem=problem,
                model_text=_snapshot_model_text(
                    status=status,
                    coverage="STALE",
                    gaps=capture.gaps,
                    targets=(),
                ),
                end_of_collection=True,
                source_summary=",".join(
                    f"{item.source}:{'ok' if item.available else 'unavailable'}"
                    for item in capture.sources
                ),
            ),
        )

    async def close(self) -> ActionResult:
        """Route explicit close through the sole ActionRunner."""
        if not isinstance(self._tab_summary, TabSummary):
            raise BrowserSDKError(
                "tab.close requires an owner-bound receiver summary",
                code="runtime_issued_value",
            )
        expectation = ActionExpectation.transition(
            BrowserCondition.all(
                SurfaceCondition.tab_closed(self._tab_summary),
            ),
        )
        result = await self._run_mutation(
            "tab.close",
            expectation=expectation,
        )
        typed = cast(ActionResult, result)
        if typed.status not in {"BLOCKED", "CANCELLED"}:
            self._invalidate_observation()
            if (
                typed.status == "SUCCEEDED"
                and self._target_registry is not None
                and self._owner_binding is not None
            ):
                self._target_registry.prove_tab_closed(
                    self._owner_binding,
                    self._tab_summary,
                )
        return typed

    async def current_prompt(self) -> BrowserPrompt | None:
        """Return the exact non-mutating prompt waiting on this tab."""
        if (
            self._target_registry is None
            or self._owner_binding is None
            or not isinstance(self._tab_summary, TabSummary)
        ):
            raise BrowserSDKError(
                "current_prompt requires owner-bound tab authority",
                code="browser_ownership_context_missing",
            )
        current = self._target_registry.current_browser_prompt(
            self._owner_binding,
            tab=self._tab_summary,
        )
        if current is not None:
            return current
        capture = getattr(self._session, "current_prompt", None)
        if callable(capture):
            capture_prompt = cast(
                Callable[[TabSummary], Awaitable[BrowserPrompt | None]],
                capture,
            )
            # pylint: disable-next=not-callable
            captured = await capture_prompt(self._tab_summary)
            if captured is not None and not isinstance(
                captured,
                BrowserPrompt,
            ):
                raise BrowserSDKError(
                    "backend returned an invalid BrowserPrompt",
                    code="prompt_binding_invalid",
                )
            return cast(BrowserPrompt | None, captured)
        return None

    async def print_to_pdf(
        self,
        *,
        options: PagePdfOptions | None = None,
    ) -> PagePdfResult:
        """Capture one context-bound PDF through the sole ActionRunner."""
        if options is not None and not isinstance(options, PagePdfOptions):
            raise TypeError("options must be PagePdfOptions or None")
        result = await self._run_mutation(
            "tab.print_to_pdf",
            arguments={"options": options},
            dispatcher=self._pdf_dispatcher(options or PagePdfOptions()),
        )
        typed = cast(PagePdfResult, result)
        if typed.status in {"SUCCEEDED", "PARTIAL"}:
            resource = typed.resource
            assert resource is not None
            if self._resources is None:
                typed = replace(
                    typed,
                    status="FAILED",
                    retry="FORBIDDEN",
                    problem=Problem(
                        code="artifact_promotion_failed",
                        phase="TRANSPORT",
                        safe_message=(
                            "Required PDF artifact storage is unavailable."
                        ),
                    ),
                )
            else:
                try:
                    await self._resources.promote_required((resource,))
                except ResourceStoreError:
                    typed = replace(
                        typed,
                        status="FAILED",
                        retry="FORBIDDEN",
                        problem=Problem(
                            code="artifact_promotion_failed",
                            phase="TRANSPORT",
                            safe_message=(
                                "Required PDF artifact promotion failed."
                            ),
                        ),
                    )
        required_blocks = (
            (
                RequiredBlock(
                    kind="artifact",
                    resource_id=str(typed.resource.id),
                    media_type=str(typed.resource.media_type),
                    payload=typed.resource,
                ),
            )
            if typed.status in {"SUCCEEDED", "PARTIAL"}
            and typed.resource is not None
            else ()
        )
        record_browser_result(typed, required_blocks=required_blocks)
        return typed

    def _pdf_dispatcher(self, options: PagePdfOptions) -> Dispatch:
        async def dispatch_pdf(
            *,
            command: object,
            dispatch_context: object,
        ) -> object:
            if self._resources is None:
                raise BrowserSDKError(
                    "Canonical ResourceStore is unavailable",
                    code="resource_store_unavailable",
                )
            capture_pdf = getattr(self._session, "print_to_pdf_resource", None)
            if not callable(capture_pdf):
                raise BrowserSDKError(
                    "Canonical page PDF dispatcher is unavailable",
                    code="page_pdf_dispatcher_missing",
                )
            capture_pdf_call = cast(
                Callable[..., Awaitable[object]],
                capture_pdf,
            )
            raw_command_payload = getattr(command, "_payload", None)
            operation = _resource_operation_from_payload(raw_command_payload)
            if getattr(command, "command_id", "") != operation.command_id:
                raise BrowserSDKError(
                    "Canonical page PDF command identity is invalid",
                    code="page_pdf_command_invalid",
                )
            command_payload = _command_arguments(
                command,
                code="page_pdf_command_invalid",
                message="Canonical page PDF command is invalid",
            )
            capture = await _invoke_async(
                capture_pdf_call,
                self.id,
                options=options,
                context_before=(
                    self._observations.context
                    if self._observations is not None
                    else None
                ),
                operation=operation,
                dispatch_context=dispatch_context,
                command_payload=command_payload,
            )
            if not isinstance(capture, PagePdfCapture):
                raise BrowserSDKError(
                    "Canonical page PDF capture is invalid",
                    code="page_pdf_capture_invalid",
                )
            handle = await self._resources.ingest_correlated_page_pdf(
                capture,
                operation,
            )
            return {
                "page_pdf": {
                    "resource": handle,
                    "context_before": capture.context_before,
                    "context_after": capture.context_after,
                },
            }

        return dispatch_pdf

    async def _run_mutation(
        self,
        api_id: str,
        *,
        arguments: dict[str, object] | None = None,
        expectation: ActionExpectation | None = None,
        dispatcher: Dispatch | None = None,
    ) -> ActionResult | PagePdfResult:
        if self._action_runner is None:
            raise BrowserSDKError(
                "Canonical ActionRunner is unavailable",
                code="action_runner_missing",
                action=api_id,
            )
        receiver = self._condition_receiver_for_action()
        result = await self._action_runner.run(
            binding=cast(BrowserRequestBinding, self._owner_binding),
            receiver_tab=self._tab_summary,
            contract=canonical_mutation_contract(api_id),
            ordered_targets=(),
            arguments=arguments or {},
            expectation=expectation,
            state=None,
            deadline=None,
            dispatcher=dispatcher,
            condition_evaluator=self._condition_evaluator,
            condition_receiver=receiver,
            condition_probe=(
                self._session.condition_probe(self.id)
                if receiver is not None
                and self._condition_evaluator is not None
                and callable(getattr(self._session, "condition_probe", None))
                else None
            ),
        )
        return result

    def _condition_receiver_for_action(self) -> ConditionReceiver | None:
        if self._observations is None or self._resources is None:
            return None
        return ConditionReceiver(
            owner_key=self._observations.owner_key,
            root_session_id=self._observations.root_session_id,
            tab_id=self.id,
            context=self._observations.context,
            generation=self._observations.generation,
            observation_store=self._observations,
            resource_store=self._resources,
            target_registry=self._target_registry,
            owner_binding=self._owner_binding,
            target_facts=self._target_facts,
        )

    async def wait_for(
        self,
        condition: BrowserCondition,
        *,
        timeout_ms: int,
        stable_ms: int = 0,
    ) -> WaitResult:
        """Wait for one bounded flat typed condition on this Tab receiver."""
        preflight = _wait_preflight(
            condition,
            timeout_ms=timeout_ms,
            stable_ms=stable_ms,
            profile=self._profile,
        )
        if preflight is not None:
            return _record_wait_result(preflight)
        if self._observations is None:
            raise _capability_blocked("tab.wait_for")
        unsupported = tuple(
            atom
            for atom in condition.atoms
            if isinstance(atom, SurfaceCondition)
        )
        if unsupported:
            observation = self._observations.issue_evidence(
                kind="SNAPSHOT",
                scope=CurrentSurface(),
                coverage="UNAVAILABLE",
                gaps=(),
            )
            return _record_wait_result(
                WaitResult(
                    operation_id=issue_operation_id(),
                    status="BLOCKED",
                    retry="AFTER_OBSERVATION",
                    problem=Problem(
                        code="capability_unavailable",
                        phase="PREFLIGHT",
                        safe_message=(
                            "One or more condition families are not active."
                        ),
                        details=CapabilityProblemDetails(
                            capability="tab.wait_for.condition_family",
                        ),
                    ),
                    evidence=observation.ref,
                    outcome="UNAVAILABLE",
                    last_observed=observation.context,
                ),
            )
        if self._session is None or self._condition_evaluator is None:
            raise _capability_blocked("tab.wait_for")
        probe = self._session.condition_probe(self.id)
        receiver = ConditionReceiver(
            owner_key=self._observations.owner_key,
            root_session_id=self._observations.root_session_id,
            tab_id=self.id,
            context=self._observations.context,
            generation=self._observations.generation,
            observation_store=self._observations,
            resource_store=self._resources,
            target_registry=self._target_registry,
            owner_binding=self._owner_binding,
            target_facts=self._target_facts,
        )
        armed = None
        has_resource_atom = any(
            isinstance(atom, ResourceCondition) for atom in condition.atoms
        )
        if has_resource_atom:
            armed = await self._condition_evaluator.arm(
                receiver,
                condition,
                probe=probe,
                baseline=None,
            )
        evaluation = await self._condition_evaluator.evaluate(
            receiver,
            condition,
            probe=probe,
            timeout_ms=timeout_ms,
            stable_ms=stable_ms,
            baseline=None,
            armed=armed,
        )
        if not isinstance(evaluation, ConditionEvaluation):
            raise BrowserSDKGap(
                "Condition evaluator returned invalid terminal facts.",
                action="tab.wait_for",
            )
        return _record_wait_result(_wait_result(evaluation))

    async def snapshot(
        self,
        *,
        scope: ObservationScope | None = None,
        query: TargetQuery | None = None,
        cursor: SnapshotCursor | None = None,
        limit: int,
    ) -> SnapshotResult:
        """Capture one caller-sized source page for this Tab receiver."""
        _snapshot_limit(limit)
        continuation: _SourceContinuation | None = None
        if cursor is not None:
            continuation = self._require_source_continuation(
                cursor,
                kind="SNAPSHOT",
            )
            if scope is not None:
                raise ObservationStoreError("cursor_scope_mismatch")
            if query is not None:
                raise ObservationStoreError("cursor_query_mismatch")
            if continuation.visual:
                return await self._snapshot_visual_region(
                    cast(VisualRegion, continuation.scope),
                    limit=limit,
                    continuation=continuation,
                    cursor=cursor,
                    query=continuation.query,
                )
            requested_scope = continuation.scope
            requested_query = continuation.query
            owner_chain = continuation.region_owner_chain
        else:
            requested_scope = scope or CurrentSurface()
            requested_query = query
            if isinstance(requested_scope, VisualRegion):
                return await self._snapshot_visual_region(
                    requested_scope,
                    limit=limit,
                    query=requested_query,
                )
            owner_chain = self._source_owner_chain(
                requested_scope,
                requested_query,
            )
        if self._session is None:
            raise _capability_blocked("tab.snapshot")
        if continuation is None and self._observations is None and (
            not isinstance(requested_scope, CurrentSurface)
            or (
                requested_query is not None
                and requested_query.region is not None
            )
        ):
            raise _capability_blocked("tab.snapshot")
        if continuation is None and self._observations is not None:
            self._invalidate_observation()
        capture = await self._capture_source_page(
            self.id,
            limit=limit,
            query=requested_query if continuation is None else None,
            cursor=(continuation.bridge_cursor if continuation else None),
            region_owner_chain=owner_chain,
        )
        if continuation is not None:
            self._consume_source_continuation(cursor, kind="SNAPSHOT")
        source_capture = capture.capture
        if continuation is None:
            self._replace_observation_store(source_capture)
        elif not self._source_context_is_current(continuation, source_capture):
            return self._stale_snapshot_result(requested_scope, source_capture)
        assert self._observations is not None
        candidates = tuple(source_capture.targets)
        coverage = source_capture.coverage
        gaps = source_capture.gaps
        observation = self._observations.issue_evidence(
            kind="SNAPSHOT",
            scope=requested_scope,
            coverage=coverage,
            gaps=gaps,
        )
        target_summaries = tuple(
            _target_summary(target, index)
            for index, target in enumerate(candidates, start=1)
        )
        self._target_facts = tuple(
            TargetFacts(
                ref=summary.ref,
                role=summary.role,
                name=summary.name,
                text=summary.name,
                states=summary.states,
                checked=(True if "checked" in summary.states else None),
            )
            for summary in target_summaries
        )
        self._refresh_actions()
        region_summaries = tuple(
            _region_summary(self._observations, region)
            for region in source_capture.regions
        )
        register_baseline = getattr(
            self._session,
            "_register_condition_region_baseline",
            None,
        )
        if callable(register_baseline):
            register = cast(Callable[[Any, Any, str], None], register_baseline)
            for captured_region, summary in zip(
                source_capture.regions,
                region_summaries,
                strict=True,
            ):
                text = normalize_visible_text(
                    " ".join(
                        target.name
                        for target in source_capture.targets
                        if tuple(target.owner_chain)
                        == tuple(captured_region.owner_chain)
                    ),
                )
                # pylint: disable-next=not-callable
                register(
                    summary.ref,
                    observation.ref,
                    sha256(text.encode()).hexdigest(),
                )
        status, retry, problem = _snapshot_terminal(coverage)
        next_cursor = self._issue_source_continuation(
            kind="SNAPSHOT",
            source=capture,
            scope=requested_scope,
            query=requested_query,
            region_owner_chain=owner_chain,
        )
        result = SnapshotResult(
            operation_id=issue_operation_id(),
            status=status,
            retry=retry,
            problem=problem,
            evidence=observation.ref,
            observation=observation,
            model_text=_snapshot_model_text(
                status=status,
                coverage=coverage,
                gaps=gaps,
                targets=target_summaries,
            ),
            targets=target_summaries,
            regions=region_summaries,
            grounding=None,
            next_cursor=cast(SnapshotCursor | None, next_cursor),
            end_of_collection=capture.end_of_collection,
            source_summary=",".join(
                f"{item.source}:{'ok' if item.available else 'unavailable'}"
                for item in source_capture.sources
            ),
        )
        return _record_snapshot_result(result)

    async def _snapshot_visual_region(
        self,
        scope: VisualRegion,
        *,
        limit: int,
        continuation: _SourceContinuation | None = None,
        cursor: SnapshotCursor | None = None,
        query: TargetQuery | None = None,
    ) -> SnapshotResult:
        """Ground a viewport region only after its source walk is complete."""
        if (
            self._session is None
            or self._observations is None
            or self._target_registry is None
            or self._owner_binding is None
        ):
            raise _capability_blocked("tab.snapshot.visual_region")
        try:
            visual_binding = self._target_registry.resolve_visual_context(
                scope.visual_context,
                owner=self._owner_binding,
                receiver_tab=self.id,
            )
        except BrowserSDKError:
            return self._visual_grounding_result(
                scope,
                coverage="STALE",
                targets=(),
                sources="visual-binding:stale",
            )
        if (
            not visual_binding.actionable
            or visual_binding.context is not self._observations.context
        ):
            return self._visual_grounding_result(
                scope,
                coverage="STALE",
                targets=(),
                sources="visual-binding:stale",
            )
        source = await self._capture_source_page(
            self.id,
            limit=limit,
            query=query,
            cursor=(continuation.bridge_cursor if continuation else None),
            region_owner_chain=self._source_owner_chain(scope, query),
            visual_scope=scope,
        )
        if continuation is not None:
            assert cursor is not None
            self._consume_source_continuation(cursor, kind="SNAPSHOT")
            if not self._source_context_is_current(
                continuation,
                source.capture,
            ):
                return self._visual_grounding_result(
                    scope,
                    coverage="STALE",
                    targets=(),
                    sources="visual-binding:stale",
                )
        capture = source.capture
        if capture.coverage in {"STALE", "UNAVAILABLE"}:
            return self._visual_grounding_result(
                scope,
                coverage=capture.coverage,
                targets=(),
                gaps=capture.gaps,
                sources=",".join(
                    f"{item.source}:{'ok' if item.available else 'unavailable'}"
                    for item in capture.sources
                ),
            )
        if capture.coverage == "PARTIAL":
            next_cursor = self._issue_source_continuation(
                kind="SNAPSHOT",
                source=source,
                scope=scope,
                query=query,
                region_owner_chain=self._source_owner_chain(scope, query),
                visual=True,
                visual_witnesses=(
                    continuation.visual_witnesses if continuation else ()
                ),
            )
            return self._visual_grounding_result(
                scope,
                coverage="PARTIAL",
                targets=(),
                gaps=capture.gaps,
                sources=",".join(
                    f"{item.source}:{'ok' if item.available else 'unavailable'}"
                    for item in capture.sources
                ),
                next_cursor=cast(SnapshotCursor | None, next_cursor),
                end_of_collection=source.end_of_collection,
            )
        witnesses = tuple(
            (*((continuation.visual_witnesses) if continuation else ()),
             *capture.targets)
        )
        # Exact-versus-multiple only needs two witnesses, never a full cache.
        witnesses = witnesses[:2]
        next_cursor = self._issue_source_continuation(
            kind="SNAPSHOT",
            source=source,
            scope=scope,
            query=query,
            region_owner_chain=self._source_owner_chain(scope, query),
            visual=True,
            visual_witnesses=witnesses,
        )
        return self._visual_grounding_result(
            scope,
            coverage="COMPLETE",
            targets=(
                tuple(capture.targets)
                if not source.end_of_collection
                else witnesses[:limit]
            ),
            regions=tuple(capture.regions),
            gaps=tuple(capture.gaps),
            sources=",".join(
                f"{item.source}:{'ok' if item.available else 'unavailable'}"
                for item in capture.sources
            ),
            next_cursor=cast(SnapshotCursor | None, next_cursor),
            end_of_collection=source.end_of_collection,
            grounding=(
                Grounding.MULTIPLE
                if source.end_of_collection and len(witnesses) > 1
                else None
            ),
        )

    def _visual_grounding_result(
        self,
        scope: VisualRegion,
        *,
        coverage: Coverage,
        targets: tuple[SnapshotTarget, ...],
        sources: str,
        regions: tuple[Any, ...] = (),
        gaps: tuple[CoverageGap, ...] = (),
        next_cursor: SnapshotCursor | None = None,
        end_of_collection: bool = True,
        grounding: Grounding | None = None,
    ) -> SnapshotResult:
        assert self._observations is not None
        grounding = grounding or (
            Grounding.STALE
            if coverage == "STALE"
            else (
                Grounding.UNAVAILABLE
                if coverage == "UNAVAILABLE"
                else (
                    Grounding.INCOMPLETE
                    if not end_of_collection
                    else (
                        Grounding.UNAVAILABLE
                        if coverage == "PARTIAL"
                        else (
                            Grounding.NO_MATCH
                            if not targets
                            else (
                                Grounding.EXACT
                                if len(targets) == 1
                                else Grounding.MULTIPLE
                            )
                        )
                    )
                )
            )
        )
        observation = self._observations.issue_evidence(
            kind="SNAPSHOT",
            scope=scope,
            coverage=coverage,
            gaps=gaps,
        )
        summaries = tuple(
            _target_summary(target, index)
            for index, target in enumerate(targets, start=1)
        )
        region_summaries = tuple(
            _region_summary(self._observations, region) for region in regions
        )
        status, retry, problem = _snapshot_terminal(coverage)
        return _record_snapshot_result(
            SnapshotResult(
                operation_id=issue_operation_id(),
                status=status,
                retry=retry,
                problem=problem,
                evidence=observation.ref,
                observation=observation,
                model_text=(
                    "\n".join(
                        (
                            f"grounding={grounding.value}; "
                            f"candidates={len(summaries)}",
                            _snapshot_model_text(
                                status=status,
                                coverage=coverage,
                                gaps=gaps,
                                targets=summaries,
                            ),
                        ),
                    )
                ),
                targets=summaries,
                regions=region_summaries,
                grounding=grounding,
                next_cursor=next_cursor,
                end_of_collection=end_of_collection,
                source_summary=sources,
            ),
        )

    async def read(
        self,
        *,
        scope: ObservationScope | None = None,
        cursor: ReadCursor | None = None,
        limit: int,
    ) -> ReadResult:
        """Read one caller-sized page from the current source."""
        _snapshot_limit(limit)
        if self._session is None:
            raise _capability_blocked("tab.read")
        continuation: _SourceContinuation | None = None
        if cursor is None:
            requested_scope = scope or CurrentSurface()
            if isinstance(requested_scope, VisualRegion):
                result = ReadResult(
                    operation_id=issue_operation_id(),
                    status="BLOCKED",
                    retry="AFTER_OBSERVATION",
                    problem=Problem(
                        code="capability_unavailable",
                        phase="PREFLIGHT",
                        safe_message=(
                            "VisualRegion read is not available in S2."
                        ),
                        details=CapabilityProblemDetails(
                            capability="tab.read.visual_region",
                        ),
                    ),
                )
                record_browser_result(result)
                return result
            owner_chain = self._source_owner_chain(requested_scope, None)
            if self._observations is not None:
                self._invalidate_observation()
        else:
            continuation = self._require_source_continuation(
                cursor,
                kind="READ",
            )
            if scope is not None:
                raise ObservationStoreError("cursor_scope_mismatch")
            requested_scope = continuation.scope
            owner_chain = continuation.region_owner_chain
        source = await self._capture_source_page(
            self.id,
            limit=limit,
            query=None,
            cursor=(continuation.bridge_cursor if continuation else None),
            region_owner_chain=owner_chain,
        )
        if continuation is not None:
            self._consume_source_continuation(cursor, kind="READ")
        capture = source.capture
        if continuation is None:
            self._replace_observation_store(capture)
        elif not self._source_context_is_current(continuation, capture):
            status, retry, problem = _read_terminal("STALE")
            result = ReadResult(
                operation_id=issue_operation_id(),
                status=status,
                retry=retry,
                problem=problem,
                model_text="status=BLOCKED coverage=STALE",
                end_of_collection=True,
            )
            record_browser_result(result)
            return result
        assert self._observations is not None
        observation = self._observations.issue_evidence(
            kind="READ",
            scope=requested_scope,
            coverage=capture.coverage,
            gaps=capture.gaps,
        )
        segments = tuple(
            _read_segment(target) for target in capture.targets
        )
        status, retry, problem = _read_terminal(capture.coverage)
        next_cursor = self._issue_source_continuation(
            kind="READ",
            source=source,
            scope=requested_scope,
            query=None,
            region_owner_chain=owner_chain,
        )
        result = ReadResult(
            operation_id=issue_operation_id(),
            status=status,
            retry=retry,
            problem=problem,
            evidence=observation.ref,
            observation=observation,
            model_text=_read_model_text(
                status=status,
                observation=observation,
                clamp_notice="",
                segments=segments,
                end_of_collection=source.end_of_collection,
            ),
            segments=segments,
            next_cursor=cast(ReadCursor | None, next_cursor),
            end_of_collection=source.end_of_collection,
        )
        record_browser_result(result)
        return result

    async def screenshot(
        self,
        *,
        scope: Literal["viewport", "full_page"] = "viewport",
    ) -> ScreenshotResult:
        """Capture one exact non-mutating image variant and ingest bytes."""
        if self._session is None or self._resources is None:
            raise _capability_blocked("tab.screenshot")
        if scope == "viewport" and self._observations is None:
            result = ScreenshotResult(
                operation_id=issue_operation_id(),
                status="BLOCKED",
                retry="AFTER_OBSERVATION",
                problem=Problem(
                    code="observation_required",
                    phase="PREFLIGHT",
                    safe_message=(
                        "Capture a fresh snapshot of this exact tab before "
                        "requesting a viewport screenshot."
                    ),
                ),
                scope=scope,
            )
            record_browser_result(result)
            return result
        if scope == "viewport" and (
            self._target_registry is None or self._owner_binding is None
        ):
            raise _capability_blocked(
                "tab.screenshot.viewport.visual_context",
            )
        captured = await self._session.screenshot_exact(self.id, scope=scope)
        if not isinstance(captured, ScreenshotCapture):
            raise BrowserSDKGap(
                "Screenshot producer returned an invalid exact capture.",
                action="tab.screenshot",
            )
        if not captured.complete or not captured.data:
            result = ScreenshotResult(
                operation_id=issue_operation_id(),
                status="FAILED",
                retry="SAFE",
                problem=Problem(
                    code="screenshot_incomplete",
                    phase="CAPTURE",
                    safe_message=(
                        "Screenshot capture did not return complete bytes."
                    ),
                ),
                scope=scope,
            )
            record_browser_result(result)
            return result
        handle = await self._resources.ingest_output(
            TrustedOutputSource.from_bytes(captured.data),
            media_type=captured.media_type,
            name=captured.name,
            required_delivery=True,
        )
        try:
            await self._resources.promote_required((handle,))
        except ResourceStoreError:
            result = ScreenshotResult(
                operation_id=issue_operation_id(),
                status="FAILED",
                retry="FORBIDDEN",
                problem=Problem(
                    code="artifact_promotion_failed",
                    phase="TRANSPORT",
                    safe_message=(
                        "Required screenshot image promotion failed."
                    ),
                ),
                scope=scope,
            )
            record_browser_result(result)
            return result
        invariant_gap = None
        if not captured.invariant_unchanged:
            invariant_gap = CoverageGap(
                stage="CAPTURE",
                detail=CaptureGap(
                    source="SCREENSHOT",
                    reason="INVARIANT_CHANGED",
                ),
            )
        observation = None
        if self._observations is not None:
            observation = self._observations.issue_evidence(
                kind="SCREENSHOT",
                scope=CurrentSurface(),
                coverage="PARTIAL" if invariant_gap else "COMPLETE",
                gaps=(invariant_gap,) if invariant_gap else (),
            )
            evidence: EvidenceRef = observation.ref
        else:
            issued_evidence = _issue_opaque_value(
                EvidenceRef,
                _RUNTIME_VALUE_ISSUER,
                id=f"evidence-{handle.id}",
            )
            assert isinstance(issued_evidence, EvidenceRef)
            evidence = issued_evidence
        visual_context: VisualContextRef | None = None
        if scope == "viewport":
            if (
                self._target_registry is not None
                and self._owner_binding is not None
                and self._observations is not None
            ):
                visual_context = self._target_registry.issue_visual_context(
                    self._owner_binding,
                    receiver_tab=self.id,
                    backend_id=str(
                        getattr(self._session, "backend_id", "canonical"),
                    ),
                    context=self._observations.context,
                    viewport=captured.before.viewport,
                    scroll=captured.before.scroll_offset,
                    zoom=captured.before.zoom,
                    device_pixel_ratio=(captured.before.device_pixel_ratio),
                    layout=captured.before.layout,
                    capture_epoch=captured.before.event_watermark,
                    image_sha256=str(handle.sha256),
                    resource_id=str(handle.id),
                    generation=captured.before.generation,
                    expires_at=0.0,
                    actionable=not bool(invariant_gap),
                )
        status: TerminalStatus = "PARTIAL" if invariant_gap else "SUCCEEDED"
        problem = (
            Problem(
                code="screenshot_invariant_changed",
                phase="VERIFY",
                safe_message=(
                    "Page state changed across screenshot capture; "
                    "image is partial evidence."
                ),
            )
            if invariant_gap
            else None
        )
        result = ScreenshotResult(
            operation_id=issue_operation_id(),
            status=status,
            retry="AFTER_OBSERVATION" if invariant_gap else "NONE",
            problem=problem,
            evidence=evidence,
            observation=observation,
            image=handle,
            visual_context=visual_context,
            scope=scope,
        )
        record_browser_result(
            result,
            required_blocks=(
                RequiredBlock(
                    kind="image",
                    resource_id=str(handle.id),
                    media_type=captured.media_type,
                    payload=handle,
                ),
            ),
        )
        return result


@dataclass(slots=True)
class BrowserTabs:
    """Canonical tab collection shell."""

    _session: Any = field(default=None, repr=False)
    _resources: ResourceStore | None = field(default=None, repr=False)
    _condition_evaluator: ConditionEvaluator | None = field(
        default=None,
        repr=False,
    )
    _profile: BackendProfile | None = field(default=None, repr=False)
    _target_registry: BrowserSessionOwnerRegistry | None = field(
        default=None,
        repr=False,
    )
    _owner_binding: BrowserRequestBinding | None = field(
        default=None,
        repr=False,
    )
    _selected: Tab | None = field(default=None, repr=False)
    _action_runner: ActionRunner | Any | None = field(
        default=None,
        repr=False,
    )
    _max_visible_tabs: int = field(default=64, repr=False)
    _max_task_created_tabs: int = field(default=16, repr=False)

    async def open(self, url: str) -> ActionResult:
        """Route create-and-navigate without changing selected Tab."""
        _require_safe_http_url(url)
        self._require_create_capacity()
        result = await self._run_mutation(
            "browser.tabs.open",
            arguments={"url": url},
            dispatcher=self._open_dispatcher(url),
        )
        record_browser_result(result)
        return result

    async def new(self) -> ActionResult:
        """Route blank task-tab creation without implicit selection."""
        self._require_create_capacity()
        return await self._run_mutation("browser.tabs.new", arguments={})

    async def list(self) -> list[TabSummary]:
        """Return a complete owner-bound visible set or a typed error."""
        if self._target_registry is None or self._owner_binding is None:
            raise BrowserSDKError(
                "Canonical tab registry is unavailable",
                code="browser_ownership_context_missing",
            )
        summaries = self._target_registry.list_tab_summaries(
            self._owner_binding,
            max_visible_tabs=self._max_visible_tabs,
        )
        record_browser_result(
            ActionResult(
                operation_id=issue_operation_id(),
                status="SUCCEEDED",
                retry="NONE",
                already_satisfied=True,
            ),
        )
        return summaries

    async def _run_mutation(
        self,
        api_id: str,
        *,
        arguments: dict[str, object],
        dispatcher: Dispatch | None = None,
    ) -> ActionResult:
        if self._action_runner is None:
            raise BrowserSDKError(
                "Canonical ActionRunner is unavailable",
                code="action_runner_missing",
                action=api_id,
            )
        result = await self._action_runner.run(
            binding=cast(BrowserRequestBinding, self._owner_binding),
            receiver_tab=None,
            contract=canonical_mutation_contract(api_id),
            ordered_targets=(),
            arguments=arguments,
            expectation=None,
            state=None,
            deadline=None,
            dispatcher=dispatcher,
        )
        return cast(ActionResult, result)

    def _open_dispatcher(self, url: str) -> Dispatch:
        async def dispatch_open(
            *,
            command: object,
            dispatch_context: object,
        ) -> object:
            del command, dispatch_context
            create_tab = getattr(self._session, "create_tab", None)
            if not callable(create_tab):
                raise BrowserSDKError(
                    "Canonical tab-create dispatcher is unavailable",
                    code="tab_create_dispatcher_missing",
                )
            created = await _invoke_async(create_tab, url)
            if not isinstance(created, Mapping):
                raise BrowserSDKError(
                    "Canonical tab-create dispatcher returned invalid data",
                    code="tab_create_result_invalid",
                )
            if (
                self._target_registry is None
                or self._owner_binding is None
            ):
                raise BrowserSDKError(
                    "Canonical tab registry is unavailable",
                    code="browser_ownership_context_missing",
                )
            tab_id = str(created.get("id") or "").strip()
            tab_url = str(created.get("url") or url).strip()
            parsed = urlsplit(tab_url)
            if not tab_id or parsed.scheme not in {"http", "https"}:
                raise BrowserSDKError(
                    "Canonical tab-create dispatcher returned invalid identity",
                    code="tab_create_result_invalid",
                )
            origin = f"{parsed.scheme}://{parsed.netloc}"
            summary = self._target_registry.issue_tab_summary(
                self._owner_binding,
                receiver_tab=tab_id,
                origin=origin,
                state_revision=f"created:{tab_id}",
                layout_revision="created",
                safe_title=str(created.get("title") or ""),
                safe_url=tab_url,
                provenance="TASK_CREATED",
            )
            return {"opened_tabs": (summary,)}

        return dispatch_open

    async def active(self) -> Tab:
        if (
            self._target_registry is not None
            and self._owner_binding is not None
        ):
            summary = self._target_registry.selected_tab_summary(
                self._owner_binding,
            )
            if summary is not None:
                return self._tab_from_summary(summary)
        if self._selected is not None:
            return self._selected
        raise BrowserSDKError(
            "No SDK tab is currently selected",
            code="no_current_tab",
            action="browser.tabs.active",
        )

    async def select(self, tab: TabSummary) -> Tab:
        """Select only one Runtime-issued owner-bound summary."""
        if not isinstance(tab, TabSummary):
            raise TypeError("tabs.select requires a TabSummary")
        if self._target_registry is None or self._owner_binding is None:
            raise BrowserSDKError(
                "Canonical tab registry is unavailable",
                code="browser_ownership_context_missing",
            )
        self._target_registry.select_tab_summary(self._owner_binding, tab)
        selected = self._tab_from_summary(tab)
        self._selected = selected
        return selected

    def _tab_from_summary(self, summary: TabSummary) -> Tab:
        assert self._target_registry is not None
        assert self._owner_binding is not None
        resolved = self._target_registry.resolve_tab_summary(
            summary,
            owner=self._owner_binding,
        )
        return Tab(
            id=resolved.receiver_tab_key,
            _session=self._session,
            _resources=self._resources,
            _condition_evaluator=self._condition_evaluator,
            _profile=self._profile,
            _target_registry=self._target_registry,
            _owner_binding=self._owner_binding,
            _tab_summary=summary,
            _action_runner=self._action_runner,
        )

    def _require_create_capacity(self) -> None:
        if self._target_registry is None or self._owner_binding is None:
            return
        if (
            self._target_registry.task_created_tab_count(self._owner_binding)
            >= self._max_task_created_tabs
        ):
            raise BrowserSDKError(
                "task-created tab limit reached",
                code="tab_limit_exceeded",
            )


def _require_choice(value: object, allowed: set[object], name: str) -> None:
    if value not in allowed:
        raise ValueError(f"invalid {name}: {value}")


def _require_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _require_modifiers(
    modifiers: object,
    *,
    allowed: set[str],
) -> None:
    if not isinstance(modifiers, tuple):
        raise TypeError("modifiers must be a tuple")
    if len(set(modifiers)) != len(modifiers):
        raise ValueError("modifiers cannot contain duplicates")
    if any(
        not isinstance(item, str) or item not in allowed for item in modifiers
    ):
        raise ValueError("invalid modifier")


def _require_key(key: object) -> str:
    key = _require_string(key, "key")
    named = {
        "Enter",
        "Tab",
        "Escape",
        "Space",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Backspace",
        "Delete",
    }
    printable_scalar = (
        len(key) == 1
        and key.isprintable()
        and not 0xD800 <= ord(key) <= 0xDFFF
    )
    if key not in named and not printable_scalar:
        raise ValueError("key must be one printable scalar or a supported key")
    return key


def _require_safe_http_url(url: object) -> str:
    url = _require_string(url, "url")
    if not url or any(ord(character) < 0x20 for character in url):
        raise ValueError("url must be a non-empty safe URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("url must be a valid HTTP(S) URL") from exc
    del port
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("url must be HTTP(S) without embedded credentials")
    return url


def _deadline(timeout_ms: int | None) -> float | None:
    if timeout_ms is None:
        return None
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool):
        raise TypeError("timeout_ms must be an integer")
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    return monotonic() + timeout_ms / 1000


def _command_arguments(
    command: object,
    *,
    code: str,
    message: str,
) -> Mapping[str, object]:
    """Expose only sealed public action arguments at the backend boundary."""
    payload = getattr(command, "_payload", None)
    arguments = payload.get("arguments") if isinstance(payload, Mapping) else None
    if not isinstance(arguments, Mapping):
        raise BrowserSDKError(message, code=code)
    return arguments


def _resource_operation_from_payload(
    payload: object,
) -> ResourceOperationBinding:
    if not isinstance(payload, Mapping):
        raise BrowserSDKError(
            "Canonical resource command payload is invalid",
            code="resource_operation_binding_invalid",
        )
    raw = payload.get("resource_operation")
    if not isinstance(raw, Mapping):
        raise BrowserSDKError(
            "Canonical resource operation binding is missing",
            code="resource_operation_binding_invalid",
        )
    owner_key = raw.get("owner_key")
    watermark = raw.get("pre_arm_watermark")
    if (
        not isinstance(owner_key, tuple)
        or len(owner_key) != 2
        or not isinstance(watermark, int)
        or isinstance(watermark, bool)
    ):
        raise BrowserSDKError(
            "Canonical resource operation owner is invalid",
            code="resource_operation_binding_invalid",
        )
    try:
        return ResourceOperationBinding(
            operation_id=str(raw.get("operation_id") or ""),
            operation_fingerprint=str(
                raw.get("operation_fingerprint") or "",
            ),
            command_id=str(raw.get("command_id") or ""),
            owner_key=(str(owner_key[0]), str(owner_key[1])),
            tab_id=str(raw.get("tab_id") or ""),
            pre_arm_watermark=int(watermark),
        )
    except (TypeError, ValueError) as exc:
        raise BrowserSDKError(
            "Canonical resource operation binding is invalid",
            code="resource_operation_binding_invalid",
        ) from exc


def _capability_blocked(capability: str) -> BrowserSDKGap:
    return BrowserSDKGap(
        f"Canonical capability is not active in S0: {capability}",
        action=capability,
        metadata={"capability": capability, "backend_dispatch_count": 0},
    )


def _blocked_canonical_action(
    capability: str,
    *,
    target: TargetRef | None = None,
    source: TargetRef | None = None,
    destination: TargetRef | None = None,
) -> ActionResult:
    """Return structured zero-dispatch truth for a valid grounded target."""
    return ActionResult(
        operation_id=issue_operation_id(),
        status="BLOCKED",
        retry="AFTER_OBSERVATION",
        problem=Problem(
            code="canonical_action_dispatch_not_enabled",
            phase="PREFLIGHT",
            safe_message=(
                f"Canonical action dispatch is not enabled: {capability}."
            ),
        ),
        target=target,
        source=source,
        destination=destination,
        commands=(),
        effect_facts=(),
    )


def _record_snapshot_result(result: SnapshotResult) -> SnapshotResult:
    record_browser_result(result)
    return result


def _record_wait_result(result: WaitResult) -> WaitResult:
    record_browser_result(result)
    return result


# pylint: disable-next=too-many-return-statements
def _wait_preflight(
    condition: BrowserCondition,
    *,
    timeout_ms: int,
    stable_ms: int,
    profile: BackendProfile | None,
) -> WaitResult | None:
    if not isinstance(condition, BrowserCondition):
        return _invalid_wait("condition must be a BrowserCondition")
    action_only = any(
        _condition_usage(atom) == "ACTION_EXPECTATION_ONLY"
        for atom in condition.atoms
    )
    if action_only:
        return _invalid_wait(
            "ResourceCondition.created is action-expectation-only",
        )
    limits = profile.hard_limits if profile is not None else {}
    max_wait_ms = int(limits.get("max_wait_ms", 30_000))
    max_stable_ms = int(limits.get("max_stable_ms", 5_000))
    max_atoms = int(limits.get("max_condition_atoms", 16))
    if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool):
        return _invalid_wait("timeout_ms must be an integer")
    if not isinstance(stable_ms, int) or isinstance(stable_ms, bool):
        return _invalid_wait("stable_ms must be an integer")
    if timeout_ms < 1 or timeout_ms > max_wait_ms:
        return _invalid_wait("timeout_ms exceeds the backend profile")
    if stable_ms < 0 or stable_ms > min(timeout_ms, max_stable_ms):
        return _invalid_wait("stable_ms exceeds the backend profile")
    if len(condition.atoms) > max_atoms:
        return _invalid_wait("condition exceeds max_condition_atoms")
    return None


def _invalid_wait(message: str) -> WaitResult:
    return WaitResult(
        operation_id=issue_operation_id(),
        status="FAILED",
        retry="NONE",
        problem=Problem(
            code="condition_invalid_argument",
            phase="PREFLIGHT",
            safe_message=message,
        ),
        outcome="INVALID_ARGUMENT",
    )


def _wait_result(evaluation: ConditionEvaluation) -> WaitResult:
    problem = _wait_problem(evaluation)
    retry: RetryDirective = "NONE"
    if evaluation.status in {"PARTIAL", "BLOCKED"}:
        retry = "AFTER_OBSERVATION"
    elif evaluation.status == "FAILED":
        retry = "SAFE"
    return WaitResult(
        operation_id=issue_operation_id(),
        status=evaluation.status,
        retry=retry,
        problem=problem,
        cleanup=evaluation.cleanup,
        evidence=(
            evaluation.evidence.ref
            if evaluation.evidence is not None
            else None
        ),
        outcome=evaluation.outcome,
        matched_atoms=evaluation.matched_atoms,
        last_observed=evaluation.last_observed,
        elapsed_ms=evaluation.elapsed_ms,
    )


def _wait_problem(evaluation: ConditionEvaluation) -> Problem | None:
    if evaluation.status == "SUCCEEDED":
        return None
    code = {
        "TIMED_OUT": "condition_timeout_partial",
        "STALE": "condition_baseline_stale",
        "UNAVAILABLE": "condition_probe_unavailable",
        "INVALID_ARGUMENT": "condition_invalid_argument",
        None: "condition_evaluator_startup",
    }[evaluation.outcome]
    phase: Literal["PREFLIGHT", "CAPTURE", "VERIFY", "TRANSPORT"]
    if evaluation.outcome == "INVALID_ARGUMENT":
        phase = "PREFLIGHT"
    elif evaluation.outcome in {"TIMED_OUT", "STALE"}:
        phase = "VERIFY"
    elif evaluation.status == "FAILED":
        phase = "TRANSPORT"
    else:
        phase = "CAPTURE"
    return Problem(
        code=code,
        phase=phase,
        safe_message="Condition evaluation did not prove satisfaction.",
    )


def _scope_owner_chain(
    store: ObservationStore,
    scope: ObservationScope,
) -> tuple[str, ...] | None:
    if isinstance(scope, CurrentSurface):
        return None
    if isinstance(scope, FrameScope):
        return store.require_region(
            scope.frame_region,
            kind="FRAME",
        ).owner_chain
    if isinstance(scope, RegionScope):
        return _region_owner_chain(store, scope.region)
    return None


def _region_owner_chain(
    store: ObservationStore,
    region: Any,
) -> tuple[str, ...]:
    kinds: tuple[Literal["FRAME", "CONTENT", "OWNER"], ...] = (
        "FRAME",
        "CONTENT",
        "OWNER",
    )
    for kind in kinds:
        try:
            return store.require_region(region, kind=kind).owner_chain
        except ObservationStoreError as exc:
            if exc.code != "region_type_mismatch":
                raise
    raise ObservationStoreError("region_type_mismatch")


def _snapshot_limit(
    limit: int,
) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("snapshot limit must be positive")
    return limit


def _query_matches(target: SnapshotTarget, query: TargetQuery) -> bool:
    checks: list[bool] = []
    if query.role:
        checks.append(normalize_visible_text(target.role) == query.role)
    if query.name:
        checks.append(_text_matches(target.name, query.name, query.match))
    if query.text:
        checks.append(_text_matches(target.name, query.text, query.match))
    return all(checks)


def _text_matches(value: str, expected: str, match: str) -> bool:
    value_key = normalize_visible_text(value)
    expected_key = normalize_visible_text(expected)
    return (
        value_key == expected_key
        if match == "exact"
        else expected_key in value_key
    )


def apply_target_query(
    targets: tuple[SnapshotTarget, ...],
    query: TargetQuery,
    *,
    region_owner_chain: tuple[str, ...] | None = None,
) -> tuple[SnapshotTarget, ...]:
    """Filter immutable evidence without selecting or issuing authority."""
    if not isinstance(query, TargetQuery):
        raise TypeError("query must be a TargetQuery")
    if query.region is not None and region_owner_chain is None:
        raise ValueError("region query requires a resolved owner chain")
    candidates = targets
    if region_owner_chain is not None:
        candidates = tuple(
            target
            for target in candidates
            if target.owner_chain[: len(region_owner_chain)]
            == region_owner_chain
        )
    return tuple(
        target for target in candidates if _query_matches(target, query)
    )


def _target_summary(target: SnapshotTarget, index: int) -> TargetSummary:
    del index
    ref = target.ref
    if not isinstance(ref, TargetRef):
        raise BrowserSDKGap(
            "Canonical snapshot target is not registry-bound.",
            code="runtime_issued_value",
            action="tab.snapshot",
        )
    return TargetSummary(
        ref=ref,
        role=target.role,
        name=target.name,
        states=target.states,
        allowed_actions=tuple(cast(Any, ref.allowed_actions)),
        observed_url=str(ref.observed_url or ""),
    )


def _read_segment(target: SnapshotTarget) -> ReadSegment:
    """Project one source-owned semantic record as a neutral read segment."""
    return ReadSegment(
        kind="link" if target.role == "link" else "text",
        text=target.name,
    )


def _region_summary(store: ObservationStore, region: Any) -> RegionSummary:
    ref = store.issue_region(
        kind=region.kind,
        native_identity=region.native_identity,
        owner_chain=region.owner_chain,
    )
    return RegionSummary(
        ref=ref,
        kind=region.kind,
        boundary=region.boundary,
        accessible=region.accessible,
    )


def _snapshot_terminal(
    coverage: str,
) -> tuple[TerminalStatus, RetryDirective, Problem | None]:
    if coverage == "COMPLETE":
        return "SUCCEEDED", "NONE", None
    if coverage == "PARTIAL":
        return (
            "PARTIAL",
            "AFTER_OBSERVATION",
            Problem(
                code="observation_partial",
                phase="CAPTURE",
                safe_message=(
                    "Snapshot evidence is partial; inspect coverage gaps."
                ),
            ),
        )
    code = (
        "observation_stale"
        if coverage == "STALE"
        else "observation_unavailable"
    )
    return (
        "BLOCKED",
        "AFTER_OBSERVATION",
        Problem(
            code=code,
            phase="CAPTURE",
            safe_message="Snapshot evidence is unavailable for this surface.",
        ),
    )


def _snapshot_model_text(
    *,
    status: str,
    coverage: str,
    gaps: tuple[CoverageGap, ...],
    targets: tuple[TargetSummary, ...],
) -> str:
    lines = [f"status={status} coverage={coverage}"]
    for gap in gaps:
        detail = gap.detail
        notice = gap.notice
        lines.append(
            " ".join(
                part
                for part in (
                    f"stage={gap.stage}",
                    f"reason={detail.reason}",
                    f"examined={detail.examined}",
                    f"omitted={detail.omitted}",
                    notice,
                )
                if part
            ),
        )
    lines.extend(
        f"target role={target.role} name={target.name}" for target in targets
    )
    return "\n".join(lines)


def _read_terminal(
    coverage: str,
) -> tuple[TerminalStatus, RetryDirective, Problem | None]:
    if coverage == "COMPLETE":
        return "SUCCEEDED", "NONE", None
    if coverage == "PARTIAL":
        return (
            "PARTIAL",
            "AFTER_OBSERVATION",
            Problem(
                code="observation_partial",
                phase="CAPTURE",
                safe_message=(
                    "Read collection is partial; inspect coverage gaps."
                ),
            ),
        )
    code = (
        "observation_stale"
        if coverage == "STALE"
        else "observation_unavailable"
    )
    return (
        "BLOCKED",
        "AFTER_OBSERVATION",
        Problem(
            code=code,
            phase="CAPTURE",
            safe_message="Read collection could not be established.",
        ),
    )


def _read_model_text(
    *,
    status: str,
    observation: Any,
    clamp_notice: str,
    segments: tuple[ReadSegment, ...],
    end_of_collection: bool,
) -> str:
    lines = [f"status={status} coverage={observation.coverage}"]
    lines.extend(
        (
            f"stage={gap.stage} reason={gap.detail.reason} "
            f"examined={gap.detail.examined} omitted={gap.detail.omitted}"
        )
        for gap in observation.gaps
    )
    if clamp_notice:
        lines.append(clamp_notice)
    lines.extend(f"{segment.kind}: {segment.text}" for segment in segments)
    lines.append(f"end_of_collection={str(end_of_collection).lower()}")
    return "\n".join(lines)


__all__ = ["BrowserTabs", "Tab", "TabActions"]
