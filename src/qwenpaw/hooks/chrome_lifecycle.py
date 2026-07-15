# -*- coding: utf-8 -*-
"""Chrome lifecycle cleanup hook."""

from __future__ import annotations

from typing import Any

from .base import LifecycleHook
from ..browser.backends.registry import (
    cleanup_browser_backend_request_resources,
)
from ..browser.primitives.types import build_browser_ownership_context
from ..runtime.hooks import HookContext, HookResult
from ..runtime.phases import Phase

CHROME_CLEANUP_EXTRA = "chrome_cleanup"
CHROME_CLEANUP_ERROR_EXTRA = "chrome_cleanup_error"
CHROME_KERNEL_CLEANUP_EXTRA = "chrome_kernel_cleanup"


class ChromeLifecycleCleanupHook(LifecycleHook):
    """Release Chrome resources at the runtime FINALLY phase."""

    phase = Phase.FINALLY
    name = "chrome_lifecycle_cleanup"
    priority = 50

    async def run(self, ctx: HookContext) -> HookResult:
        ctx.extras["chrome_request_released"] = True
        return HookResult()


async def cleanup_chrome_request_resources(
    *,
    session_id: str,
    root_session_id: str,
    request_scope_key: str = "",
    workspace_id: str,
    cleanup_reason: str,
    preserve_owned_tabs: bool = False,
) -> dict[str, Any]:
    """Release Browser SDK backend request resources."""
    ownership_context = build_browser_ownership_context(
        session_id=session_id,
        root_session_id=root_session_id,
        request_scope_key=request_scope_key,
        retention="debug" if preserve_owned_tabs else "clean",
    )
    return await cleanup_browser_backend_request_resources(
        session_id=session_id,
        root_session_id=root_session_id,
        request_scope_key=request_scope_key,
        owner_id=ownership_context.owner_id,
        workspace_id=ownership_context.workspace_id,
        legacy_workspace_id=workspace_id,
        ownership_context=ownership_context,
        cleanup_reason=cleanup_reason,
        preserve_owned_tabs=preserve_owned_tabs,
    )


__all__ = [
    "CHROME_CLEANUP_ERROR_EXTRA",
    "CHROME_CLEANUP_EXTRA",
    "CHROME_KERNEL_CLEANUP_EXTRA",
    "ChromeLifecycleCleanupHook",
    "cleanup_chrome_request_resources",
]
