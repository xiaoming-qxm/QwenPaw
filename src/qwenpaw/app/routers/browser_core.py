# -*- coding: utf-8 -*-
"""Authenticated, read-only Browser Core retirement evidence."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from hashlib import sha256
import json
from re import fullmatch
import secrets
from threading import Lock
from time import monotonic
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from qwenpaw.app import auth
from qwenpaw.browser.sdk.backends.registry import (
    RETIREMENT_EVIDENCE_BACKEND_ID,
    get_default_backend_registry,
)
from qwenpaw.browser.sdk.docs.capabilities import browser_support_manifest
from qwenpaw.browser.sdk.telemetry.trace import get_legacy_usage_snapshot
from qwenpaw.runtime.root_request_coordinator import (
    _OWNER_REGISTRY,
    _trusted_rollout_default,
)

router = APIRouter(prefix="/browser-core", tags=["browser-core"])

_PROCESS_STARTED_MONOTONIC = monotonic()
_PROCESS_INSTANCE_ID = secrets.token_urlsafe(24)
_NONCE_CAPACITY = 4096
_SEEN_NONCES: set[str] = set()
_NONCE_ORDER: deque[str] = deque()
_NONCE_LOCK = Lock()
_UNKNOWN_REASONS = frozenset(
    {
        "BACKEND_MISSING",
        "BACKEND_DISCONNECTED",
        "SAMPLE_CHANGED",
        "STATE_UNAVAILABLE",
    },
)


def _require_authenticated_nonce(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if scheme != "Bearer" or separator != " " or not token:
        raise HTTPException(status_code=401, detail="authentication required")
    if auth.verify_token(token) is None:
        raise HTTPException(status_code=401, detail="authentication required")
    nonce = request.headers.get("X-QwenPaw-Retirement-Nonce", "")
    if (
        len(nonce) < 32
        or len(nonce) > 256
        or fullmatch(r"[A-Za-z0-9_-]+", nonce) is None
        or len(set(nonce)) < 8
    ):
        raise HTTPException(
            status_code=400,
            detail="a high-entropy retirement nonce is required",
        )
    with _NONCE_LOCK:
        if nonce in _SEEN_NONCES:
            raise HTTPException(status_code=409, detail="nonce already used")
        _SEEN_NONCES.add(nonce)
        _NONCE_ORDER.append(nonce)
        while len(_NONCE_ORDER) > _NONCE_CAPACITY:
            _SEEN_NONCES.discard(_NONCE_ORDER.popleft())
    return nonce


@router.get("/retirement-evidence")
async def retirement_evidence(
    request_nonce: str = Depends(_require_authenticated_nonce),
) -> JSONResponse:
    """Return one bounded, identity-free sample from the live process."""
    payload = await collect_retirement_evidence(request_nonce)
    return JSONResponse(
        payload,
        headers={"Cache-Control": "no-store"},
    )


async def collect_retirement_evidence(
    request_nonce: str,
) -> dict[str, Any]:
    """Collect one host/Bridge double-sample without retry or mutation."""
    host_before = await _host_snapshot()
    bridge_backend = get_default_backend_registry().get(
        RETIREMENT_EVIDENCE_BACKEND_ID,
    )
    bridge_before = _bridge_snapshot(bridge_backend)
    host_after = await _host_snapshot()
    bridge_after = _bridge_snapshot(bridge_backend)

    host_stable = host_before["revision"] == host_after["revision"]
    bridge_stable = (
        bridge_before["revision"] is not None
        and bridge_before["revision"] == bridge_after["revision"]
    )
    unknown_reasons: dict[str, str] = {}
    host_counts: dict[str, int | None] = {
        **host_before["counts"],
        "active_legacy_calls": host_before["active_legacy_calls"],
    }
    legacy_usage = host_before["legacy_usage"]
    legacy_quiet_seconds: int | None = host_before["legacy_quiet_seconds"]
    legacy_admission = dict(host_before["legacy_admission"])
    canonical_admission_age: int | None = host_before[
        "canonical_admission_age_seconds"
    ]
    if not host_stable:
        host_counts = {key: None for key in host_counts}
        legacy_usage = []
        legacy_quiet_seconds = None
        for key in host_counts:
            unknown_reasons[f"host_counts.{key}"] = "SAMPLE_CHANGED"
        unknown_reasons["legacy_quiet_seconds"] = "SAMPLE_CHANGED"
        unknown_reasons["legacy_usage"] = "SAMPLE_CHANGED"
        legacy_admission["closed_age_seconds"] = None
        canonical_admission_age = None
        unknown_reasons[
            "legacy_admission.closed_age_seconds"
        ] = "SAMPLE_CHANGED"
        unknown_reasons[
            "canonical_admission_age_seconds"
        ] = "SAMPLE_CHANGED"

    bridge_counts: dict[str, int | None]
    bridge_quiet_seconds: int | None
    if bridge_stable:
        bridge_counts = dict(bridge_before["counts"])
        bridge_quiet_seconds = bridge_before["legacy_quiet_seconds"]
    else:
        bridge_counts = {
            "legacy_holders": None,
            "legacy_sessions": None,
            "legacy_pending_receipts": None,
        }
        bridge_quiet_seconds = None
        reason = _bridge_unknown_reason(bridge_before, bridge_after)
        for key in bridge_counts:
            unknown_reasons[f"bridge_counts.{key}"] = reason
        unknown_reasons["bridge_legacy_quiet_seconds"] = reason

    host_revision_before = _known_int(host_before["revision"])
    host_revision_after = _known_int(host_after["revision"])
    bridge_revision_before = _optional_int(bridge_before["revision"])
    bridge_revision_after = _optional_int(bridge_after["revision"])
    if bridge_revision_before is None:
        unknown_reasons["sample.bridge_revision_before"] = (
            _bridge_unknown_reason(bridge_before, bridge_after)
        )
    if bridge_revision_after is None:
        unknown_reasons["sample.bridge_revision_after"] = (
            _bridge_unknown_reason(bridge_before, bridge_after)
        )

    now = monotonic()
    uptime = max(0, int(now - _PROCESS_STARTED_MONOTONIC))
    manifest = browser_support_manifest()
    if legacy_admission["closed_age_seconds"] is None:
        unknown_reasons.setdefault(
            "legacy_admission.closed_age_seconds",
            "STATE_UNAVAILABLE",
        )
    return {
        "schema_version": 1,
        "request_nonce": request_nonce,
        "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "process_instance_id": _PROCESS_INSTANCE_ID,
        "process_uptime_seconds": uptime,
        "sample": {
            "consistent": host_stable and bridge_stable,
            "host_revision_before": host_revision_before,
            "host_revision_after": host_revision_after,
            "bridge_revision_before": bridge_revision_before,
            "bridge_revision_after": bridge_revision_after,
        },
        "fingerprints": {
            "build": str(manifest.get("build_fingerprint") or ""),
            "contract": str(manifest.get("contract_fingerprint") or ""),
            "profile": str(manifest.get("profile_fingerprint") or ""),
            "extension": str(manifest.get("extension_fingerprint") or ""),
            "provider": str(manifest.get("provider_fingerprint") or ""),
        },
        "host_default": _trusted_rollout_default().value,
        "legacy_admission": legacy_admission,
        "canonical_admission_age_seconds": canonical_admission_age,
        "required_quiet_window_seconds": max(
            int(manifest["max_retained_state_ttl_seconds"]),
            int(manifest["max_legacy_token_ttl_seconds"]),
        ),
        "legacy_quiet_seconds": legacy_quiet_seconds,
        "bridge_legacy_quiet_seconds": bridge_quiet_seconds,
        "host_counts": host_counts,
        "bridge_counts": bridge_counts,
        "legacy_usage": legacy_usage,
        "unknown_reasons": unknown_reasons,
    }


async def _host_snapshot() -> dict[str, Any]:
    owner = await _OWNER_REGISTRY.retirement_snapshot()
    usage = tuple(get_legacy_usage_snapshot())
    revision = _revision(
        {
            "owner_revision": owner["revision"],
            "usage": [
                {
                    "caller": row["caller"],
                    "api_id": row["api_id"],
                    "total_count": row["total_count"],
                    "active_calls": row["active_calls"],
                    "last_activity_monotonic": row[
                        "last_activity_monotonic"
                    ],
                }
                for row in usage
            ],
        },
    )
    process_age = max(0, int(monotonic() - _PROCESS_STARTED_MONOTONIC))
    quiet = min(
        (int(row["quiet_seconds"]) for row in usage),
        default=process_age,
    )
    return {
        "revision": revision,
        "counts": dict(owner["counts"]),
        "active_legacy_calls": sum(
            int(row["active_calls"]) for row in usage
        ),
        "legacy_quiet_seconds": max(0, quiet),
        "legacy_usage": [
            {
                "caller": str(row["caller"]),
                "api_id": str(row["api_id"]),
                "total_count": int(row["total_count"]),
                "active_calls": int(row["active_calls"]),
                "quiet_seconds": max(0, int(row["quiet_seconds"])),
            }
            for row in usage
        ],
        "legacy_admission": dict(owner["legacy_admission"]),
        "canonical_admission_age_seconds": int(
            owner["canonical_admission_age_seconds"],
        ),
    }


def _bridge_snapshot(backend: object | None) -> dict[str, Any]:
    if backend is None:
        return _unknown_bridge_snapshot("BACKEND_MISSING")
    snapshot = getattr(backend, "retirement_snapshot", None)
    if not callable(snapshot):
        return _unknown_bridge_snapshot("STATE_UNAVAILABLE")
    try:
        result = snapshot()
    except Exception:
        return _unknown_bridge_snapshot("STATE_UNAVAILABLE")
    if not isinstance(result, dict):
        return _unknown_bridge_snapshot("STATE_UNAVAILABLE")
    revision = result.get("revision")
    counts = result.get("counts")
    quiet = result.get("legacy_quiet_seconds")
    if revision is None:
        reason = str(result.get("reason") or "")
        return _unknown_bridge_snapshot(
            reason if reason in _UNKNOWN_REASONS else "STATE_UNAVAILABLE",
        )
    expected_count_keys = {
        "legacy_holders",
        "legacy_sessions",
        "legacy_pending_receipts",
    }
    if (
        not _is_nonnegative_int(revision)
        or not isinstance(counts, dict)
        or set(counts) != expected_count_keys
        or any(not _is_nonnegative_int(value) for value in counts.values())
        or not _is_nonnegative_int(quiet)
    ):
        return _unknown_bridge_snapshot("STATE_UNAVAILABLE")
    return {
        "revision": revision,
        "counts": counts,
        "legacy_quiet_seconds": quiet,
        "reason": None,
    }


def _unknown_bridge_snapshot(reason: str) -> dict[str, Any]:
    return {
        "revision": None,
        "counts": None,
        "legacy_quiet_seconds": None,
        "reason": reason,
    }


def _bridge_unknown_reason(
    before: dict[str, Any],
    after: dict[str, Any],
) -> str:
    if before.get("revision") is not None and after.get("revision") is not None:
        return "SAMPLE_CHANGED"
    reason = str(before.get("reason") or after.get("reason") or "")
    return reason if reason in _UNKNOWN_REASONS else "STATE_UNAVAILABLE"


def _revision(material: object) -> int:
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return int(sha256(encoded).hexdigest()[:12], 16)


def _known_int(value: object) -> int:
    return max(0, int(value))


def _optional_int(value: object) -> int | None:
    return None if value is None else _known_int(value)


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = ["collect_retirement_evidence", "retirement_evidence", "router"]
