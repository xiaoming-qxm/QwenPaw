# -*- coding: utf-8 -*-
"""Proxy-fetch official plugin catalog from the download CDN."""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)

PLUGIN_DOWNLOAD_CDN = "https://download.qwenpaw.agentscope.io"
_FETCH_TIMEOUT = 30


def _fetch_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _plugin_id_from_file_entry(entry: dict[str, Any]) -> str:
    explicit = entry.get("plugin_id")
    if explicit:
        return str(explicit)

    file_id = str(entry.get("id") or "")
    version = str(entry.get("version") or "")
    if not version:
        return file_id

    # Legacy index ids: ``{plugin_id}-{version}``
    suffix = f"-{version}"
    if file_id.endswith(suffix):
        return file_id[: -len(suffix)]

    # Legacy index ids with content-hash suffix:
    # ``{plugin_id}-{version}-{sha8}``
    marker = f"-{version}-"
    idx = file_id.rfind(marker)
    if idx > 0:
        tail = file_id[idx + len(marker) :]
        if len(tail) == 8 and all(
            c in "0123456789abcdef" for c in tail.lower()
        ):
            return file_id[:idx]

    return file_id


def _is_upgrade_available(
    installed_version: str,
    catalog_version: str,
) -> bool:
    """Return True when the catalog advertises a newer plugin release."""
    if not installed_version or not catalog_version:
        return False
    try:
        return Version(catalog_version) > Version(installed_version)
    except InvalidVersion:
        return installed_version != catalog_version


def _pick_en(value: Any) -> str:
    if isinstance(value, dict):
        return str(
            value.get("en-US")
            or value.get("en")
            or value.get("zh-CN")
            or value.get("zh")
            or "",
        )
    return str(value) if value is not None else ""


def _installed_plugin_ids() -> dict[str, str]:
    """Return ``{plugin_id: installed_version}`` from disk manifests."""
    from ..config.utils import get_plugins_dir

    plugins_dir = get_plugins_dir()
    if not plugins_dir.is_dir():
        return {}

    installed: dict[str, str] = {}
    for item in plugins_dir.iterdir():
        if not item.is_dir():
            continue
        manifest_path = item / "plugin.json"
        if not manifest_path.is_file():
            continue
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("Skip %s: %s", manifest_path, exc)
            continue
        plugin_id = str(manifest.get("id") or item.name)
        installed[plugin_id] = str(manifest.get("version") or "0.0.0")
    return installed


def _source_bundled_plugin_entries(
    installed: dict[str, str],
) -> list[dict[str, Any]]:
    """Return catalog entries for tool plugins shipped in a source checkout."""
    repo_root = Path(__file__).resolve().parents[3]
    tool_plugins_dir = repo_root / "plugins" / "tool"
    if not tool_plugins_dir.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for plugin_dir in sorted(tool_plugins_dir.iterdir()):
        if not plugin_dir.is_dir():
            continue
        manifest_path = plugin_dir / "plugin.json"
        if not manifest_path.is_file():
            continue
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("Skip source plugin %s: %s", manifest_path, exc)
            continue

        plugin_id = str(manifest.get("id") or plugin_dir.name)
        version = str(manifest.get("version") or "")
        installed_version = installed.get(plugin_id)
        raw_desc = manifest.get("description_i18n")
        description_i18n: dict[str, str] = {}
        if isinstance(raw_desc, dict):
            description_i18n = {k: str(v) for k, v in raw_desc.items() if v}

        entries.append(
            {
                "id": plugin_id,
                "plugin_id": plugin_id,
                "name": _pick_en(manifest.get("name")),
                "description": _pick_en(
                    manifest.get("description_i18n")
                    or manifest.get("description"),
                ),
                "description_i18n": description_i18n,
                "version": version,
                "author": str(manifest.get("author") or ""),
                "kind": str(manifest.get("type") or "tool"),
                "size": "",
                "sha256": "",
                "install_url": str(plugin_dir.resolve()),
                "installed": plugin_id in installed,
                "installed_version": installed_version,
                "upgrade_available": _is_upgrade_available(
                    installed_version or "",
                    version,
                ),
            },
        )

    return entries


def _merge_source_bundled_plugins(
    result: dict[str, Any],
    installed: dict[str, str],
) -> None:
    """Merge source-bundled plugin entries not present in remote catalog."""
    existing_ids = {
        str(plugin.get("plugin_id") or plugin.get("id") or "")
        for plugin in result.get("plugins", [])
        if isinstance(plugin, dict)
    }
    for entry in _source_bundled_plugin_entries(installed):
        if entry["plugin_id"] in existing_ids:
            continue
        result["plugins"].append(entry)
        existing_ids.add(entry["plugin_id"])


def build_plugin_catalog() -> dict[str, Any]:
    """Download main + plugins index from CDN and normalize for the console.

    Returns:
        Dict with ``updated_at`` and ``plugins`` list.  On CDN failure returns
        empty ``plugins`` and optional ``error`` message (HTTP 200 still).
    """
    base = PLUGIN_DOWNLOAD_CDN.rstrip("/")
    result: dict[str, Any] = {"updated_at": None, "plugins": [], "error": None}
    installed = _installed_plugin_ids()

    try:
        main_index = _fetch_json(f"{base}/metadata/index.json")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("Plugin catalog: main index fetch failed: %s", exc)
        result["error"] = "Failed to fetch plugin catalog index"
        _merge_source_bundled_plugins(result, installed)
        result["plugins"].sort(
            key=lambda p: (p.get("kind") or "", p.get("name") or ""),
        )
        return result

    products = main_index.get("products") or {}
    plugins_product = products.get("plugins")
    if not plugins_product:
        _merge_source_bundled_plugins(result, installed)
        result["plugins"].sort(
            key=lambda p: (p.get("kind") or "", p.get("name") or ""),
        )
        return result

    index_path = str(plugins_product.get("index_url") or "")
    if not index_path.startswith("/"):
        result["error"] = "Invalid plugins index_url in main metadata"
        _merge_source_bundled_plugins(result, installed)
        result["plugins"].sort(
            key=lambda p: (p.get("kind") or "", p.get("name") or ""),
        )
        return result

    try:
        plugins_index = _fetch_json(f"{base}{index_path}")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("Plugin catalog: plugins index fetch failed: %s", exc)
        result["error"] = "Failed to fetch plugins metadata"
        _merge_source_bundled_plugins(result, installed)
        result["plugins"].sort(
            key=lambda p: (p.get("kind") or "", p.get("name") or ""),
        )
        return result

    result["updated_at"] = plugins_index.get("updated_at")
    files = plugins_index.get("files") or {}

    plugins: list[dict[str, Any]] = []
    for _file_id, entry in files.items():
        if not isinstance(entry, dict):
            continue
        rel_url = str(entry.get("url") or "")
        if not rel_url.startswith("/"):
            continue
        plugin_id = _plugin_id_from_file_entry(entry)
        catalog_version = str(entry.get("version") or "")
        installed_version = installed.get(plugin_id)
        # Build description_i18n dict from the raw entry
        raw_desc = entry.get("description")
        description_i18n: dict[str, str] = {}
        if isinstance(raw_desc, dict):
            description_i18n = {k: str(v) for k, v in raw_desc.items() if v}

        plugins.append(
            {
                "id": str(entry.get("id") or _file_id),
                "plugin_id": plugin_id,
                "name": _pick_en(entry.get("name")),
                "description": _pick_en(entry.get("description")),
                "description_i18n": description_i18n,
                "version": catalog_version,
                "author": str(entry.get("author") or ""),
                "kind": str(entry.get("platform") or ""),
                "size": str(entry.get("size") or ""),
                "sha256": str(entry.get("sha256") or ""),
                "install_url": f"{base}{rel_url}",
                "installed": plugin_id in installed,
                "installed_version": installed_version,
                "upgrade_available": _is_upgrade_available(
                    installed_version or "",
                    catalog_version,
                ),
            },
        )

    result["plugins"] = plugins
    _merge_source_bundled_plugins(result, installed)
    result["plugins"].sort(
        key=lambda p: (p.get("kind") or "", p.get("name") or ""),
    )
    return result


async def fetch_plugin_catalog_async() -> dict[str, Any]:
    """Async wrapper around :func:`build_plugin_catalog`."""
    return await asyncio.to_thread(build_plugin_catalog)
