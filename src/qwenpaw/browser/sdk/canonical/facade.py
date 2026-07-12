# -*- coding: utf-8 -*-
"""Canonical Browser facade physically separated from LEGACY."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..backends.registry import get_default_backend_registry
from ..governance.errors import BrowserContextUnavailable, BrowserSDKError
from ..governance.resolver import BrowserContextResolver
from ..primitives.types import BrowserOwnershipContext, ResolvedBrowserContext
from ..runtime.kernel import get_current_execution_context
from ..runtime.session_owner import ContractMode
from .tabs import BrowserTabs


@dataclass(slots=True)
class Browser:
    """Canonical connected Browser bound to trusted runtime identity."""

    session: Any
    context: ResolvedBrowserContext
    ownership_context: BrowserOwnershipContext
    tabs: BrowserTabs = field(init=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.tabs = BrowserTabs(self.session)

    @classmethod
    async def connect(
        cls,
        context: Literal["auto", "user", "isolated"] = "auto",
    ) -> "Browser":
        """Connect using only registry-issued execution identity."""
        execution = get_current_execution_context()
        if (
            execution is None
            or execution.contract_mode is not ContractMode.CANONICAL
        ):
            raise BrowserSDKError(
                (
                    "Canonical Browser requires trusted CANONICAL "
                    "execution context."
                ),
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

    async def close(self) -> None:
        """Release the current SDK lease only."""
        self._closed = True


def execution_binding(execution: Any):
    """Build the exact registry binding from trusted kernel context."""
    from ..runtime.session_owner import BrowserRequestBinding

    return BrowserRequestBinding(
        root_session_id=execution.root_session_id,
        root_task_id=execution.root_task_id,
        browser_owner_id=execution.browser_owner_id,
        contract_mode=execution.contract_mode,
        lease_generation=execution.lease_generation,
    )


__all__ = ["Browser"]
