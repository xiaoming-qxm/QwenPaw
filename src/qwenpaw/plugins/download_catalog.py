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


def _localized_text_map(value: Any) -> dict[str, str]:
    """Return a locale-keyed text map from a manifest/catalog value."""
    if not isinstance(value, dict):
        return {}
    return {k: str(v) for k, v in value.items() if v}


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


def _iter_source_bundle_manifests() -> list[tuple[Path, dict[str, Any]]]:
    """Return valid source-bundled plugin manifests shipped with QwenPaw."""
    from ..config.utils import get_bundle_plugins_dir

    bundle_dir = get_bundle_plugins_dir()
    if not bundle_dir.is_dir():
        return []

    manifests: list[tuple[Path, dict[str, Any]]] = []
    for item in sorted(bundle_dir.iterdir()):
        if not item.is_dir():
            continue
        manifest_path = item / "plugin.json"
        if not manifest_path.is_file():
            continue
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("Skip bundled plugin %s: %s", manifest_path, exc)
            continue
        if manifest.get("id") and manifest.get("version"):
            manifests.append((item, manifest))
    return manifests


def _append_source_bundle_plugins(
    plugins: list[dict[str, Any]],
    installed: dict[str, str],
) -> None:
    """Append source-bundled official plugins missing from CDN metadata."""
    seen = {str(plugin.get("plugin_id") or "") for plugin in plugins}

    for plugin_dir, manifest in _iter_source_bundle_manifests():
        plugin_id = str(manifest.get("id") or plugin_dir.name)
        if plugin_id in seen:
            continue
        catalog_version = str(manifest.get("version") or "")
        installed_version = installed.get(plugin_id)
        description_i18n = _localized_text_map(
            manifest.get("description_i18n"),
        )
        if not description_i18n:
            description_i18n = _localized_text_map(manifest.get("description"))

        plugins.append(
            {
                "id": f"{plugin_id}-{catalog_version}",
                "plugin_id": plugin_id,
                "name": _pick_en(manifest.get("name")) or plugin_id,
                "description": _pick_en(manifest.get("description")),
                "description_i18n": description_i18n,
                "version": catalog_version,
                "author": str(manifest.get("author") or ""),
                "kind": "bundle",
                "size": "",
                "sha256": "",
                "install_url": str(plugin_dir),
                "installed": plugin_id in installed,
                "installed_version": installed_version,
                "upgrade_available": _is_upgrade_available(
                    installed_version or "",
                    catalog_version,
                ),
            },
        )
        seen.add(plugin_id)


def _finalize_catalog(result: dict[str, Any]) -> dict[str, Any]:
    """Merge source-bundled official plugins and sort catalog entries."""
    installed = _installed_plugin_ids()
    plugins = result.get("plugins")
    if not isinstance(plugins, list):
        result["plugins"] = []
        plugins = result["plugins"]

    _append_source_bundle_plugins(plugins, installed)
    plugins.sort(key=lambda p: (p.get("kind") or "", p.get("name") or ""))
    return result


def build_plugin_catalog() -> dict[str, Any]:
    """Download main + plugins index from CDN and normalize for the console.

    Returns:
        Dict with ``updated_at`` and ``plugins`` list.  On CDN failure returns
        empty ``plugins`` and optional ``error`` message (HTTP 200 still).
    """
    base = PLUGIN_DOWNLOAD_CDN.rstrip("/")
    result: dict[str, Any] = {"updated_at": None, "plugins": [], "error": None}

    try:
        main_index = _fetch_json(f"{base}/metadata/index.json")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("Plugin catalog: main index fetch failed: %s", exc)
        result["error"] = "Failed to fetch plugin catalog index"
        return _finalize_catalog(result)

    products = main_index.get("products") or {}
    plugins_product = products.get("plugins")
    if not plugins_product:
        return _finalize_catalog(result)

    index_path = str(plugins_product.get("index_url") or "")
    if not index_path.startswith("/"):
        result["error"] = "Invalid plugins index_url in main metadata"
        return _finalize_catalog(result)

    try:
        plugins_index = _fetch_json(f"{base}{index_path}")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        logger.warning("Plugin catalog: plugins index fetch failed: %s", exc)
        result["error"] = "Failed to fetch plugins metadata"
        return _finalize_catalog(result)

    result["updated_at"] = plugins_index.get("updated_at")
    files = plugins_index.get("files") or {}
    installed = _installed_plugin_ids()

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
        raw_desc = entry.get("description")
        description_i18n = _localized_text_map(raw_desc)

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
    return _finalize_catalog(result)


async def fetch_plugin_catalog_async() -> dict[str, Any]:
    """Async wrapper around :func:`build_plugin_catalog`."""
    return await asyncio.to_thread(build_plugin_catalog)
