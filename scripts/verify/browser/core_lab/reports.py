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
        "oracle": {
            "provenance": (
                "fixture_ax_dom_native_call_log"
                if case.family.value == "ObserveRead"
                else (
                    "fake_native_object_effect_log"
                    if case.family.value == "TargetControl"
                    else (
                        "approval_request_grant_attempt_log"
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


__all__ = ["case_report", "write_report"]
