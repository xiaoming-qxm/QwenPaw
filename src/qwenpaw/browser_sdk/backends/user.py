# -*- coding: utf-8 -*-
"""Chrome Extension backend adapter for the unified Browser SDK."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from qwenpaw.browser.connection_manager import get_bridge_connection_manager
from qwenpaw.browser.control_engine import get_control_engine
from qwenpaw.browser_sdk.backend_registry import get_default_backend_registry
from qwenpaw.browser_sdk.errors import (
    BrowserContextUnavailable,
    BrowserPolicyDenied,
)
from qwenpaw.browser_sdk.observation import (
    coerce_observation,
    coerce_screenshot,
)
from qwenpaw.browser_sdk.policy import (
    BrowserPolicy,
    DefaultBrowserPolicy,
    maybe_await_policy_decision,
)
from qwenpaw.browser_sdk.risk import classify_browser_action
from qwenpaw.browser_sdk.types import (
    BrowserActionRequest,
    BrowserActionResult,
    BrowserBackendCapabilities,
    BrowserBackendDiagnostic,
    BrowserContextRequest,
    BrowserDiagnosticCheck,
    BrowserDiagnosticStatus,
    BrowserPageInfo,
    ResolvedBrowserContext,
)
from qwenpaw.browser_sdk.types import BrowserObservation, BrowserScreenshot

BACKEND_ID = "user.chrome_extension"
_BROWSER_SENTINEL_TAB_ID = "__browser__"
_ENGINE_ACTION_ALIASES = {
    "back": "navigate_back",
    "forward": "navigate_forward",
    "press": "press_key",
    "select": "select_option",
}


class ChromeExtensionBrowserBackend:
    """Browser SDK backend backed by the Chrome Extension bridge."""

    backend_id = BACKEND_ID

    def __init__(
        self,
        *,
        bridge_manager: Any | None = None,
        control_engine: Any | None = None,
        policy: BrowserPolicy | None = None,
    ) -> None:
        self._bridge_manager = bridge_manager
        self._control_engine = control_engine
        self._policy = policy or DefaultBrowserPolicy()

    def capabilities(self) -> BrowserBackendCapabilities:
        return BrowserBackendCapabilities(
            backend_id=self.backend_id,
            browser_context="user",
            features=frozenset({"chrome_extension_bridge"}),
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

    def diagnose(self) -> BrowserBackendDiagnostic:
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
            code = "browser_control_engine_missing"
            message = "Browser Control engine is not registered."
            hint_key = code
        else:
            status = "available"
            code = ""
            message = "Chrome Extension browser backend is available."
            hint_key = ""
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
                    name="bridge_manager",
                    status="available"
                    if bridge_manager_present
                    else "unavailable",
                    code="" if bridge_manager_present else code,
                    message=(
                        "Bridge manager is configured."
                        if bridge_manager_present
                        else "Bridge manager is missing."
                    ),
                    hint_key="" if bridge_manager_present else hint_key,
                    metadata={"backend_id": self.backend_id},
                ),
                BrowserDiagnosticCheck(
                    name="bridge_connection",
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
                    name="control_engine",
                    status="available"
                    if control_engine_registered
                    else "degraded",
                    code=""
                    if control_engine_registered
                    else "browser_control_engine_missing",
                    message=(
                        "Browser Control engine is registered."
                        if control_engine_registered
                        else "Browser Control engine is not registered."
                    ),
                    hint_key=""
                    if control_engine_registered
                    else "browser_control_engine_missing",
                    metadata={"backend_id": self.backend_id},
                ),
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
        return ChromeExtensionBrowserSession(
            bridge=bridge,
            session_id=session_id,
            context=context,
            policy=self._policy,
            control_engine=self._engine(),
        )

    def _bridge(self) -> Any | None:
        manager = self._bridge_manager or get_bridge_connection_manager()
        if manager is None:
            return None
        get_connection = getattr(manager, "get_connection", None)
        if callable(get_connection):
            return get_connection()  # pylint: disable=not-callable
        return manager

    def _engine(self) -> Any | None:
        return self._control_engine or get_control_engine()


class ChromeExtensionBrowserSession:
    """Connected user-browser session for Browser SDK facade calls."""

    backend_id = BACKEND_ID

    def __init__(
        self,
        *,
        bridge: Any,
        session_id: str,
        context: ResolvedBrowserContext,
        policy: BrowserPolicy,
        control_engine: Any | None = None,
    ) -> None:
        self.bridge = bridge
        self.session_id = session_id
        self.context = context
        self.holder_id = f"browser_sdk:{session_id or 'default'}"
        self._policy = policy
        self._control_engine = control_engine
        self._state: dict[str, Any] = {"workspace_id": "browser_sdk"}

    async def close(self) -> None:
        release_all = getattr(self.bridge, "release_all", None)
        if callable(release_all):
            result = release_all(self.holder_id)
            if hasattr(result, "__await__"):
                await result

    async def active_tab(self) -> dict[str, Any]:
        tabs = await self.list_tabs()
        for tab in tabs:
            if tab.get("active"):
                return tab
        return tabs[0] if tabs else {"id": "default"}

    async def list_tabs(self) -> list[dict[str, Any]]:
        tabs = await self.bridge.discover_tabs()
        return [_normalize_tab(tab) for tab in tabs if isinstance(tab, dict)]

    async def open_tab(self, url: str | None = None) -> dict[str, Any]:
        target_url = url or "about:blank"
        payload = {"url": target_url, "active": True}
        response = await self.bridge.request("tab.create", payload)
        tab = _tab_from_create_response(response, fallback_url=target_url)
        await self._claim(tab["id"])
        return tab

    async def select_tab(self, tab_id: str) -> dict[str, Any]:
        await self._claim(tab_id)
        await self.bridge.request(
            "tab.attach",
            {"tabId": int(tab_id), "holderId": self.holder_id},
        )
        return {"id": str(tab_id)}

    async def page_info(self, tab_id: str) -> BrowserPageInfo:
        page_id = str(tab_id)
        for tab in await self.list_tabs():
            if str(tab.get("id") or "") == page_id:
                return BrowserPageInfo(
                    tab_id=page_id,
                    url=str(tab.get("url") or ""),
                    title=str(tab.get("title") or ""),
                    metadata={"active": bool(tab.get("active", False))},
                )
        return BrowserPageInfo(tab_id=page_id)

    async def snapshot(self, tab_id: str) -> BrowserObservation:
        payload = await self._bridge_or_engine_action("snapshot", tab_id)
        return coerce_observation(str(tab_id), payload)

    async def screenshot(self, tab_id: str) -> BrowserScreenshot:
        payload = await self._bridge_or_engine_action("screenshot", tab_id)
        return coerce_screenshot(str(tab_id), payload)

    async def evaluate(
        self,
        tab_id: str,
        script: str,
        *,
        read_only: bool = False,
    ) -> Any:
        return await self._bridge_or_engine_action(
            "evaluate",
            tab_id,
            script=script,
            code=script,
            read_only=read_only,
        )

    async def action(
        self,
        tab_id: str,
        name: str,
        **kwargs: Any,
    ) -> BrowserActionResult:
        risk = classify_browser_action(name, kwargs)
        decision = await maybe_await_policy_decision(
            self._policy.allow_action(
                BrowserActionRequest(
                    session_id=self.session_id,
                    action=name,
                    context=self.context,
                    sensitive=risk.sensitive,
                    risk=risk,
                    metadata=dict(kwargs),
                ),
            ),
        )
        if not decision.allowed:
            raise BrowserPolicyDenied(
                decision.reason or "Browser action denied by policy",
                action=name,
                backend_id=self.backend_id,
                metadata=decision.metadata,
            )

        if tab_id == _BROWSER_SENTINEL_TAB_ID:
            payload = await self.bridge.request(name, dict(kwargs))
        else:
            payload = await self._bridge_or_engine_action(
                name,
                tab_id,
                **kwargs,
            )
        return _action_result(payload, name)

    async def close_tab(self, tab_id: str) -> BrowserActionResult:
        release = getattr(self.bridge, "release", None)
        if callable(release):
            result = release(int(tab_id), self.holder_id)
            if hasattr(result, "__await__"):
                await result
        return BrowserActionResult(ok=True, message="Tab released")

    async def _claim(self, tab_id: str) -> None:
        claim_tab = getattr(self.bridge, "claim_tab", None)
        if not callable(claim_tab):
            return
        result = claim_tab(int(tab_id), self.holder_id)
        if hasattr(result, "__await__"):
            await result

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


def register_user_backend_once(
    *,
    policy: BrowserPolicy | None = None,
) -> ChromeExtensionBrowserBackend:
    """Register the Chrome Extension backend if it is not registered."""
    registry = get_default_backend_registry()
    existing = registry.get(BACKEND_ID)
    if isinstance(existing, ChromeExtensionBrowserBackend):
        if policy is not None:
            existing.set_policy(policy)
        return existing
    backend = ChromeExtensionBrowserBackend(policy=policy)
    if existing is None:
        registry.register(backend)
    return backend


def _normalize_tab(tab: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(tab.get("id") or tab.get("tabId") or ""),
        "url": str(tab.get("url") or tab.get("pendingUrl") or ""),
        "title": str(tab.get("title") or ""),
        "active": bool(tab.get("active", False)),
    }


def _tab_from_create_response(
    response: dict[str, Any],
    *,
    fallback_url: str,
) -> dict[str, Any]:
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        result = response if isinstance(response, dict) else {}
    tab_id = result.get("id") or result.get("tabId")
    return {
        "id": str(tab_id or ""),
        "url": str(result.get("url") or fallback_url),
        "title": str(result.get("title") or ""),
        "active": True,
    }


def _action_result(payload: Any, name: str) -> BrowserActionResult:
    if isinstance(payload, BrowserActionResult):
        return payload
    if isinstance(payload, dict):
        return BrowserActionResult(
            ok=bool(payload.get("ok", True)),
            message=str(payload.get("message") or name),
            needs_observation=bool(payload.get("needs_observation", True)),
            data=dict(payload.get("data") or {}),
        )
    return BrowserActionResult(ok=True, message=str(payload or name))


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, dict):
        return chunk
    try:
        content = getattr(chunk, "content", [])
        first = content[0] if content else None
        text = getattr(first, "text", "")
    except (AttributeError, IndexError, TypeError):
        text = str(chunk)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {"ok": False, "message": str(text or "")}
    return parsed if isinstance(parsed, dict) else {"ok": False}


def _diagnostic_observed_at() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "BACKEND_ID",
    "ChromeExtensionBrowserBackend",
    "ChromeExtensionBrowserSession",
    "register_user_backend_once",
]
