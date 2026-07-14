# -*- coding: utf-8 -*-
"""Manifest registry for chrome backend instances."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

MANIFEST_PATH = Path.home() / ".qwenpaw" / "chrome-hosts.json"
SCHEMA_VERSION = 1
PROTOCOL_VERSION = 2


@dataclass(frozen=True)
class ManifestEntry:
    """One QwenPaw backend endpoint advertised to chrome."""

    entryId: str
    channel: str
    appVersion: str
    protocolVersion: int
    wsUrl: str
    token: str
    presence: dict
    updatedAt: str


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    """Load manifest data, returning an empty schema when missing."""
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(data: dict, path: Path = MANIFEST_PATH) -> None:
    """Atomically save manifest data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def register_instance(
    ws_url: str,
    token: str,
    channel: str = "stable",
    app_version: str = "",
    path: Path = MANIFEST_PATH,
) -> str:
    """Register a QwenPaw backend endpoint and return its entry id."""
    manifest = load_manifest(path)
    manifest.setdefault("schemaVersion", SCHEMA_VERSION)
    manifest.setdefault("entries", [])
    _cleanup_stale(manifest)

    entry_id = f"qwenpaw-runtime-{uuid4().hex[:8]}"
    now = _utc_now()
    entry = ManifestEntry(
        entryId=entry_id,
        channel=channel,
        appVersion=app_version,
        protocolVersion=PROTOCOL_VERSION,
        wsUrl=ws_url,
        token=token,
        presence={
            "pid": os.getpid(),
            "startedAt": now,
            "lastSeenAt": now,
        },
        updatedAt=now,
    )
    manifest["entries"].append(asdict(entry))
    save_manifest(manifest, path)
    return entry_id


def deregister_instance(
    entry_id: str,
    path: Path = MANIFEST_PATH,
) -> None:
    """Remove an entry from the chrome manifest."""
    manifest = load_manifest(path)
    entries = manifest.get("entries", [])
    manifest["entries"] = [
        entry for entry in entries if entry.get("entryId") != entry_id
    ]
    save_manifest(manifest, path)


def _cleanup_stale(manifest: dict) -> None:
    entries = manifest.get("entries", [])
    manifest["entries"] = [
        entry
        for entry in entries
        if _pid_alive((entry.get("presence") or {}).get("pid"))
    ]


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, (int, str)):
        return False
    try:
        pid_value = int(pid)
        os.kill(pid_value, 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


__all__ = [
    "MANIFEST_PATH",
    "PROTOCOL_VERSION",
    "SCHEMA_VERSION",
    "ManifestEntry",
    "deregister_instance",
    "load_manifest",
    "register_instance",
    "save_manifest",
]
