# -*- coding: utf-8 -*-
"""Machine-readable Core Lab report serialization."""

from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from hashlib import sha256
import subprocess
from typing import Any

from .model import CapabilityFamily, LabCase, OracleResult

RELEASE_HANDOFF_SCHEMA = "browser-core-release-handoff-v1"
DEPLOYMENT_ATTESTATION_SCHEMA = "browser-core-deployment-attestation-v1"
LEGACY_PUBLIC_PATHS = (
    "src/qwenpaw/browser/sdk/facade/__init__.py",
    "src/qwenpaw/browser/sdk/facade/browser.py",
    "src/qwenpaw/browser/sdk/contracts.py",
    "src/qwenpaw/browser/sdk/actions/__init__.py",
    "src/qwenpaw/browser/sdk/actions/tab_actions.py",
    "src/qwenpaw/browser/sdk/primitives/tab.py",
    "src/qwenpaw/browser/sdk/primitives/tabs.py",
    "src/qwenpaw/browser/sdk/runtime/proxy.py",
    "src/qwenpaw/browser/sdk/runtime/guard.py",
    "src/qwenpaw/browser/sdk/generated/api_catalog.json",
    "src/qwenpaw/browser/sdk/generated/capabilities.json",
    "src/qwenpaw/browser/sdk/generated/help/index.md",
)
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

_SUPPORT_PATH = Path(
    "src/qwenpaw/browser/sdk/generated/browser-support.json",
)


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
    if len(case_ids) != len(set(case_ids)) or set(case_ids) != set(expected_ids):
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
            }
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
    if not isinstance(family_rows, list) or len(family_rows) != len(CapabilityFamily):
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
        _DEPLOYMENT_REQUIRED_FIELDS
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
        f"{expected_fingerprints['build']}:"
        f"{payload['artifact']['sha256']}"
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
    return payload


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
) -> None:
    if not isinstance(value, dict) or set(value) != _FINGERPRINT_KEYS:
        raise ValueError("fingerprint inventory mismatch")
    if not all(isinstance(item, str) and item for item in value.values()):
        raise ValueError("fingerprint value missing")
    if expected is not None and value != expected:
        raise ValueError("fingerprint identity mismatch")


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
    temporary = target.parent / (
        f".{target.name}.{secrets.token_hex(8)}.tmp"
    )
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
                cases[case_id]["validation_evidence"]
                for case_id in case_ids
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
    "serialize_retirement_evidence",
    "update_s6_support_from_report",
    "update_s7_support_from_report",
    "update_s8_support_from_report",
    "update_s9_support_from_report",
    "validate_release_handoff_payload",
    "verify_family_report",
    "verify_release_handoff",
    "write_atomic_report",
    "write_report",
]
