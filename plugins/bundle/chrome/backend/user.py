# -*- coding: utf-8 -*-
"""Chrome Extension backend adapter for the unified Browser SDK."""

# pylint: disable=redefined-builtin,too-many-public-methods,too-many-statements
# pylint: disable=protected-access

from __future__ import annotations

import base64
from hashlib import sha256
import json
import logging
from datetime import UTC, datetime
from time import monotonic, perf_counter
from typing import Any, Callable, Literal, Mapping, cast
from urllib.parse import urlparse

from qwenpaw.browser.backends.registry import get_default_backend_registry
from qwenpaw.browser.action_runner import DispatchContext
from qwenpaw.browser.canonical.contracts import (
    ActionResult,
    BrowserPrompt,
    CaptureGap,
    ContextVersion,
    CoverageGap,
    Coverage,
    CurrentSurface,
    EvidenceRef,
    RegionCondition,
    RegionRef,
    Problem,
    TabSummary,
    TargetQuery,
    TargetRef,
    VisualRegion,
    _RUNTIME_VALUE_ISSUER,
    _issue_opaque_value,
    issue_operation_id,
)
from qwenpaw.browser.condition_evaluator import (
    ConditionProbe,
    PageFacts,
    ProbeHint,
    ProbeObservation,
    ProbeRequest,
    ProbeSubscription,
    RegionFacts,
)
from qwenpaw.browser.governance.errors import (
    BrowserContextUnavailable,
    BrowserPolicyDenied,
    BrowserSDKError,
)
from qwenpaw.browser.governance.error_codes import classify_browser_error
from qwenpaw.browser.primitives.observation import (
    coerce_observation,
    coerce_screenshot,
)
from qwenpaw.browser.governance.policy import (
    BrowserPolicy,
    DefaultBrowserPolicy,
)
from qwenpaw.browser.governance.boundary import (
    evaluate_browser_boundary,
    raise_if_boundary_denied,
    require_canonical_effect_floor,
)
from qwenpaw.browser.governance.effects import EffectClassification
from qwenpaw.browser.telemetry.trace import record_browser_trace_event
from qwenpaw.browser.primitives.types import (
    BrowserActionResult,
    BrowserBackendCapabilities,
    BrowserBackendDiagnostic,
    BrowserContextRequest,
    BrowserDiagnosticCheck,
    BrowserDiagnosticStatus,
    BrowserOwnershipContext,
    BrowserPageInfo,
    BrowserRetention,
    ResolvedBrowserContext,
    build_browser_ownership_context,
)
from qwenpaw.browser.primitives.types import (
    BrowserObservation,
    BrowserScreenshot,
)
from qwenpaw.browser.runtime.resources import (
    DownloadCapture,
    PagePdfCapture,
    ScreenshotCapture,
    ScreenshotInvariant,
)
from qwenpaw.browser.runtime.session_owner import (
    BrowserRequestBinding,
    BrowserSessionOwnerRegistry,
    ContractMode,
    MAX_LEGACY_TOKEN_TTL_SECONDS,
    MAX_RETAINED_STATE_TTL_SECONDS,
    NativeContextVersion,
    TargetBinding,
)
from qwenpaw.browser.runtime.snapshot import (
    RegionSummary as SnapshotRegionSummary,
    SnapshotCapture,
    SnapshotTarget,
    SourceTraversalCapture,
    SourceOutcome,
)
from ..action_runtime.handlers.protocol import (
    _issue_trusted_command_envelope,
)
from ..action_runtime.source_traversal import invalidate_source_traversals

BACKEND_ID = "user.chrome_extension"
PROVIDER_FINGERPRINT = "provider-v1"
logger = logging.getLogger(__name__)
_BROWSER_SENTINEL_TAB_ID = "__browser__"
_TabOwnership = Literal[
    "owned",
    "borrowed",
    "protected",
    "orphaned",
    "released",
]
_TAB_OWNERSHIP_STATES = {
    "owned",
    "borrowed",
    "protected",
    "orphaned",
    "released",
}
_PROTECTED_TAB_ERROR_CODE = "PROTECTED_TAB_REQUIRES_EXPLICIT_OVERRIDE"
_BROWSER_INTERNAL_SCHEMES = {
    "brave",
    "chrome",
    "chrome-extension",
    "devtools",
    "edge",
    "moz-extension",
    "opera",
    "vivaldi",
}
_LOCAL_QWENPAW_HOSTS = {"127.0.0.1", "::1", "localhost"}
_LOCAL_QWENPAW_PORTS = {8088}
_ENGINE_ACTION_ALIASES = {
    "back": "navigate_back",
    "forward": "navigate_forward",
    "press": "press_key",
    "select": "select_option",
}
_USER_BROWSER_SESSIONS: dict[str, set["ChromeExtensionBrowserSession"]] = {}


def _validate_canonical_effect_floor(
    api_id: str,
    arguments: Mapping[str, object],
    classification: EffectClassification,
) -> EffectClassification:
    """Apply the shared Canonical floor at the User backend boundary."""
    return require_canonical_effect_floor(
        api_id,
        arguments,
        classification,
    )


def _validate_consumed_dispatch_context(
    registry: BrowserSessionOwnerRegistry,
    context: DispatchContext,
    *,
    execution: Any,
    tab_id: str,
    command_payload: Mapping[str, object],
) -> None:
    """Recheck the consumed context against sole owner-registry records."""
    owner = context._owner_binding
    expected_execution = (
        execution.root_task_id,
        execution.browser_owner_id,
        execution.root_session_id,
        execution.lease_generation,
    )
    observed_execution = (
        context.root_task_id,
        context.browser_owner_id,
        context.session_id,
        context.owner_lease_generation,
    )
    if expected_execution != observed_execution or not context.is_bound_to(
        registry,
        str(tab_id),
    ):
        raise BrowserSDKError(
            "Canonical DispatchContext owner or receiver is invalid",
            code="dispatch_context_invalid",
        )
    pending = registry.require_pending_action(owner, context.operation_id)
    commands = getattr(pending, "commands", {})
    command = commands.get(context.command_id)
    payload = getattr(command, "_payload", None)
    expected_payload = (
        payload.get("arguments") if isinstance(payload, Mapping) else None
    )
    expected_effects = tuple(
        str(item) for item in getattr(pending, "classified_effects", ())
    )
    observed_effects = tuple(str(item) for item in context.effects)
    pending_invalid = (
        command is None
        or getattr(pending, "logical_api", None) != context.api_id
        or getattr(pending, "operation_fingerprint", None)
        != context.operation_fingerprint
        or getattr(pending, "expectation_digest", None)
        != context.expectation_digest
        or getattr(command, "command_fingerprint", None)
        != context.command_fingerprint
        or getattr(command, "operation_fingerprint", None)
        != context.operation_fingerprint
        or expected_payload != dict(command_payload)
        or expected_effects != observed_effects
    )
    state = registry._require_current_lease(owner)
    grant = state.grants.get(context.grant_id)
    grant_invalid = (
        grant is None
        or grant.remaining_uses != 0
        or grant.dispatch_context_identity != id(context)
        or grant.operation_id != context.operation_id
        or grant.operation_fingerprint != context.operation_fingerprint
        or grant.binding_hash != context.binding_hash
        or grant.effects != observed_effects
        or grant.expectation_digest != context.expectation_digest
    )
    if pending_invalid or grant_invalid:
        raise BrowserSDKError(
            "Canonical DispatchContext is forged, stale, or not consumed",
            code="dispatch_context_invalid",
        )


class ChromeExtensionBrowserBackend:
    """Browser SDK backend backed by the Chrome Extension bridge."""

    backend_id = BACKEND_ID

    def __init__(
        self,
        *,
        bridge_manager: Any | None = None,
        control_engine: Any | None = None,
        policy: BrowserPolicy | None = None,
        trace_recorder: Callable[..., Any] | None = None,
    ) -> None:
        self._bridge_manager = bridge_manager
        self._control_engine = control_engine
        self._policy = policy or DefaultBrowserPolicy()
        self._trace_recorder = trace_recorder or record_browser_trace_event

    def capabilities(self) -> BrowserBackendCapabilities:
        return BrowserBackendCapabilities(
            backend_id=self.backend_id,
            browser_context="user",
            features=frozenset({"chrome_extension_bridge"}),
        )

    def profile(self):
        """Return exact reviewed variants; diagnostics may only narrow them."""
        from qwenpaw.browser.backends.protocols import BackendProfile

        from ..action_runtime.handlers.capabilities import backend_profile

        base = backend_profile()
        return BackendProfile(
            variants={
                **base.variants,
                "observe.snapshot": "READY",
                "observe.read": "READY",
                "observe.screenshot.viewport": "READY",
                "observe.screenshot.full_page": "READY",
                "synchronize.page.url": "READY",
                "synchronize.page.title": "READY",
                "synchronize.page.document_changed": "READY",
                "synchronize.page.ready": "READY",
                "synchronize.region.text": "READY",
                "synchronize.region.item_count": "READY",
                "synchronize.region.changed": "READY",
            },
            hard_limits={
                **base.hard_limits,
                "max_wait_ms": 30_000,
                "max_stable_ms": 5_000,
                "max_condition_atoms": 16,
                "max_retained_state_ttl_seconds": (
                    MAX_RETAINED_STATE_TTL_SECONDS
                ),
                "max_legacy_token_ttl_seconds": (MAX_LEGACY_TOKEN_TTL_SECONDS),
            },
            contract_fingerprint=base.contract_fingerprint,
            profile_fingerprint=base.profile_fingerprint,
            build_fingerprint=base.build_fingerprint,
            extension_fingerprint=base.extension_fingerprint,
            state_verifiers=(),
        )

    def is_available(self) -> bool:
        bridge = self._bridge()
        if bridge is None:
            return False
        is_connected = getattr(bridge, "is_connected", None)
        if callable(is_connected):
            return bool(is_connected())  # pylint: disable=not-callable
        return bool(getattr(bridge, "connected", False))

    def unavailable_error(self) -> BrowserContextUnavailable:
        """Return the precise error for resolver availability failures."""
        return BrowserContextUnavailable(
            "Chrome extension is not connected.",
            code="chrome_disconnected",
            backend_id=self.backend_id,
        )

    def diagnostics(self) -> dict[str, Any]:
        """Return user backend diagnostic metadata without connecting."""
        return {"bridge_connected": self.is_available()}

    def set_policy(self, policy: BrowserPolicy) -> None:
        """Replace the action/context policy used by new sessions."""
        self._policy = policy

    def configure_runtime(
        self,
        *,
        bridge_manager: Any | None = None,
        control_engine: Any | None = None,
        trace_recorder: Callable[..., Any] | None = None,
    ) -> None:
        """Refresh injected Chrome runtime dependencies."""
        if bridge_manager is not None:
            self._bridge_manager = bridge_manager
        if control_engine is not None:
            self._control_engine = control_engine
        if trace_recorder is not None:
            self._trace_recorder = trace_recorder

    async def diagnose(self) -> BrowserBackendDiagnostic:
        """Return typed Chrome Extension backend diagnostics."""
        bridge = self._bridge()
        bridge_manager_present = bridge is not None
        bridge_connected = False
        if bridge is not None:
            is_connected = getattr(bridge, "is_connected", None)
            if callable(is_connected):
                bridge_connected = bool(
                    is_connected(),
                )  # pylint: disable=not-callable
            else:
                bridge_connected = bool(getattr(bridge, "connected", False))
        control_engine_registered = self._engine() is not None
        available = bridge_connected
        if not bridge_connected:
            status: BrowserDiagnosticStatus = "unavailable"
            code = "chrome_disconnected"
            message = "Chrome Extension Chrome is not connected."
            hint_key = code
        elif not control_engine_registered:
            status = "degraded"
            code = "chrome_engine_missing"
            message = "Chrome engine is not registered."
            hint_key = code
        else:
            status = "available"
            code = ""
            message = "Chrome Extension browser backend is available."
            hint_key = ""
        (
            actionable_check,
            cleanup_check,
        ) = await _diagnose_actionable_round_trip(
            bridge,
            enabled=bridge_connected,
        )
        if actionable_check.status != "available":
            available = False
            status = "unavailable"
            code = actionable_check.code or "browser_backend_unavailable"
            message = actionable_check.message
            hint_key = actionable_check.hint_key or code
        elif cleanup_check.status != "available":
            available = False
            status = "degraded"
            code = cleanup_check.code or "browser_cleanup_incomplete"
            message = cleanup_check.message
            hint_key = cleanup_check.hint_key or code
        return BrowserBackendDiagnostic(
            backend_id=self.backend_id,
            browser_context="user",
            available=available,
            code=code,
            reason="" if available and status == "available" else message,
            status=status,
            message=message,
            hint_key=hint_key,
            message_fallback=message,
            checks=(
                BrowserDiagnosticCheck(
                    name="connected",
                    status="available" if bridge_connected else "unavailable",
                    code="" if bridge_connected else code,
                    message=(
                        "Chrome Extension bridge is connected."
                        if bridge_connected
                        else "Chrome Extension bridge is disconnected."
                    ),
                    hint_key="" if bridge_connected else hint_key,
                    metadata={"backend_id": self.backend_id},
                ),
                BrowserDiagnosticCheck(
                    name="routable",
                    status=(
                        "available"
                        if bridge_manager_present and bridge_connected
                        else "unavailable"
                    ),
                    code=(
                        ""
                        if bridge_manager_present and bridge_connected
                        else code
                    ),
                    message=(
                        "Chrome Extension bridge is routable."
                        if bridge_manager_present and bridge_connected
                        else "Chrome Extension bridge is not routable."
                    ),
                    hint_key=(
                        ""
                        if bridge_manager_present and bridge_connected
                        else hint_key
                    ),
                    metadata={"backend_id": self.backend_id},
                ),
                BrowserDiagnosticCheck(
                    name="control_engine",
                    status=(
                        "available"
                        if control_engine_registered
                        else "degraded"
                    ),
                    code=(
                        ""
                        if control_engine_registered
                        else "chrome_engine_missing"
                    ),
                    message=(
                        "Chrome engine is registered."
                        if control_engine_registered
                        else "Chrome engine is not registered."
                    ),
                    hint_key=(
                        ""
                        if control_engine_registered
                        else "chrome_engine_missing"
                    ),
                    metadata={"backend_id": self.backend_id},
                ),
                actionable_check,
                cleanup_check,
            ),
            observed_at=_diagnostic_observed_at(),
            features=self.capabilities().features,
            metadata={
                "bridge_manager_present": bridge_manager_present,
                "bridge_connected": bridge_connected,
                "control_engine_registered": control_engine_registered,
                "selected_backend_id": self.backend_id,
            },
        )

    async def connect(
        self,
        session_id: str,
        context: ResolvedBrowserContext,
        *,
        request_scope_key: str = "",
        retention: BrowserRetention = "clean",
        ownership_context: BrowserOwnershipContext | None = None,
    ) -> "ChromeExtensionBrowserSession":
        if not self.is_available():
            raise BrowserContextUnavailable(
                "Chrome Extension Chrome is not connected.",
                code="chrome_disconnected",
                backend_id=self.backend_id,
            )
        decision = self._policy.allow_context_acquisition(
            BrowserContextRequest(
                session_id=session_id,
                requested_context=context.requested,
                selected_context=context.selected,
                requires_user_state=context.requires_user_state,
                backend_id=self.backend_id,
            ),
        )
        if not decision.allowed:
            raise BrowserPolicyDenied(
                decision.reason or "Browser context denied by policy",
                backend_id=self.backend_id,
                metadata=decision.metadata,
            )
        bridge = self._bridge()
        if bridge is None:
            raise BrowserContextUnavailable(
                "Chrome Extension Chrome is not connected.",
                code="chrome_disconnected",
                backend_id=self.backend_id,
            )
        from qwenpaw.browser.runtime.kernel import (
            get_current_execution_context,
        )

        execution = get_current_execution_context()
        if (
            execution is None
            or execution.contract_mode is not ContractMode.CANONICAL
        ):
            raise BrowserSDKError(
                "User Chrome sessions require Canonical execution",
                code="canonical_dispatch_context_missing",
            )
        session = ChromeExtensionBrowserSession(
            bridge=bridge,
            session_id=session_id,
            request_scope_key=request_scope_key,
            retention=retention,
            context=context,
            policy=self._policy,
            control_engine=self._engine(),
            trace_recorder=self._trace_recorder,
            ownership_context=ownership_context,
            contract_mode=ContractMode.CANONICAL,
        )
        _register_user_browser_session(session)
        return session

    def _bridge(self) -> Any | None:
        manager = self._bridge_manager
        if manager is None:
            return None
        get_connection = getattr(manager, "get_connection", None)
        if callable(get_connection):
            return get_connection()  # pylint: disable=not-callable
        return manager

    def _engine(self) -> Any | None:
        return self._control_engine

    def retirement_snapshot(self) -> dict[str, object]:
        """Read live Bridge retirement facts without querying or mutation."""
        bridge = self._bridge()
        if bridge is None:
            return {
                "revision": None,
                "counts": None,
                "legacy_quiet_seconds": None,
                "reason": "BACKEND_MISSING",
            }
        is_connected = getattr(bridge, "is_connected", None)
        connected = (
            bool(is_connected())  # pylint: disable=not-callable
            if callable(is_connected)
            else bool(getattr(bridge, "connected", False))
        )
        if not connected:
            return {
                "revision": None,
                "counts": None,
                "legacy_quiet_seconds": None,
                "reason": "BACKEND_DISCONNECTED",
            }
        leases = getattr(bridge, "_leases", None)
        pending = getattr(bridge, "_pending", None)
        if not isinstance(leases, dict) or not isinstance(pending, dict):
            return {
                "revision": None,
                "counts": None,
                "legacy_quiet_seconds": None,
                "reason": "STATE_UNAVAILABLE",
            }
        sessions = _registered_user_sessions_for_bridge(bridge)
        counts = {
            "legacy_holders": 0,
            "legacy_sessions": 0,
            "legacy_pending_receipts": 0,
        }
        material = {
            "sessions": [
                (
                    session.session_id,
                    session.holder_id,
                    session.contract_mode.value,
                    session._last_activity_monotonic,
                    tuple(sorted(session._tab_ownership.items())),
                    bool(
                        session._state.get(
                            "control_pending_action_transition",
                        ),
                    ),
                )
                for session in sessions
            ],
            "leases": [
                (
                    str(tab_id),
                    str(getattr(lease, "owner_id", "") or ""),
                    int(getattr(lease, "version", 0) or 0),
                    float(getattr(lease, "expires_at", 0.0) or 0.0),
                )
                for tab_id, lease in leases.items()
            ],
            "pending": tuple(
                sorted(str(item) for item in dict.keys(pending)),
            ),
            "counts": counts,
        }
        return {
            "revision": _bridge_retirement_revision(material),
            "counts": counts,
            "legacy_quiet_seconds": MAX_LEGACY_TOKEN_TTL_SECONDS,
            "reason": None,
        }

    async def cleanup_for_request(
        self,
        *,
        session_id: str = "",
        root_session_id: str = "",
        holder_id: str = "",
        workspace_id: str = "",
        cleanup_reason: str = "finally",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Release Chrome resources owned by one request."""
        cleanup_errors = 0
        user_result: dict[str, Any] = {}
        runtime_result: dict[str, Any] = {}
        try:
            user_result = await cleanup_user_browser_sessions_for_request(
                session_id=session_id,
                root_session_id=root_session_id,
                holder_id=holder_id,
                cleanup_reason=cleanup_reason,
                **kwargs,
            )
        except Exception:
            cleanup_errors += 1
            logger.debug(
                "chrome user backend cleanup failed",
                exc_info=True,
            )

        try:
            runtime_result = await _cleanup_action_runtime_for_request(
                self._control_engine,
                session_id=session_id,
                root_session_id=root_session_id,
                workspace_id=workspace_id,
                cleanup_reason=cleanup_reason,
                **kwargs,
            )
        except Exception:
            cleanup_errors += 1
            logger.debug(
                "chrome action runtime cleanup failed",
                exc_info=True,
            )

        fallback_result: dict[str, Any] = {}
        try:
            fallback_result = await _cleanup_extension_metadata_fallback(
                self._bridge(),
                owner_id=str(kwargs.get("owner_id") or ""),
                workspace_id=workspace_id,
                cleanup_reason=cleanup_reason,
                preserve_owned_tabs=bool(
                    kwargs.get("preserve_owned_tabs", False),
                ),
            )
        except Exception:
            cleanup_errors += 1
            logger.debug(
                "chrome extension metadata cleanup failed",
                exc_info=True,
            )

        merged = _merge_cleanup_results(
            user_result,
            _merge_cleanup_results(
                runtime_result,
                fallback_result,
                cleanup_reason=cleanup_reason,
            ),
            cleanup_reason=cleanup_reason,
        )
        merged["cleanup_errors"] = cleanup_errors
        return merged


class ChromeExtensionBrowserSession:
    """Connected user-browser session for Browser SDK facade calls."""

    backend_id = BACKEND_ID

    def __init__(
        self,
        *,
        bridge: Any,
        session_id: str,
        request_scope_key: str = "",
        retention: BrowserRetention = "clean",
        context: ResolvedBrowserContext,
        policy: BrowserPolicy,
        control_engine: Any | None = None,
        trace_recorder: Callable[..., Any] | None = None,
        ownership_context: BrowserOwnershipContext | None = None,
        contract_mode: ContractMode = ContractMode.CANONICAL,
    ) -> None:
        self.bridge = bridge
        self.session_id = session_id
        self.request_scope_key = _normalize_session_id(
            request_scope_key or session_id,
        )
        self.retention = _normalize_retention(retention)
        self.ownership_context = (
            ownership_context
            or build_browser_ownership_context(
                session_id=session_id,
                root_session_id=session_id,
                request_scope_key=self.request_scope_key,
                retention=self.retention,
            )
        )
        self.context = context
        self.owner_id = self.ownership_context.owner_id
        self.holder_id = self.owner_id
        self._policy = policy
        self._control_engine = control_engine
        self._trace_recorder = trace_recorder or record_browser_trace_event
        self.contract_mode = ContractMode(contract_mode)
        self._last_activity_monotonic = monotonic()
        self._state: dict[str, Any] = {
            "workspace_id": self.ownership_context.workspace_id,
            "owner_id": self.owner_id,
            "ownership_context": self.ownership_context,
        }
        self._tab_ownership: dict[str, _TabOwnership] = {}
        self._current_tab_id: str | None = None
        self._registry_keys: set[str] = set()
        self._condition_region_baselines: dict[tuple[str, str], str] = {}

    def set_registry_keys(self, keys: set[str]) -> None:
        """Store cleanup registry keys owned by this request session."""
        self._registry_keys = set(keys)

    def registry_keys(self) -> set[str]:
        """Return cleanup registry keys for this request session."""
        return set(self._registry_keys)

    def clear_registry_keys(self) -> None:
        """Clear cleanup registry keys after successful release."""
        self._registry_keys.clear()

    async def close(self) -> None:
        await self._cleanup(cleanup_reason="browser_close")

    async def stop(self) -> None:
        await self._cleanup(cleanup_reason="browser_stop")

    async def cleanup_for_request(
        self,
        *,
        cleanup_reason: str = "finally",
        preserve_owned_tabs: bool = False,
    ) -> dict[str, Any]:
        """Release all tabs held by this Browser SDK user session."""
        return await self._cleanup(
            cleanup_reason=cleanup_reason,
            preserve_owned_tabs=preserve_owned_tabs,
        )

    async def _cleanup(
        self,
        *,
        cleanup_reason: str,
        preserve_owned_tabs: bool = False,
    ) -> dict[str, Any]:
        self._touch_activity()
        self._state.pop("control_condition_subscriptions", None)
        self._condition_region_baselines.clear()
        closed_tabs = 0
        released_tabs = 0
        released_borrowed_tabs = 0
        preserved_owned_tabs = 0
        skipped_protected_tabs = 0
        cleanup_errors = 0
        should_preserve_owned_tabs = (
            preserve_owned_tabs
            or cleanup_reason == "handoff_required"
            or self.retention != "clean"
        )
        for tab_id, ownership in list(self._tab_ownership.items()):
            if ownership == "protected":
                skipped_protected_tabs += 1
                self._tab_ownership.pop(str(tab_id), None)
                continue
            close_owned = (
                ownership == "owned" and not should_preserve_owned_tabs
            )
            try:
                await self._cleanup_tab(
                    tab_id,
                    ownership,
                    cleanup_reason=cleanup_reason,
                    close_owned=close_owned,
                )
            except Exception:
                cleanup_errors += 1
                logger.debug(
                    "chrome tab cleanup failed tab=%s",
                    tab_id,
                    exc_info=True,
                )
                self._tab_ownership.pop(str(tab_id), None)
                continue
            if ownership == "owned" and close_owned:
                closed_tabs += 1
            elif ownership == "owned":
                preserved_owned_tabs += 1
                released_tabs += 1
            else:
                released_tabs += 1
                released_borrowed_tabs += 1
        if not self._tab_ownership:
            _unregister_user_browser_session(self)
        return {
            "closed_tabs": closed_tabs,
            "released_tabs": released_tabs,
            "closed_owned_tabs": closed_tabs,
            "released_borrowed_tabs": released_borrowed_tabs,
            "preserved_owned_tabs": preserved_owned_tabs,
            "skipped_protected_tabs": skipped_protected_tabs,
            "remaining_orphaned_tabs": self._remaining_orphaned_tabs(),
            "cleanup_errors": cleanup_errors,
            "cleanup_reason": cleanup_reason,
            "preserve_owned_tabs": should_preserve_owned_tabs,
            "retention": self.retention,
            "request_scope_key": self.request_scope_key,
        }

    async def active_tab(self) -> dict[str, Any]:
        started = perf_counter()
        tabs = await self.list_tabs()
        selected = self._current_working_tab(tabs)
        selection_reason = "current_working_tab"
        if selected is None:
            selected = _default_workspace_tab(
                tabs,
                workspace_id=self._state["workspace_id"],
                owner_id=self.owner_id,
                protocol_version=self.ownership_context.protocol_version,
            )
            selection_reason = "existing_controlled_workspace"
        if selected is None:
            _raise_workspace_candidate_error(
                tabs,
                workspace_id=self._state["workspace_id"],
                owner_id=self.owner_id,
                protocol_version=self.ownership_context.protocol_version,
                backend_id=self.backend_id,
                action="tabs.active",
            )
        if selected is None:
            raise BrowserSDKError(
                "No current Browser tab exists for this request.",
                code="browser_no_current_tab",
                backend_id=self.backend_id,
                action="tabs.active",
                metadata={"creation_allowed": False},
            )
        tab_id = str(selected.get("id") or "")
        if selection_reason == "current_working_tab":
            await self._claim(tab_id)
            await self._attach(tab_id)
            ownership = self._tab_ownership.get(tab_id, "borrowed")
        else:
            await self._claim_existing_tab(selected)
            ownership = _ownership_from_tab(selected, default="owned")
        tab = self._tab_metadata(
            selected,
            ownership=ownership,
            selection_reason=selection_reason,
        )
        self._record_workspace_selection_trace(
            tab,
            duration_ms=_duration_ms(started),
            selection_reason=selection_reason,
            activation_reason="existing_tab_not_activated",
        )
        return tab

    async def list_tabs(self) -> list[dict[str, Any]]:
        self._touch_activity()
        tabs = await self.bridge.discover_tabs()
        return [_normalize_tab(tab) for tab in tabs if isinstance(tab, dict)]

    async def current_prompt(
        self,
        tab: TabSummary,
    ) -> BrowserPrompt | None:
        """Project the exact captured Canonical prompt into owner authority."""
        from qwenpaw.browser.runtime.kernel import (
            get_current_execution_context,
        )
        from qwenpaw.runtime.root_request_coordinator import _OWNER_REGISTRY

        execution = get_current_execution_context()
        if (
            execution is None
            or execution.contract_mode is not ContractMode.CANONICAL
        ):
            raise BrowserSDKError(
                "current_prompt requires Canonical owner context",
                code="browser_ownership_context_missing",
            )
        owner = BrowserRequestBinding(
            root_session_id=execution.root_session_id,
            root_task_id=execution.root_task_id,
            browser_owner_id=execution.browser_owner_id,
            contract_mode=execution.contract_mode,
            lease_generation=execution.lease_generation,
        )
        current = _OWNER_REGISTRY.current_browser_prompt(owner, tab=tab)
        if current is not None:
            return current
        tab_state = _OWNER_REGISTRY.resolve_tab_summary(tab, owner=owner)
        prompts = self._state.get("canonical_current_prompts")
        raw = (
            prompts.get(tab_state.receiver_tab_key)
            if isinstance(prompts, dict)
            else None
        )
        if not isinstance(raw, dict):
            return None
        prompt_type = str(raw.get("type") or "")
        if prompt_type not in {
            "alert",
            "confirm",
            "prompt",
            "before_unload",
        }:
            return None
        return _OWNER_REGISTRY.capture_browser_prompt(
            owner,
            tab=tab,
            prompt_type=cast(Any, prompt_type),
            origin=tab_state.origin,
            safe_message=str(raw.get("message") or ""),
            allows_text=bool(raw.get("allows_text")),
            native_identity=str(raw.get("native_identity") or ""),
            parent_operation_id=(
                str(raw["parent_operation_id"])
                if raw.get("parent_operation_id")
                else None
            ),
            expires_at=_OWNER_REGISTRY.pending_action_expiry(),
        )

    async def open_tab(self, url: str | None = None) -> dict[str, Any]:
        target_url = _require_target_url(url)
        return await self._create_owned_tab(
            target_url,
            selection_reason="created_explicit_new_tab",
        )

    async def create_tab(self, url: str | None = None) -> dict[str, Any]:
        """Create a new backend tab through the existing user flow."""
        return await self.open_tab(url)

    async def open_workspace_tab(self, url: str) -> dict[str, Any]:
        target_url = _require_target_url(url)
        started = perf_counter()
        tabs = await self.list_tabs()
        selected = self._current_working_tab(tabs)
        if selected is not None:
            tab_id = str(selected.get("id") or "")
            ownership = self._tab_ownership.get(tab_id, "borrowed")
            await self._claim(tab_id)
            await self._attach(tab_id)
            await self._bridge_or_engine_action(
                "navigate",
                tab_id,
                url=target_url,
            )
            selected = {**selected, "url": target_url}
            tab = self._tab_metadata(
                selected,
                ownership=ownership,
                selection_reason="reused_current_working_tab",
            )
            self._record_workspace_selection_trace(
                tab,
                duration_ms=_duration_ms(started),
                selection_reason="reused_current_working_tab",
                activation_reason="target_url_navigation",
            )
            return tab

        selected = _default_workspace_tab(
            tabs,
            workspace_id=self._state["workspace_id"],
            owner_id=self.owner_id,
            protocol_version=self.ownership_context.protocol_version,
        )
        if selected is None:
            _raise_workspace_candidate_error(
                tabs,
                workspace_id=self._state["workspace_id"],
                owner_id=self.owner_id,
                protocol_version=self.ownership_context.protocol_version,
                backend_id=self.backend_id,
                action="tabs.open",
            )
        if selected is None:
            tab = await self._create_owned_tab(
                target_url,
                selection_reason="created_controlled_workspace",
            )
            self._current_tab_id = str(tab.get("id") or "") or None
            self._record_workspace_selection_trace(
                tab,
                duration_ms=_duration_ms(started),
                selection_reason="created_controlled_workspace",
                activation_reason="target_url_create",
            )
            return tab

        tab_id = str(selected.get("id") or "")
        await self._claim(tab_id)
        await self._attach(tab_id)
        self._record_tab_ownership(tab_id, "owned")
        self._current_tab_id = tab_id
        await self._bridge_or_engine_action("navigate", tab_id, url=target_url)
        selected = {**selected, "url": target_url}
        tab = self._tab_metadata(
            selected,
            ownership="owned",
            selection_reason="reused_controlled_workspace",
        )
        self._record_workspace_selection_trace(
            tab,
            duration_ms=_duration_ms(started),
            selection_reason="reused_controlled_workspace",
            activation_reason="target_url_navigation",
        )
        return tab

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        tab = await self._find_listed_tab(tab_id)
        if tab is not None and _is_protected_tab(tab):
            self._record_ownership_trace(
                tab_id=str(tab_id),
                ownership_state_before="",
                ownership_state_after="protected",
                url=str(tab.get("url") or ""),
                status="denied",
                error_code=_PROTECTED_TAB_ERROR_CODE,
            )
            raise _protected_tab_denied(tab)
        await self._claim(tab_id)
        await self._attach(tab_id)
        self._record_tab_ownership(tab_id, "borrowed")
        self._current_tab_id = str(tab_id)
        return self._tab_metadata(
            tab or {"id": str(tab_id)},
            ownership="borrowed",
            selection_reason="explicit_tab_id",
        )

    async def page_info(self, tab_id: str) -> BrowserPageInfo:
        page_id = str(tab_id)
        for tab in await self.list_tabs():
            if str(tab.get("id") or "") == page_id:
                enriched = self._tab_metadata(
                    tab,
                    ownership=self._tab_ownership.get(page_id, "borrowed"),
                )
                return BrowserPageInfo(
                    tab_id=page_id,
                    url=str(enriched.get("url") or ""),
                    title=str(enriched.get("title") or ""),
                    metadata=_page_info_metadata(enriched),
                )
        ownership = self._tab_ownership.get(page_id, "borrowed")
        return BrowserPageInfo(
            tab_id=page_id,
            metadata={"ownership": ownership},
        )

    async def snapshot(self, tab_id: str) -> BrowserObservation:
        payload = await self._bridge_or_engine_action("snapshot", tab_id)
        return coerce_observation(str(tab_id), payload)

    async def capture_snapshot(
        self,
        tab_id: str,
        *,
        scope: Any,
        budget: Any,
    ) -> SnapshotCapture:
        """Return a registry-issued Canonical capture from trusted payload."""
        payload = await self._bridge_or_engine_action(
            "snapshot",
            tab_id,
            budget={
                "capture_nodes": int(budget.capture_nodes),
                "output_targets": int(budget.output_targets),
                "hard_maximum": int(budget.hard_maximum),
            },
        )
        if not isinstance(payload, dict):
            raise BrowserSDKError(
                "Canonical snapshot returned an invalid payload.",
                code="snapshot_payload_invalid",
            )
        from qwenpaw.browser.runtime.kernel import (
            get_current_execution_context,
        )
        from qwenpaw.runtime.root_request_coordinator import _OWNER_REGISTRY

        execution = get_current_execution_context()
        if execution is None:
            raise BrowserSDKError(
                "Canonical snapshot owner is unavailable.",
                code="browser_ownership_context_missing",
            )
        owner = BrowserRequestBinding(
            root_session_id=execution.root_session_id,
            root_task_id=execution.root_task_id,
            browser_owner_id=execution.browser_owner_id,
            contract_mode=execution.contract_mode,
            lease_generation=execution.lease_generation,
        )
        return _canonical_capture_from_payload(
            payload,
            registry=_OWNER_REGISTRY,
            owner=owner,
            receiver_tab=str(tab_id),
            scope=scope,
        )

    async def capture_source_page(
        self,
        tab_id: str,
        *,
        limit: int,
        query: TargetQuery | None = None,
        cursor: str | None = None,
        region_owner_chain: tuple[str, ...] = (),
        visual_region: dict[str, object] | None = None,
    ) -> SourceTraversalCapture:
        """Request one opaque, source-owned canonical traversal page."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("source traversal limit must be positive")
        if query is not None and not isinstance(query, TargetQuery):
            raise TypeError("query must be a TargetQuery")
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise ValueError("source traversal cursor is invalid")
        if not all(
            isinstance(owner, str) and owner for owner in region_owner_chain
        ):
            raise ValueError("region owner chain is invalid")
        if visual_region is not None and not isinstance(visual_region, dict):
            raise TypeError("visual source traversal region is invalid")
        traversal: dict[str, object] = {
            "cursor": cursor,
            "limit": limit,
        }
        if cursor is None:
            traversal["region_owner_chain"] = list(region_owner_chain)
            if query is not None:
                traversal["query"] = {
                    key: value
                    for key, value in {
                        "role": query.role,
                        "name": query.name,
                        "text": query.text,
                        "match": query.match,
                    }.items()
                    if isinstance(value, str) and value
                }
            if visual_region is not None:
                traversal["visual_region"] = dict(visual_region)
        payload = await self._bridge_or_engine_action(
            "snapshot_page",
            tab_id,
            traversal=traversal,
        )
        if not isinstance(payload, dict):
            raise BrowserSDKError(
                "Canonical source traversal returned an invalid payload.",
                code="snapshot_payload_invalid",
            )
        continuation = payload.get("continuation")
        if continuation is not None and (
            not isinstance(continuation, str) or not continuation
        ):
            raise BrowserSDKError(
                "Canonical source traversal continuation is invalid.",
                code="snapshot_payload_invalid",
            )
        end_of_collection = payload.get("end_of_collection")
        if not isinstance(end_of_collection, bool):
            raise BrowserSDKError(
                "Canonical source traversal state is invalid.",
                code="snapshot_payload_invalid",
            )
        from qwenpaw.browser.runtime.kernel import (
            get_current_execution_context,
        )
        from qwenpaw.runtime.root_request_coordinator import _OWNER_REGISTRY

        execution = get_current_execution_context()
        if execution is None:
            raise BrowserSDKError(
                "Canonical snapshot owner is unavailable.",
                code="browser_ownership_context_missing",
            )
        owner = BrowserRequestBinding(
            root_session_id=execution.root_session_id,
            root_task_id=execution.root_task_id,
            browser_owner_id=execution.browser_owner_id,
            contract_mode=execution.contract_mode,
            lease_generation=execution.lease_generation,
        )
        capture = _canonical_capture_from_payload(
            payload,
            registry=_OWNER_REGISTRY,
            owner=owner,
            receiver_tab=str(tab_id),
            trusted_bindings=_canonical_bindings_from_session_state(
                self._state,
                payload,
                owner=owner,
                receiver_tab=str(tab_id),
            ),
            trusted_surface_candidates=(
                _canonical_surface_candidates_from_session_state(
                    self._state,
                    payload,
                    owner=owner,
                    receiver_tab=str(tab_id),
                )
            ),
        )
        return SourceTraversalCapture(
            capture=capture,
            cursor=continuation,
            end_of_collection=end_of_collection,
        )

    async def capture_visual_source_page(
        self,
        tab_id: str,
        *,
        scope: VisualRegion | None = None,
        limit: int,
        query: TargetQuery | None = None,
        cursor: str | None = None,
        region_owner_chain: tuple[str, ...] = (),
    ) -> SourceTraversalCapture:
        """Page one VisualRegion through the same bridge-owned traversal."""
        if cursor is not None:
            return await self.capture_source_page(
                tab_id,
                limit=limit,
                cursor=cursor,
            )
        if not isinstance(scope, VisualRegion):
            raise TypeError("scope must be a VisualRegion")
        from qwenpaw.browser.runtime.kernel import (
            get_current_execution_context,
        )
        from qwenpaw.runtime.root_request_coordinator import _OWNER_REGISTRY

        execution = get_current_execution_context()
        if execution is None:
            raise BrowserSDKError(
                "Canonical visual owner is unavailable.",
                code="browser_ownership_context_missing",
            )
        owner = BrowserRequestBinding(
            root_session_id=execution.root_session_id,
            root_task_id=execution.root_task_id,
            browser_owner_id=execution.browser_owner_id,
            contract_mode=execution.contract_mode,
            lease_generation=execution.lease_generation,
        )
        binding = _OWNER_REGISTRY.resolve_visual_context(
            scope.visual_context,
            owner=owner,
            receiver_tab=str(tab_id),
        )
        return await self.capture_source_page(
            tab_id,
            limit=limit,
            query=query,
            cursor=cursor,
            region_owner_chain=region_owner_chain,
            visual_region={
                "x": scope.x,
                "y": scope.y,
                "width": scope.width,
                "height": scope.height,
                "generation": binding.generation,
                "viewport": binding.viewport,
                "scroll": binding.scroll,
                "zoom": binding.zoom,
                "device_pixel_ratio": binding.device_pixel_ratio,
                "layout": binding.layout,
                "visual_context_ref": str(scope.visual_context.id),
            },
        )

    async def cancel_source_page(
        self,
        tab_id: str,
        *,
        cursor: str,
    ) -> bool:
        """Release one private bridge traversal cursor without observation."""
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("source traversal cursor is invalid")
        payload = await self._bridge_or_engine_action(
            "snapshot_page",
            tab_id,
            traversal={
                "cursor": cursor,
                "limit": 1,
                "cancel": True,
                "region_owner_chain": [],
            },
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("cancelled"),
            bool,
        ):
            raise BrowserSDKError(
                "Canonical source traversal cancellation is invalid.",
                code="snapshot_payload_invalid",
            )
        return bool(payload["cancelled"])

    async def capture_visual_snapshot(
        self,
        tab_id: str,
        *,
        scope: VisualRegion,
        budget: Any,
    ) -> SnapshotCapture:
        """Ground one registry-bound viewport region through the Bridge."""
        from qwenpaw.browser.runtime.kernel import (
            get_current_execution_context,
        )
        from qwenpaw.runtime.root_request_coordinator import _OWNER_REGISTRY

        execution = get_current_execution_context()
        if execution is None:
            raise BrowserSDKError(
                "Canonical visual owner is unavailable.",
                code="browser_ownership_context_missing",
            )
        owner = BrowserRequestBinding(
            root_session_id=execution.root_session_id,
            root_task_id=execution.root_task_id,
            browser_owner_id=execution.browser_owner_id,
            contract_mode=execution.contract_mode,
            lease_generation=execution.lease_generation,
        )
        binding = _OWNER_REGISTRY.resolve_visual_context(
            scope.visual_context,
            owner=owner,
            receiver_tab=str(tab_id),
        )
        payload = await self._bridge_or_engine_action(
            "snapshot",
            tab_id,
            visual_region={
                "x": scope.x,
                "y": scope.y,
                "width": scope.width,
                "height": scope.height,
                "generation": binding.generation,
                "viewport": binding.viewport,
                "scroll": binding.scroll,
                "zoom": binding.zoom,
                "device_pixel_ratio": binding.device_pixel_ratio,
                "layout": binding.layout,
                "visual_context_ref": str(scope.visual_context.id),
                "budget": {
                    "capture_nodes": int(budget.capture_nodes),
                    "output_targets": int(budget.output_targets),
                    "hard_maximum": int(budget.hard_maximum),
                },
            },
        )
        if not isinstance(payload, dict):
            raise BrowserSDKError(
                "Canonical visual snapshot returned invalid payload.",
                code="snapshot_payload_invalid",
            )
        return _canonical_capture_from_payload(
            payload,
            registry=_OWNER_REGISTRY,
            owner=owner,
            receiver_tab=str(tab_id),
            scope=scope,
        )

    async def screenshot(self, tab_id: str) -> BrowserScreenshot:
        payload = await self._bridge_or_engine_action("screenshot", tab_id)
        return coerce_screenshot(str(tab_id), payload)

    async def screenshot_exact(
        self,
        tab_id: str,
        *,
        scope: Literal["viewport", "full_page"],
    ) -> ScreenshotCapture:
        """Return private exact bytes and controller-owned invariant facts."""
        payload = await self._bridge_or_engine_action(
            "screenshot",
            tab_id,
            full_page=scope == "full_page",
        )
        if not isinstance(payload, dict):
            raise BrowserSDKError(
                "Canonical screenshot returned an invalid payload.",
                code="screenshot_payload_invalid",
            )
        data = str(payload.get("image_base64") or "")
        complete = bool(payload.get("complete")) and bool(data)
        return ScreenshotCapture(
            scope=scope,
            data=base64.b64decode(data) if data else b"",
            media_type=str(payload.get("media_type") or "image/png"),
            name=str(payload.get("name") or f"browser-{scope}.png"),
            width=int(payload.get("width") or 0),
            height=int(payload.get("height") or 0),
            complete=complete,
            before=_screenshot_invariant_from_payload(payload.get("before")),
            after=_screenshot_invariant_from_payload(payload.get("after")),
        )

    async def extract(
        self,
        tab_id: str,
        instruction: str,
        *,
        format: str = "text",
    ) -> str:
        del instruction, format
        observation = await self.snapshot(tab_id)
        return observation.text

    async def wait_for(
        self,
        tab_id: str,
        condition: dict[str, Any] | str,
        *,
        timeout_ms: int = 10000,
    ) -> BrowserActionResult:
        return await self.action(
            tab_id,
            "wait_for",
            condition=condition,
            timeout_ms=timeout_ms,
        )

    def condition_probe(self, tab_id: str) -> ConditionProbe:
        """Return a private raw-fact probe bound to one receiver tab."""
        return _UserConditionProbe(self, str(tab_id))

    def _register_condition_region_baseline(
        self,
        region: RegionRef,
        evidence: EvidenceRef,
        digest: str,
    ) -> None:
        """Bind a private snapshot digest for future Region.changed checks."""
        region_id = str(region.to_dict().get("id") or "")
        evidence_id = str(evidence.to_dict().get("id") or "")
        if not region_id or not evidence_id or not digest:
            raise ValueError("condition region baseline is incomplete")
        self._condition_region_baselines[(region_id, evidence_id)] = digest

    async def evaluate(
        self,
        tab_id: str,
        script: str,
        *,
        read_only: bool = False,
    ) -> Any:
        metadata = await self._action_metadata(
            tab_id,
            {
                "script": script,
                "code": script,
                "read_only": read_only,
            },
        )
        evaluation = await evaluate_browser_boundary(
            policy=self._policy,
            session_id=self.session_id,
            context=self.context,
            action="evaluate",
            metadata=metadata,
        )
        raise_if_boundary_denied(
            evaluation,
            action="evaluate",
            tab_id=tab_id,
            action_metadata=metadata,
            context=self.context,
            backend_id=self.backend_id,
        )
        return await self._bridge_or_engine_action(
            "evaluate",
            tab_id,
            script=script,
            code=script,
            read_only=read_only,
        )

    async def navigate(self, tab_id: str, url: str) -> BrowserActionResult:
        return await self.action(tab_id, "navigate", url=url)

    async def back(self, tab_id: str) -> BrowserActionResult:
        return await self.action(tab_id, "back")

    async def forward(self, tab_id: str) -> BrowserActionResult:
        return await self.action(tab_id, "forward")

    async def reload(self, tab_id: str) -> BrowserActionResult:
        return await self.action(tab_id, "reload")

    async def click(
        self,
        tab_id: str,
        target: dict[str, Any],
        *,
        allow_new_context: bool = False,
    ) -> BrowserActionResult:
        return await self.action(
            tab_id,
            "click",
            target=target,
            allow_new_context=allow_new_context,
        )

    async def fill(
        self,
        tab_id: str,
        target: dict[str, Any],
        text: str,
    ) -> BrowserActionResult:
        return await self.action(tab_id, "type", target=target, text=text)

    async def press_key(self, tab_id: str, key: str) -> BrowserActionResult:
        return await self.action(tab_id, "press", key=key)

    async def scroll(
        self,
        tab_id: str,
        *,
        direction: str = "down",
        amount: str | int | None = None,
        target: dict[str, Any] | None = None,
    ) -> BrowserActionResult:
        kwargs: dict[str, Any] = {"direction": direction}
        if amount is not None:
            kwargs["amount"] = amount
        if target is not None:
            kwargs["target"] = target
        return await self.action(tab_id, "scroll", **kwargs)

    async def select_option(
        self,
        tab_id: str,
        target: dict[str, Any],
        value: Any,
    ) -> BrowserActionResult:
        return await self.action(
            tab_id,
            "select",
            target=target,
            value=value,
        )

    async def hover(
        self,
        tab_id: str,
        target: dict[str, Any],
    ) -> BrowserActionResult:
        return await self.action(tab_id, "hover", target=target)

    async def upload_file(
        self,
        tab_id: str,
        target: dict[str, Any],
        file_path: str | list[str],
    ) -> BrowserActionResult:
        return await self.action(
            tab_id,
            "upload",
            target=target,
            file_path=file_path,
        )

    async def upload_resources(
        self,
        tab_id: str,
        target: TargetRef,
        *,
        resource_ids: tuple[str, ...],
        private_paths: tuple[str, ...],
        dispatch_context: DispatchContext,
        command_payload: Mapping[str, object],
    ) -> object:
        """Forward private locators with trusted target context."""
        return await self.action(
            tab_id,
            "upload",
            dispatch_context=dispatch_context,
            command_payload=command_payload,
            target=target,
            _canonical_resource_ids=resource_ids,
            _canonical_resource_paths=private_paths,
        )

    async def download_file(
        self,
        tab_id: str,
        target: dict[str, Any] | None = None,
        *,
        timeout_ms: int = 30000,
    ) -> BrowserActionResult:
        kwargs: dict[str, Any] = {"max_wait_ms": timeout_ms}
        if target is not None:
            kwargs["target"] = target
        return await self.action(tab_id, "download", **kwargs)

    async def download_resource(
        self,
        tab_id: str,
        target: TargetRef,
        *,
        operation: Any,
        dispatch_context: DispatchContext,
        command_payload: Mapping[str, object],
    ) -> DownloadCapture:
        """Return private bytes for one exact trusted download command."""
        binding = dispatch_context._registry.resolve_target(
            target,
            receiver_tab=str(tab_id),
            owner=dispatch_context._owner_binding,
        )
        target_token = str(getattr(target, "ref", "") or "")
        if not target_token:
            raise BrowserSDKError(
                "Canonical download target token is unavailable",
                code="target_binding_invalid",
            )
        result = await self.action(
            tab_id,
            "download",
            dispatch_context=dispatch_context,
            command_payload=command_payload,
            _canonical_target_tokens={"target": target_token},
            _canonical_native_facts={"target": binding.native_identity},
        )
        payload = (
            result.data if isinstance(result, BrowserActionResult) else {}
        )
        raw_capture = payload.get("capture")
        if not isinstance(raw_capture, Mapping):
            raise BrowserSDKError(
                "Canonical download capture is unavailable",
                code="download_capture_invalid",
            )
        try:
            data = base64.b64decode(
                str(raw_capture.get("bytes_base64") or ""),
                validate=True,
            )
            return DownloadCapture(
                data=data,
                media_type=str(raw_capture.get("media_type") or ""),
                name=str(raw_capture.get("name") or ""),
                complete=bool(raw_capture.get("complete")),
                native_guid=str(raw_capture.get("native_guid") or ""),
                operation_id=str(operation.operation_id),
                operation_fingerprint=str(
                    operation.operation_fingerprint,
                ),
                command_id=str(operation.command_id),
                owner_key=operation.owner_key,
                tab_id=str(operation.tab_id),
                pre_arm_watermark=int(operation.pre_arm_watermark),
            )
        except (TypeError, ValueError) as exc:
            raise BrowserSDKError(
                "Canonical download capture is invalid",
                code="download_capture_invalid",
            ) from exc

    async def print_to_pdf_resource(
        self,
        tab_id: str,
        *,
        options: Any,
        context_before: ContextVersion,
        operation: Any,
        dispatch_context: DispatchContext,
        command_payload: Mapping[str, object],
    ) -> PagePdfCapture:
        """Return private PDF bytes with one-version context evidence."""
        if not isinstance(context_before, ContextVersion):
            raise BrowserSDKError(
                "Canonical page PDF context is unavailable",
                code="page_pdf_context_invalid",
            )
        result = await self.action(
            tab_id,
            "page_pdf",
            dispatch_context=dispatch_context,
            command_payload=command_payload,
            _canonical_pdf_options={
                "paper": options.paper,
                "landscape": options.landscape,
                "print_background": options.print_background,
                "margins": options.margins,
            },
        )
        payload = (
            result.data if isinstance(result, BrowserActionResult) else {}
        )
        raw_capture = payload.get("capture")
        if not isinstance(raw_capture, Mapping):
            raise BrowserSDKError(
                "Canonical page PDF capture is unavailable",
                code="page_pdf_capture_invalid",
            )
        try:
            data = base64.b64decode(
                str(raw_capture.get("bytes_base64") or ""),
                validate=True,
            )
            context_after: ContextVersion = context_before
            if not bool(raw_capture.get("context_same")):
                context_after = cast(
                    ContextVersion,
                    _issue_opaque_value(
                        ContextVersion,
                        _RUNTIME_VALUE_ISSUER,
                        id=f"context-changed-{operation.command_id}",
                    ),
                )
            assert isinstance(context_after, ContextVersion)
            return PagePdfCapture(
                data=data,
                context_before=context_before,
                context_after=context_after,
                complete=bool(raw_capture.get("complete")),
                operation_id=str(operation.operation_id),
                operation_fingerprint=str(
                    operation.operation_fingerprint,
                ),
                command_id=str(operation.command_id),
                owner_key=operation.owner_key,
                tab_id=str(operation.tab_id),
                pre_arm_watermark=int(operation.pre_arm_watermark),
            )
        except (TypeError, ValueError) as exc:
            raise BrowserSDKError(
                "Canonical page PDF capture is invalid",
                code="page_pdf_capture_invalid",
            ) from exc

    async def paste_controlled(
        self,
        tab_id: str,
        target: TargetRef,
        *,
        content: str,
        dispatch_context: DispatchContext,
        command_payload: Mapping[str, object],
    ) -> object:
        """Insert caller content through one trusted target dispatch."""
        binding = dispatch_context._registry.resolve_target(
            target,
            receiver_tab=str(tab_id),
            owner=dispatch_context._owner_binding,
        )
        target_token = str(getattr(target, "ref", "") or "")
        if not target_token:
            raise BrowserSDKError(
                "Canonical paste target token is unavailable",
                code="target_binding_invalid",
            )
        return await self.action(
            tab_id,
            "paste",
            dispatch_context=dispatch_context,
            command_payload=command_payload,
            _canonical_target_tokens={"target": target_token},
            _canonical_native_facts={"target": binding.native_identity},
            _canonical_paste_content=content,
        )

    async def dispatch_targeted_interaction(
        self,
        tab_id: str,
        *,
        action: Literal["click", "hover", "drag"],
        targets: tuple[tuple[str, TargetRef], ...],
        dispatch_context: DispatchContext,
        command_payload: Mapping[str, object],
    ) -> object:
        """Dispatch exact Runtime targets through the owning Bridge session."""
        if action not in {"click", "hover", "drag"}:
            raise BrowserSDKError(
                "Canonical interaction action is invalid",
                code="interaction_action_invalid",
            )
        target_tokens: dict[str, str] = {}
        native_facts: dict[str, tuple[tuple[str, str | int], ...]] = {}
        surface_policy_facts: dict[str, dict[str, object]] = {}
        for label, target in targets:
            binding = dispatch_context._registry.resolve_target(
                target,
                receiver_tab=str(tab_id),
                owner=dispatch_context._owner_binding,
            )
            token = str(binding.bridge_token or getattr(target, "ref", ""))
            if not token:
                raise BrowserSDKError(
                    "Canonical Bridge target token is unavailable",
                    code="target_binding_invalid",
                )
            target_tokens[str(label)] = token
            native_facts[str(label)] = binding.native_identity
            if binding.surface_policy_proof:
                proof_refs = set(
                    str(dispatch_context.effect_proof_ref or "").split("|"),
                )
                if binding.surface_policy_proof not in proof_refs:
                    raise BrowserSDKError(
                        "trusted surface policy proof is not sealed",
                        code="effect_proof_invalid",
                    )
                surface_policy_facts[str(label)] = {
                    "origin": binding.surface_origin,
                    "surface_identity": binding.surface_identity,
                    "revision": binding.surface_policy_revision,
                    "evidence_ref": binding.surface_policy_evidence,
                    "effect_ceiling": binding.effect_ceiling,
                    "expires_at": binding.surface_policy_expires_at,
                }
        return await self.action(
            tab_id,
            action,
            dispatch_context=dispatch_context,
            command_payload=command_payload,
            _canonical_target_tokens=target_tokens,
            _canonical_native_facts=native_facts,
            _canonical_surface_policy_facts=surface_policy_facts,
        )

    async def dispatch_scroll(
        self,
        tab_id: str,
        *,
        target: TargetRef | None,
        dispatch_context: DispatchContext,
        command_payload: Mapping[str, object],
    ) -> object:
        """Dispatch one receiver-bound scroll with optional exact target."""
        target_tokens: dict[str, str] = {}
        native_facts: dict[str, tuple[tuple[str, str | int], ...]] = {}
        surface_policy_facts: dict[str, dict[str, object]] = {}
        if target is not None:
            binding = dispatch_context._registry.resolve_target(
                target,
                receiver_tab=str(tab_id),
                owner=dispatch_context._owner_binding,
            )
            token = str(binding.bridge_token or getattr(target, "ref", ""))
            if not token:
                raise BrowserSDKError(
                    "Canonical Bridge target token is unavailable",
                    code="target_binding_invalid",
                )
            target_tokens["target"] = token
            native_facts["target"] = binding.native_identity
            if binding.surface_policy_proof:
                proof_refs = set(
                    str(dispatch_context.effect_proof_ref or "").split("|"),
                )
                if binding.surface_policy_proof not in proof_refs:
                    raise BrowserSDKError(
                        "trusted surface policy proof is not sealed",
                        code="effect_proof_invalid",
                    )
                surface_policy_facts["target"] = {
                    "origin": binding.surface_origin,
                    "surface_identity": binding.surface_identity,
                    "revision": binding.surface_policy_revision,
                    "evidence_ref": binding.surface_policy_evidence,
                    "effect_ceiling": binding.effect_ceiling,
                    "expires_at": binding.surface_policy_expires_at,
                }
        return await self.action(
            tab_id,
            "scroll",
            dispatch_context=dispatch_context,
            command_payload=command_payload,
            _canonical_target_tokens=target_tokens,
            _canonical_native_facts=native_facts,
            _canonical_surface_policy_facts=surface_policy_facts,
        )

    async def handle_dialog(
        self,
        tab_id: str,
        *,
        accept: bool = True,
        prompt_text: str | None = None,
    ) -> BrowserActionResult:
        return await self.action(
            tab_id,
            "dialog",
            accept=accept,
            prompt_text=prompt_text,
        )

    async def action(
        self,
        tab_id: str,
        name: str,
        *,
        dispatch_context: DispatchContext | None = None,
        command_payload: Mapping[str, object] | None = None,
        **kwargs: Any,
    ) -> BrowserActionResult:
        self._touch_activity()
        from qwenpaw.browser.runtime.kernel import (
            get_current_execution_context,
        )
        from qwenpaw.runtime.root_request_coordinator import _OWNER_REGISTRY

        execution = get_current_execution_context()
        if (
            execution is None
            or execution.contract_mode is not ContractMode.CANONICAL
        ):
            raise BrowserSDKError(
                "User Chrome actions require Canonical execution",
                code="canonical_dispatch_context_missing",
            )
        if not isinstance(dispatch_context, DispatchContext):
            raise BrowserSDKError(
                "Canonical action requires a DispatchContext.",
                code="canonical_dispatch_context_missing",
            )
        if not dispatch_context.is_bound_to(_OWNER_REGISTRY, str(tab_id)):
            raise BrowserSDKError(
                "Canonical DispatchContext is not valid for this tab.",
                code="dispatch_context_invalid",
            )
        if command_payload is not None:
            _validate_consumed_dispatch_context(
                _OWNER_REGISTRY,
                dispatch_context,
                execution=execution,
                tab_id=tab_id,
                command_payload=command_payload,
            )
            _validate_canonical_effect_floor(
                dispatch_context.api_id,
                command_payload,
                EffectClassification(
                    categories=dispatch_context.effects,
                    proof_ref=dispatch_context.effect_proof_ref,
                ),
            )
            envelope = _issue_trusted_command_envelope(
                dispatch_context,
                action=name,
                command_payload=command_payload,
            )
            bridge_action = cast(Any, self._bridge_or_engine_action)
            private_dispatch = {
                key: value
                for key, value in kwargs.items()
                if str(key).startswith("_canonical_")
            }
            payload = await bridge_action(
                name,
                tab_id,
                trusted_envelope=envelope,
                **dict(command_payload),
                **private_dispatch,
            )
            if isinstance(payload, BrowserActionResult):
                return payload
            return BrowserActionResult(
                ok=bool(payload.get("ok"))
                if isinstance(payload, Mapping)
                else False,
                message=(
                    str(payload.get("message") or "")
                    if isinstance(payload, Mapping)
                    else ""
                ),
                data=dict(payload) if isinstance(payload, Mapping) else {},
            )
        _validate_canonical_effect_floor(
            dispatch_context.api_id,
            kwargs,
            EffectClassification(
                categories=dispatch_context.effects,
                proof_ref=dispatch_context.effect_proof_ref,
            ),
        )
        await _OWNER_REGISTRY.consume_grant_for_dispatch(
            dispatch_context,
        )
        raise BrowserSDKError(
            "Canonical native action dispatch is not enabled in S5.",
            code="canonical_action_dispatch_not_enabled",
        )

    async def close_tab(self, tab_id: str) -> BrowserActionResult:
        normalized = str(tab_id)
        ownership = self._tab_ownership.get(normalized, "borrowed")
        await self._cleanup_tab(
            normalized,
            ownership,
            cleanup_reason="tab_close",
            close_owned=True,
        )
        if self._current_tab_id == normalized:
            self._current_tab_id = None
        message = "Tab closed" if ownership == "owned" else "Tab released"
        return BrowserActionResult(ok=True, message=message)

    def _current_working_tab(
        self,
        tabs: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        current_tab_id = str(self._current_tab_id or "")
        if not current_tab_id:
            return None
        if self._tab_ownership.get(current_tab_id) not in {
            "owned",
            "borrowed",
        }:
            return None
        for tab in tabs:
            if str(
                tab.get("id") or "",
            ) == current_tab_id and not _is_protected_tab(tab):
                return tab
        return None

    async def _create_owned_tab(
        self,
        target_url: str,
        *,
        selection_reason: str,
    ) -> dict[str, Any]:
        response = await self.bridge.request(
            "tab.create",
            {
                "protocolVersion": self.ownership_context.protocol_version,
                "ownerId": self.owner_id,
                "workspaceId": self._state["workspace_id"],
                "url": target_url,
                "active": False,
            },
        )
        tab = _tab_from_create_response(
            response,
            fallback_url=target_url,
            fallback_active=False,
            fallback_workspace=self._state["workspace_id"],
        )
        claimed = False
        try:
            await self._claim(tab["id"])
            claimed = True
            await self._attach(tab["id"])
            await self._commit_tab_metadata(tab["id"])
        except Exception:
            await self._rollback_created_owned_tab(
                tab["id"],
                release_lease=claimed,
            )
            raise
        self._record_tab_ownership(tab["id"], "owned")
        return self._tab_metadata(
            tab,
            ownership="owned",
            selection_reason=selection_reason,
        )

    async def _rollback_created_owned_tab(
        self,
        tab_id: str,
        *,
        release_lease: bool,
    ) -> None:
        try:
            tab_id_int = int(tab_id)
        except (TypeError, ValueError):
            return
        if release_lease:
            try:
                await self._release_tab(tab_id_int)
            except Exception:
                logger.debug(
                    "chrome rollback release failed tab=%s",
                    tab_id,
                    exc_info=True,
                )
        try:
            await self.bridge.request(
                "tab.close",
                {"tabId": tab_id_int, "ownerId": self.owner_id},
            )
        except Exception:
            logger.debug(
                "chrome rollback close failed tab=%s",
                tab_id,
                exc_info=True,
            )

    async def _claim_existing_tab(self, tab: dict[str, Any]) -> None:
        tab_id = str(tab.get("id") or "")
        if not tab_id or tab_id == "default":
            return
        await self._claim(tab_id)
        await self._attach(tab_id)
        self._record_tab_ownership(
            tab_id,
            _ownership_from_tab(tab, default="owned"),
        )

    async def _find_listed_tab(self, tab_id: str) -> dict[str, Any] | None:
        normalized = str(tab_id)
        for tab in await self.list_tabs():
            if str(tab.get("id") or "") == normalized:
                return tab
        return None

    def _tab_metadata(
        self,
        tab: dict[str, Any],
        *,
        ownership: _TabOwnership,
        selection_reason: str = "",
    ) -> dict[str, Any]:
        enriched = dict(tab)
        workspace_id = _workspace_id(enriched)
        enriched.update(
            {
                "workspace_id": workspace_id,
                "controlled_workspace": _is_controlled_workspace_tab(
                    enriched,
                    workspace_id=self._state["workspace_id"],
                ),
                "protected_origin": _is_protected_tab(enriched),
                "ownership": ownership,
            },
        )
        if selection_reason:
            enriched["selection_reason"] = selection_reason
        return enriched

    def _record_workspace_selection_trace(
        self,
        tab: dict[str, Any],
        *,
        duration_ms: float,
        selection_reason: str,
        activation_reason: str,
    ) -> None:
        self._trace_recorder(
            session_id=self.session_id,
            phase="tab_lifecycle",
            backend_id=self.backend_id,
            requested_context=self.context.requested,
            selected_context=self.context.selected,
            action="workspace_tab_select",
            tab_id=str(tab.get("id") or ""),
            url=str(tab.get("url") or ""),
            status="ok",
            duration_ms=duration_ms,
            metadata={
                "workspace_id": str(tab.get("workspace_id") or ""),
                "controlled_workspace": bool(
                    tab.get("controlled_workspace"),
                ),
                "ownership": str(tab.get("ownership") or ""),
                "selection_reason": selection_reason,
                "activation_reason": activation_reason,
                "protected_origin": bool(tab.get("protected_origin", False)),
            },
        )

    async def _claim(self, tab_id: str) -> None:
        claim_tab = getattr(self.bridge, "claim_tab", None)
        if not callable(claim_tab):
            return
        result = claim_tab(int(tab_id), self.holder_id)
        if hasattr(result, "__await__"):
            result = await result
        self._validate_claimed_lease(tab_id, result)

    async def _attach(self, tab_id: str) -> None:
        await self.bridge.request(
            "tab.attach",
            {"tabId": int(tab_id), "ownerId": self.owner_id},
        )

    async def _commit_tab_metadata(self, tab_id: str) -> None:
        await self.bridge.request(
            "tab.metadata.commit",
            {
                "tabId": int(tab_id),
                "ownerId": self.owner_id,
                "workspaceId": self._state["workspace_id"],
            },
        )

    def _validate_claimed_lease(
        self,
        tab_id: str,
        lease_version: Any,
    ) -> None:
        validate_or_renew = getattr(self.bridge, "validate_or_renew", None)
        if not callable(validate_or_renew):
            return
        validate_or_renew(int(tab_id), self.owner_id, lease_version)

    def _record_tab_ownership(
        self,
        tab_id: str,
        ownership: _TabOwnership,
    ) -> None:
        normalized = str(tab_id)
        if not normalized:
            return
        ownership_state = _coerce_tab_ownership(ownership)
        current = self._tab_ownership.get(normalized)
        if current == "owned" and ownership_state == "borrowed":
            return
        if ownership_state == "released":
            self._tab_ownership.pop(normalized, None)
            if self._current_tab_id == normalized:
                self._current_tab_id = None
        else:
            self._tab_ownership[normalized] = ownership_state
        self._record_ownership_trace(
            tab_id=normalized,
            ownership_state_before=current or "",
            ownership_state_after=ownership_state,
        )

    def _record_ownership_trace(
        self,
        *,
        tab_id: str,
        ownership_state_before: str,
        ownership_state_after: str,
        url: str = "",
        status: str = "ok",
        error_code: str = "",
    ) -> None:
        self._trace_recorder(
            session_id=self.session_id,
            phase="tab_lifecycle",
            backend_id=self.backend_id,
            requested_context=self.context.requested,
            selected_context=self.context.selected,
            action="tab_ownership_transition",
            tab_id=str(tab_id),
            url=url,
            status=status,
            error_code=error_code,
            metadata={
                "ownership_state": ownership_state_after,
                "ownership_state_before": ownership_state_before,
                "ownership_state_after": ownership_state_after,
            },
        )

    async def _cleanup_tab(
        self,
        tab_id: str,
        ownership: _TabOwnership,
        *,
        cleanup_reason: str,
        close_owned: bool,
    ) -> None:
        started = perf_counter()
        tab_id_int = int(tab_id)
        try:
            invalidate_source_traversals(self._state, tab_id=tab_id_int)
            await self._hide_banner_best_effort(tab_id_int)
            await self.bridge.request(
                "tab.detach",
                {"tabId": tab_id_int, "ownerId": self.owner_id},
            )
            if ownership == "owned" and close_owned:
                await self.bridge.request(
                    "tab.close",
                    {"tabId": tab_id_int, "ownerId": self.owner_id},
                )
            await self._release_tab(tab_id_int)
        except Exception:
            self._record_cleanup_trace(
                tab_id=str(tab_id),
                status="error",
                duration_ms=_duration_ms(started),
                cleanup_reason=cleanup_reason,
                closed_owned_tabs=0,
                released_borrowed_tabs=0,
                owned_tabs_remaining=self._owned_tabs_remaining(),
                error_code="browser_cleanup_failed",
            )
            raise
        self._tab_ownership.pop(str(tab_id), None)
        if self._current_tab_id == str(tab_id):
            self._current_tab_id = None
        self._record_ownership_trace(
            tab_id=str(tab_id),
            ownership_state_before=ownership,
            ownership_state_after="released",
        )
        self._record_cleanup_trace(
            tab_id=str(tab_id),
            status="ok",
            duration_ms=_duration_ms(started),
            cleanup_reason=cleanup_reason,
            closed_owned_tabs=1 if ownership == "owned" and close_owned else 0,
            released_borrowed_tabs=1 if ownership == "borrowed" else 0,
            owned_tabs_remaining=self._owned_tabs_remaining(),
            ownership_state_before=ownership,
            ownership_state_after="released",
        )

    async def _hide_banner_best_effort(self, tab_id: int) -> None:
        try:
            await self.bridge.request("banner.hide", {"tabId": tab_id})
        except Exception:
            return

    async def _release_tab(self, tab_id: int) -> None:
        release = getattr(self.bridge, "release", None)
        if not callable(release):
            return
        result = release(tab_id, self.holder_id)
        if hasattr(result, "__await__"):
            await result

    def _record_cleanup_trace(
        self,
        *,
        tab_id: str,
        status: str,
        duration_ms: float,
        cleanup_reason: str,
        closed_owned_tabs: int,
        released_borrowed_tabs: int,
        owned_tabs_remaining: int,
        ownership_state_before: str = "",
        ownership_state_after: str = "",
        error_code: str = "",
    ) -> None:
        self._trace_recorder(
            session_id=self.session_id,
            phase="cleanup",
            backend_id=self.backend_id,
            requested_context=self.context.requested,
            selected_context=self.context.selected,
            action="tab_lifecycle_cleanup",
            tab_id=tab_id,
            status=status,
            duration_ms=duration_ms,
            error_code=error_code,
            metadata={
                "closed_owned_tabs": closed_owned_tabs,
                "released_borrowed_tabs": released_borrowed_tabs,
                "owned_tabs_remaining": owned_tabs_remaining,
                "cleanup_reason": cleanup_reason,
                "ownership_state": ownership_state_after,
                "ownership_state_before": ownership_state_before,
                "ownership_state_after": ownership_state_after,
                "error_code": error_code,
            },
        )

    def _owned_tabs_remaining(self) -> int:
        return sum(
            1
            for ownership in self._tab_ownership.values()
            if ownership == "owned"
        )

    def _remaining_orphaned_tabs(self) -> int:
        return sum(
            1
            for ownership in self._tab_ownership.values()
            if ownership == "orphaned"
        )

    async def _bridge_or_engine_action(
        self,
        name: str,
        tab_id: str,
        *,
        apply_aliases: bool = True,
        **kwargs: Any,
    ) -> Any:
        self._touch_activity()
        if self._control_engine is not None:
            engine_name = (
                _ENGINE_ACTION_ALIASES.get(name, name)
                if apply_aliases
                else name
            )
            supported = getattr(
                self._control_engine,
                "supported_actions",
                None,
            )
            actions = supported() if callable(supported) else frozenset()
            if engine_name in actions:
                chunk = await self._control_engine.dispatch(
                    self._state,
                    engine_name,
                    page_id=str(tab_id),
                    **kwargs,
                )
                return _chunk_payload(chunk)
        params = {"tab_id": int(tab_id), **kwargs}
        return await self.bridge.request(name, params)

    def _touch_activity(self) -> None:
        self._last_activity_monotonic = monotonic()

    async def _action_metadata(
        self,
        tab_id: str,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(kwargs)
        if tab_id == _BROWSER_SENTINEL_TAB_ID:
            return metadata

        metadata["tab_id"] = str(tab_id)
        try:
            page = await self.page_info(tab_id)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return metadata

        if page.url and not metadata.get("url"):
            metadata["url"] = page.url
        if page.title and not metadata.get("title"):
            metadata["title"] = page.title

        url = str(metadata.get("url") or "")
        if url and not metadata.get("domain"):
            domain = _domain_from_url(url)
            if domain:
                metadata["domain"] = domain
        return metadata


def _canonical_capture_from_payload(
    payload: dict[str, Any],
    *,
    registry: BrowserSessionOwnerRegistry,
    owner: BrowserRequestBinding,
    receiver_tab: str,
    expires_at: float | None = None,
    scope: Any = None,
    trusted_bindings: dict[str, dict[str, Any]] | None = None,
    trusted_surface_candidates: dict[str, dict[str, Any]] | None = None,
) -> SnapshotCapture:
    """Convert trusted Bridge side-channel facts into owner-issued handles."""
    context_payload = payload.get("context")
    if not isinstance(context_payload, dict):
        raise BrowserSDKError(
            "Canonical snapshot context is invalid.",
            code="snapshot_payload_invalid",
        )
    try:
        native_context = NativeContextVersion(
            connection_generation=int(
                context_payload["connection_generation"],
            ),
            tab_generation=int(context_payload["tab_generation"]),
            frame_generation=int(context_payload["frame_generation"]),
            document_generation=int(
                context_payload["document_generation"],
            ),
            spa_route_generation=int(
                context_payload["spa_route_generation"],
            ),
            layout_generation=int(context_payload["layout_generation"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BrowserSDKError(
            "Canonical snapshot context is malformed.",
            code="snapshot_payload_invalid",
        ) from exc
    expiry = 0.0 if expires_at is None else float(expires_at)
    context = registry.issue_context(
        owner,
        receiver_tab=receiver_tab,
        native=native_context,
        safe_receiver=receiver_tab,
        expires_at=expiry,
    )
    trusted = (
        trusted_bindings
        if trusted_bindings is not None
        else payload.get("_trusted_bindings")
    )
    raw_targets = payload.get("targets")
    if not isinstance(trusted, dict) or not isinstance(raw_targets, list):
        raise BrowserSDKError(
            "Canonical target bindings are unavailable.",
            code="snapshot_payload_invalid",
        )
    targets: list[SnapshotTarget] = []
    for raw in raw_targets:
        if not isinstance(raw, dict):
            raise BrowserSDKError(
                "Canonical target projection is malformed.",
                code="snapshot_payload_invalid",
            )
        token = str(raw.get("binding_token") or "")
        binding_payload = trusted.get(token)
        if not token.startswith("target_") or not isinstance(
            binding_payload,
            dict,
        ):
            raise BrowserSDKError(
                "Canonical target token is not trusted.",
                code="runtime_issued_value",
            )
        _require_canonical_payload_owner(
            binding_payload,
            owner=owner,
            receiver_tab=receiver_tab,
        )
        native_identity = _binding_pairs(
            binding_payload.get("native_identity"),
            value_type=(str, int),
        )
        action_state = _binding_pairs(
            binding_payload.get("action_state"),
            value_type=bool,
        )
        allowed_actions = tuple(
            str(item) for item in binding_payload.get("allowed_actions", ())
        )
        target_binding = TargetBinding(
            root_task_id=owner.root_task_id,
            browser_owner_id=owner.browser_owner_id,
            session_id=owner.root_session_id,
            backend_id=str(binding_payload.get("backend_id") or BACKEND_ID),
            receiver_tab_key=receiver_tab,
            frame_key=str(binding_payload.get("frame_key") or ""),
            context_ref=str(context.version_ref),
            native_identity=cast(Any, native_identity),
            action_state=cast(Any, action_state),
            geometry_digest=str(
                binding_payload.get("geometry_digest") or "",
            ),
            visual_context_ref=(
                str(binding_payload["visual_context_ref"])
                if binding_payload.get("visual_context_ref") is not None
                else None
            ),
            allowed_actions=allowed_actions,
            effect_ceiling=tuple(
                str(item) for item in binding_payload.get("effect_ceiling", ())
            ),
            use_state="FRESH",
            expires_at=expiry,
            bridge_token=token,
        )
        ref = registry.issue_target(
            target_binding,
            safe_role=str(raw.get("role") or ""),
            safe_name=str(raw.get("name") or ""),
            observed_url=(
                str(raw["observed_url"])
                if raw.get("observed_url") is not None
                else None
            ),
            single_use=bool(binding_payload.get("single_use")),
        )
        targets.append(
            SnapshotTarget(
                native_identity=token,
                owner=str(raw.get("owner") or ""),
                owner_chain=(str(raw.get("owner") or ""),),
                role=str(raw.get("role") or ""),
                name=str(raw.get("name") or ""),
                states=tuple(str(item) for item in raw.get("states", ())),
                sources=cast(Any, tuple(raw.get("sources", ()))),
                identity_conflict=bool(raw.get("identity_conflict")),
                executable=bool(raw.get("executable")),
                ref=ref,
            ),
        )
    surface_candidates = (
        trusted_surface_candidates
        if trusted_surface_candidates is not None
        else payload.get("_trusted_surface_candidates", {})
    )
    if not isinstance(surface_candidates, dict):
        raise BrowserSDKError(
            "Canonical surface bindings are invalid.",
            code="snapshot_payload_invalid",
        )
    for token, binding_payload in surface_candidates.items():
        if not str(token).startswith("target_") or not isinstance(
            binding_payload,
            dict,
        ):
            raise BrowserSDKError(
                "Canonical surface token is not trusted.",
                code="runtime_issued_value",
            )
        _require_canonical_payload_owner(
            binding_payload,
            owner=owner,
            receiver_tab=receiver_tab,
        )
        native_identity = _binding_pairs(
            binding_payload.get("native_identity"),
            value_type=(str, int),
        )
        action_state = _binding_pairs(
            binding_payload.get("action_state"),
            value_type=bool,
        )
        candidate = TargetBinding(
            root_task_id=owner.root_task_id,
            browser_owner_id=owner.browser_owner_id,
            session_id=owner.root_session_id,
            backend_id=str(binding_payload.get("backend_id") or BACKEND_ID),
            receiver_tab_key=receiver_tab,
            frame_key=str(binding_payload.get("frame_key") or ""),
            context_ref=str(context.version_ref),
            native_identity=cast(Any, native_identity),
            action_state=cast(Any, action_state),
            geometry_digest=str(binding_payload.get("geometry_digest") or ""),
            visual_context_ref=str(
                binding_payload.get("visual_context_ref") or "",
            ),
            allowed_actions=(),
            effect_ceiling=(),
            use_state="FRESH",
            expires_at=expiry,
            bridge_token=str(token),
            surface_origin=str(binding_payload.get("surface_origin") or ""),
            surface_identity=str(
                binding_payload.get("surface_identity") or "",
            ),
        )
        surface_ref = registry.issue_trusted_surface_candidate(
            owner,
            candidate=candidate,
            receiver_tab=receiver_tab,
            origin=candidate.surface_origin,
            surface_identity=candidate.surface_identity,
        )
        if surface_ref is None:
            continue
        targets.append(
            SnapshotTarget(
                native_identity=str(token),
                owner=str(binding_payload.get("frame_key") or "main"),
                owner_chain=(str(binding_payload.get("frame_key") or "main"),),
                role="canvas",
                name="Reviewed visual surface",
                states=("visible",),
                sources=("DOM",),
                identity_conflict=False,
                executable=True,
                ref=surface_ref,
            ),
        )
    sources = tuple(
        SourceOutcome(
            source=cast(Any, str(item.get("source") or "AX")),
            available=bool(item.get("available")),
            examined=int(item.get("examined") or 0),
            error_code=str(item.get("error_code") or ""),
        )
        for item in payload.get("sources", ())
        if isinstance(item, dict)
    )
    gaps = tuple(
        CoverageGap(
            stage=cast(Any, str(item.get("stage") or "CAPTURE")),
            detail=CaptureGap(
                source=cast(Any, str(item.get("source") or "DOM")),
                reason=cast(
                    Any,
                    str(item.get("reason") or "SOURCE_UNAVAILABLE"),
                ),
                frontier=(
                    str(item["frontier"])
                    if item.get("frontier") is not None
                    else None
                ),
                examined=int(item.get("examined") or 0),
                omitted=int(item.get("omitted") or 0),
            ),
        )
        for item in payload.get("gaps", ())
        if isinstance(item, dict) and item.get("stage") == "CAPTURE"
    )
    regions = tuple(
        SnapshotRegionSummary(
            kind=cast(Any, str(item.get("kind") or "CONTENT")),
            owner=str(item.get("owner") or "main"),
            owner_chain=tuple(
                str(part) for part in item.get("owner_chain", ("main",))
            ),
            boundary=cast(Any, str(item.get("boundary") or "DEFAULT")),
            accessible=bool(item.get("accessible")),
            native_identity=str(
                item.get("region_token") or item.get("native_identity") or "",
            ),
        )
        for item in payload.get("regions", ())
        if isinstance(item, dict)
        and (item.get("region_token") or item.get("native_identity"))
    )
    coverage = cast(
        Coverage,
        str(payload.get("coverage") or "UNAVAILABLE"),
    )
    if coverage == "COMPLETE" and gaps:
        coverage = "PARTIAL"
    return SnapshotCapture(
        context=context,
        scope=scope or CurrentSurface(),
        generation=str(payload.get("generation") or ""),
        coverage=coverage,
        gaps=gaps,
        sources=sources,
        targets=tuple(targets),
        regions=regions,
    )


async def _canonical_action_dispatch_not_enabled(
    *,
    action: str,
) -> ActionResult:
    """Keep public Canonical mutation blocked with zero native commands."""
    return ActionResult(
        operation_id=issue_operation_id(),
        status="BLOCKED",
        retry="AFTER_OBSERVATION",
        problem=Problem(
            code="canonical_action_dispatch_not_enabled",
            phase="PREFLIGHT",
            safe_message=(
                f"Canonical action dispatch is not enabled: {action}."
            ),
        ),
        commands=(),
        effect_facts=(),
    )


def _require_canonical_payload_owner(
    payload: dict[str, Any],
    *,
    owner: BrowserRequestBinding,
    receiver_tab: str,
) -> None:
    if (
        str(payload.get("root_task_id") or "") != owner.root_task_id
        or str(payload.get("browser_owner_id") or "") != owner.browser_owner_id
        or str(payload.get("session_id") or "") != owner.root_session_id
        or str(payload.get("root_session_id") or "") != owner.root_session_id
    ):
        raise BrowserSDKError(
            "Canonical target owner mismatch.",
            code="target_wrong_owner",
        )
    if str(payload.get("tab_id") or "") != str(receiver_tab):
        raise BrowserSDKError(
            "Canonical target receiver mismatch.",
            code="target_wrong_receiver",
        )


def _canonical_bindings_from_session_state(
    state: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    owner: BrowserRequestBinding,
    receiver_tab: str,
) -> dict[str, dict[str, Any]]:
    """Resolve page tokens from server state without serializing native IDs."""
    raw_targets = payload.get("targets")
    bindings = state.get("canonical_target_bindings")
    if not isinstance(raw_targets, list):
        raise BrowserSDKError(
            "Canonical target bindings are unavailable.",
            code="snapshot_payload_invalid",
        )
    if not raw_targets:
        return {}
    if not isinstance(bindings, dict):
        raise BrowserSDKError(
            "Canonical target bindings are unavailable.",
            code="snapshot_payload_invalid",
        )
    resolved: dict[str, dict[str, Any]] = {}
    for target in raw_targets:
        if not isinstance(target, Mapping):
            raise BrowserSDKError(
                "Canonical target projection is malformed.",
                code="snapshot_payload_invalid",
            )
        token = str(target.get("binding_token") or "")
        binding = bindings.get(token)
        if not token.startswith("target_") or not isinstance(binding, dict):
            raise BrowserSDKError(
                "Canonical target token is not trusted.",
                code="runtime_issued_value",
            )
        if tuple(binding.get("owner_key", ())) != (
            owner.root_task_id,
            owner.browser_owner_id,
        ):
            raise BrowserSDKError(
                "Canonical target owner mismatch.",
                code="target_wrong_owner",
            )
        for field, expected in (
            ("root_task_id", owner.root_task_id),
            ("browser_owner_id", owner.browser_owner_id),
            ("session_id", owner.root_session_id),
        ):
            if field in binding and str(binding[field]) != expected:
                raise BrowserSDKError(
                    "Canonical target owner mismatch.",
                    code="target_wrong_owner",
                )
        if str(binding.get("root_session_id") or "") != (
            owner.root_session_id
        ):
            raise BrowserSDKError(
                "Canonical target session owner mismatch.",
                code="target_wrong_owner",
            )
        bound_tab = binding.get("tab_id")
        if (
            isinstance(bound_tab, bool)
            or not isinstance(bound_tab, int)
            or str(bound_tab) != str(receiver_tab)
        ):
            raise BrowserSDKError(
                "Canonical target receiver mismatch.",
                code="target_wrong_receiver",
            )
        resolved[token] = {
            **binding,
            "root_task_id": owner.root_task_id,
            "browser_owner_id": owner.browser_owner_id,
            "root_session_id": owner.root_session_id,
            "session_id": owner.root_session_id,
            "backend_id": BACKEND_ID,
        }
    return resolved


def _canonical_surface_candidates_from_session_state(
    state: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    owner: BrowserRequestBinding,
    receiver_tab: str,
) -> dict[str, dict[str, Any]]:
    """Resolve opaque visual-surface tokens only from bridge-owned state."""
    raw_candidates = payload.get("surface_candidates", [])
    if not isinstance(raw_candidates, list):
        raise BrowserSDKError(
            "Canonical surface candidates are invalid.",
            code="snapshot_payload_invalid",
        )
    if not raw_candidates:
        return {}
    if any(
        not isinstance(candidate, Mapping)
        or set(candidate) != {"binding_token"}
        for candidate in raw_candidates
    ):
        raise BrowserSDKError(
            "Canonical surface candidate projection is malformed.",
            code="snapshot_payload_invalid",
        )
    resolved = _canonical_bindings_from_session_state(
        state,
        {"targets": list(raw_candidates)},
        owner=owner,
        receiver_tab=receiver_tab,
    )
    if any(
        not str(binding.get("surface_identity") or "")
        or not str(binding.get("surface_origin") or "")
        or not str(binding.get("visual_context_ref") or "")
        or not _canonical_binding_context_is_current(
            state,
            binding,
            receiver_tab=receiver_tab,
        )
        for binding in resolved.values()
    ):
        raise BrowserSDKError(
            "Canonical surface candidate is stale or not trusted.",
            code="target_stale",
        )
    return resolved


def _canonical_binding_context_is_current(
    state: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    receiver_tab: str,
) -> bool:
    """Require a surface candidate to match the live bridge generation."""
    bound = binding.get("context")
    contexts = state.get("canonical_context_generations")
    if not isinstance(bound, Mapping) or not isinstance(contexts, Mapping):
        return False
    current = contexts.get(str(receiver_tab))
    if not isinstance(current, Mapping):
        return False
    fields = (
        "connection_generation",
        "tab_generation",
        "frame_generation",
        "document_generation",
        "spa_route_generation",
        "layout_generation",
    )
    try:
        return all(
            isinstance(bound[field], int)
            and not isinstance(bound[field], bool)
            and isinstance(current[field], int)
            and not isinstance(current[field], bool)
            and int(bound[field]) == int(current[field])
            for field in fields
        )
    except KeyError:
        return False


def _binding_pairs(
    value: Any,
    *,
    value_type: Any,
) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise BrowserSDKError(
            "Canonical target binding facts are malformed.",
            code="snapshot_payload_invalid",
        )
    result: list[tuple[str, Any]] = []
    for item in value:
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], value_type)
        ):
            raise BrowserSDKError(
                "Canonical target binding pair is malformed.",
                code="snapshot_payload_invalid",
            )
        result.append((item[0], item[1]))
    if not result:
        raise BrowserSDKError(
            "Canonical target binding is empty.",
            code="snapshot_payload_invalid",
        )
    return tuple(result)


class _UserConditionProbe:
    """User Chrome adapter for raw facts and watermarked hints only."""

    def __init__(
        self,
        session: ChromeExtensionBrowserSession,
        tab_id: str,
    ) -> None:
        self._session = session
        self._tab_id = tab_id

    # pylint: disable-next=too-many-branches
    async def check(self, request: ProbeRequest) -> ProbeObservation:
        store = request.receiver.observation_store
        if store is None:
            raise BrowserSDKError(
                "Condition probe requires an observation store.",
                code="condition_probe_store_unavailable",
            )
        descriptors: list[dict[str, Any]] = []
        regions: dict[str, Any] = {}
        baselines: dict[str, list[tuple[EvidenceRef, str]]] = {}
        baseline_unavailable = False
        for atom in request.condition.atoms:
            if not isinstance(atom, RegionCondition):
                continue
            key = str(atom.region.to_dict().get("id") or "")
            if key in regions:
                continue
            binding = None
            for kind in ("FRAME", "CONTENT", "OWNER"):
                try:
                    binding = store.require_region(
                        atom.region,
                        kind=cast(Any, kind),
                    )
                    break
                except Exception:  # pylint: disable=broad-exception-caught
                    continue
            if binding is None:
                evidence = store.issue_evidence(
                    kind="SNAPSHOT",
                    scope=CurrentSurface(),
                    coverage="STALE",
                    gaps=(),
                )
                return ProbeObservation(
                    evidence=evidence,
                    context=request.receiver.context,
                    coverage="STALE",
                    state="STALE",
                )
            regions[key] = atom.region
            if atom.kind == "changed":
                evidence_ref = cast(EvidenceRef, atom.value)
                evidence_id = str(
                    evidence_ref.to_dict().get("id") or "",
                )
                registry = getattr(
                    self._session,
                    "_condition_region_baselines",
                    {},
                )
                digest = registry.get((key, evidence_id))
                if digest:
                    baselines.setdefault(key, []).append(
                        (evidence_ref, str(digest)),
                    )
                else:
                    baseline_unavailable = True
            descriptors.append(
                {
                    "key": key,
                    "kind": binding.kind,
                    "owner_chain": list(binding.owner_chain),
                },
            )
        if baseline_unavailable:
            evidence = store.issue_evidence(
                kind="SNAPSHOT",
                scope=CurrentSurface(),
                coverage="UNAVAILABLE",
                gaps=(),
            )
            return ProbeObservation(
                evidence=evidence,
                context=request.receiver.context,
                coverage="UNAVAILABLE",
                state="UNAVAILABLE",
            )
        payload = await self._dispatch(
            "check",
            region_descriptors=descriptors,
        )
        if not payload.get("ok"):
            raise BrowserSDKError(
                "User Chrome condition check failed.",
                code=str(payload.get("code") or "condition_probe_failed"),
            )
        coverage = cast(
            Coverage,
            str(payload.get("coverage") or "UNAVAILABLE"),
        )
        evidence = store.issue_evidence(
            kind="SNAPSHOT",
            scope=CurrentSurface(),
            coverage=coverage,
            gaps=(),
        )
        page_payload = payload.get("page")
        page = None
        if isinstance(page_payload, dict):
            page = PageFacts(
                url=str(page_payload.get("url") or ""),
                title=str(page_payload.get("title") or ""),
                document_generation=str(
                    page_payload.get("document_generation") or "",
                ),
                ready_state=cast(
                    Any,
                    str(page_payload.get("ready_state") or "loading"),
                ),
            )
        region_facts: list[RegionFacts] = []
        raw_regions = payload.get("regions")
        if isinstance(raw_regions, list):
            for raw in raw_regions:
                if not isinstance(raw, dict):
                    continue
                region = regions.get(str(raw.get("key") or ""))
                if region is None:
                    continue
                region_facts.append(
                    RegionFacts(
                        region=region,
                        text=str(raw.get("text") or ""),
                        item_count=int(raw.get("item_count") or 0),
                        digest=str(raw.get("digest") or ""),
                        coverage=cast(
                            Coverage,
                            str(raw.get("coverage") or coverage),
                        ),
                        baselines=tuple(
                            baselines.get(str(raw.get("key") or ""), ()),
                        ),
                    ),
                )
        return ProbeObservation(
            evidence=evidence,
            context=request.receiver.context,
            coverage=coverage,
            state=cast(Any, str(payload.get("state") or "AVAILABLE")),
            page=page,
            regions=tuple(region_facts),
        )

    async def subscribe(self, request: ProbeRequest) -> ProbeSubscription:
        del request
        payload = await self._dispatch("subscribe")
        if not payload.get("ok"):
            raise BrowserSDKError(
                "User Chrome condition subscription failed.",
                code=str(payload.get("code") or "condition_subscribe_failed"),
            )
        return ProbeSubscription(
            token=str(payload.get("subscription") or ""),
            watermark=int(payload.get("watermark") or 0),
        )

    async def next_hint(
        self,
        subscription: ProbeSubscription,
        *,
        deadline: float,
    ) -> ProbeHint | None:
        timeout_ms = max(0, round((deadline - perf_counter()) * 1000))
        payload = await self._dispatch(
            "next_hint",
            subscription=str(subscription.token),
            timeout_ms=timeout_ms,
        )
        sequence = payload.get("sequence")
        if sequence is None:
            return None
        return ProbeHint(sequence=int(sequence))

    async def unsubscribe(self, subscription: ProbeSubscription) -> None:
        await self._dispatch(
            "unsubscribe",
            subscription=str(subscription.token),
        )

    async def _dispatch(
        self,
        operation: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # pylint: disable-next=protected-access
        if self._session._control_engine is None:
            raise BrowserSDKError(
                "Canonical condition probe requires the trusted "
                "control engine.",
                code="condition_probe_unavailable",
            )
        # pylint: disable-next=protected-access
        payload = await self._session._bridge_or_engine_action(
            "wait_for",
            self._tab_id,
            apply_aliases=False,
            probe_operation=operation,
            **kwargs,
        )
        if not isinstance(payload, dict):
            raise BrowserSDKError(
                "Condition probe returned an invalid payload.",
                code="condition_probe_payload_invalid",
            )
        return payload


def _screenshot_invariant_from_payload(value: Any) -> ScreenshotInvariant:
    payload = value if isinstance(value, dict) else {}
    scroll = payload.get("scroll_offset")
    viewport = payload.get("viewport")
    layout = payload.get("layout")
    return ScreenshotInvariant(
        generation=str(payload.get("generation") or ""),
        scroll_offset=(
            (
                float(scroll[0]),
                float(scroll[1]),
            )
            if isinstance(scroll, list) and len(scroll) == 2
            else (0.0, 0.0)
        ),
        focused_backend_node=(
            int(payload["focused_backend_node"])
            if isinstance(payload.get("focused_backend_node"), int)
            else None
        ),
        viewport=(
            (int(viewport[0]), int(viewport[1]))
            if isinstance(viewport, list) and len(viewport) == 2
            else (0, 0)
        ),
        layout=(
            (int(layout[0]), int(layout[1]))
            if isinstance(layout, list) and len(layout) == 2
            else (0, 0)
        ),
        event_watermark=int(payload.get("event_watermark") or 0),
        zoom=float(payload.get("zoom") or 1.0),
        device_pixel_ratio=float(payload.get("device_pixel_ratio") or 1.0),
    )


def register_user_backend_once(
    *,
    bridge_manager: Any | None = None,
    control_engine: Any | None = None,
    policy: BrowserPolicy | None = None,
    trace_recorder: Callable[..., Any] | None = None,
) -> ChromeExtensionBrowserBackend:
    """Register the Chrome Extension backend if it is not registered."""
    registry = get_default_backend_registry()
    existing = registry.get(BACKEND_ID)
    if isinstance(existing, ChromeExtensionBrowserBackend):
        existing.configure_runtime(
            bridge_manager=bridge_manager,
            control_engine=control_engine,
            trace_recorder=trace_recorder,
        )
        if policy is not None:
            existing.set_policy(policy)
        return existing
    backend = ChromeExtensionBrowserBackend(
        bridge_manager=bridge_manager,
        control_engine=control_engine,
        policy=policy,
        trace_recorder=trace_recorder,
    )
    if existing is None:
        registry.register(backend)
    return backend


async def _cleanup_action_runtime_for_request(
    control_engine: Any | None,
    **kwargs: Any,
) -> dict[str, Any]:
    cleanup = getattr(control_engine, "cleanup_for_request", None)
    if not callable(cleanup):
        return {}
    result = cleanup(
        session_id=str(kwargs.get("session_id") or ""),
        root_session_id=str(kwargs.get("root_session_id") or ""),
        holder_id=str(kwargs.get("holder_id") or ""),
        workspace_id=str(kwargs.get("workspace_id") or ""),
        cleanup_reason=str(kwargs.get("cleanup_reason") or ""),
    )
    if hasattr(result, "__await__"):
        result = await result
    return dict(result or {}) if isinstance(result, dict) else {}


async def _cleanup_extension_metadata_fallback(
    bridge: Any | None,
    *,
    owner_id: str,
    workspace_id: str,
    cleanup_reason: str,
    preserve_owned_tabs: bool,
) -> dict[str, Any]:
    if bridge is None or not owner_id or not workspace_id:
        return {}
    discover_tabs = getattr(bridge, "discover_tabs", None)
    if not callable(discover_tabs):
        return {}
    raw_tabs = discover_tabs()
    if hasattr(raw_tabs, "__await__"):
        raw_tabs = await raw_tabs
    tabs = raw_tabs if isinstance(raw_tabs, list) else []
    result: dict[str, Any] = {
        "matched_tabs": 0,
        "closed_tabs": 0,
        "released_tabs": 0,
        "closed_owned_tabs": 0,
        "released_borrowed_tabs": 0,
        "preserved_owned_tabs": 0,
        "remaining_orphaned_tabs": 0,
        "cleanup_reason": cleanup_reason,
    }
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        if str(tab.get("ownerId") or "") != owner_id:
            continue
        if (
            str(tab.get("workspaceId") or tab.get("workspace") or "")
            != workspace_id
        ):
            continue
        tab_id = tab.get("id") or tab.get("tabId")
        if tab_id is None:
            continue
        ownership = str(tab.get("ownershipState") or "").strip().lower()
        created = bool(tab.get("createdByQwenPaw", False))
        if ownership != "owned" and not created:
            continue
        result["matched_tabs"] += 1
        if preserve_owned_tabs:
            result["preserved_owned_tabs"] += 1
            result["released_tabs"] += 1
            await bridge.request(
                "tab.metadata.commit",
                {
                    "tabId": int(tab_id),
                    "ownerId": owner_id,
                    "workspaceId": workspace_id,
                },
            )
            continue
        await bridge.request(
            "tab.close",
            {"tabId": int(tab_id), "ownerId": owner_id},
        )
        result["closed_tabs"] += 1
        result["closed_owned_tabs"] += 1
    return result


async def _diagnose_actionable_round_trip(
    bridge: Any | None,
    *,
    enabled: bool,
) -> tuple[BrowserDiagnosticCheck, BrowserDiagnosticCheck]:
    owner_context = build_browser_ownership_context(
        session_id="browser-diagnostics",
        root_session_id="browser-diagnostics",
        request_scope_key="browser-diagnostics:request:scratch",
        retention="clean",
    )
    base_metadata = {
        "backend_id": BACKEND_ID,
        "protocol_version": owner_context.protocol_version,
        "owner_id": owner_context.owner_id,
        "workspace_id": owner_context.workspace_id,
        "scratch": True,
    }
    if bridge is None or not enabled:
        unavailable = BrowserDiagnosticCheck(
            name="actionable",
            status="unavailable",
            code="chrome_disconnected",
            message="Chrome Extension bridge is not connected.",
            hint_key="chrome_disconnected",
            metadata=base_metadata,
        )
        cleanup = BrowserDiagnosticCheck(
            name="cleanup_verified",
            status="unavailable",
            code="chrome_disconnected",
            message="Scratch cleanup could not run.",
            hint_key="chrome_disconnected",
            metadata=base_metadata,
        )
        return unavailable, cleanup

    protocol_error = _bridge_protocol_error(bridge)
    if protocol_error:
        code = str(
            protocol_error.get("code") or "browser_protocol_version_mismatch",
        )
        metadata = {**base_metadata, **protocol_error}
        return _diagnostic_failure_pair(
            code=code,
            message="Chrome protocol version is not supported.",
            metadata=metadata,
        )

    metadata_error = await _diagnose_workspace_metadata(
        bridge,
        owner_context=owner_context,
        base_metadata=base_metadata,
    )
    if metadata_error:
        return _diagnostic_failure_pair(
            code="browser_workspace_metadata_missing",
            message="Browser workspace tab is missing Protocol v2 metadata.",
            metadata=metadata_error,
        )

    tab_id: int | None = None
    actionable_status: BrowserDiagnosticStatus = "available"
    actionable_code = ""
    actionable_message = "Scratch Browser round-trip succeeded."
    try:
        response = await bridge.request(
            "tab.create",
            {
                "protocolVersion": owner_context.protocol_version,
                "ownerId": owner_context.owner_id,
                "workspaceId": owner_context.workspace_id,
                "url": "about:blank",
                "active": False,
                "diagnostic": True,
            },
        )
        result = response.get("result") if isinstance(response, dict) else {}
        if not isinstance(result, dict):
            result = {}
        raw_tab_id = result.get("id") or result.get("tabId")
        if raw_tab_id is None:
            raise RuntimeError(
                "Scratch Browser round-trip did not return a tab id.",
            )
        tab_id = int(raw_tab_id)
        claim_tab = getattr(bridge, "claim_tab", None)
        lease_version = None
        if callable(claim_tab):
            lease_version = claim_tab(tab_id, owner_context.owner_id)
            if hasattr(lease_version, "__await__"):
                lease_version = await lease_version
        validate_or_renew = getattr(bridge, "validate_or_renew", None)
        if callable(validate_or_renew):
            validate_or_renew(tab_id, owner_context.owner_id, lease_version)
        await bridge.request(
            "tab.ensure",
            {"tabId": tab_id, "ownerId": owner_context.owner_id},
        )
    except Exception as exc:
        info = classify_browser_error(exc)
        actionable_status = "unavailable"
        actionable_code = info.code.value
        actionable_message = str(exc) or "Scratch Browser round-trip failed."

    cleanup_status: BrowserDiagnosticStatus = "available"
    cleanup_code = ""
    cleanup_message = "Scratch Browser cleanup succeeded."
    if tab_id is None:
        cleanup_status = "unavailable"
        cleanup_code = actionable_code or "browser_cleanup_incomplete"
        cleanup_message = "Scratch tab was not created."
    else:
        try:
            await bridge.request(
                "tab.close",
                {"tabId": tab_id, "ownerId": owner_context.owner_id},
            )
        except Exception as exc:
            cleanup_status = "unavailable"
            cleanup_code = classify_browser_error(exc).code.value
            cleanup_message = str(exc) or "Scratch Browser cleanup failed."

    actionable = BrowserDiagnosticCheck(
        name="actionable",
        status=actionable_status,
        code=actionable_code,
        message=actionable_message,
        hint_key=actionable_code,
        metadata={**base_metadata, "tab_id": tab_id or ""},
    )
    cleanup = BrowserDiagnosticCheck(
        name="cleanup_verified",
        status=cleanup_status,
        code=cleanup_code,
        message=cleanup_message,
        hint_key=cleanup_code,
        metadata={**base_metadata, "tab_id": tab_id or ""},
    )
    return actionable, cleanup


def _diagnostic_failure_pair(
    *,
    code: str,
    message: str,
    metadata: dict[str, Any],
) -> tuple[BrowserDiagnosticCheck, BrowserDiagnosticCheck]:
    actionable = BrowserDiagnosticCheck(
        name="actionable",
        status="unavailable",
        code=code,
        message=message,
        hint_key=code,
        metadata=metadata,
    )
    cleanup = BrowserDiagnosticCheck(
        name="cleanup_verified",
        status="unavailable",
        code=code,
        message="Scratch cleanup skipped after early diagnostics failure.",
        hint_key=code,
        metadata=metadata,
    )
    return actionable, cleanup


def _bridge_protocol_error(bridge: Any) -> dict[str, Any]:
    error = getattr(bridge, "protocol_error", None)
    if callable(error):
        error = error()
    if not isinstance(error, dict):
        return {}
    code = str(error.get("code") or "")
    if code != "browser_protocol_version_mismatch":
        return {}
    return dict(error)


async def _diagnose_workspace_metadata(
    bridge: Any,
    *,
    owner_context: BrowserOwnershipContext,
    base_metadata: dict[str, Any],
) -> dict[str, Any]:
    discover_tabs = getattr(bridge, "discover_tabs", None)
    if not callable(discover_tabs):
        return {}
    raw_tabs = discover_tabs()
    if hasattr(raw_tabs, "__await__"):
        raw_tabs = await raw_tabs
    tabs = raw_tabs if isinstance(raw_tabs, list) else []
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        if (
            _classify_workspace_candidate(
                tab,
                workspace_id=owner_context.workspace_id,
                owner_id=owner_context.owner_id,
                protocol_version=owner_context.protocol_version,
            )
            == "metadata_missing"
        ):
            return {
                **base_metadata,
                "tab_id": str(tab.get("id") or tab.get("tabId") or ""),
            }
    return {}


def _merge_cleanup_results(
    user_result: dict[str, Any] | None,
    runtime_result: dict[str, Any] | None,
    *,
    cleanup_reason: str,
) -> dict[str, Any]:
    user_result = dict(user_result or {})
    runtime_result = dict(runtime_result or {})
    merged = dict(runtime_result)
    merged["user_backend_sessions"] = int(
        user_result.get("matched_sessions") or 0,
    )
    for key in (
        "closed_tabs",
        "released_tabs",
        "closed_owned_tabs",
        "released_borrowed_tabs",
        "preserved_owned_tabs",
        "skipped_protected_tabs",
        "remaining_orphaned_tabs",
    ):
        merged[key] = int(runtime_result.get(key) or 0) + int(
            user_result.get(key) or 0,
        )
    merged["cleanup_reason"] = str(
        runtime_result.get("cleanup_reason")
        or user_result.get("cleanup_reason")
        or cleanup_reason,
    )
    return merged


async def cleanup_user_browser_sessions_for_request(
    *,
    session_id: str = "",
    root_session_id: str = "",
    holder_id: str = "",
    request_scope_key: str = "",
    cleanup_reason: str = "finally",
    preserve_owned_tabs: bool = False,
    **_: Any,
) -> dict[str, Any]:
    """Release Browser SDK user sessions for the current request."""
    session_ids = _cleanup_registry_keys(
        session_id=session_id,
        root_session_id=root_session_id,
        holder_id=holder_id,
        request_scope_key=request_scope_key,
    )
    sessions: list[ChromeExtensionBrowserSession] = []
    seen: set[int] = set()
    for key in session_ids:
        if not key:
            continue
        for session in list(_USER_BROWSER_SESSIONS.get(key, ())):
            marker = id(session)
            if marker in seen:
                continue
            seen.add(marker)
            sessions.append(session)

    closed_tabs = 0
    released_tabs = 0
    closed_owned_tabs = 0
    released_borrowed_tabs = 0
    preserved_owned_tabs = 0
    skipped_protected_tabs = 0
    remaining_orphaned_tabs = 0
    for session in sessions:
        result = await session.cleanup_for_request(
            cleanup_reason=cleanup_reason,
            preserve_owned_tabs=preserve_owned_tabs,
        )
        closed_tabs += int(result.get("closed_tabs") or 0)
        released_tabs += int(result.get("released_tabs") or 0)
        closed_owned_tabs += int(result.get("closed_owned_tabs") or 0)
        released_borrowed_tabs += int(
            result.get("released_borrowed_tabs") or 0,
        )
        preserved_owned_tabs += int(result.get("preserved_owned_tabs") or 0)
        skipped_protected_tabs += int(
            result.get("skipped_protected_tabs") or 0,
        )
        remaining_orphaned_tabs += int(
            result.get("remaining_orphaned_tabs") or 0,
        )
    return {
        "matched_sessions": len(sessions),
        "closed_tabs": closed_tabs,
        "released_tabs": released_tabs,
        "closed_owned_tabs": closed_owned_tabs,
        "released_borrowed_tabs": released_borrowed_tabs,
        "preserved_owned_tabs": preserved_owned_tabs,
        "skipped_protected_tabs": skipped_protected_tabs,
        "remaining_orphaned_tabs": remaining_orphaned_tabs,
        "cleanup_reason": cleanup_reason,
        "preserve_owned_tabs": preserve_owned_tabs,
    }


def _cleanup_registry_keys(
    *,
    session_id: str,
    root_session_id: str,
    holder_id: str,
    request_scope_key: str,
) -> set[str]:
    if str(request_scope_key or "").strip():
        return {_normalize_session_id(request_scope_key)}
    return {
        _normalize_session_id(raw_session_id)
        for raw_session_id in (session_id, root_session_id, holder_id)
        if str(raw_session_id or "").strip()
    }


def _register_user_browser_session(
    session: ChromeExtensionBrowserSession,
) -> None:
    keys = _session_registry_keys(session)
    session.set_registry_keys(keys)
    for key in keys:
        sessions = _USER_BROWSER_SESSIONS.setdefault(key, set())
        sessions.add(session)


def _registered_user_sessions_for_bridge(
    bridge: Any,
) -> tuple[ChromeExtensionBrowserSession, ...]:
    sessions: dict[int, ChromeExtensionBrowserSession] = {}
    for registered in _USER_BROWSER_SESSIONS.values():
        for session in registered:
            if session.bridge is bridge:
                sessions[id(session)] = session
    return tuple(sessions[key] for key in sorted(sessions))


def _bridge_retirement_revision(material: object) -> int:
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return int(sha256(encoded).hexdigest()[:12], 16)


def _unregister_user_browser_session(
    session: ChromeExtensionBrowserSession,
) -> None:
    keys = session.registry_keys()
    if not keys:
        keys.add(_normalize_session_id(session.session_id))
    for key in keys:
        sessions = _USER_BROWSER_SESSIONS.get(key)
        if sessions is None:
            continue
        sessions.discard(session)
        if not sessions:
            _USER_BROWSER_SESSIONS.pop(key, None)
    session.clear_registry_keys()


def _session_registry_keys(
    session: ChromeExtensionBrowserSession,
) -> set[str]:
    raw_ids: list[Any] = [session.request_scope_key, session.holder_id]
    if session.request_scope_key == _normalize_session_id(session.session_id):
        raw_ids.append(session.session_id)
    keys = {
        _normalize_session_id(raw_id)
        for raw_id in raw_ids
        if str(raw_id or "").strip()
    }
    if not keys:
        keys.add("default")
    return keys


def _normalize_session_id(session_id: str) -> str:
    return str(session_id or "default").strip() or "default"


def _normalize_retention(retention: str) -> BrowserRetention:
    value = str(retention or "clean").strip().casefold()
    if value in {"clean", "debug", "handoff"}:
        return value  # type: ignore[return-value]
    return "clean"


def _normalize_tab(tab: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(
        tab.get("workspaceId")
        or tab.get("workspace_id")
        or tab.get("workspace")
        or "",
    )
    return {
        "id": str(tab.get("id") or tab.get("tabId") or ""),
        "url": str(tab.get("url") or tab.get("pendingUrl") or ""),
        "title": str(tab.get("title") or ""),
        "active": bool(tab.get("active", False)),
        "created_by_qwenpaw": bool(tab.get("createdByQwenPaw", False)),
        "managed": bool(tab.get("managed", False)),
        "workspace": workspace_id,
        "workspaceId": workspace_id,
        "ownerId": str(tab.get("ownerId") or ""),
        "protocolVersion": int(tab.get("protocolVersion") or 0),
        "ownershipState": str(tab.get("ownershipState") or ""),
    }


def _tab_from_create_response(
    response: dict[str, Any],
    *,
    fallback_url: str,
    fallback_active: bool,
    fallback_workspace: str,
) -> dict[str, Any]:
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        result = response if isinstance(response, dict) else {}
    tab_id = result.get("id") or result.get("tabId")
    workspace_id = str(
        result.get("workspaceId")
        or result.get("workspace")
        or fallback_workspace,
    )
    return {
        "id": str(tab_id or ""),
        "url": str(result.get("url") or fallback_url),
        "title": str(result.get("title") or ""),
        "active": bool(result.get("active", fallback_active)),
        "created_by_qwenpaw": bool(result.get("createdByQwenPaw", False)),
        "managed": bool(result.get("managed", False)),
        "workspace": workspace_id,
        "workspaceId": workspace_id,
        "ownerId": str(result.get("ownerId") or ""),
        "protocolVersion": int(result.get("protocolVersion") or 0),
        "ownershipState": str(result.get("ownershipState") or ""),
    }


def _default_workspace_tab(
    tabs: list[dict[str, Any]],
    *,
    workspace_id: str = "browser_sdk",
    owner_id: str = "",
    protocol_version: int = 2,
) -> dict[str, Any] | None:
    for tab in tabs:
        if (
            _classify_workspace_candidate(
                tab,
                workspace_id=workspace_id,
                owner_id=owner_id,
                protocol_version=protocol_version,
            )
            == "usable"
        ):
            return tab
    return None


def _raise_workspace_candidate_error(
    tabs: list[dict[str, Any]],
    *,
    workspace_id: str,
    owner_id: str,
    protocol_version: int,
    backend_id: str,
    action: str,
) -> None:
    statuses = [
        _classify_workspace_candidate(
            tab,
            workspace_id=workspace_id,
            owner_id=owner_id,
            protocol_version=protocol_version,
        )
        for tab in tabs
    ]
    if "ownership_mismatch" in statuses:
        raise BrowserSDKError(
            "Browser workspace tab is owned by another request.",
            code="browser_ownership_mismatch",
            backend_id=backend_id,
            action=action,
            metadata={
                "workspace_id": workspace_id,
                "expected_owner_id": owner_id,
            },
        )
    if "metadata_missing" in statuses:
        raise BrowserSDKError(
            "Browser workspace tab is missing Protocol v2 metadata.",
            code="browser_workspace_metadata_missing",
            backend_id=backend_id,
            action=action,
            metadata={
                "workspace_id": workspace_id,
                "expected_protocol_version": protocol_version,
            },
        )


def _classify_workspace_candidate(
    tab: dict[str, Any],
    *,
    workspace_id: str,
    owner_id: str,
    protocol_version: int,
) -> str:
    if _is_protected_tab(tab):
        return "ignored"
    if _workspace_id(tab) != workspace_id:
        return "ignored"
    tab_owner_id = str(tab.get("ownerId") or "")
    tab_protocol_version = int(tab.get("protocolVersion") or 0)
    if not tab_owner_id or tab_protocol_version != protocol_version:
        return "metadata_missing"
    if owner_id and tab_owner_id != owner_id:
        return "ownership_mismatch"
    return "usable"


def _is_controlled_workspace_tab(
    tab: dict[str, Any],
    *,
    workspace_id: str = "",
) -> bool:
    actual_workspace_id = _workspace_id(tab)
    if workspace_id:
        return actual_workspace_id == workspace_id
    return (
        actual_workspace_id == "browser_sdk"
        or actual_workspace_id.startswith(
            "browser_sdk:",
        )
    )


def _browser_workspace_id(session_id: str) -> str:
    return f"browser_sdk:{_normalize_session_id(session_id)}"


def _workspace_id(tab: dict[str, Any]) -> str:
    return str(
        tab.get("workspace")
        or tab.get("workspace_id")
        or tab.get("workspaceId")
        or "",
    )


def _ownership_from_tab(
    tab: dict[str, Any],
    *,
    default: _TabOwnership,
) -> _TabOwnership:
    value = str(tab.get("ownershipState") or tab.get("ownership") or "")
    normalized = value.strip().lower()
    if normalized in _TAB_OWNERSHIP_STATES:
        return normalized  # type: ignore[return-value]
    return default


def _require_target_url(url: str | None) -> str:
    target_url = str(url or "").strip()
    if not target_url:
        raise BrowserSDKError(
            "A non-empty target URL is required.",
            code="browser_target_url_required",
            backend_id=BACKEND_ID,
        )
    return target_url


def _page_info_metadata(tab: dict[str, Any]) -> dict[str, Any]:
    return {
        "active": bool(tab.get("active", False)),
        "workspace_id": str(tab.get("workspace_id") or ""),
        "controlled_workspace": bool(tab.get("controlled_workspace", False)),
        "ownership": str(tab.get("ownership") or ""),
        "protected_origin": bool(tab.get("protected_origin", False)),
    }


def _coerce_tab_ownership(value: str) -> _TabOwnership:
    normalized = str(value or "").strip().lower()
    if normalized not in _TAB_OWNERSHIP_STATES:
        raise ValueError(f"Unknown tab ownership state: {value}")
    return normalized  # type: ignore[return-value]


def _is_protected_tab(tab: dict[str, Any]) -> bool:
    return _is_protected_origin(str(tab.get("url") or ""))


def _is_protected_origin(url: str) -> bool:
    value = str(url or "").strip()
    if not value:
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    scheme = (parsed.scheme or "").lower()
    if scheme in _BROWSER_INTERNAL_SCHEMES:
        return True
    if scheme == "about" and value.casefold() != "about:blank":
        return True
    host = (parsed.hostname or "").lower()
    if host in _LOCAL_QWENPAW_HOSTS and parsed.port in _LOCAL_QWENPAW_PORTS:
        return True
    return False


def _protected_tab_denied(tab: dict[str, Any]) -> BrowserPolicyDenied:
    tab_id = str(tab.get("id") or "")
    return BrowserPolicyDenied(
        "Protected Chrome tab requires an explicit override.",
        code=_PROTECTED_TAB_ERROR_CODE,
        backend_id=BACKEND_ID,
        action="select_tab",
        metadata={
            "tab_id": tab_id,
            "url": str(tab.get("url") or ""),
            "protected_origin": True,
        },
    )


def _domain_from_url(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


def _browser_sdk_holder_id(session_id: str) -> str:
    session_scope = str(session_id or "default").strip() or "default"
    return f"browser_sdk:browser_sdk:{session_scope}"


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        return chunk
    try:
        content = list(getattr(chunk, "content", []) or [])
    except (AttributeError, TypeError):
        content = []
    payload: dict[str, Any] | None = None
    blocks: list[dict[str, Any]] = []
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                blocks.append({"kind": "text", "text": text})
            else:
                if payload is None and isinstance(parsed, dict):
                    payload = parsed
                else:
                    blocks.append({"kind": "text", "text": text})
            continue
        source = getattr(block, "source", None)
        blocks.append(
            {
                "kind": str(getattr(block, "type", "data")),
                "source": source,
                "name": str(getattr(block, "name", "") or ""),
            },
        )
    if payload is None:
        payload = {"ok": False, "message": str(chunk)}
    if blocks:
        payload = dict(payload)
        payload["_ordered_blocks"] = blocks
    return payload


def _diagnostic_observed_at() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "BACKEND_ID",
    "ChromeExtensionBrowserBackend",
    "ChromeExtensionBrowserSession",
    "cleanup_user_browser_sessions_for_request",
    "register_user_backend_once",
]
