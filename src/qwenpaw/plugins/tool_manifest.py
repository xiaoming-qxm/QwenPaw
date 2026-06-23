# -*- coding: utf-8 -*-
"""Helpers for reading tool declarations from plugin manifests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _first_bool(data: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            return value
    return None


def tool_entries_from_meta(meta: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return normalized tool entries from a plugin ``meta`` object."""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    legacy_name = meta.get("tool_name")
    if isinstance(legacy_name, str) and legacy_name.strip():
        name = legacy_name.strip()
        entries.append(
            {
                "name": name,
                "description": meta.get("tool_description", ""),
                "icon": meta.get("tool_icon", "🔧"),
                "enabled": _first_bool(
                    meta,
                    "tool_enabled",
                    "enabled_by_default",
                    "default_enabled",
                ),
            },
        )
        seen.add(name)

    tools = meta.get("tools", [])
    if isinstance(tools, list):
        for tool in tools:
            if not isinstance(tool, Mapping):
                continue
            raw_name = tool.get("name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            name = raw_name.strip()
            if name in seen:
                continue
            entries.append(
                {
                    "name": name,
                    "description": tool.get(
                        "description",
                        meta.get("tool_description", ""),
                    ),
                    "icon": tool.get("icon", meta.get("tool_icon", "🔧")),
                    "enabled": _first_bool(
                        tool,
                        "enabled",
                        "enabled_by_default",
                        "default_enabled",
                    ),
                },
            )
            seen.add(name)

    return entries


def tool_entries_from_manifest(
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return normalized tool entries from a plugin manifest dictionary."""
    meta = manifest.get("meta", {})
    if not isinstance(meta, Mapping):
        return []
    return tool_entries_from_meta(meta)


def tool_entry_enabled_default(entry: Mapping[str, Any]) -> bool:
    """Return the explicit manifest default, falling back to disabled."""
    enabled = entry.get("enabled")
    return enabled if isinstance(enabled, bool) else False
