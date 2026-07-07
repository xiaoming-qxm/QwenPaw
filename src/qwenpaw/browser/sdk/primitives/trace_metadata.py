# -*- coding: utf-8 -*-
"""Helpers for Browser action trace metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .types import BrowserActionResult
from .types import ResolvedBrowserContext


def with_route_metadata(
    metadata: dict[str, Any] | None,
    context: ResolvedBrowserContext,
) -> dict[str, Any]:
    """Attach resolved Browser route metadata to a trace metadata payload."""
    trace_metadata = dict(metadata or {})
    route_metadata = {
        "browser_intent": context.browser_intent,
        "preferred_backend_id": context.preferred_backend_id,
        "selected_backend_degraded": context.selected_backend_degraded,
        "fallback_allowed": context.fallback_allowed,
        "fallback_reason": context.fallback_reason,
        "auto_route_policy": context.auto_route_policy,
    }
    for key, value in route_metadata.items():
        trace_metadata.setdefault(key, value)
    return trace_metadata


def coerce_action_result(value: Any) -> BrowserActionResult:
    """Coerce backend action payloads for metadata inspection."""
    if isinstance(value, BrowserActionResult):
        return value
    if isinstance(value, dict):
        return BrowserActionResult(
            ok=bool(value.get("ok", True)),
            message=str(value.get("message") or value.get("error") or ""),
            needs_observation=bool(value.get("needs_observation", True)),
            data=dict(value.get("data") or {}),
        )
    return BrowserActionResult(ok=True, message=str(value or ""))


def with_boundary_decision(
    metadata: dict[str, Any],
    boundary_decision: Any,
) -> dict[str, Any]:
    """Keep boundary decisions both nested and flattened in trace metadata."""
    trace_metadata = dict(metadata)
    if not isinstance(boundary_decision, Mapping):
        return trace_metadata
    boundary_payload = dict(boundary_decision)
    trace_metadata["boundary_decision"] = boundary_payload
    trace_metadata.update(boundary_payload)
    return trace_metadata


def with_exception_metadata(
    metadata: dict[str, Any],
    exc: Exception,
) -> dict[str, Any]:
    """Merge Browser SDK exception metadata into trace metadata."""
    trace_metadata = dict(metadata)
    raw_error_metadata = getattr(exc, "metadata", None)
    if not isinstance(raw_error_metadata, Mapping):
        return trace_metadata
    error_metadata = dict(raw_error_metadata)
    trace_metadata.update(error_metadata)
    return with_boundary_decision(
        trace_metadata,
        error_metadata.get("boundary_decision"),
    )


__all__ = [
    "coerce_action_result",
    "with_boundary_decision",
    "with_exception_metadata",
    "with_route_metadata",
]
