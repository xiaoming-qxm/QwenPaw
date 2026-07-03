# -*- coding: utf-8 -*-
"""Top-level Browser facade for the unified Browser SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .backend_registry import get_default_backend_registry
from .errors import BrowserContextUnavailable
from .kernel import get_current_execution_context
from .resolver import BrowserContextResolver
from .actions import BrowserActions
from .tabs import Tabs
from .types import BrowserActionResult
from .types import BrowserContext, ResolvedBrowserContext


@dataclass
class Browser:
    """Connected browser facade.

    T002 provides the connection shell used by browser(code=...). T003 fills
    in tabs, actions, and extraction on top of the backend session.
    """

    session: Any
    context: ResolvedBrowserContext
    tabs: Tabs = field(init=False)
    actions: BrowserActions = field(init=False)

    def __post_init__(self) -> None:
        self.tabs = Tabs(self)
        self.actions = BrowserActions(self)

    @property
    def backend_id(self) -> str:
        """Return the selected backend id."""
        return self.context.backend_id

    async def close(self) -> None:
        """Release browser session resources through the selected backend."""
        close = getattr(self.session, "close", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def stop(self) -> None:
        """Destroy the backend runtime for this browser session."""
        stop = getattr(self.session, "stop", None)
        if callable(stop):
            result = stop()
            if hasattr(result, "__await__"):
                await result
            return
        await self.close()

    @classmethod
    async def connect(
        cls,
        context: BrowserContext = "auto",
        *,
        requires_user_state: bool | None = None,
        session_id: str | None = None,
    ) -> "Browser":
        """Connect to a browser backend using runtime context arbitration."""
        execution_context = get_current_execution_context()
        effective_context = _effective_context(context, execution_context)
        effective_requires_user_state = (
            requires_user_state
            if requires_user_state is not None
            else (
                execution_context.requires_user_state
                if execution_context is not None
                else None
            )
        )
        effective_session_id = (
            session_id
            or (
                execution_context.session_id
                if execution_context is not None
                else ""
            )
            or "default"
        )

        resolved = BrowserContextResolver().resolve(
            session_id=effective_session_id,
            context=effective_context,
            requires_user_state=effective_requires_user_state,
        )
        registry = get_default_backend_registry()
        backend = registry.get(resolved.backend_id)
        if backend is None:
            raise BrowserContextUnavailable(
                f"Resolved browser backend is not registered: "
                f"{resolved.backend_id}",
                backend_id=resolved.backend_id,
            )
        session = await backend.connect(effective_session_id, resolved)
        return cls(session=session, context=resolved)

    async def _call_browser_action(
        self,
        name: str,
        **kwargs: Any,
    ) -> BrowserActionResult | Any:
        action = getattr(self.session, "action", None)
        if callable(action):
            return await action("__browser__", name, **kwargs)
        browser_action = getattr(self.session, "browser_action", None)
        if callable(browser_action):
            return await browser_action(name, **kwargs)
        return {
            "ok": False,
            "message": f"Backend does not support browser action: {name}",
        }


async def connect_browser(
    context: BrowserContext = "auto",
    *,
    requires_user_state: bool | None = None,
    session_id: str | None = None,
) -> Browser:
    """Alias for Browser.connect()."""
    return await Browser.connect(
        context=context,
        requires_user_state=requires_user_state,
        session_id=session_id,
    )


def _effective_context(
    context: BrowserContext,
    execution_context: Any,
) -> BrowserContext:
    if context == "auto" and execution_context is not None:
        return execution_context.context
    return context


__all__ = ["Browser", "connect_browser"]
