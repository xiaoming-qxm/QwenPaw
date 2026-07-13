# -*- coding: utf-8 -*-
"""CLI for deterministic Browser Core capability cases."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .model import CapabilityFamily, CaseOutcome
from .reports import (
    case_report,
    current_build_fingerprints,
    update_s6_support_from_report,
    update_s7_support_from_report,
    update_s8_support_from_report,
    update_s9_support_from_report,
    write_report,
)
from .runner import build_case, registered_case_ids, run_case


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Browser Core Lab")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument(
        "--gate",
        choices=("pr", "nightly", "pre-release"),
        required=True,
    )
    run.add_argument(
        "--family",
        choices=[item.value for item in CapabilityFamily],
        required=True,
    )
    run.add_argument("--case")
    run.add_argument("--seed", type=int, required=True)
    run.add_argument("--report", required=True)
    run.add_argument("--release-dir")
    replay = commands.add_parser("replay")
    replay.add_argument("--from-report", required=True)
    replay.add_argument("--case", required=True)
    replay.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    return _run(args) if args.command == "run" else _replay(args)


def _run(args: argparse.Namespace) -> int:
    family = CapabilityFamily(args.family)
    case_ids = (args.case,) if args.case else registered_case_ids(family)
    reports = []
    for case_id in case_ids:
        case = build_case(family=family, case_id=case_id, seed=args.seed)
        reports.append(
            case_report(case, run_case(case), from_report=args.report),
        )
    payload = {
        "schema_version": "browser-core-lab-v1",
        "build": os.environ.get(
            "QWENPAW_BUILD",
            current_build_fingerprints()["build"],
        ),
        "gate": args.gate,
        "family": family.value,
        "release_dir": args.release_dir,
        "cases": reports,
    }
    write_report(args.report, payload)
    if family is CapabilityFamily.STATE_APPROVAL_EFFECT:
        update_s6_support_from_report(
            payload,
            manifest_path=(
                "src/qwenpaw/browser/sdk/generated/browser-support.json"
            ),
        )
    if family in {
        CapabilityFamily.CONTEXT_NAVIGATE,
        CapabilityFamily.TARGET_CONTROL,
        CapabilityFamily.SURFACES_WIDGETS,
        CapabilityFamily.USER_CHROME_LIFECYCLE,
    }:
        update_s7_support_from_report(
            payload,
            manifest_path=(
                "src/qwenpaw/browser/sdk/generated/browser-support.json"
            ),
        )
    if family in {
        CapabilityFamily.RESOURCE_FILE,
        CapabilityFamily.SYNCHRONIZE,
        CapabilityFamily.RESULT_DELIVERY,
    }:
        update_s8_support_from_report(
            payload,
            manifest_path=(
                "src/qwenpaw/browser/sdk/generated/browser-support.json"
            ),
        )
    if family is CapabilityFamily.VISUAL_CANVAS:
        update_s9_support_from_report(
            payload,
            manifest_path=(
                "src/qwenpaw/browser/sdk/generated/browser-support.json"
            ),
        )
    return _exit_for(reports)


def _replay(args: argparse.Namespace) -> int:
    source = json.loads(Path(args.from_report).read_text(encoding="utf-8"))
    source_case = next(
        item for item in source["cases"] if item["case_id"] == args.case
    )
    family = CapabilityFamily(source_case["family"])
    case = build_case(
        family=family,
        case_id=args.case,
        seed=int(source_case["seed"]),
    )
    reports = [case_report(case, run_case(case), from_report=args.from_report)]
    payload = {
        "schema_version": "browser-core-lab-v1",
        "build": source["build"],
        "gate": source.get("gate", "replay"),
        "family": family.value,
        "replay_of": str(args.from_report),
        "cases": reports,
    }
    write_report(args.report, payload)
    return _exit_for(reports)


def _exit_for(reports) -> int:
    return (
        0
        if reports
        and all(item["outcome"] == CaseOutcome.PASS.value for item in reports)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
