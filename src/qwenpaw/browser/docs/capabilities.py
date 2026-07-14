# -*- coding: utf-8 -*-
"""Browser SDK generated capability docs and gap helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from ..governance.errors import BrowserSDKGap
from ..backends.protocols import BackendProfile


_FINGERPRINT_KEYS = (
    "build_fingerprint",
    "contract_fingerprint",
    "profile_fingerprint",
    "extension_fingerprint",
    "provider_fingerprint",
)
_RETIREMENT_LIMIT_KEYS = (
    "max_retained_state_ttl_seconds",
    "max_legacy_token_ttl_seconds",
)


@dataclass(frozen=True, slots=True)
class SessionCapabilityTruth:
    ready: frozenset[str]
    blocked: dict[str, str]
    fingerprints: dict[str, str]
    retirement_limits: dict[str, int]


def browser_support_manifest() -> dict[str, Any]:
    """Return the reviewed release/build support manifest."""
    artifact = (
        resources.files("qwenpaw.browser")
        / "generated"
        / "browser-support.json"
    )
    return json.loads(artifact.read_text(encoding="utf-8"))


def reviewed_family_evidence(family: str) -> dict[str, tuple[str, ...]]:
    """Return current-build evidence ids for READY rows in one family."""
    manifest = browser_support_manifest()
    build = str(manifest.get("build_fingerprint") or "")
    evidence: dict[str, tuple[str, ...]] = {}
    for row in manifest.get("capabilities", []):
        if row.get("family") != family or row.get("status") != "READY":
            continue
        items = tuple(
            str(item) for item in row.get("validation_evidence") or ()
        )
        if not items or any(not item.endswith(f"@{build}") for item in items):
            continue
        evidence[str(row.get("capability_id") or "")] = items
    return evidence


# pylint: disable-next=too-many-branches
def compute_session_capabilities(
    *,
    manifest: dict[str, Any],
    backend: BackendProfile,
    provider: Any,
    session_ready: frozenset[str],
    diagnostics_ready: frozenset[str] | None = None,
) -> SessionCapabilityTruth:
    """Intersect contract, reviewed build, backend, provider, and session."""
    ready: set[str] = set()
    blocked: dict[str, str] = {}
    build = str(manifest.get("build_fingerprint") or "")
    contract = str(manifest.get("contract_fingerprint") or "")
    profile = str(manifest.get("profile_fingerprint") or "")
    provider_expected = str(manifest.get("provider_fingerprint") or "")
    provider_actual = str(
        getattr(provider, "provider_fingerprint", provider_expected)
        or provider_expected,
    )
    core_mismatch = (
        backend.build_fingerprint != build
        or backend.contract_fingerprint != contract
        or backend.profile_fingerprint != profile
    )
    extension_expected = str(manifest.get("extension_fingerprint") or "")
    extension_mismatch = backend.extension_fingerprint != extension_expected
    provider_mismatch = provider_actual != provider_expected
    diagnostics = diagnostics_ready
    for row in manifest.get("capabilities", []):
        capability_id = str(row.get("capability_id") or "")
        required_blocks = tuple(row.get("required_blocks") or ())
        evidence = tuple(row.get("validation_evidence") or ())
        reason = ""
        if provider_mismatch:
            reason = "fingerprint_mismatch:provider"
        elif row.get("status") != "READY":
            reason = "release_blocked"
        elif not evidence or any(
            not str(item).endswith(f"@{build}") for item in evidence
        ):
            reason = "current_build_evidence_missing"
        elif backend.variants.get(capability_id) != "READY":
            reason = "backend_variant_blocked"
        elif core_mismatch:
            reason = "fingerprint_mismatch"
        elif extension_mismatch and required_blocks:
            reason = "fingerprint_mismatch:extension"
        elif capability_id not in session_ready:
            reason = "session_unavailable"
        elif diagnostics is not None and capability_id not in diagnostics:
            reason = "diagnostics_unavailable"
        else:
            for block_kind in required_blocks:
                if not bool(getattr(provider, str(block_kind), False)):
                    reason = f"provider_{block_kind}_unsupported"
                    break
        if reason:
            blocked[capability_id] = reason
        else:
            ready.add(capability_id)
    return SessionCapabilityTruth(
        ready=frozenset(ready),
        blocked=blocked,
        fingerprints={
            key: str(manifest.get(key) or "") for key in _FINGERPRINT_KEYS
        },
        retirement_limits={
            key: int(manifest.get(key) or 0) for key in _RETIREMENT_LIMIT_KEYS
        },
    )


def browser_capabilities(scope: str = "all") -> dict[str, Any]:
    """Return generated public Browser SDK capabilities."""
    capabilities = _generated_capabilities()
    normalized_scope = _normalize_scope(scope)
    if normalized_scope == "all":
        return dict(capabilities)
    scopes = capabilities["scopes"]
    if normalized_scope not in scopes:
        raise BrowserSDKGap(
            f"Unknown Browser capabilities scope: {scope}",
            action="browser.capabilities",
            metadata={"available_scopes": tuple(sorted(scopes))},
        )
    api_ids = scopes[normalized_scope]
    return {
        "version": capabilities["version"],
        "source": capabilities["source"],
        "scope": normalized_scope,
        "apis": {api_id: capabilities["apis"][api_id] for api_id in api_ids},
    }


def browser_sdk_help(
    scope: str | None = None,
    api_id: str | None = None,
) -> str:
    """Return generated model-facing Browser SDK usage help."""
    help_payload = _generated_capabilities().get("help") or {}
    if api_id:
        api_help = help_payload.get("apis") or {}
        normalized_api_id = str(api_id).strip()
        if normalized_api_id in api_help:
            return str(api_help[normalized_api_id])
        raise BrowserSDKGap(
            f"Unknown Browser help API id: {api_id}",
            action="browser.help",
            metadata={"available_api_ids": tuple(sorted(api_help))},
        )
    if scope:
        scope_help = help_payload.get("scopes") or {}
        normalized_scope = _normalize_scope(scope)
        if normalized_scope in scope_help:
            return str(scope_help[normalized_scope])
        raise BrowserSDKGap(
            f"Unknown Browser help scope: {scope}",
            action="browser.help",
            metadata={"available_scopes": tuple(sorted(scope_help))},
        )
    return str(help_payload.get("index") or "")


def capability_gap(action: str, message: str) -> dict[str, Any]:
    """Return a typed generic capability-missing payload."""
    return BrowserSDKGap(
        message,
        action=str(action or "browser"),
    ).to_dict()


@lru_cache(maxsize=1)
def _generated_capabilities() -> dict[str, Any]:
    artifact = (
        resources.files("qwenpaw.browser")
        / "generated"
        / "canonical"
        / "capabilities.json"
    )
    return json.loads(artifact.read_text(encoding="utf-8"))


def _normalize_scope(scope: str | None) -> str:
    normalized = str(scope or "all").strip().casefold()
    return normalized or "all"


__all__ = [
    "SessionCapabilityTruth",
    "browser_capabilities",
    "browser_support_manifest",
    "browser_sdk_help",
    "capability_gap",
    "compute_session_capabilities",
    "reviewed_family_evidence",
]
