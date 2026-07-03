# -*- coding: utf-8 -*-
"""Observation coercion helpers for Browser SDK backends."""

from __future__ import annotations

from typing import Any

from .types import BrowserObservation, BrowserScreenshot


def coerce_observation(tab_id: str, value: Any) -> BrowserObservation:
    """Normalize backend snapshot output into BrowserObservation."""
    if isinstance(value, BrowserObservation):
        return value
    if isinstance(value, dict):
        return BrowserObservation(
            tab_id=str(value.get("tab_id") or value.get("id") or tab_id),
            text=str(value.get("text") or value.get("snapshot") or ""),
            url=str(value.get("url") or ""),
            title=str(value.get("title") or ""),
            refs=dict(value.get("refs") or {}),
            degraded=bool(value.get("degraded", False)),
            metadata=dict(value.get("metadata") or {}),
        )
    return BrowserObservation(tab_id=tab_id, text=str(value or ""))


def coerce_screenshot(tab_id: str, value: Any) -> BrowserScreenshot:
    """Normalize backend screenshot output into BrowserScreenshot."""
    if isinstance(value, BrowserScreenshot):
        return value
    if isinstance(value, dict):
        return BrowserScreenshot(
            tab_id=str(value.get("tab_id") or value.get("id") or tab_id),
            path=str(value.get("path") or ""),
            media_type=str(value.get("media_type") or "image/png"),
            url=str(value.get("url") or ""),
            title=str(value.get("title") or ""),
            metadata=dict(value.get("metadata") or {}),
        )
    return BrowserScreenshot(tab_id=tab_id, path=str(value or ""))


__all__ = ["coerce_observation", "coerce_screenshot"]
