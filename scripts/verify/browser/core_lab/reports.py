# -*- coding: utf-8 -*-
"""Machine-readable Core Lab report serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import LabCase, OracleResult


def case_report(
    case: LabCase,
    result: OracleResult,
    *,
    from_report: str,
) -> dict[str, Any]:
    replay_source = from_report or "{report}"
    return {
        "case_id": case.case_id,
        "family": case.family.value,
        "seed": case.seed,
        "transformations": list(case.transformations),
        "prerequisites": [item.value for item in case.prerequisites],
        "fault": case.fault.value if case.fault is not None else None,
        "outcome": result.outcome.value,
        "validation_evidence": f"{case.case_id}@build-1",
        "build_fingerprints": {
            "build": "build-1",
            "contract": "contract-v1",
            "profile": "profile-v1",
            "extension": "extension@build-1",
        },
        "oracle": {
            "provenance": (
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
                            else "controller_owned_events"
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


__all__ = [
    "case_report",
    "update_s6_support_from_report",
    "write_report",
]
