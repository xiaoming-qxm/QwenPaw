# -*- coding: utf-8 -*-
"""Browser Control lifecycle cleanup hook."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from .base import LifecycleHook
from ..agents.tools.browser_control import cleanup_control_sessions_for_request
from ..browser_sdk.backends.user import (
    cleanup_user_browser_sessions_for_request,
)
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
            result = await cleanup_browser_control_request_resources(
                session_id=session_id,
                root_session_id=root_session_id,
                workspace_id=_workspace_id(ctx),
                cleanup_reason="finally",
            )
            ctx.extras[BROWSER_CONTROL_CLEANUP_EXTRA] = dict(result or {})
            cleanup_errors = int((result or {}).get("cleanup_errors", 0))
            if cleanup_errors:
                ctx.extras[BROWSER_CONTROL_CLEANUP_ERROR_EXTRA] = {
                    "cleanup_errors": cleanup_errors,
                    "error_code": "browser_cleanup_failed",
                }
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
            cleanup_errors = int((result or {}).get("cleanup_errors", 0))
            _record_cleanup_trace(
                session_id=session_id or root_session_id,
                status="error" if cleanup_errors else "ok",
                duration_ms=_duration_ms(started),
                cleanup_reason="finally",
                closed_owned_tabs=int((result or {}).get("closed_tabs", 0)),
                released_borrowed_tabs=int(
                    (result or {}).get("released_tabs", 0),
                ),
                error_code=(
                    "browser_cleanup_failed" if cleanup_errors else ""
                ),
            )
        return HookResult()


async def cleanup_browser_control_request_resources(
    *,
    session_id: str,
    root_session_id: str,
    workspace_id: str,
    cleanup_reason: str,
) -> dict[str, Any]:
    """Release Browser SDK and Browser Control engine request resources."""
    del cleanup_reason
    cleanup_errors = 0
    user_result: dict[str, int] = {}
    control_result: dict[str, int] = {}
    try:
        user_result = await cleanup_user_browser_sessions_for_request(
            session_id=session_id,
            root_session_id=root_session_id,
        )
    except Exception:
        cleanup_errors += 1
        logger.debug(
            "browser_control_lifecycle_cleanup: user backend cleanup failed",
            exc_info=True,
        )

    try:
        control_result = await cleanup_control_sessions_for_request(
            session_id=session_id,
            root_session_id=root_session_id,
            workspace_id=workspace_id,
        )
    except Exception:
        cleanup_errors += 1
        logger.debug(
            "browser_control_lifecycle_cleanup: engine cleanup failed",
            exc_info=True,
        )

    merged = _merge_cleanup_results(user_result, control_result)
    merged["cleanup_errors"] = cleanup_errors
    return merged


def _workspace_id(ctx: HookContext) -> str:
    workspace = ctx.workspace
    for attr in ("workspace_id", "agent_id"):
        value = getattr(workspace, attr, "") if workspace is not None else ""
        if value:
            return str(value)
    return str(ctx.agent_id or "default")


def _merge_cleanup_results(
    user_result: dict[str, int] | None,
    control_result: dict[str, int] | None,
) -> dict[str, int]:
    user_result = dict(user_result or {})
    control_result = dict(control_result or {})
    merged = dict(control_result)
    matched_user_sessions = int(user_result.get("matched_sessions") or 0)
    merged["user_backend_sessions"] = matched_user_sessions
    merged["closed_tabs"] = int(control_result.get("closed_tabs") or 0) + int(
        user_result.get("closed_tabs") or 0,
    )
    merged["released_tabs"] = int(
        control_result.get("released_tabs") or 0,
    ) + int(user_result.get("released_tabs") or 0)
    return merged


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
    "cleanup_browser_control_request_resources",
]
