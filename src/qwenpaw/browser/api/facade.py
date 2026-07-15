# -*- coding: utf-8 -*-
"""Browser SDK facade."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Literal

from ..action_runner import ActionRunner
from ..backends.registry import get_default_backend_registry
from ..condition_evaluator import ConditionEvaluator
from ..governance.errors import (
    BrowserContextUnavailable,
    BrowserSDKError,
)
from ..governance.resolver import BrowserContextResolver
from ..primitives.types import BrowserOwnershipContext, ResolvedBrowserContext
from ..runtime.kernel import get_current_execution_context
from ..runtime.resources import ResourceStore, get_or_create_resource_store
from .contracts import ResourceHandle
from .tabs import BrowserTabs


@dataclass(frozen=True, slots=True)
class BrowserResources:
    """Thin public view over the current task-owned ResourceStore."""

    _store: ResourceStore = field(repr=False)

    def list(self) -> list[ResourceHandle]:
        return self._store.list()

    def require(self, resource_id: str) -> ResourceHandle:
        return self._store.require(resource_id)

    def from_workspace(self, path: str) -> ResourceHandle:
        return self._store.ingest_workspace_file(path)


@dataclass(slots=True)
class Browser:
    """Connected Browser bound to trusted runtime identity."""

    session: Any
    context: ResolvedBrowserContext
    ownership_context: BrowserOwnershipContext
    tabs: BrowserTabs = field(init=False)
    resources: BrowserResources = field(init=False)
    _condition_evaluator: ConditionEvaluator = field(init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        owner_key = (
            self.ownership_context.request_scope_key.split(":", 1)[0],
            self.ownership_context.owner_id,
        )
        store = get_or_create_resource_store(owner_key)
        self._condition_evaluator = ConditionEvaluator(clock=_RuntimeClock())
        profile = get_default_backend_registry().profile(
            self.context.backend_id,
        )
        execution = get_current_execution_context()
        target_registry = None
        owner_binding = None
        action_runner = None
        if execution is not None:
            from qwenpaw.runtime.root_request_coordinator import (
                _OWNER_REGISTRY,
            )

            target_registry = _OWNER_REGISTRY
            owner_binding = execution_binding(execution)
            approval_requester = getattr(self.session, "_policy", None)
            trusted_surface_policy = getattr(
                approval_requester,
                "trusted_surface_policy",
                None,
            )
            if trusted_surface_policy is not None:
                _OWNER_REGISTRY.install_trusted_surface_policy(
                    owner_binding,
                    trusted_surface_policy,
                )
            action_runner = ActionRunner(
                registry=_OWNER_REGISTRY,
                approval_requester=approval_requester,
            )
        self.tabs = BrowserTabs(
            _session=self.session,
            _resources=store,
            _condition_evaluator=self._condition_evaluator,
            _profile=profile,
            _target_registry=target_registry,
            _owner_binding=owner_binding,
            _action_runner=action_runner,
        )
        self.resources = BrowserResources(store)

    @classmethod
    async def connect(
        cls,
        context: Literal["auto", "user", "isolated"] = "auto",
    ) -> "Browser":
        """Connect using only registry-issued execution identity."""
        execution = get_current_execution_context()
        if execution is None:
            raise BrowserSDKError(
                "Browser requires a trusted execution context.",
                code="browser_ownership_context_missing",
                action="browser.connect",
            )
        resolved = BrowserContextResolver().resolve(
            session_id=execution.session_id,
            context=context,
            requires_user_state=execution.requires_user_state,
            browser_intent=execution.browser_intent,
        )
        backend = get_default_backend_registry().get(resolved.backend_id)
        if backend is None:
            raise BrowserContextUnavailable(
                (
                    "Resolved browser backend is not registered: "
                    f"{resolved.backend_id}"
                ),
                backend_id=resolved.backend_id,
            )
        ownership = BrowserOwnershipContext(
            protocol_version=2,
            session_id=execution.session_id,
            root_session_id=execution.root_session_id,
            request_scope_key=(
                f"{execution.root_task_id}:{execution.browser_owner_id}"
            ),
            owner_id=execution.browser_owner_id,
            workspace_id=(
                f"browser_workspace:{execution.root_task_id}:"
                f"{execution.browser_owner_id}"
            ),
            retention="clean",
        )
        session = await backend.connect(
            execution.session_id,
            resolved,
            request_scope_key=ownership.request_scope_key,
            retention="clean",
            ownership_context=ownership,
        )
        from qwenpaw.runtime.root_request_coordinator import _OWNER_REGISTRY

        await _OWNER_REGISTRY.bind_owner_attachment(
            execution_binding(execution),
            resolved_context=resolved.selected,
        )
        return cls(
            session=session,
            context=resolved,
            ownership_context=ownership,
        )

    @classmethod
    async def help(cls, api_id: str | None = None) -> str:
        """Return model-facing Browser SDK usage help without a connection."""
        from ..docs.capabilities import browser_sdk_help

        return browser_sdk_help(api_id=api_id)

    async def close(self) -> None:
        """Release the current SDK lease only."""
        self._closed = True

    @property
    def capabilities(self) -> dict[str, Any]:
        """Return reviewed static build/release capability truth."""
        from ..docs.capabilities import browser_support_manifest

        return browser_support_manifest()

    @property
    def session_capabilities(self) -> dict[str, Any]:
        """Return static truth narrowed by explicit backend session profile."""
        from ..docs.capabilities import (
            browser_support_manifest,
            compute_session_capabilities,
        )

        backend = get_default_backend_registry().profile(
            self.context.backend_id,
        )
        manifest = browser_support_manifest()
        fingerprints = {
            key: str(manifest.get(key) or "")
            for key in (
                "build_fingerprint",
                "contract_fingerprint",
                "profile_fingerprint",
                "extension_fingerprint",
                "provider_fingerprint",
            )
        }
        retirement_limits = {
            key: int(manifest.get(key) or 0)
            for key in (
                "max_retained_state_ttl_seconds",
                "max_legacy_token_ttl_seconds",
            )
        }
        if backend is None:
            return {
                "ready": (),
                "blocked": {"all": "backend_profile_missing"},
                "fingerprints": fingerprints,
                "retirement_limits": retirement_limits,
            }
        execution = get_current_execution_context()
        provider = getattr(execution, "provider_block_profile", None)
        if provider is None:
            provider = type(
                "NoProviderBlocks",
                (),
                {
                    "text": False,
                    "data": False,
                    "image": False,
                    "artifact": False,
                    "provider_fingerprint": manifest.get(
                        "provider_fingerprint",
                    ),
                },
            )()
        session = compute_session_capabilities(
            manifest=manifest,
            backend=backend,
            provider=provider,
            session_ready=frozenset(backend.variants),
        )
        return {
            "ready": tuple(sorted(session.ready)),
            "blocked": session.blocked,
            "fingerprints": session.fingerprints,
            "retirement_limits": session.retirement_limits,
        }


def execution_binding(execution: Any):
    """Build the exact registry binding from trusted kernel context."""
    from ..runtime.session_owner import BrowserRequestBinding

    return BrowserRequestBinding(
        root_session_id=execution.root_session_id,
        root_task_id=execution.root_task_id,
        browser_owner_id=execution.browser_owner_id,
        lease_generation=execution.lease_generation,
    )


class _RuntimeClock:
    """Production monotonic clock injected into the sole evaluator."""

    def now(self) -> float:
        return monotonic()

    async def sleep_until(self, deadline: float) -> None:
        await asyncio.sleep(max(0.0, deadline - monotonic()))


__all__ = ["Browser", "BrowserResources"]
