# -*- coding: utf-8 -*-
"""Machine-readable Core Lab report serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import CapabilityFamily, LabCase, OracleResult

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
    }


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
            "provenance": (
                "native_transfer_effect_and_stored_byte_log"
                if case.family is CapabilityFamily.RESOURCE_FILE
                else (
                    "fixture_ax_dom_native_call_log"
                    if case.family.value == "ObserveRead"
                    else (
                        "fake_native_object_effect_log"
                        if case.family.value == "TargetControl"
                        else (
                            (
                                "native_dispatch_effect_receipt_cleanup_log"
                                if case.case_id.startswith("action.fault.")
                                else "approval_request_grant_attempt_log"
                            )
                            if case.family.value == "StateApprovalEffect"
                            else (
                                "virtual_clock_raw_probe_event_log"
                                if case.family.value == "Synchronize"
                                and not case.case_id.startswith(
                                    "synchronize.surface-",
                                )
                                else "controller_native_event_log"
                            )
                        )
                    )
                )
            ),
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


def write_report(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
    "case_report",
    "current_build_fingerprints",
    "update_s6_support_from_report",
    "update_s7_support_from_report",
    "update_s8_support_from_report",
    "write_report",
]
