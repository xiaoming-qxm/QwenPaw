# -*- coding: utf-8 -*-
"""Chrome Extension backend adapter for the unified Browser SDK."""
# pylint: disable=redefined-builtin,too-many-public-methods,too-many-statements

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from qwenpaw.browser.sdk.backends.registry import get_default_backend_registry
from qwenpaw.browser.sdk.governance.errors import (
    BrowserContextUnavailable,
    BrowserPolicyDenied,
    BrowserSDKError,
)
from qwenpaw.browser.sdk.governance.error_codes import classify_browser_error
from qwenpaw.browser.sdk.primitives.observation import (
    coerce_observation,
    coerce_screenshot,
)
from qwenpaw.browser.sdk.governance.policy import (
    BrowserPolicy,
    DefaultBrowserPolicy,
)
from qwenpaw.browser.sdk.governance.boundary import (
    action_result_with_boundary_decision,
    evaluate_browser_boundary,
    policy_metadata_kwargs,
    raise_if_boundary_denied,
)
from qwenpaw.browser.sdk.telemetry.trace import record_browser_trace_event
from qwenpaw.browser.sdk.primitives.types import (
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
from qwenpaw.browser.sdk.primitives.types import (
    BrowserObservation,
    BrowserScreenshot,
)

BACKEND_ID = "user.chrome_extension"
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
        from ..action_runtime.handlers.capabilities import backend_profile

        return backend_profile()

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
            "Chrome Extension browser bridge is not connected.",
            code="browser_bridge_disconnected",
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
        """Refresh injected Browser Bridge runtime dependencies."""
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
            code = "browser_bridge_disconnected"
            message = "Chrome Extension browser bridge is not connected."
            hint_key = code
        elif not control_engine_registered:
            status = "degraded"
            code = "browser_bridge_engine_missing"
            message = "Browser Bridge engine is not registered."
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
                    status="available"
                    if control_engine_registered
                    else "degraded",
                    code=(
                        ""
                        if control_engine_registered
                        else "browser_bridge_engine_missing"
                    ),
                    message=(
                        "Browser Bridge engine is registered."
                        if control_engine_registered
                        else "Browser Bridge engine is not registered."
                    ),
                    hint_key=(
                        ""
                        if control_engine_registered
                        else "browser_bridge_engine_missing"
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
                "Chrome Extension browser bridge is not connected.",
                code="browser_bridge_disconnected",
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
                "Chrome Extension browser bridge is not connected.",
                code="browser_bridge_disconnected",
                backend_id=self.backend_id,
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
        """Release Browser Bridge resources owned by one request."""
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
                "browser_bridge user backend cleanup failed",
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
                "browser_bridge action runtime cleanup failed",
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
                "browser_bridge extension metadata cleanup failed",
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
        self._state: dict[str, Any] = {
            "workspace_id": self.ownership_context.workspace_id,
            "owner_id": self.owner_id,
            "ownership_context": self.ownership_context,
        }
        self._tab_ownership: dict[str, _TabOwnership] = {}
        self._current_tab_id: str | None = None
        self._registry_keys: set[str] = set()

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
                    "browser_bridge tab cleanup failed tab=%s",
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
        tabs = await self.bridge.discover_tabs()
        return [_normalize_tab(tab) for tab in tabs if isinstance(tab, dict)]

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

    async def screenshot(self, tab_id: str) -> BrowserScreenshot:
        payload = await self._bridge_or_engine_action("screenshot", tab_id)
        return coerce_screenshot(str(tab_id), payload)

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
        **kwargs: Any,
    ) -> BrowserActionResult:
        metadata = await self._action_metadata(
            tab_id,
            policy_metadata_kwargs(name, kwargs),
        )
        evaluation = await evaluate_browser_boundary(
            policy=self._policy,
            session_id=self.session_id,
            context=self.context,
            action=name,
            metadata=metadata,
        )
        raise_if_boundary_denied(
            evaluation,
            action=name,
            tab_id=tab_id,
            action_metadata=metadata,
            context=self.context,
            backend_id=self.backend_id,
        )

        if tab_id == _BROWSER_SENTINEL_TAB_ID:
            payload = await self.bridge.request(name, dict(kwargs))
        else:
            payload = await self._bridge_or_engine_action(
                name,
                tab_id,
                **kwargs,
            )
        return action_result_with_boundary_decision(
            payload,
            name,
            boundary_decision=evaluation.boundary_decision,
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
                    "browser_bridge rollback release failed tab=%s",
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
                "browser_bridge rollback close failed tab=%s",
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
            code="browser_bridge_disconnected",
            message="Chrome Extension bridge is not connected.",
            hint_key="browser_bridge_disconnected",
            metadata=base_metadata,
        )
        cleanup = BrowserDiagnosticCheck(
            name="cleanup_verified",
            status="unavailable",
            code="browser_bridge_disconnected",
            message="Scratch cleanup could not run.",
            hint_key="browser_bridge_disconnected",
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
            message="Browser Bridge protocol version is not supported.",
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
        "Protected Browser Bridge tab requires an explicit override.",
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
