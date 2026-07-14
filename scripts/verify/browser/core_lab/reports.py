# -*- coding: utf-8 -*-
"""Machine-readable Core Lab report serialization."""
# pylint: disable=too-many-branches,too-many-return-statements
# pylint: disable=too-many-statements
# pylint: disable=too-many-boolean-expressions

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import secrets
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
import subprocess
from typing import Any
from urllib.parse import urlsplit

import httpx

from .model import CapabilityFamily, LabCase, OracleResult

RELEASE_HANDOFF_SCHEMA = "browser-core-release-handoff-v1"
DEPLOYMENT_ATTESTATION_SCHEMA = "browser-core-deployment-attestation-v1"
LEGACY_PUBLIC_PATHS = (
    "src/qwenpaw/browser/facade/__init__.py",
    "src/qwenpaw/browser/facade/browser.py",
    "src/qwenpaw/browser/contracts.py",
    "src/qwenpaw/browser/actions/__init__.py",
    "src/qwenpaw/browser/actions/tab_actions.py",
    "src/qwenpaw/browser/primitives/tab.py",
    "src/qwenpaw/browser/primitives/tabs.py",
    "src/qwenpaw/browser/runtime/proxy.py",
    "src/qwenpaw/browser/runtime/guard.py",
    "src/qwenpaw/browser/generated/api_catalog.json",
    "src/qwenpaw/browser/generated/capabilities.json",
    "src/qwenpaw/browser/generated/help/index.md",
)
BRIDGE_SYMBOL_PATHS = (
    "plugins/bundle/chrome/action_runtime/handlers/__init__.py",
    "plugins/bundle/chrome/action_runtime/handlers/dispatcher.py",
    "plugins/bundle/chrome/action_runtime/handlers/click.py",
    "plugins/bundle/chrome/action_runtime/handlers/drag.py",
    "plugins/bundle/chrome/action_runtime/handlers/paste.py",
    "plugins/bundle/chrome/action_runtime/handlers/press_key.py",
    "plugins/bundle/chrome/action_runtime/handlers/protocol.py",
    "plugins/bundle/chrome/action_runtime/handlers/screenshot.py",
    "plugins/bundle/chrome/action_runtime/handlers/scroll.py",
    "plugins/bundle/chrome/action_runtime/handlers/set_checked.py",
    "plugins/bundle/chrome/action_runtime/handlers/snapshot.py",
    "plugins/bundle/chrome/action_runtime/handlers/type_text.py",
    "plugins/bundle/chrome/action_runtime/handlers/wait_for.py",
    "plugins/bundle/chrome/action_runtime/snapshot_builder.py",
    "plugins/bundle/chrome/action_runtime/ref_scope.py",
    "plugins/bundle/chrome/action_runtime/session_manager.py",
    "plugins/bundle/chrome/action_runtime/state.py",
    "plugins/bundle/chrome/action_runtime/tab_manager.py",
    "plugins/bundle/chrome/action_runtime/targets.py",
    "plugins/bundle/chrome/action_runtime/transitions.py",
    "plugins/bundle/chrome/action_runtime/interactions.py",
    "plugins/bundle/chrome/action_runtime/handlers/hover.py",
    "plugins/bundle/chrome/action_runtime/handlers/select_option.py",
    "plugins/bundle/chrome/action_runtime/handlers/capabilities.py",
    "plugins/bundle/chrome/backend/user.py",
    "plugins/bundle/chrome/engine_impl.py",
    "plugins/bundle/chrome/transport/native_messaging.py",
    "plugins/bundle/chrome/assets/extensions/chrome/service_worker.js",
)
_BRIDGE_SYMBOL_ROOTS = (
    (
        "plugins/bundle/chrome/action_runtime/handlers/__init__.py",
        "ACTION_HANDLERS",
        "DELETE",
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/__init__.py",
        "ActionHandler",
        "DELETE",
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/__init__.py",
        "__module__",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/dispatcher.py",
        "_LEGACY_FALLBACK_ACTIONS",
        "DELETE",
    ),
    (
        "plugins/bundle/chrome/action_runtime/snapshot_builder.py",
        "build_control_snapshot",
        "DELETE",
    ),
    (
        "plugins/bundle/chrome/action_runtime/snapshot_builder.py",
        "_CONTROL_ACTION_REPEAT_LIMITED_LABELS",
        "DELETE",
    ),
    (
        "plugins/bundle/chrome/action_runtime/snapshot_builder.py",
        "_CONTROL_ACTION_WEAK_ADD_CART_EXCLUSION_RE",
        "DELETE",
    ),
    (
        "plugins/bundle/chrome/action_runtime/snapshot_builder.py",
        "_CONTROL_ACTION_SEMANTIC_LABELS",
        "DELETE",
    ),
    (
        "plugins/bundle/chrome/action_runtime/ref_scope.py",
        "_control_snapshot_payload_refs",
        "DELETE",
    ),
    (
        "plugins/bundle/chrome/action_runtime/ref_scope.py",
        "_control_current_snapshot_ref",
        "DELETE",
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/dispatcher.py",
        "dispatch",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/protocol.py",
        "TrustedCommandEnvelope",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/action_runtime/snapshot_builder.py",
        "build_canonical_snapshot",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/action_runtime/ref_scope.py",
        "_control_bind_canonical_target",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/action_runtime/ref_scope.py",
        "_control_revalidate_canonical_target",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/action_runtime/targets.py",
        "canonical_live_target_point",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/action_runtime/transitions.py",
        "_control_resolve_action_transition",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/backend/user.py",
        "ChromeExtensionBrowserBackend",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/backend/user.py",
        "ChromeExtensionBrowserSession",
        "KEEP",
    ),
    (
        "plugins/bundle/chrome/engine_impl.py",
        "ControlEngineImpl",
        "KEEP",
    ),
)
_BRIDGE_DELETE_BRANCH_SEEDS = (
    (
        "plugins/bundle/chrome/action_runtime/handlers/click.py",
        "__legacy_dispatch_branch__",
        "_canonical_runner_request",
        ("click_control",),
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/press_key.py",
        "__legacy_dispatch_branch__",
        "_canonical_runner_request",
        ("press_key_control",),
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/type_text.py",
        "__legacy_dispatch_branch__",
        "_canonical_runner_request",
        ("type_control",),
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/scroll.py",
        "__legacy_dispatch_branch__",
        "_canonical_runner_request",
        (
            "_absolute_scroll_position",
            "_read_scroll_metrics",
            "_scroll_delta",
            "_scroll_pixels",
            "_scroll_to_absolute",
            "_scroll_tracking_ref",
            "_send_scroll_key_fallback",
            "_send_with_timeout",
        ),
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/hover.py",
        "__legacy_dispatch_branch__",
        "_canonical_runner_request",
        ("_hover_point",),
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/select_option.py",
        "__legacy_dispatch_branch__",
        "_canonical_runner_request",
        ("_select_node_params", "_select_value"),
    ),
    (
        "plugins/bundle/chrome/action_runtime/handlers/screenshot.py",
        "__legacy_dispatch_branch__",
        "contract_mode",
        ("_control_snapshot_hash", "_url_source"),
    ),
    (
        "plugins/bundle/chrome/action_runtime/session_manager.py",
        "__legacy_dispatch_branch__",
        'if contract_mode == "CANONICAL"',
        ("_control_register_dialog_auto_handler",),
    ),
    (
        "plugins/bundle/chrome/backend/user.py",
        "__legacy_dispatch_branch__",
        "ContractMode.LEGACY",
        ("ChromeExtensionBrowserBackend", "ChromeExtensionBrowserSession"),
    ),
)
BRIDGE_SYMBOL_MANIFEST_SCHEMA = "chrome-symbol-manifest-v1"
_FINGERPRINT_KEYS = {"build", "contract", "profile", "extension", "provider"}
_DEPLOYMENT_FACT_KEYS = {
    "scope_id",
    "s10a_build_id",
    "release_handoff_sha256",
    "deployment_generation",
    "declared_complete",
    "declared_at",
    "last_deployed_at",
    "expected_instance_names",
    "expected_instance_count",
    "endpoints",
}
_DEPLOYMENT_REQUIRED_FIELDS = _DEPLOYMENT_FACT_KEYS | {"schema_version"}
_DEPLOYMENT_BASE_ENDPOINT_FIELDS = {
    "name",
    "base_url",
    "bearer_token_env",
}
_S10B_ENDPOINT_FIELDS = _DEPLOYMENT_BASE_ENDPOINT_FIELDS | {
    "process_instance_id",
    "build_id",
    "artifact_sha256",
}

_SUPPORT_PATH = Path(
    "src/qwenpaw/browser/generated/browser-support.json",
)
RETIREMENT_REPORT_SCHEMA = "browser-core-retirement-authorization-v1"
_HOST_ZERO_KEYS = {
    "legacy_mode_bindings",
    "active_legacy_root_sessions",
    "retained_or_handoff_states",
    "active_legacy_leases",
    "unexpired_legacy_tokens",
    "unresolved_prompts",
    "pending_actions",
    "pending_approvals",
    "uncertain_effects",
    "active_legacy_calls",
}
_BRIDGE_ZERO_KEYS = {
    "legacy_holders",
    "legacy_sessions",
    "legacy_pending_receipts",
}
_REMOTE_EVIDENCE_FIELDS = {
    "schema_version",
    "request_nonce",
    "observed_at",
    "process_instance_id",
    "process_uptime_seconds",
    "sample",
    "fingerprints",
    "host_default",
    "legacy_admission",
    "canonical_admission_age_seconds",
    "required_quiet_window_seconds",
    "legacy_quiet_seconds",
    "bridge_legacy_quiet_seconds",
    "host_counts",
    "bridge_counts",
    "legacy_usage",
    "unknown_reasons",
}
_RETIREMENT_REPORT_FIELDS = {
    "schema_version",
    "outcome",
    "completed_at",
    "authorization_max_age_seconds",
    "expires_at",
    "required_quiet_window_seconds",
    "scope_id",
    "deployment_generation",
    "expected_instance_names",
    "expected_instance_set_sha256",
    "process_instance_ids",
    "build_id",
    "artifact_sha256",
    "fingerprints",
    "input_sha256",
    "verifier_sha256",
    "instances",
}
_AUTHORIZED_INSTANCE_FIELDS = {
    "name",
    "requested_at",
    "decision",
    "reasons",
    "responded_at",
    "process_instance_id",
    "build_id",
    "artifact_sha256",
    "response_sha256",
    "evidence",
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} timezone missing")
    return parsed.astimezone(UTC)


def _tool_digest() -> str:
    cli_path = Path(__file__).with_name("cli.py")
    return sha256(
        Path(__file__).read_bytes() + cli_path.read_bytes(),
    ).hexdigest()


def _instance_set_digest(names: list[str]) -> str:
    encoded = json.dumps(sorted(names), separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _validate_attestation(
    payload: dict[str, Any],
    handoff_path: Path,
    handoff: dict[str, Any],
) -> None:
    declared_schema = handoff.get("deployment_attestation_schema")
    if (
        not isinstance(declared_schema, dict)
        or set(declared_schema.get("endpoint_fields") or ())
        != _DEPLOYMENT_BASE_ENDPOINT_FIELDS
    ):
        raise ValueError("handoff deployment endpoint schema mismatch")
    if set(payload) != _DEPLOYMENT_REQUIRED_FIELDS:
        raise ValueError("deployment attestation fields mismatch")
    if payload.get("schema_version") != 1:
        raise ValueError("deployment attestation schema mismatch")
    if payload.get("declared_complete") is not True:
        raise ValueError("deployment scope is not complete")
    names = payload.get("expected_instance_names")
    endpoints = payload.get("endpoints")
    if (
        not isinstance(names, list)
        or not names
        or any(not isinstance(x, str) or not x for x in names)
    ):
        raise ValueError("expected instance names invalid")
    if len(names) != len(set(names)) or payload.get(
        "expected_instance_count",
    ) != len(names):
        raise ValueError("expected instance set mismatch")
    if not isinstance(endpoints, list) or len(endpoints) != len(names):
        raise ValueError("deployment endpoints mismatch")
    endpoint_names = []
    for row in endpoints:
        if not isinstance(row, dict) or set(row) != _S10B_ENDPOINT_FIELDS:
            raise ValueError("deployment endpoint fields mismatch")
        if (
            not isinstance(row.get("process_instance_id"), str)
            or not row["process_instance_id"]
            or row.get("build_id") != handoff.get("build_id")
            or row.get("artifact_sha256")
            != handoff.get("artifact", {}).get("sha256")
        ):
            raise ValueError("deployment endpoint artifact binding mismatch")
        endpoint_names.append(row["name"])
    if sorted(endpoint_names) != sorted(names) or len(endpoint_names) != len(
        set(endpoint_names),
    ):
        raise ValueError("deployment endpoint set mismatch")
    if payload.get("release_handoff_sha256") != _sha256_file(handoff_path):
        raise ValueError("deployment handoff digest mismatch")
    process_ids = [row["process_instance_id"] for row in endpoints]
    if len(process_ids) != len(set(process_ids)):
        raise ValueError("deployment process instance set mismatch")
    _parse_time(payload.get("declared_at"), "declared_at")
    _parse_time(payload.get("last_deployed_at"), "last_deployed_at")


def _validate_endpoint_url(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("endpoint URL missing")
    parsed = urlsplit(raw)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("endpoint URL contains forbidden components")
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("endpoint URL invalid")
    host = parsed.hostname
    loopback = host == "localhost"
    try:
        loopback = loopback or ip_address(host).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not loopback:
        raise ValueError("non-loopback endpoint requires HTTPS")
    return raw.rstrip("/")


def _fetch_retirement_row(
    row: dict[str, Any],
    fingerprints: dict[str, str],
    window: int,
) -> dict[str, Any]:
    started = _utc_now()
    result: dict[str, Any] = {
        "name": row["name"],
        "requested_at": _iso(started),
        "decision": "REFUSED",
        "reasons": [],
    }
    try:
        base_url = _validate_endpoint_url(row["base_url"])
        env_name = row["bearer_token_env"]
        if (
            not isinstance(env_name, str)
            or not env_name
            or not os.environ.get(env_name)
        ):
            raise ValueError("endpoint bearer token unavailable")
        nonce = secrets.token_urlsafe(40)
        with httpx.Client(
            timeout=httpx.Timeout(5.0, connect=3.0),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(
                f"{base_url}/api/browser-core/retirement-evidence",
                headers={
                    "Authorization": f"Bearer {os.environ[env_name]}",
                    "X-QwenPaw-Retirement-Nonce": nonce,
                },
            )
        if response.status_code != 200:
            raise ValueError(f"unexpected HTTP status {response.status_code}")
        if response.headers.get("cache-control") != "no-store":
            raise ValueError("Cache-Control no-store required")
        if "application/json" not in response.headers.get("content-type", ""):
            raise ValueError("application/json required")
        evidence = response.json()
        if (
            not isinstance(evidence, dict)
            or evidence.get("request_nonce") != nonce
        ):
            raise ValueError("retirement nonce mismatch")
        _validate_remote_evidence(evidence, fingerprints, window)
        if evidence["process_instance_id"] != row["process_instance_id"]:
            raise ValueError("attested process instance mismatch")
        result.update(
            {
                "decision": "AUTHORIZED",
                "responded_at": _iso(_utc_now()),
                "process_instance_id": evidence["process_instance_id"],
                "build_id": row["build_id"],
                "artifact_sha256": row["artifact_sha256"],
                "response_sha256": sha256(
                    serialize_retirement_evidence(evidence).encode(),
                ).hexdigest(),
                "evidence": evidence,
            },
        )
    except Exception as exc:  # noqa: BLE001 - fail-closed evidence row
        result["responded_at"] = _iso(_utc_now())
        result["reasons"] = [str(exc)]
    return result


def _validate_remote_evidence(
    payload: dict[str, Any],
    fingerprints: dict[str, str],
    window: int,
    *,
    reference_time: datetime | None = None,
) -> None:
    if (
        set(payload) != _REMOTE_EVIDENCE_FIELDS
        or payload.get("schema_version") != 1
        or payload.get("fingerprints") != fingerprints
    ):
        raise ValueError("remote schema or fingerprints mismatch")
    nonce = payload.get("request_nonce")
    if not isinstance(nonce, str) or len(nonce) < 40:
        raise ValueError("remote nonce invalid")
    observed = _parse_time(payload.get("observed_at"), "observed_at")
    reference = reference_time or _utc_now()
    if abs((reference - observed).total_seconds()) > 30:
        raise ValueError("remote observation is stale")
    if (
        payload.get("host_default") != "CANONICAL"
        or payload.get("required_quiet_window_seconds") != window
    ):
        raise ValueError("remote Canonical/window mismatch")
    admission = payload.get("legacy_admission")
    sample = payload.get("sample")
    if not isinstance(admission, dict) or admission.get("closed") is not True:
        raise ValueError("Legacy admission is not CLOSED")
    if not isinstance(sample, dict) or sample.get("consistent") is not True:
        raise ValueError("remote sample is inconsistent")
    if sample.get("host_revision_before") != sample.get(
        "host_revision_after",
    ) or sample.get("bridge_revision_before") != sample.get(
        "bridge_revision_after",
    ):
        raise ValueError("remote revisions changed")
    if payload.get("unknown_reasons") != {}:
        raise ValueError("remote UNKNOWN facts present")
    host = payload.get("host_counts")
    bridge = payload.get("bridge_counts")
    if (
        not isinstance(host, dict)
        or set(host) != _HOST_ZERO_KEYS
        or any(value != 0 for value in host.values())
    ):
        raise ValueError("remote Host facts non-zero or incomplete")
    if (
        not isinstance(bridge, dict)
        or set(bridge) != _BRIDGE_ZERO_KEYS
        or any(value != 0 for value in bridge.values())
    ):
        raise ValueError("remote Bridge facts non-zero or incomplete")
    ages = [
        payload.get("process_uptime_seconds"),
        admission.get("closed_age_seconds"),
        payload.get("canonical_admission_age_seconds"),
        payload.get("legacy_quiet_seconds"),
        payload.get("bridge_legacy_quiet_seconds"),
    ]
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < window
        for value in ages
    ):
        raise ValueError("remote quiet/admission/uptime insufficient")
    usage = payload.get("legacy_usage")
    if not isinstance(usage, list):
        raise ValueError("remote Legacy usage missing")
    for item in usage:
        if (
            not isinstance(item, dict)
            or item.get("active_calls") != 0
            or not isinstance(item.get("quiet_seconds"), int)
            or item["quiet_seconds"] < window
        ):
            raise ValueError(
                "remote Legacy caller active or insufficiently quiet",
            )
    process_id = payload.get("process_instance_id")
    if not isinstance(process_id, str) or not process_id:
        raise ValueError("remote process id missing")


def retirement_gate(
    release_handoff: str | Path,
    deployment_attestation: str | Path,
    rollback_report: str | Path,
    report: str | Path,
) -> dict[str, Any]:
    """Query only the attested live endpoints and atomically save a verdict."""
    handoff_path = Path(release_handoff).expanduser().resolve()
    deployment_path = Path(deployment_attestation).expanduser().resolve()
    rollback_path = Path(rollback_report).expanduser().resolve()
    handoff = _read_json_object(handoff_path)
    deployment = _read_json_object(deployment_path)
    rollback = _read_json_object(rollback_path)
    if (
        handoff.get("outcome") != "READY_FOR_DEPLOYMENT"
        or handoff.get("legacy_state") != "present"
    ):
        raise ValueError(
            "S10A handoff is not deployable Legacy-present evidence",
        )
    if (
        rollback.get("schema_version") != 1
        or rollback.get("outcome") != "PASS"
    ):
        raise ValueError("rollback report is not PASS")
    rollback_row = handoff.get("rollback_report")
    if not isinstance(rollback_row, dict) or rollback_row.get(
        "sha256",
    ) != _sha256_file(rollback_path):
        raise ValueError("rollback digest mismatch")
    _validate_attestation(deployment, handoff_path, handoff)
    if deployment.get("s10a_build_id") != handoff.get("build_id"):
        raise ValueError("deployed S10A build mismatch")
    fingerprints = _require_fingerprints(handoff.get("fingerprints"))
    window = handoff.get("required_quiet_window_seconds")
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        raise ValueError("required quiet window invalid")
    raw_endpoints = deployment.get("endpoints")
    if not isinstance(raw_endpoints, list) or not all(
        isinstance(row, dict) for row in raw_endpoints
    ):
        raise ValueError("deployment endpoints invalid")
    endpoints = [row for row in raw_endpoints if isinstance(row, dict)]
    with ThreadPoolExecutor(max_workers=min(8, len(endpoints))) as pool:
        rows = list(
            pool.map(
                lambda row: _fetch_retirement_row(row, fingerprints, window),
                endpoints,
            ),
        )
    process_ids = [
        row.get("process_instance_id")
        for row in rows
        if row.get("decision") == "AUTHORIZED"
    ]
    if len(process_ids) != len(set(process_ids)):
        for row in rows:
            row["decision"] = "REFUSED"
            row["reasons"] = ["duplicate process instance id"]
    completed = _utc_now()
    outcome = (
        "AUTHORIZED"
        if rows and all(row["decision"] == "AUTHORIZED" for row in rows)
        else "REFUSED"
    )
    payload = {
        "schema_version": RETIREMENT_REPORT_SCHEMA,
        "outcome": outcome,
        "completed_at": _iso(completed),
        "authorization_max_age_seconds": 300,
        "expires_at": _iso(completed + timedelta(seconds=300)),
        "required_quiet_window_seconds": window,
        "scope_id": deployment["scope_id"],
        "deployment_generation": deployment["deployment_generation"],
        "expected_instance_names": deployment["expected_instance_names"],
        "expected_instance_set_sha256": _instance_set_digest(
            deployment["expected_instance_names"],
        ),
        "process_instance_ids": process_ids,
        "build_id": handoff["build_id"],
        "artifact_sha256": handoff["artifact"]["sha256"],
        "fingerprints": fingerprints,
        "input_sha256": {
            "release_handoff": _sha256_file(handoff_path),
            "deployment_attestation": _sha256_file(deployment_path),
            "rollback_report": _sha256_file(rollback_path),
        },
        "verifier_sha256": _tool_digest(),
        "instances": rows,
    }
    write_atomic_report(report, payload)
    return payload


def verify_retirement_report(
    report: str | Path,
    release_handoff: str | Path,
    deployment_attestation: str | Path,
    rollback_report: str | Path,
    *,
    max_age_seconds: int = 300,
) -> dict[str, Any]:
    handoff_path = Path(release_handoff).expanduser().resolve()
    deployment_path = Path(deployment_attestation).expanduser().resolve()
    rollback_path = Path(rollback_report).expanduser().resolve()
    payload = _read_json_object(report)
    handoff = _read_json_object(handoff_path)
    deployment = _read_json_object(deployment_path)
    rollback = _read_json_object(rollback_path)
    if (
        set(payload) != _RETIREMENT_REPORT_FIELDS
        or payload.get("schema_version") != RETIREMENT_REPORT_SCHEMA
        or payload.get("outcome") != "AUTHORIZED"
    ):
        raise ValueError("retirement report is not AUTHORIZED")
    if (
        handoff.get("outcome") != "READY_FOR_DEPLOYMENT"
        or handoff.get("legacy_state") != "present"
        or rollback.get("schema_version") != 1
        or rollback.get("outcome") != "PASS"
    ):
        raise ValueError("retirement report source release is invalid")
    _validate_attestation(deployment, handoff_path, handoff)
    completed = _parse_time(payload.get("completed_at"), "completed_at")
    expires = _parse_time(payload.get("expires_at"), "expires_at")
    now = _utc_now()
    if (
        now > expires
        or (now - completed).total_seconds() > max_age_seconds
        or payload.get("authorization_max_age_seconds") != 300
        or (expires - completed).total_seconds() != 300
    ):
        raise ValueError("retirement authorization expired")
    expected_digests = {
        "release_handoff": _sha256_file(handoff_path),
        "deployment_attestation": _sha256_file(deployment_path),
        "rollback_report": _sha256_file(rollback_path),
    }
    if (
        payload.get("input_sha256") != expected_digests
        or payload.get("verifier_sha256") != _tool_digest()
    ):
        raise ValueError("retirement report input/tool digest mismatch")
    names = deployment.get("expected_instance_names")
    endpoints = deployment.get("endpoints")
    rows = payload.get("instances")
    fingerprints = _require_fingerprints(handoff.get("fingerprints"))
    window = handoff.get("required_quiet_window_seconds")
    artifact_sha256 = handoff.get("artifact", {}).get("sha256")
    if (
        not isinstance(names, list)
        or not all(isinstance(name, str) and name for name in names)
        or not isinstance(endpoints, list)
        or not all(isinstance(row, dict) for row in endpoints)
        or not isinstance(window, int)
        or isinstance(window, bool)
        or window <= 0
    ):
        raise ValueError("retirement report deployment shape mismatch")
    if (
        payload.get("build_id") != handoff.get("build_id")
        or payload.get("artifact_sha256") != artifact_sha256
        or payload.get("fingerprints") != fingerprints
        or payload.get("required_quiet_window_seconds") != window
        or payload.get("scope_id") != deployment.get("scope_id")
        or payload.get("deployment_generation")
        != deployment.get("deployment_generation")
        or payload.get("expected_instance_names") != names
        or payload.get("expected_instance_set_sha256")
        != _instance_set_digest(names)
    ):
        raise ValueError("retirement report build mismatch")
    if (
        not isinstance(rows, list)
        or len(rows) != len(names)
        or [row.get("name") for row in rows] != names
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise ValueError("retirement report instance set mismatch")
    endpoint_rows = {
        row["name"]: row for row in endpoints if isinstance(row, dict)
    }
    process_ids: list[str] = []
    for row in rows:
        if set(row) != _AUTHORIZED_INSTANCE_FIELDS:
            raise ValueError("retirement instance fields mismatch")
        endpoint = endpoint_rows.get(row["name"])
        evidence = row.get("evidence")
        if not isinstance(endpoint, dict) or not isinstance(evidence, dict):
            raise ValueError("retirement instance evidence missing")
        process_id = evidence.get("process_instance_id")
        requested_at = _parse_time(row.get("requested_at"), "requested_at")
        responded_at = _parse_time(row.get("responded_at"), "responded_at")
        _validate_remote_evidence(
            evidence,
            fingerprints,
            window,
            reference_time=responded_at,
        )
        if (
            row.get("decision") != "AUTHORIZED"
            or row.get("reasons") != []
            or requested_at > responded_at
            or responded_at > completed
            or row.get("process_instance_id") != process_id
            or process_id != endpoint.get("process_instance_id")
            or row.get("build_id") != handoff.get("build_id")
            or row.get("build_id") != endpoint.get("build_id")
            or row.get("artifact_sha256") != artifact_sha256
            or row.get("artifact_sha256") != endpoint.get("artifact_sha256")
            or row.get("response_sha256")
            != sha256(
                serialize_retirement_evidence(evidence).encode(),
            ).hexdigest()
        ):
            raise ValueError("retirement instance evidence mismatch")
        process_ids.append(str(process_id))
    if (
        len(process_ids) != len(set(process_ids))
        or payload.get("process_instance_ids") != process_ids
    ):
        raise ValueError("retirement process instance set mismatch")
    return payload


def verify_legacy_inventory(
    release_handoff: str | Path,
    source_root: str | Path,
    *,
    mode: str,
) -> None:
    handoff = _read_json_object(release_handoff)
    rows = handoff.get("legacy_inventory")
    if not isinstance(rows, list) or [row.get("path") for row in rows] != list(
        LEGACY_PUBLIC_PATHS,
    ):
        raise ValueError("legacy inventory mismatch")
    root = Path(source_root)
    for row in rows:
        path = root / row["path"]
        if mode == "present":
            if not path.is_file() or _sha256_file(path) != row.get("sha256"):
                raise ValueError("legacy inventory source mismatch")
        elif mode == "absent":
            if path.exists():
                raise ValueError("legacy inventory target still present")
        else:
            raise ValueError("legacy inventory mode invalid")


def _bridge_baseline_binding(
    release_handoff: str | Path,
) -> dict[str, Any]:
    handoff_path = Path(release_handoff).expanduser().resolve()
    handoff = _read_json_object(handoff_path)
    source = handoff.get("source")
    if (
        handoff.get("schema_version") != RELEASE_HANDOFF_SCHEMA
        or handoff.get("outcome") != "READY_FOR_DEPLOYMENT"
        or handoff.get("legacy_state") != "present"
        or not isinstance(source, dict)
        or set(source) != {"commit", "tree"}
        or not all(_is_hex_digest(source.get(key)) for key in source)
    ):
        raise ValueError("S10A release handoff source identity mismatch")
    return {
        "release_handoff_sha256": _sha256_file(handoff_path),
        "source": dict(source),
    }


def _git_output(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(
            "bridge baseline source is not a Git checkout",
        ) from exc
    return completed.stdout.strip()


def _validate_bridge_baseline_source(
    source_root: str | Path,
    binding: dict[str, Any],
) -> Path:
    root = Path(source_root).expanduser().resolve()
    top_level = Path(
        _git_output(root, "rev-parse", "--show-toplevel"),
    ).resolve()
    if top_level != root:
        raise ValueError("bridge baseline source root mismatch")
    if _git_output(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("bridge baseline source is not clean")
    try:
        symbolic_head = subprocess.run(
            ["git", "-C", str(root), "symbolic-ref", "-q", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ValueError(
            "bridge baseline source detached state is unavailable",
        ) from exc
    if symbolic_head.returncode == 0:
        raise ValueError("bridge baseline source is not detached")
    if symbolic_head.returncode != 1:
        raise ValueError("bridge baseline source detached state is invalid")
    source = binding["source"]
    if (
        _git_output(root, "rev-parse", "HEAD") != source["commit"]
        or _git_output(root, "rev-parse", "HEAD^{tree}") != source["tree"]
    ):
        raise ValueError("bridge baseline source identity mismatch")
    return root


def _verify_bridge_pre_root_binding(
    payload: dict[str, Any],
    *,
    baseline_source_root: str | Path,
    binding: dict[str, Any],
) -> dict[str, Any]:
    _verify_bridge_report_shape(payload, phase="pre-root")
    if payload.get("verifier_sha256") != _tool_digest():
        raise ValueError("bridge pre-root verifier digest mismatch")
    if payload.get("baseline") != binding:
        raise ValueError("bridge pre-root baseline binding mismatch")
    baseline_root = _validate_bridge_baseline_source(
        baseline_source_root,
        binding,
    )
    snapshot = _bridge_symbol_snapshot(baseline_root)
    rows = _bridge_manifest_rows(snapshot, pre_payload=None)
    outcome = _bridge_manifest_outcome(snapshot, rows, phase="pre-root")
    if (
        payload.get("scope") != snapshot.get("scope")
        or payload.get("roots") != snapshot.get("roots")
        or payload.get("rows") != rows
        or payload.get("outcome") != outcome
    ):
        raise ValueError("bridge pre-root baseline snapshot mismatch")
    return snapshot


def bridge_symbol_inventory(
    *,
    source_root: str | Path,
    phase: str,
    report: str | Path,
    release_handoff: str | Path,
    pre_root: str | Path | None = None,
    baseline_source_root: str | Path | None = None,
) -> dict[str, Any]:
    """Write the one bounded Bridge root/closure inventory."""
    if phase not in {"pre-root", "post-root"}:
        raise ValueError("bridge symbol phase invalid")
    binding = _bridge_baseline_binding(release_handoff)
    if phase == "pre-root":
        source_path = _validate_bridge_baseline_source(
            source_root,
            binding,
        )
    else:
        source_path = Path(source_root).expanduser().resolve()
    snapshot = _bridge_symbol_snapshot(source_path)
    pre_payload = None
    if phase == "post-root":
        if pre_root is None or baseline_source_root is None:
            raise ValueError(
                "post-root inventory requires pre-root report and baseline source",
            )
        pre_payload = _read_json_object(pre_root)
        _verify_bridge_pre_root_binding(
            pre_payload,
            baseline_source_root=baseline_source_root,
            binding=binding,
        )
    rows = _bridge_manifest_rows(snapshot, pre_payload=pre_payload)
    payload = {
        "schema_version": BRIDGE_SYMBOL_MANIFEST_SCHEMA,
        "phase": phase,
        "outcome": _bridge_manifest_outcome(
            snapshot,
            rows,
            phase=phase,
        ),
        "verifier_sha256": _tool_digest(),
        "baseline": binding,
        "pre_root_sha256": (
            _sha256_file(Path(pre_root)) if pre_root is not None else None
        ),
        "scope": snapshot["scope"],
        "roots": snapshot["roots"],
        "rows": rows,
    }
    write_atomic_report(report, payload)
    return payload


def verify_bridge_symbol_manifest(
    *,
    report: str | Path,
    source_root: str | Path,
    mode: str,
    release_handoff: str | Path,
    baseline_source_root: str | Path,
    pre_root: str | Path | None = None,
) -> dict[str, Any]:
    """Verify one bounded Bridge inventory without widening its universe."""
    if mode not in {"pre-root", "post-root", "applied"}:
        raise ValueError("bridge symbol verification mode invalid")
    payload = _read_json_object(report)
    expected_phase = "pre-root" if mode == "pre-root" else "post-root"
    _verify_bridge_report_shape(payload, phase=expected_phase)
    binding = _bridge_baseline_binding(release_handoff)
    if payload.get("baseline") != binding:
        raise ValueError("bridge baseline binding mismatch")
    if payload.get("verifier_sha256") != _tool_digest():
        raise ValueError("bridge symbol verifier digest mismatch")
    if list(payload["scope"].get("paths") or ()) != list(
        BRIDGE_SYMBOL_PATHS,
    ):
        raise ValueError("bridge symbol universe mismatch")
    if mode in {"post-root", "applied"}:
        if pre_root is None:
            raise ValueError(
                "post-root/applied verification requires pre-root",
            )
        if payload.get("pre_root_sha256") != _sha256_file(Path(pre_root)):
            raise ValueError("bridge pre-root digest mismatch")
        pre_payload = _read_json_object(pre_root)
        _verify_bridge_pre_root_binding(
            pre_payload,
            baseline_source_root=baseline_source_root,
            binding=binding,
        )
    else:
        pre_payload = None
        _verify_bridge_pre_root_binding(
            payload,
            baseline_source_root=baseline_source_root,
            binding=binding,
        )
    current = _bridge_symbol_snapshot(Path(source_root))
    if payload.get("scope") != current.get("scope"):
        raise ValueError("bridge scoped source digest mismatch")
    if payload.get("roots") != current.get("roots"):
        raise ValueError("bridge root table mismatch")
    expected_rows = _bridge_manifest_rows(
        current,
        pre_payload=pre_payload,
    )
    if payload.get("rows") != expected_rows:
        raise ValueError("bridge symbol rows mismatch")
    expected_outcome = _bridge_manifest_outcome(
        current,
        expected_rows,
        phase=expected_phase,
    )
    if payload.get("outcome") != expected_outcome:
        raise ValueError("bridge symbol outcome mismatch")
    if mode in {"post-root", "applied"} and expected_outcome != "PROVEN":
        raise ValueError("bridge symbol closure is not proven")
    if mode == "applied":
        current_keys = set(current["symbols"])
        for row in payload["rows"]:
            key = f'{row["path"]}::{row["symbol"]}'
            if row["decision"] == "DELETE" and key in current_keys:
                raise ValueError(f"bridge DELETE symbol remains: {key}")
            if row["decision"] == "KEEP" and key not in current_keys:
                raise ValueError(f"bridge KEEP symbol missing: {key}")
    return payload


def _verify_bridge_report_shape(
    payload: dict[str, Any],
    *,
    phase: str,
) -> None:
    required = {
        "schema_version",
        "phase",
        "outcome",
        "verifier_sha256",
        "baseline",
        "pre_root_sha256",
        "scope",
        "roots",
        "rows",
    }
    if set(payload) != required:
        raise ValueError("bridge symbol report fields mismatch")
    if (
        payload.get("schema_version") != BRIDGE_SYMBOL_MANIFEST_SCHEMA
        or payload.get("phase") != phase
        or not isinstance(payload.get("baseline"), dict)
        or not isinstance(payload.get("scope"), dict)
        or not isinstance(payload.get("roots"), list)
        or not isinstance(payload.get("rows"), list)
    ):
        raise ValueError("bridge symbol report shape invalid")


def _bridge_symbol_snapshot(root: Path) -> dict[str, Any]:
    symbols: dict[str, dict[str, Any]] = {}
    source_texts: dict[str, str] = {}
    files = []
    for relative in BRIDGE_SYMBOL_PATHS:
        source_path = root / relative
        if not source_path.is_file():
            raise ValueError(f"bridge symbol path missing: {relative}")
        content = source_path.read_bytes()
        files.append({"path": relative, "sha256": sha256(content).hexdigest()})
        if source_path.suffix != ".py":
            continue
        try:
            source_text = content.decode("utf-8")
            tree = ast.parse(source_text, filename=relative)
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise ValueError(
                f"bridge symbol parse failed: {relative}",
            ) from exc
        source_texts[relative] = source_text
        imports = _bridge_import_rows(tree)
        module_body = [
            node
            for node in tree.body
            if not isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            )
        ]
        module_node = ast.Module(body=module_body, type_ignores=[])
        symbols[f"{relative}::__module__"] = {
            "path": relative,
            "symbol": "__module__",
            "references": sorted(_bridge_loaded_names(module_node)),
            "imports": imports,
            "unresolved_dynamic_inbound": _bridge_dynamic_calls(module_node),
        }
        for node in tree.body:
            for name in _bridge_defined_names(node):
                bounded_attribute_names: frozenset[str] = frozenset()
                if (
                    relative.endswith("/action_runtime/state.py")
                    and name == "ControlState"
                ):
                    bounded_attribute_names = frozenset({"field_name"})
                elif (
                    relative.endswith("/action_runtime/session_manager.py")
                    and name == "_control_remove_dialog_auto_handlers"
                ):
                    bounded_attribute_names = frozenset(
                        {"attribute", "registered"},
                    )
                symbols[f"{relative}::{name}"] = {
                    "path": relative,
                    "symbol": name,
                    "references": sorted(_bridge_loaded_names(node)),
                    "imports": imports,
                    "unresolved_dynamic_inbound": _bridge_dynamic_calls(
                        node,
                        bounded_attribute_names=bounded_attribute_names,
                    ),
                }
    for branch_path, symbol, marker, seeds in _BRIDGE_DELETE_BRANCH_SEEDS:
        if marker not in source_texts.get(branch_path, ""):
            continue
        symbols[f"{branch_path}::{symbol}"] = {
            "path": branch_path,
            "symbol": symbol,
            "references": sorted(seeds),
            "imports": [],
            "unresolved_dynamic_inbound": False,
        }
    name_index: dict[str, list[str]] = {}
    for key, row in symbols.items():
        name_index.setdefault(row["symbol"], []).append(key)
    graph = {}
    for key, row in symbols.items():
        graph[key] = tuple(
            sorted(
                {
                    target
                    for name in row["references"]
                    for target in name_index.get(name, ())
                    if target != key
                },
            ),
        )
    roots = []
    root_rows = _BRIDGE_SYMBOL_ROOTS + tuple(
        (branch_path, symbol, "DELETE")
        for branch_path, symbol, _marker, _seeds in _BRIDGE_DELETE_BRANCH_SEEDS
    )
    for path, symbol, decision in root_rows:
        roots.append(
            {
                "path": path,
                "symbol": symbol,
                "decision": decision,
                "defined": f"{path}::{symbol}" in symbols,
            },
        )
    scope_material = {"paths": list(BRIDGE_SYMBOL_PATHS), "files": files}
    scope = {
        **scope_material,
        "sha256": sha256(
            json.dumps(
                scope_material,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        ).hexdigest(),
    }
    return {"scope": scope, "roots": roots, "symbols": symbols, "graph": graph}


def _bridge_defined_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        return tuple(
            target.id for target in targets if isinstance(target, ast.Name)
        )
    return ()


def _bridge_loaded_names(node: ast.AST) -> set[str]:
    names = {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }
    names.update(
        str(child.args[1].value)
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id in {"getattr", "setattr"}
        and len(child.args) >= 2
        and isinstance(child.args[1], ast.Constant)
        and isinstance(child.args[1].value, str)
    )
    return names


def _bridge_dynamic_calls(
    node: ast.AST,
    *,
    bounded_attribute_names: frozenset[str] = frozenset(),
) -> bool:
    always_dynamic = {
        "eval",
        "exec",
        "globals",
        "locals",
        "__import__",
        "import_module",
    }
    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(
            child.func,
            ast.Name,
        ):
            continue
        if child.func.id in always_dynamic:
            return True
        if child.func.id in {"getattr", "setattr"}:
            if len(child.args) < 2:
                return True
            attribute = child.args[1]
            if isinstance(attribute, ast.Constant) and isinstance(
                attribute.value,
                str,
            ):
                continue
            if (
                isinstance(attribute, ast.Name)
                and attribute.id in bounded_attribute_names
            ):
                continue
            return True
    return False


def _bridge_import_rows(tree: ast.Module) -> list[str]:
    rows: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            rows.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + str(node.module or "")
            rows.extend(f"{module}:{alias.name}" for alias in node.names)
    return sorted(rows)


def _bridge_reachable(
    graph: dict[str, tuple[str, ...]],
    root: str,
) -> set[str]:
    pending = [root]
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(graph.get(current, ()))
    return seen


def _bridge_manifest_rows(
    snapshot: dict[str, Any],
    *,
    pre_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    symbols = snapshot["symbols"]
    graph = snapshot["graph"]
    source_roots = (
        pre_payload["roots"] if pre_payload is not None else snapshot["roots"]
    )
    delete_roots = [
        f'{row["path"]}::{row["symbol"]}'
        for row in source_roots
        if row["decision"] == "DELETE"
    ]
    keep_roots = [
        f'{row["path"]}::{row["symbol"]}'
        for row in snapshot["roots"]
        if row["decision"] == "KEEP" and row["defined"]
    ]
    delete_paths: dict[str, list[str]] = {}
    keep_paths: dict[str, list[str]] = {}
    if pre_payload is None:
        for root in delete_roots:
            for key in _bridge_reachable(graph, root):
                delete_paths.setdefault(key, []).append(root)
    else:
        for row in pre_payload["rows"]:
            key = f'{row["path"]}::{row["symbol"]}'
            for root in row.get("delete_paths") or ():
                delete_paths.setdefault(key, []).append(root)
    for root in keep_roots:
        for key in _bridge_reachable(graph, root):
            keep_paths.setdefault(key, []).append(root)
    unresolved_keep_dispatch = any(
        symbols.get(key, {}).get("unresolved_dynamic_inbound")
        for key in keep_paths
    )
    keys = (
        set(delete_paths) | set(keep_paths)
        if pre_payload is None
        else {f'{row["path"]}::{row["symbol"]}' for row in pre_payload["rows"]}
    )
    pre_rows = {
        f'{row["path"]}::{row["symbol"]}': row
        for row in (pre_payload or {}).get("rows", ())
    }
    rows = []
    for key in sorted(keys):
        path, symbol = key.rsplit("::", 1)
        current = symbols.get(key)
        dynamic = bool(
            (current and current["unresolved_dynamic_inbound"])
            or pre_rows.get(key, {}).get("unresolved_dynamic_inbound")
            or (delete_paths.get(key) and unresolved_keep_dispatch),
        )
        delete = sorted(set(delete_paths.get(key, ())))
        keep = sorted(set(keep_paths.get(key, ())))
        if (
            not keep
            and pre_payload is not None
            and current is not None
            and pre_rows.get(key, {}).get("decision") == "KEEP"
        ):
            keep = sorted(
                set(pre_rows[key].get("keep_paths") or ()),
            )
        if keep:
            decision = "KEEP"
        elif delete and not dynamic:
            decision = "DELETE"
        else:
            decision = "UNKNOWN"
        rows.append(
            {
                "path": path,
                "symbol": symbol,
                "present": current is not None,
                "decision": decision,
                "delete_paths": delete,
                "keep_paths": keep,
                "unresolved_dynamic_inbound": dynamic,
            },
        )
    return rows


def _bridge_manifest_outcome(
    snapshot: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    phase: str,
) -> str:
    if phase == "pre-root":
        return "CAPTURED"
    roots = snapshot["roots"]
    roots_valid = all(
        (row["decision"] == "DELETE" and not row["defined"])
        or (row["decision"] == "KEEP" and row["defined"])
        for row in roots
    )
    rows_valid = bool(rows) and all(
        row["decision"] in {"DELETE", "KEEP"}
        and (row["decision"] != "KEEP" or row["present"] is True)
        and (
            row["decision"] != "DELETE"
            or (
                bool(row["delete_paths"])
                and not row["keep_paths"]
                and not row["unresolved_dynamic_inbound"]
            )
        )
        for row in rows
    )
    return "PROVEN" if roots_valid and rows_valid else "REFUSED"


def verify_deployment_start_receipt(
    receipt: str | Path,
    deployment_attestation: str | Path,
    release_report: str | Path,
    authorization_report: str | Path,
) -> dict[str, Any]:
    payload = _read_json_object(receipt)
    deployment = _read_json_object(deployment_attestation)
    release = _read_json_object(release_report)
    authorization = _read_json_object(authorization_report)
    required = {
        "schema_version",
        "outcome",
        "scope_id",
        "expected_deployment_generation",
        "expected_instance_set_sha256",
        "final_authorization_sha256",
        "s10b_release_report_sha256",
        "artifact_sha256",
        "started_at",
        "rollout_lock_id",
        "rollout_policy",
    }
    if (
        set(payload) != required
        or payload.get("schema_version") != 1
        or payload.get("outcome") != "STARTED"
    ):
        raise ValueError("deployment start receipt schema mismatch")
    names = deployment.get("expected_instance_names")
    if (
        not isinstance(names, list)
        or not names
        or not all(isinstance(name, str) and name for name in names)
        or set(authorization) != _RETIREMENT_REPORT_FIELDS
        or authorization.get("schema_version") != RETIREMENT_REPORT_SCHEMA
        or authorization.get("outcome") != "AUTHORIZED"
        or authorization.get("scope_id") != deployment.get("scope_id")
        or authorization.get("deployment_generation")
        != deployment.get("deployment_generation")
        or authorization.get("expected_instance_names") != names
        or authorization.get("authorization_max_age_seconds") != 300
    ):
        raise ValueError("deployment start authorization mismatch")
    started_at = _parse_time(payload.get("started_at"), "started_at")
    authorized_at = _parse_time(
        authorization.get("completed_at"),
        "authorization completed_at",
    )
    authorization_expires = _parse_time(
        authorization.get("expires_at"),
        "authorization expires_at",
    )
    if (authorization_expires - authorized_at).total_seconds() != 300:
        raise ValueError("deployment start authorization interval mismatch")
    checks = (
        payload.get("scope_id") == deployment.get("scope_id"),
        payload.get("expected_deployment_generation")
        == deployment.get("deployment_generation"),
        payload.get("expected_instance_set_sha256")
        == _instance_set_digest(names),
        payload.get("final_authorization_sha256")
        == _sha256_file(Path(authorization_report)),
        payload.get("s10b_release_report_sha256")
        == _sha256_file(Path(release_report)),
        payload.get("artifact_sha256")
        == release.get("artifact", {}).get("sha256"),
        payload.get("rollout_policy") == "LOCKED_FORWARD_OR_FULL_ROLLBACK",
        isinstance(payload.get("rollout_lock_id"), str)
        and bool(payload.get("rollout_lock_id")),
        authorized_at <= started_at <= authorization_expires,
    )
    if not all(checks):
        raise ValueError("deployment start receipt binding mismatch")
    return payload


def verify_deployment_completion_receipt(
    receipt: str | Path,
    deployment_attestation: str | Path,
    release_handoff: str | Path,
    release_report: str | Path,
    start_receipt: str | Path,
    *,
    require_outcome: str,
) -> dict[str, Any]:
    payload = _read_json_object(receipt)
    deployment = _read_json_object(deployment_attestation)
    s10a = _read_json_object(release_handoff)
    release = _read_json_object(release_report)
    start = _read_json_object(start_receipt)
    required = {
        "schema_version",
        "outcome",
        "scope_id",
        "deployment_generation",
        "expected_instance_set_sha256",
        "start_receipt_sha256",
        "s10b_release_report_sha256",
        "artifact_sha256",
        "rollout_lock_id",
        "completed_at",
        "instances",
    }
    if (
        require_outcome not in {"COMPLETED", "ROLLED_BACK"}
        or set(payload) != required
        or payload.get("schema_version") != 1
        or payload.get("outcome") != require_outcome
    ):
        raise ValueError("deployment terminal outcome mismatch")
    names = deployment.get("expected_instance_names")
    rows = payload.get("instances")
    if (
        not isinstance(names, list)
        or not names
        or not all(isinstance(name, str) and name for name in names)
        or not isinstance(rows, list)
        or not all(isinstance(row, dict) for row in rows)
        or [row.get("name") for row in rows] != names
        or len(rows) != len(names)
    ):
        raise ValueError("deployment terminal instance set mismatch")
    expected_artifact = (
        release.get("artifact", {}).get("sha256")
        if require_outcome == "COMPLETED"
        else s10a.get("artifact", {}).get("sha256")
    )
    expected_build = (
        release.get("build_id")
        if require_outcome == "COMPLETED"
        else s10a.get("build_id")
    )
    base_row_fields = {"name", "outcome", "build_id", "artifact_sha256"}
    rollback_row_fields = base_row_fields | {
        "process_instance_id",
        "retirement_endpoint_present",
        "legacy_admission_closed",
    }
    for row in rows:
        expected_fields = (
            base_row_fields
            if require_outcome == "COMPLETED"
            else rollback_row_fields
        )
        if (
            set(row) != expected_fields
            or row.get("outcome") != require_outcome
            or row.get("build_id") != expected_build
            or row.get("artifact_sha256") != expected_artifact
        ):
            raise ValueError("deployment terminal row mismatch")
        if require_outcome == "ROLLED_BACK" and (
            row.get("retirement_endpoint_present") is not True
            or row.get("legacy_admission_closed") is not True
            or not isinstance(row.get("process_instance_id"), str)
            or not row.get("process_instance_id")
        ):
            raise ValueError("deployment rollback restoration mismatch")
    start_required = {
        "schema_version",
        "outcome",
        "scope_id",
        "expected_deployment_generation",
        "expected_instance_set_sha256",
        "final_authorization_sha256",
        "s10b_release_report_sha256",
        "artifact_sha256",
        "started_at",
        "rollout_lock_id",
        "rollout_policy",
    }
    if (
        set(start) != start_required
        or start.get("schema_version") != 1
        or start.get("outcome") != "STARTED"
        or start.get("rollout_policy") != "LOCKED_FORWARD_OR_FULL_ROLLBACK"
    ):
        raise ValueError("deployment start receipt invalid")
    checks = (
        payload.get("scope_id") == deployment.get("scope_id"),
        payload.get("deployment_generation")
        == deployment.get("deployment_generation"),
        payload.get("expected_instance_set_sha256")
        == _instance_set_digest(names),
        payload.get("start_receipt_sha256")
        == _sha256_file(Path(start_receipt)),
        payload.get("s10b_release_report_sha256")
        == _sha256_file(Path(release_report)),
        payload.get("artifact_sha256") == expected_artifact,
        payload.get("rollout_lock_id") == start.get("rollout_lock_id"),
        payload.get("scope_id") == start.get("scope_id"),
        payload.get("deployment_generation")
        == start.get("expected_deployment_generation"),
        payload.get("expected_instance_set_sha256")
        == start.get("expected_instance_set_sha256"),
        start.get("artifact_sha256")
        == release.get("artifact", {}).get("sha256"),
        start.get("s10b_release_report_sha256")
        == _sha256_file(Path(release_report)),
        _parse_time(payload.get("completed_at"), "completed_at")
        >= _parse_time(start.get("started_at"), "started_at"),
    )
    if not all(checks):
        raise ValueError("deployment terminal binding mismatch")
    return payload


def current_build_fingerprints() -> dict[str, str]:
    """Read the checked-in current-build evidence identities."""
    manifest = json.loads(_SUPPORT_PATH.read_text(encoding="utf-8"))
    return {
        "build": str(manifest["build_fingerprint"]),
        "contract": str(manifest["contract_fingerprint"]),
        "profile": str(manifest["profile_fingerprint"]),
        "extension": str(manifest["extension_fingerprint"]),
        "provider": str(manifest["provider_fingerprint"]),
    }


def release_artifact_identity(release_dir: str | Path) -> dict[str, str]:
    """Return the only wheel in one explicit absolute release directory."""
    raw = Path(release_dir).expanduser()
    if not raw.is_absolute():
        raise ValueError("release_dir must be absolute")
    root = raw.resolve()
    if not root.is_dir():
        raise ValueError("release_dir is unavailable")
    wheels = tuple(sorted(root.glob("*.whl")))
    if len(wheels) != 1:
        raise ValueError("release_dir must contain exactly one wheel")
    artifact = wheels[0].resolve()
    return {"path": str(artifact), "sha256": _sha256_file(artifact)}


def verify_family_report(
    report_path: str | Path,
    *,
    family: CapabilityFamily | str,
    release_dir: str | Path,
) -> dict[str, Any]:
    """Strictly bind one complete PASS family report to one release wheel."""
    from .runner import registered_case_ids

    expected_family = CapabilityFamily(family)
    report = _read_json_object(report_path)
    artifact = release_artifact_identity(release_dir)
    fingerprints = current_build_fingerprints()
    if report.get("schema_version") != "browser-core-lab-v1":
        raise ValueError("family report schema mismatch")
    if report.get("outcome") != "PASS":
        raise ValueError("family report is not PASS")
    if report.get("gate") != "pre-release":
        raise ValueError("family report gate mismatch")
    if report.get("family") != expected_family.value:
        raise ValueError("family report family mismatch")
    if report.get("build") != fingerprints["build"]:
        raise ValueError("family report build mismatch")
    expected_root = str(Path(release_dir).expanduser().resolve())
    if report.get("release_dir") != expected_root:
        raise ValueError("family report release directory mismatch")
    if report.get("artifact") != artifact:
        raise ValueError("family report artifact mismatch")
    _require_fingerprints(report.get("build_fingerprints"), fingerprints)
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise ValueError("family report cases missing")
    expected_ids = registered_case_ids(expected_family)
    case_ids = tuple(
        str(case.get("case_id")) if isinstance(case, dict) else ""
        for case in cases
    )
    if len(case_ids) != len(set(case_ids)) or set(case_ids) != set(
        expected_ids,
    ):
        raise ValueError("family report case inventory mismatch")
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("invalid family case")
        if case.get("family") != expected_family.value:
            raise ValueError("family case mismatch")
        if case.get("outcome") != "PASS":
            raise ValueError("family case is not PASS")
        if case.get("artifact_sha256") != artifact["sha256"]:
            raise ValueError("family case artifact mismatch")
        _require_fingerprints(case.get("build_fingerprints"), fingerprints)
    return report


def build_release_handoff(
    *,
    legacy_state: str,
    release_dir: str | Path,
    rollback_report: str | Path | None,
    family_reports: dict[CapabilityFamily | str, str | Path],
    bridge_pre_root: str | Path | None = None,
    bridge_post_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build release evidence only; deployment facts remain external."""
    if legacy_state not in {"present", "retired"}:
        raise ValueError("invalid legacy_state")
    artifact = release_artifact_identity(release_dir)
    fingerprints = current_build_fingerprints()
    support = _read_json_object(_SUPPORT_PATH)
    max_retained = _positive_int(
        support.get("max_retained_state_ttl_seconds"),
        "max_retained_state_ttl_seconds",
    )
    max_token = _positive_int(
        support.get("max_legacy_token_ttl_seconds"),
        "max_legacy_token_ttl_seconds",
    )
    normalized = {
        CapabilityFamily(key): Path(value).expanduser().resolve()
        for key, value in family_reports.items()
    }
    if set(normalized) != set(CapabilityFamily):
        raise ValueError("exactly ten family reports are required")
    family_rows = []
    for family in CapabilityFamily:
        path = normalized[family]
        verify_family_report(path, family=family, release_dir=release_dir)
        family_rows.append(
            {
                "family": family.value,
                "path": str(path),
                "sha256": _sha256_file(path),
            },
        )
    rollback_row = _rollback_row(legacy_state, rollback_report)
    legacy_rows = _legacy_inventory(legacy_state)
    payload = {
        "schema_version": RELEASE_HANDOFF_SCHEMA,
        "outcome": "READY_FOR_DEPLOYMENT",
        "legacy_state": legacy_state,
        "source": _source_identity(),
        "build_id": f"{fingerprints['build']}:{artifact['sha256']}",
        "artifact": artifact,
        "fingerprints": fingerprints,
        "max_retained_state_ttl_seconds": max_retained,
        "max_legacy_token_ttl_seconds": max_token,
        "required_quiet_window_seconds": max(max_retained, max_token),
        "rollback_report": rollback_row,
        "family_reports": family_rows,
        "legacy_inventory": legacy_rows,
        "deployment_attestation_schema": {
            "schema_version": DEPLOYMENT_ATTESTATION_SCHEMA,
            "fact_source": "external_deployment_workflow",
            "required_fields": sorted(_DEPLOYMENT_REQUIRED_FIELDS),
            "endpoint_fields": ["name", "base_url", "bearer_token_env"],
        },
    }
    if legacy_state == "retired":
        payload["bridge_symbol_reports"] = _bridge_release_rows(
            bridge_pre_root,
            bridge_post_root,
        )
    validate_release_handoff_payload(
        payload,
        expected_legacy_state=legacy_state,
    )
    return payload


def validate_release_handoff_payload(
    payload: dict[str, Any],
    *,
    expected_legacy_state: str,
) -> None:
    """Validate the closed handoff schema without inferring file existence."""
    if not isinstance(payload, dict):
        raise ValueError("release handoff must be an object")
    if _DEPLOYMENT_FACT_KEYS.intersection(payload):
        raise ValueError("deployment facts do not belong in release handoff")
    required = {
        "schema_version",
        "outcome",
        "legacy_state",
        "source",
        "build_id",
        "artifact",
        "fingerprints",
        "max_retained_state_ttl_seconds",
        "max_legacy_token_ttl_seconds",
        "required_quiet_window_seconds",
        "rollback_report",
        "family_reports",
        "legacy_inventory",
        "deployment_attestation_schema",
    }
    if expected_legacy_state == "retired":
        required.add("bridge_symbol_reports")
    if set(payload) != required:
        raise ValueError("release handoff fields mismatch")
    if payload["schema_version"] != RELEASE_HANDOFF_SCHEMA:
        raise ValueError("release handoff schema mismatch")
    if payload["outcome"] != "READY_FOR_DEPLOYMENT":
        raise ValueError("release handoff outcome mismatch")
    if payload["legacy_state"] != expected_legacy_state:
        raise ValueError("release handoff legacy state mismatch")
    source = payload["source"]
    if not isinstance(source, dict) or set(source) != {"commit", "tree"}:
        raise ValueError("release handoff source mismatch")
    if not all(_is_hex_digest(source[key]) for key in ("commit", "tree")):
        raise ValueError("release handoff source digest mismatch")
    if not isinstance(payload["build_id"], str) or not payload["build_id"]:
        raise ValueError("release handoff build id missing")
    _require_artifact_row(payload["artifact"])
    _require_fingerprints(payload["fingerprints"])
    retained = _positive_int(
        payload["max_retained_state_ttl_seconds"],
        "max_retained_state_ttl_seconds",
    )
    token = _positive_int(
        payload["max_legacy_token_ttl_seconds"],
        "max_legacy_token_ttl_seconds",
    )
    if payload["required_quiet_window_seconds"] != max(retained, token):
        raise ValueError("required quiet window mismatch")
    family_rows = payload["family_reports"]
    if not isinstance(family_rows, list) or len(family_rows) != len(
        CapabilityFamily,
    ):
        raise ValueError("family report rows mismatch")
    families = []
    for row in family_rows:
        _require_path_digest_row(row, "family report")
        if not Path(row["path"]).is_absolute():
            raise ValueError("family report path must be absolute")
        families.append(row.get("family"))
    if families != [family.value for family in CapabilityFamily]:
        raise ValueError("family report inventory mismatch")
    legacy_rows = payload["legacy_inventory"]
    rollback = payload["rollback_report"]
    if expected_legacy_state == "present":
        _require_path_digest_row(rollback, "rollback report")
        if not isinstance(legacy_rows, list) or len(legacy_rows) != 12:
            raise ValueError("legacy inventory mismatch")
        for row in legacy_rows:
            _require_path_digest_row(row, "legacy inventory")
        if [row["path"] for row in legacy_rows] != list(LEGACY_PUBLIC_PATHS):
            raise ValueError("legacy inventory paths mismatch")
    elif expected_legacy_state == "retired":
        if rollback is not None or legacy_rows != []:
            raise ValueError("retired handoff must omit legacy and rollback")
        bridge_rows = payload["bridge_symbol_reports"]
        if not isinstance(bridge_rows, dict) or set(bridge_rows) != {
            "pre_root",
            "post_root",
        }:
            raise ValueError("retired handoff bridge reports mismatch")
        for row in bridge_rows.values():
            _require_path_digest_row(row, "bridge symbol report")
            if not Path(row["path"]).is_absolute():
                raise ValueError("bridge symbol report path must be absolute")
    else:
        raise ValueError("invalid expected legacy state")
    declaration = payload["deployment_attestation_schema"]
    if not isinstance(declaration, dict):
        raise ValueError("deployment attestation schema missing")
    if declaration.get("schema_version") != DEPLOYMENT_ATTESTATION_SCHEMA:
        raise ValueError("deployment attestation schema mismatch")
    if declaration.get("fact_source") != "external_deployment_workflow":
        raise ValueError("deployment attestation fact source mismatch")
    if declaration.get("required_fields") != sorted(
        _DEPLOYMENT_REQUIRED_FIELDS,
    ):
        raise ValueError("deployment attestation fields mismatch")
    if declaration.get("endpoint_fields") != [
        "name",
        "base_url",
        "bearer_token_env",
    ]:
        raise ValueError("deployment endpoint schema mismatch")


def verify_release_handoff(
    report_path: str | Path,
    *,
    legacy_state: str,
    release_dir: str | Path,
    rollback_report: str | Path | None,
    bridge_pre_root: str | Path | None = None,
    bridge_post_root: str | Path | None = None,
) -> dict[str, Any]:
    """Revalidate every digest and identity frozen in a handoff."""
    payload = _read_json_object(report_path)
    validate_release_handoff_payload(
        payload,
        expected_legacy_state=legacy_state,
    )
    if payload["source"] != _source_identity():
        raise ValueError("source identity mismatch")
    if payload["artifact"] != release_artifact_identity(release_dir):
        raise ValueError("release artifact mismatch")
    expected_fingerprints = current_build_fingerprints()
    _require_fingerprints(payload["fingerprints"], expected_fingerprints)
    expected_build_id = (
        f"{expected_fingerprints['build']}:" f"{payload['artifact']['sha256']}"
    )
    if payload["build_id"] != expected_build_id:
        raise ValueError("release build id mismatch")
    support = _read_json_object(_SUPPORT_PATH)
    for key in (
        "max_retained_state_ttl_seconds",
        "max_legacy_token_ttl_seconds",
    ):
        if payload[key] != _positive_int(support.get(key), key):
            raise ValueError(f"{key} mismatch")
    for row in payload["family_reports"]:
        path = Path(row["path"])
        if _sha256_file(path) != row["sha256"]:
            raise ValueError("family report digest mismatch")
        verify_family_report(
            path,
            family=CapabilityFamily(row["family"]),
            release_dir=release_dir,
        )
    expected_rollback = _rollback_row(legacy_state, rollback_report)
    if payload["rollback_report"] != expected_rollback:
        raise ValueError("rollback report mismatch")
    if payload["legacy_inventory"] != _legacy_inventory(legacy_state):
        raise ValueError("legacy inventory digest mismatch")
    if legacy_state == "retired" and payload["bridge_symbol_reports"] != (
        _bridge_release_rows(bridge_pre_root, bridge_post_root)
    ):
        raise ValueError("bridge symbol report digest mismatch")
    return payload


def _bridge_release_rows(
    pre_root: str | Path | None,
    post_root: str | Path | None,
) -> dict[str, dict[str, str]]:
    if pre_root is None or post_root is None:
        raise ValueError("retired handoff requires final Bridge reports")
    pre_path = Path(pre_root).expanduser().resolve()
    post_path = Path(post_root).expanduser().resolve()
    pre = _read_json_object(pre_path)
    post = _read_json_object(post_path)
    _verify_bridge_report_shape(pre, phase="pre-root")
    _verify_bridge_report_shape(post, phase="post-root")
    if (
        pre.get("verifier_sha256") != _tool_digest()
        or post.get("verifier_sha256") != _tool_digest()
        or pre.get("baseline") != post.get("baseline")
        or post.get("pre_root_sha256") != _sha256_file(pre_path)
        or post.get("outcome") != "PROVEN"
    ):
        raise ValueError("final Bridge report chain mismatch")
    return {
        "pre_root": {
            "path": str(pre_path),
            "sha256": _sha256_file(pre_path),
        },
        "post_root": {
            "path": str(post_path),
            "sha256": _sha256_file(post_path),
        },
    }


def _read_json_object(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON evidence") from exc
    if not isinstance(payload, dict):
        raise ValueError("evidence must be an object")
    return payload


def _sha256_file(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError(f"evidence unavailable: {path}") from exc


def _require_fingerprints(
    value: object,
    expected: dict[str, str] | None = None,
) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != _FINGERPRINT_KEYS:
        raise ValueError("fingerprint inventory mismatch")
    if not all(isinstance(item, str) and item for item in value.values()):
        raise ValueError("fingerprint value missing")
    if expected is not None and value != expected:
        raise ValueError("fingerprint identity mismatch")
    return {str(key): str(item) for key, item in value.items()}


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a finite positive integer")
    return value


def _is_hex_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) not in {40, 64}:
        return False
    return all(character in "0123456789abcdef" for character in value)


def _require_artifact_row(row: object) -> None:
    if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
        raise ValueError("artifact row mismatch")
    if not Path(str(row["path"])).is_absolute():
        raise ValueError("artifact path must be absolute")
    if not _is_hex_digest(row["sha256"]) or len(row["sha256"]) != 64:
        raise ValueError("artifact digest mismatch")


def _require_path_digest_row(row: object, label: str) -> None:
    if not isinstance(row, dict):
        raise ValueError(f"{label} row missing")
    required = {"path", "sha256"}
    allowed = required | {"family"}
    if not required.issubset(row) or not set(row).issubset(allowed):
        raise ValueError(f"{label} row mismatch")
    if not isinstance(row["path"], str) or not row["path"]:
        raise ValueError(f"{label} path missing")
    if not _is_hex_digest(row["sha256"]) or len(row["sha256"]) != 64:
        raise ValueError(f"{label} digest mismatch")


def _rollback_row(
    legacy_state: str,
    rollback_report: str | Path | None,
) -> dict[str, str] | None:
    if legacy_state == "retired":
        if rollback_report is not None:
            raise ValueError("retired handoff forbids rollback report")
        return None
    if rollback_report is None:
        raise ValueError("present handoff requires rollback report")
    path = Path(rollback_report).expanduser().resolve()
    payload = _read_json_object(path)
    if payload.get("schema_version") != 1 or payload.get("outcome") != "PASS":
        raise ValueError("rollback report is not PASS")
    return {"path": str(path), "sha256": _sha256_file(path)}


def _legacy_inventory(legacy_state: str) -> list[dict[str, str]]:
    rows = []
    for raw in LEGACY_PUBLIC_PATHS:
        path = Path(raw)
        if legacy_state == "present":
            if not path.is_file():
                raise ValueError(f"legacy path missing: {raw}")
            rows.append({"path": raw, "sha256": _sha256_file(path)})
        elif path.exists():
            raise ValueError(f"retired legacy path still exists: {raw}")
    return rows


def _source_identity() -> dict[str, str]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("source identity unavailable") from exc
    if not _is_hex_digest(commit) or not _is_hex_digest(tree):
        raise ValueError("source identity invalid")
    return {"commit": commit, "tree": tree}


def serialize_retirement_evidence(payload: dict[str, Any]) -> str:
    """Serialize a captured endpoint response for offline report storage."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def case_report(
    case: LabCase,
    result: OracleResult,
    *,
    from_report: str,
) -> dict[str, Any]:
    replay_source = from_report or "{report}"
    fingerprints = current_build_fingerprints()
    return {
        "case_id": case.case_id,
        "family": case.family.value,
        "seed": case.seed,
        "transformations": list(case.transformations),
        "prerequisites": [item.value for item in case.prerequisites],
        "fault": case.fault.value if case.fault is not None else None,
        "outcome": result.outcome.value,
        "validation_evidence": (f"{case.case_id}@{fingerprints['build']}"),
        "build_fingerprints": fingerprints,
        "oracle": {
            "provenance": _oracle_provenance(case),
            "expected": result.expected,
            "observed": result.observed,
            "diff": result.diff,
        },
        "replay_command": (
            "python -m scripts.verify.browser.core_lab.cli replay "
            f"--from-report {replay_source} --case {case.case_id} "
            "--report /tmp/browser-core-replay.json"
        ),
    }


def _oracle_provenance(case: LabCase) -> str:
    if case.family is CapabilityFamily.RESOURCE_FILE:
        return "native_transfer_effect_and_stored_byte_log"
    if case.family is CapabilityFamily.VISUAL_CANVAS:
        return "fixture_hit_event_and_target_identity_log"
    if case.family is CapabilityFamily.OBSERVE_READ:
        return "fixture_ax_dom_native_call_log"
    if case.family is CapabilityFamily.TARGET_CONTROL:
        return "fake_native_object_effect_log"
    if case.family is CapabilityFamily.STATE_APPROVAL_EFFECT:
        return (
            "native_dispatch_effect_receipt_cleanup_log"
            if case.case_id.startswith("action.fault.")
            else "approval_request_grant_attempt_log"
        )
    if (
        case.family is CapabilityFamily.SYNCHRONIZE
        and not case.case_id.startswith("synchronize.surface-")
    ):
        return "virtual_clock_raw_probe_event_log"
    return "controller_native_event_log"


def write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_atomic_report(path: str | Path, payload: dict[str, Any]) -> None:
    """Create one durable report by same-directory exclusive replace."""
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / (f".{target.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def update_s6_support_from_report(
    report: dict[str, Any],
    *,
    manifest_path: str | Path,
) -> None:
    """Promote only S6 rows backed by all exact current-build PASS cases."""
    cases = {
        item["case_id"]: item
        for item in report.get("cases", ())
        if item.get("family") == "StateApprovalEffect"
    }
    required = {
        "action.runner": (
            "action.fault.before-dispatch",
            "action.fault.after-effect-before-verify",
        ),
        "action.receipt": (
            "action.fault.after-send-before-ack",
            "action.fault.after-ack-before-effect",
            "action.fault.bridge-or-extension-loss",
        ),
        "action.reconcile": (
            "action.fault.after-effect-before-verify",
            "action.fault.during-result-mapping",
            "action.fault.drop-required-resource-block",
            "action.fault.cleanup-failure",
        ),
    }
    if any(
        case_id not in cases or cases[case_id].get("outcome") != "PASS"
        for case_ids in required.values()
        for case_id in case_ids
    ):
        return
    target = Path(manifest_path)
    manifest = json.loads(target.read_text(encoding="utf-8"))
    retained = [
        row
        for row in manifest["capabilities"]
        if row["capability_id"] not in required
    ]
    for capability_id, case_ids in required.items():
        retained.append(
            {
                "capability_id": capability_id,
                "family": "StateApprovalEffect",
                "requirement": "REQUIRED",
                "status": "READY",
                "limits": {},
                "required_blocks": [],
                "validation_evidence": [
                    cases[case_id]["validation_evidence"]
                    for case_id in case_ids
                ],
            },
        )
    manifest["capabilities"] = retained
    target.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def update_s7_support_from_report(
    report: dict[str, Any],
    *,
    manifest_path: str | Path,
) -> None:
    """Project only passing S7 primary-family evidence into support rows."""
    family = str(report.get("family") or "")
    cases = {
        str(item["case_id"]): item
        for item in report.get("cases", ())
        if item.get("family") == family
    }
    mappings: dict[str, dict[str, tuple[str, ...]]] = {
        CapabilityFamily.CONTEXT_NAVIGATE.value: {
            "context.navigate": tuple(cases),
        },
        CapabilityFamily.TARGET_CONTROL.value: {
            "target.interactions": tuple(
                case_id
                for case_id in cases
                if case_id.startswith("target.interaction-")
                or case_id
                in {"target.frame-boundary", "target.open-shadow-boundary"}
            ),
        },
        CapabilityFamily.SURFACES_WIDGETS.value: {
            "surfaces.widgets": tuple(
                case_id for case_id in cases if case_id.startswith("widget.")
            ),
            "surfaces.prompt": tuple(
                case_id
                for case_id in cases
                if case_id.startswith("prompt.")
                and case_id != "prompt.permission-handoff"
            ),
        },
        CapabilityFamily.USER_CHROME_LIFECYCLE.value: {
            "user_chrome.lifecycle": tuple(cases),
        },
    }
    required = mappings.get(family)
    if not required or any(
        not case_ids
        or any(
            case_id not in cases or cases[case_id].get("outcome") != "PASS"
            for case_id in case_ids
        )
        for case_ids in required.values()
    ):
        return
    target = Path(manifest_path)
    manifest = json.loads(target.read_text(encoding="utf-8"))
    replaced_ids = set(required)
    if family == CapabilityFamily.SURFACES_WIDGETS.value:
        replaced_ids.add("surfaces.prompt.permission")
    retained = [
        row
        for row in manifest["capabilities"]
        if row["capability_id"] not in replaced_ids
    ]
    for capability_id, case_ids in required.items():
        retained.append(
            {
                "capability_id": capability_id,
                "family": family,
                "requirement": "REQUIRED",
                "status": "READY",
                "limits": {},
                "required_blocks": [],
                "validation_evidence": [
                    cases[case_id]["validation_evidence"]
                    for case_id in case_ids
                ],
            },
        )
    if family == CapabilityFamily.SURFACES_WIDGETS.value:
        permission = cases.get("prompt.permission-handoff")
        retained.append(
            {
                "capability_id": "surfaces.prompt.permission",
                "family": family,
                "requirement": "OPTIONAL",
                "status": "BLOCKED",
                "limits": {},
                "required_blocks": [],
                "validation_evidence": (
                    [permission["validation_evidence"]] if permission else []
                ),
            },
        )
    manifest["capabilities"] = retained
    target.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def update_s8_support_from_report(
    report: dict[str, Any],
    *,
    manifest_path: str | Path,
) -> None:
    """Bind passing S8 cases to one current-build primary family."""
    family = str(report.get("family") or "")
    cases = {
        str(item["case_id"]): item
        for item in report.get("cases", ())
        if item.get("family") == family
    }
    mappings: dict[str, dict[str, tuple[str, ...]]] = {
        CapabilityFamily.RESOURCE_FILE.value: {
            "browser.resources": tuple(
                case_id
                for case_id in cases
                if case_id.startswith("resource.upload.")
            ),
            "tab.actions.upload_file": tuple(
                case_id
                for case_id in cases
                if case_id.startswith("resource.upload.")
            ),
            "tab.actions.download_file": tuple(
                case_id
                for case_id in cases
                if case_id.startswith("resource.download.")
                or case_id == "resource.condition.created-download"
            ),
            "tab.print_to_pdf": tuple(
                case_id
                for case_id in cases
                if case_id.startswith("resource.pdf.")
                or case_id == "resource.condition.created-pdf"
            ),
            "tab.actions.paste": tuple(
                case_id
                for case_id in cases
                if case_id.startswith("resource.paste.")
            ),
        },
        CapabilityFamily.SYNCHRONIZE.value: {
            "synchronize.resource.available": tuple(
                case_id
                for case_id in cases
                if case_id.startswith("synchronize.resource-available-")
            ),
        },
        CapabilityFamily.RESULT_DELIVERY.value: {
            "result.artifact_delivery": tuple(
                case_id
                for case_id in cases
                if case_id.startswith("result.artifact-")
                and case_id != "result.artifact-provider-unsupported"
            ),
        },
    }
    required = mappings.get(family)
    if not required or any(
        not case_ids
        or any(
            case_id not in cases or cases[case_id].get("outcome") != "PASS"
            for case_id in case_ids
        )
        for case_ids in required.values()
    ):
        return
    target = Path(manifest_path)
    manifest = json.loads(target.read_text(encoding="utf-8"))
    replaced = set(required)
    optional_rows: list[dict[str, Any]] = []
    if family == CapabilityFamily.RESOURCE_FILE.value:
        replaced.update(
            {
                "resource.upload.os_picker",
                "resource.print.physical",
                "resource.workspace.permission",
            },
        )
        optional_rows.extend(
            _blocked_support_row(capability_id, family)
            for capability_id in (
                "resource.upload.os_picker",
                "resource.print.physical",
            )
        )
        permission = cases.get("resource.workspace.permission-handoff")
        optional_rows.append(
            _blocked_support_row(
                "resource.workspace.permission",
                family,
                evidence=(
                    [permission["validation_evidence"]]
                    if permission is not None
                    else []
                ),
            ),
        )
    elif family == CapabilityFamily.RESULT_DELIVERY.value:
        replaced.add("result.artifact_delivery.unsupported_provider")
        optional_rows.append(
            _blocked_support_row(
                "result.artifact_delivery.unsupported_provider",
                family,
                evidence=(
                    [
                        cases["result.artifact-provider-unsupported"][
                            "validation_evidence"
                        ],
                    ]
                    if "result.artifact-provider-unsupported" in cases
                    else []
                ),
            ),
        )
    retained = [
        row
        for row in manifest["capabilities"]
        if row["capability_id"] not in replaced
    ]
    for capability_id, case_ids in required.items():
        retained.append(
            {
                "capability_id": capability_id,
                "family": family,
                "requirement": "REQUIRED",
                "status": "READY",
                "limits": {},
                "required_blocks": (
                    ["artifact"]
                    if capability_id == "result.artifact_delivery"
                    else []
                ),
                "validation_evidence": [
                    cases[case_id]["validation_evidence"]
                    for case_id in case_ids
                ],
            },
        )
    manifest["capabilities"] = retained + optional_rows
    target.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


def update_s9_support_from_report(
    report: dict[str, Any],
    *,
    manifest_path: str | Path,
) -> None:
    """Keep required generic visual evidence separate from policy action."""
    if str(report.get("family") or "") != CapabilityFamily.VISUAL_CANVAS.value:
        return
    cases = {
        str(item["case_id"]): item
        for item in report.get("cases", ())
        if item.get("family") == CapabilityFamily.VISUAL_CANVAS.value
    }
    required = {
        "visual.viewport_grounding": (
            "visual.viewport-grounding-exact",
            "visual.icon-only-exact",
            "visual.repeated-targets-multiple",
            "visual.overlapping-candidates-multiple",
            "visual.frame-target-exact",
            "visual.open-shadow-target-exact",
            "visual.closed-shadow-host-exact",
            "visual.full-page-evidence-only",
        ),
        "visual.occlusion_revalidation": (
            "visual.ref-churn-stale",
            "visual.resize-stale",
            "visual.overlay-occluded-no-send",
            "visual.scroll-stale",
            "visual.zoom-stale",
            "visual.dpr-stale",
            "visual.layout-change-stale",
            *_VISUAL_FAULT_EVIDENCE,
        ),
        "visual.opaque_canvas_handoff": (
            "visual.canvas-no-policy-handoff",
            "visual.map-no-policy-handoff",
        ),
    }
    if any(
        case_id not in cases or cases[case_id].get("outcome") != "PASS"
        for case_ids in required.values()
        for case_id in case_ids
    ):
        return
    policy_case = cases.get("visual.policy-low-risk-action")
    target = Path(manifest_path)
    manifest = json.loads(target.read_text(encoding="utf-8"))
    replaced = set(required) | {"visual.policy_scoped_low_risk_action"}
    retained = [
        row
        for row in manifest["capabilities"]
        if row["capability_id"] not in replaced
    ]
    rows = [
        {
            "capability_id": capability_id,
            "family": CapabilityFamily.VISUAL_CANVAS.value,
            "requirement": "REQUIRED",
            "status": "READY",
            "limits": {},
            "required_blocks": [],
            "validation_evidence": [
                cases[case_id]["validation_evidence"] for case_id in case_ids
            ],
        }
        for capability_id, case_ids in required.items()
    ]
    rows.append(
        {
            "capability_id": "visual.policy_scoped_low_risk_action",
            "family": CapabilityFamily.VISUAL_CANVAS.value,
            "requirement": "OPTIONAL",
            "status": (
                "READY"
                if policy_case is not None
                and policy_case.get("outcome") == "PASS"
                else "BLOCKED"
            ),
            "limits": {
                "effect_ceiling": ["PRESENTATION", "SESSION_STATE"],
                "single_use": True,
            },
            "required_blocks": [],
            "validation_evidence": (
                [policy_case["validation_evidence"]]
                if policy_case is not None
                else []
            ),
        },
    )
    manifest["capabilities"] = retained + rows
    target.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


_VISUAL_FAULT_EVIDENCE = (
    "visual.fault.before-screenshot",
    "visual.fault.after-screenshot",
    "visual.fault.after-binding-issue",
    "visual.fault.after-hit-test",
    "visual.fault.after-ref-storage",
    "visual.fault.after-preflight",
    "visual.fault.after-final-revalidation",
    "visual.fault.after-input-send",
    "visual.fault.after-receipt",
    "visual.fault.after-postcondition",
)


def _blocked_support_row(
    capability_id: str,
    family: str,
    *,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "family": family,
        "requirement": "OPTIONAL",
        "status": "BLOCKED",
        "limits": {},
        "required_blocks": [],
        "validation_evidence": list(evidence or ()),
    }


__all__ = [
    "DEPLOYMENT_ATTESTATION_SCHEMA",
    "LEGACY_PUBLIC_PATHS",
    "RELEASE_HANDOFF_SCHEMA",
    "build_release_handoff",
    "case_report",
    "current_build_fingerprints",
    "release_artifact_identity",
    "retirement_gate",
    "serialize_retirement_evidence",
    "update_s6_support_from_report",
    "update_s7_support_from_report",
    "update_s8_support_from_report",
    "update_s9_support_from_report",
    "validate_release_handoff_payload",
    "verify_family_report",
    "verify_deployment_completion_receipt",
    "verify_deployment_start_receipt",
    "verify_legacy_inventory",
    "verify_retirement_report",
    "verify_release_handoff",
    "write_atomic_report",
    "write_report",
]
