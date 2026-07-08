# -*- coding: utf-8 -*-
"""Browser Bridge lifecycle cleanup hook."""

from __future__ import annotations

import logging
import asyncio
from time import perf_counter
from typing import Any

from .base import LifecycleHook
from ..browser.sdk.backends.registry import (
    cleanup_browser_backend_request_resources,
)
from ..browser.sdk.primitives.types import build_browser_ownership_context
from ..browser.sdk.governance.errors import BrowserPolicyDenied
from ..browser.sdk.runtime.kernel import cleanup_browser_kernels_for_lifecycle
from ..browser.sdk.telemetry.trace import record_browser_trace_event
from ..runtime.hooks import HookContext, HookResult
from ..runtime.phases import Phase

logger = logging.getLogger(__name__)

BROWSER_BRIDGE_CLEANUP_EXTRA = "browser_bridge_cleanup"
BROWSER_BRIDGE_CLEANUP_ERROR_EXTRA = "browser_bridge_cleanup_error"
BROWSER_BRIDGE_KERNEL_CLEANUP_EXTRA = "browser_bridge_kernel_cleanup"


class BrowserBridgeLifecycleCleanupHook(LifecycleHook):
    """Release Browser Bridge resources at the runtime FINALLY phase."""

    phase = Phase.FINALLY
    name = "browser_bridge_lifecycle_cleanup"
    priority = 50

    async def run(self, ctx: HookContext) -> HookResult:
        session_id = str(ctx.session_id or "")
        root_session_id = str(ctx.root_session_id or session_id or "")
        if not session_id and not root_session_id:
            return HookResult()

        started = perf_counter()
        cleanup_reason = _cleanup_reason(ctx)
        preserve_owned_tabs = _preserve_owned_tabs(
            ctx,
            cleanup_reason=cleanup_reason,
        )
        request_scope_key = _request_scope_key(ctx)
        _record_cleanup_start_trace(
            session_id=session_id or root_session_id,
            cleanup_reason=cleanup_reason,
            request_scope={
                "session_id": session_id,
                "root_session_id": root_session_id,
                "request_scope_key": request_scope_key,
                "workspace_id": _workspace_id(ctx),
                "preserve_owned_tabs": preserve_owned_tabs,
            },
        )
        try:
            result = await cleanup_browser_bridge_request_resources(
                session_id=session_id,
                root_session_id=root_session_id,
                request_scope_key=request_scope_key,
                workspace_id=_workspace_id(ctx),
                cleanup_reason=cleanup_reason,
                preserve_owned_tabs=preserve_owned_tabs,
            )
            ctx.extras[BROWSER_BRIDGE_CLEANUP_EXTRA] = dict(result or {})
            cleanup_errors = int((result or {}).get("cleanup_errors", 0))
            if cleanup_errors:
                ctx.extras[BROWSER_BRIDGE_CLEANUP_ERROR_EXTRA] = {
                    "cleanup_errors": cleanup_errors,
                    "error_code": "browser_cleanup_failed",
                }
        except Exception as exc:  # pragma: no cover - exercised by T004 traces
            _record_cleanup_trace(
                session_id=session_id or root_session_id,
                status="error",
                duration_ms=_duration_ms(started),
                cleanup_reason=cleanup_reason,
                closed_owned_tabs=0,
                released_borrowed_tabs=0,
                error_code="browser_cleanup_failed",
            )
            ctx.extras[BROWSER_BRIDGE_CLEANUP_ERROR_EXTRA] = {
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
            logger.debug(
                "browser_bridge_lifecycle_cleanup: failed",
                exc_info=True,
            )
        else:
            cleanup_errors = int((result or {}).get("cleanup_errors", 0))
            _record_cleanup_trace(
                session_id=session_id or root_session_id,
                status="error" if cleanup_errors else "ok",
                duration_ms=_duration_ms(started),
                cleanup_reason=str(
                    (result or {}).get("cleanup_reason") or cleanup_reason,
                ),
                closed_owned_tabs=int(
                    _cleanup_result_counter(
                        result or {},
                        primary="closed_owned_tabs",
                        fallback="closed_tabs",
                    ),
                ),
                released_borrowed_tabs=int(
                    _cleanup_result_counter(
                        result or {},
                        primary="released_borrowed_tabs",
                        fallback="released_tabs",
                    ),
                ),
                preserved_owned_tabs=int(
                    (result or {}).get("preserved_owned_tabs") or 0,
                ),
                skipped_protected_tabs=int(
                    (result or {}).get("skipped_protected_tabs") or 0,
                ),
                remaining_orphaned_tabs=int(
                    (result or {}).get("remaining_orphaned_tabs") or 0,
                ),
                owned_tabs_remaining=int(
                    (result or {}).get("owned_tabs_remaining") or 0,
                ),
                error_code=(
                    "browser_cleanup_failed" if cleanup_errors else ""
                ),
            )
        ctx.extras[
            BROWSER_BRIDGE_KERNEL_CLEANUP_EXTRA
        ] = await cleanup_browser_kernels_for_lifecycle(
            session_id=session_id,
            root_session_id=root_session_id,
            cleanup_reason=cleanup_reason,
        )
        return HookResult()


async def cleanup_browser_bridge_request_resources(
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


def _workspace_id(ctx: HookContext) -> str:
    workspace = ctx.workspace
    for attr in ("workspace_id", "agent_id"):
        value = getattr(workspace, attr, "") if workspace is not None else ""
        if value:
            return str(value)
    return str(ctx.agent_id or "default")


def _request_scope_key(ctx: HookContext) -> str:
    request = ctx.request
    root = str(ctx.root_session_id or ctx.session_id or "default")
    request_context = (
        getattr(request, "request_context", None) if request is not None else None
    )
    if isinstance(request_context, dict):
        for key in ("browser_request_scope_key", "request_scope_key"):
            value = str(request_context.get(key) or "").strip()
            if value:
                return value
    metadata = getattr(request, "metadata", None)
    if isinstance(metadata, dict):
        for key in ("request_id", "message_id", "event_id", "turn_id"):
            metadata_value = metadata.get(key)
            if metadata_value:
                return f"{root}:request:{metadata_value}"
    for attr in ("request_id", "id", "message_id", "event_id"):
        value = getattr(request, attr, "") if request is not None else ""
        if value:
            return f"{root}:request:{value}"
    return f"{root}:request:{id(request)}"


def _merge_cleanup_results(
    user_result: dict[str, Any] | None,
    control_result: dict[str, Any] | None,
    *,
    session_id: str,
    root_session_id: str,
    workspace_id: str,
    cleanup_reason: str,
) -> dict[str, Any]:
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
    ownership_counts = _merge_ownership_counts(user_result, control_result)
    closed_owned_tabs = _sum_cleanup_field(
        user_result,
        control_result,
        primary="closed_owned_tabs",
        fallback="closed_tabs",
    )
    released_borrowed_tabs = _sum_cleanup_field(
        user_result,
        control_result,
        primary="released_borrowed_tabs",
        fallback="released_tabs",
    )
    merged["request_key"] = _request_key(
        session_id=session_id,
        root_session_id=root_session_id,
        workspace_id=workspace_id,
    )
    merged["cleanup_reason"] = cleanup_reason
    merged["closed_owned_tabs"] = closed_owned_tabs
    merged["released_borrowed_tabs"] = released_borrowed_tabs
    merged["preserved_owned_tabs"] = int(
        user_result.get("preserved_owned_tabs") or 0,
    ) + int(control_result.get("preserved_owned_tabs") or 0)
    merged["skipped_protected_tabs"] = (
        int(
            user_result.get("skipped_protected_tabs") or 0,
        )
        + int(control_result.get("skipped_protected_tabs") or 0)
        + int(
            ownership_counts.get("protected") or 0,
        )
    )
    merged["remaining_orphaned_tabs"] = (
        int(
            user_result.get("remaining_orphaned_tabs") or 0,
        )
        + int(control_result.get("remaining_orphaned_tabs") or 0)
        + int(
            ownership_counts.get("orphaned") or 0,
        )
    )
    if ownership_counts:
        merged["ownership_counts"] = ownership_counts
    return merged


def _cleanup_reason(ctx: HookContext) -> str:
    extras = ctx.extras or {}
    reason = "finally"
    if extras.get("browser_bridge_shutdown"):
        reason = "shutdown"
    elif extras.get("browser_bridge_disconnected"):
        reason = "bridge_disconnect"
    elif extras.get("browser_bridge_blocked"):
        reason = "blocked"
    elif _handoff_required(ctx):
        reason = "handoff_required"
    elif isinstance(ctx.error, asyncio.CancelledError):
        reason = "cancelled"
    elif isinstance(ctx.error, BrowserPolicyDenied):
        error = ctx.error
        approval_state = str(error.metadata.get("approval_state") or "")
        if approval_state == "denied" or error.code == "browser_policy_denied":
            reason = "approval_denied"
    elif ctx.error is not None:
        reason = "tool_error"
    return reason


def _preserve_owned_tabs(ctx: HookContext, *, cleanup_reason: str) -> bool:
    return cleanup_reason == "handoff_required" or (
        _handoff_required(ctx)
        and cleanup_reason not in {"shutdown", "bridge_disconnect"}
    )


def _handoff_required(ctx: HookContext) -> bool:
    return any(
        str(value or "").strip().lower() == "handoff_required"
        for value in _error_marker_values(getattr(ctx, "error", None))
    )


def _error_marker_values(error: Any) -> list[Any]:
    values: list[Any] = []
    if error is None:
        return values

    for attr in ("browser_error_code", "error_code", "code"):
        values.append(getattr(error, attr, ""))

    if isinstance(error, dict):
        _append_error_mapping_values(values, error)

    metadata = getattr(error, "metadata", None)
    if isinstance(metadata, dict):
        _append_error_mapping_values(values, metadata)
    return values


def _append_error_mapping_values(
    values: list[Any],
    payload: dict[Any, Any],
) -> None:
    for key in ("browser_error_code", "error_code", "code"):
        values.append(payload.get(key))
    nested = payload.get("error")
    if isinstance(nested, dict):
        for key in ("browser_error_code", "error_code", "code"):
            values.append(nested.get(key))


def _sum_cleanup_field(
    user_result: dict[str, Any],
    control_result: dict[str, Any],
    *,
    primary: str,
    fallback: str,
) -> int:
    return _cleanup_result_counter(
        user_result,
        primary=primary,
        fallback=fallback,
    ) + _cleanup_result_counter(
        control_result,
        primary=primary,
        fallback=fallback,
    )


def _cleanup_result_counter(
    result: dict[str, Any],
    *,
    primary: str,
    fallback: str,
) -> int:
    if primary in result and result.get(primary) is not None:
        return int(result.get(primary) or 0)
    return int(result.get(fallback) or 0)


def _merge_ownership_counts(
    user_result: dict[str, Any],
    control_result: dict[str, Any],
) -> dict[str, int]:
    merged: dict[str, int] = {}
    for source in (user_result, control_result):
        counts = source.get("ownership_counts") or {}
        if not isinstance(counts, dict):
            continue
        for key, value in counts.items():
            merged[str(key)] = merged.get(str(key), 0) + int(value or 0)
    return merged


def _request_key(
    *,
    session_id: str,
    root_session_id: str,
    workspace_id: str,
) -> str:
    request_id = str(root_session_id or session_id or "default")
    return f"{workspace_id or 'default'}:{request_id}"


def _record_cleanup_trace(
    *,
    session_id: str,
    status: str,
    duration_ms: float,
    cleanup_reason: str,
    closed_owned_tabs: int,
    released_borrowed_tabs: int,
    preserved_owned_tabs: int = 0,
    skipped_protected_tabs: int = 0,
    remaining_orphaned_tabs: int = 0,
    owned_tabs_remaining: int = 0,
    error_code: str = "",
) -> None:
    record_browser_trace_event(
        session_id=session_id,
        phase="cleanup",
        backend_id="user.chrome_extension",
        requested_context="user",
        selected_context="user",
        action="browser_bridge_lifecycle_cleanup",
        status=status,
        duration_ms=duration_ms,
        error_code=error_code,
        metadata={
            "closed_owned_tabs": closed_owned_tabs,
            "released_borrowed_tabs": released_borrowed_tabs,
            "preserved_owned_tabs": preserved_owned_tabs,
            "skipped_protected_tabs": skipped_protected_tabs,
            "remaining_orphaned_tabs": remaining_orphaned_tabs,
            "owned_tabs_remaining": owned_tabs_remaining,
            "cleanup_reason": cleanup_reason,
            "error_code": error_code,
        },
    )


def _record_cleanup_start_trace(
    *,
    session_id: str,
    cleanup_reason: str,
    request_scope: dict[str, Any],
) -> None:
    record_browser_trace_event(
        session_id=session_id,
        phase="cleanup",
        backend_id="user.chrome_extension",
        requested_context="user",
        selected_context="user",
        action="browser_bridge_lifecycle_cleanup_start",
        status="started",
        metadata={
            "cleanup_reason": cleanup_reason,
            "request_scope": request_scope,
        },
    )


def _duration_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


__all__ = [
    "BROWSER_BRIDGE_CLEANUP_ERROR_EXTRA",
    "BROWSER_BRIDGE_CLEANUP_EXTRA",
    "BROWSER_BRIDGE_KERNEL_CLEANUP_EXTRA",
    "BrowserBridgeLifecycleCleanupHook",
    "cleanup_browser_bridge_request_resources",
]
