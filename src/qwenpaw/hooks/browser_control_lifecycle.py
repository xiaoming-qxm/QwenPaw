# -*- coding: utf-8 -*-
"""Browser Control lifecycle cleanup hook."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from .base import LifecycleHook
from ..agents.tools.browser_control import cleanup_control_sessions_for_request
from ..browser_sdk.trace import record_browser_trace_event
from ..runtime.hooks import HookContext, HookResult
from ..runtime.phases import Phase

logger = logging.getLogger(__name__)

BROWSER_CONTROL_CLEANUP_EXTRA = "browser_control_cleanup"
BROWSER_CONTROL_CLEANUP_ERROR_EXTRA = "browser_control_cleanup_error"


class BrowserControlLifecycleCleanupHook(LifecycleHook):
    """Release Browser Control resources at the runtime FINALLY phase."""

    phase = Phase.FINALLY
    name = "browser_control_lifecycle_cleanup"
    priority = 50

    async def run(self, ctx: HookContext) -> HookResult:
        session_id = str(ctx.session_id or "")
        root_session_id = str(ctx.root_session_id or session_id or "")
        if not session_id and not root_session_id:
            return HookResult()

        started = perf_counter()
        try:
            result = await cleanup_control_sessions_for_request(
                session_id=session_id,
                root_session_id=root_session_id,
                workspace_id=_workspace_id(ctx),
            )
            ctx.extras[BROWSER_CONTROL_CLEANUP_EXTRA] = dict(result or {})
        except Exception as exc:  # pragma: no cover - exercised by T004 traces
            _record_cleanup_trace(
                session_id=session_id or root_session_id,
                status="error",
                duration_ms=_duration_ms(started),
                cleanup_reason="finally",
                closed_owned_tabs=0,
                released_borrowed_tabs=0,
                error_code="browser_cleanup_failed",
            )
            ctx.extras[BROWSER_CONTROL_CLEANUP_ERROR_EXTRA] = {
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            logger.debug(
                "browser_control_lifecycle_cleanup: failed",
                exc_info=True,
            )
        else:
            _record_cleanup_trace(
                session_id=session_id or root_session_id,
                status="ok",
                duration_ms=_duration_ms(started),
                cleanup_reason="finally",
                closed_owned_tabs=int((result or {}).get("closed_tabs", 0)),
                released_borrowed_tabs=int(
                    (result or {}).get("released_tabs", 0),
                ),
            )
        return HookResult()


def _workspace_id(ctx: HookContext) -> str:
    workspace = ctx.workspace
    for attr in ("workspace_id", "agent_id"):
        value = getattr(workspace, attr, "") if workspace is not None else ""
        if value:
            return str(value)
    return str(ctx.agent_id or "default")


def _record_cleanup_trace(
    *,
    session_id: str,
    status: str,
    duration_ms: float,
    cleanup_reason: str,
    closed_owned_tabs: int,
    released_borrowed_tabs: int,
    error_code: str = "",
) -> None:
    record_browser_trace_event(
        session_id=session_id,
        phase="cleanup",
        backend_id="user.chrome_extension",
        requested_context="user",
        selected_context="user",
        action="browser_control_lifecycle_cleanup",
        status=status,
        duration_ms=duration_ms,
        error_code=error_code,
        metadata={
            "closed_owned_tabs": closed_owned_tabs,
            "released_borrowed_tabs": released_borrowed_tabs,
            "cleanup_reason": cleanup_reason,
            "error_code": error_code,
        },
    )


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


__all__ = [
    "BROWSER_CONTROL_CLEANUP_ERROR_EXTRA",
    "BROWSER_CONTROL_CLEANUP_EXTRA",
    "BrowserControlLifecycleCleanupHook",
]
