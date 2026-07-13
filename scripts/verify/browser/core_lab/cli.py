# -*- coding: utf-8 -*-
"""CLI for deterministic Browser Core capability cases."""
# pylint: disable=too-many-return-statements,too-many-statements

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .model import CapabilityFamily, CaseOutcome, LegacyState
from .reports import (
    bridge_symbol_inventory,
    build_release_handoff,
    case_report,
    current_build_fingerprints,
    release_artifact_identity,
    retirement_gate,
    update_s6_support_from_report,
    update_s7_support_from_report,
    update_s8_support_from_report,
    update_s9_support_from_report,
    verify_family_report,
    verify_bridge_symbol_manifest,
    verify_deployment_completion_receipt,
    verify_deployment_start_receipt,
    verify_legacy_inventory,
    verify_retirement_report,
    verify_release_handoff,
    write_atomic_report,
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
    verify_family = commands.add_parser("verify-family-report")
    verify_family.add_argument(
        "--family",
        choices=[item.value for item in CapabilityFamily],
        required=True,
    )
    verify_family.add_argument("--release-dir", required=True)
    verify_family.add_argument("--report", required=True)
    handoff = commands.add_parser("release-handoff")
    handoff.add_argument(
        "--legacy-state",
        choices=[item.value for item in LegacyState],
        required=True,
    )
    handoff.add_argument("--release-dir", required=True)
    handoff.add_argument("--rollback-report")
    handoff.add_argument("--bridge-pre-root")
    handoff.add_argument("--bridge-post-root")
    handoff.add_argument("--family-report", action="append", default=[])
    handoff.add_argument("--report", required=True)
    verify_handoff = commands.add_parser("verify-release-handoff")
    verify_handoff.add_argument(
        "--legacy-state",
        choices=[item.value for item in LegacyState],
        required=True,
    )
    verify_handoff.add_argument("--release-dir", required=True)
    verify_handoff.add_argument("--rollback-report")
    verify_handoff.add_argument("--bridge-pre-root")
    verify_handoff.add_argument("--bridge-post-root")
    verify_handoff.add_argument("--report", required=True)
    retirement = commands.add_parser("retirement-gate")
    retirement.add_argument("--release-handoff", required=True)
    retirement.add_argument("--deployment-attestation", required=True)
    retirement.add_argument("--rollback-report", required=True)
    retirement.add_argument("--report", required=True)
    verify_retirement = commands.add_parser("verify-retirement-report")
    verify_retirement.add_argument("--release-handoff", required=True)
    verify_retirement.add_argument("--deployment-attestation", required=True)
    verify_retirement.add_argument("--rollback-report", required=True)
    verify_retirement.add_argument("--max-age-seconds", type=int, default=300)
    verify_retirement.add_argument("--report", required=True)
    inventory = commands.add_parser("verify-legacy-inventory")
    inventory.add_argument(
        "--mode",
        choices=("present", "absent"),
        required=True,
    )
    inventory.add_argument("--release-handoff", required=True)
    inventory.add_argument("--source-root", required=True)
    bridge_inventory = commands.add_parser("bridge-symbol-inventory")
    bridge_inventory.add_argument(
        "--phase",
        choices=("pre-root", "post-root"),
        required=True,
    )
    bridge_inventory.add_argument("--source-root", required=True)
    bridge_inventory.add_argument("--release-handoff", required=True)
    bridge_inventory.add_argument("--baseline-source-root")
    bridge_inventory.add_argument("--pre-root")
    bridge_inventory.add_argument("--report", required=True)
    verify_bridge = commands.add_parser("verify-bridge-symbol-manifest")
    verify_bridge.add_argument(
        "--mode",
        choices=("pre-root", "post-root", "applied"),
        required=True,
    )
    verify_bridge.add_argument("--source-root", required=True)
    verify_bridge.add_argument("--release-handoff", required=True)
    verify_bridge.add_argument("--baseline-source-root", required=True)
    verify_bridge.add_argument("--pre-root")
    verify_bridge.add_argument("--report", required=True)
    start_receipt = commands.add_parser("verify-deployment-start-receipt")
    start_receipt.add_argument("--deployment-attestation", required=True)
    start_receipt.add_argument("--release-report", required=True)
    start_receipt.add_argument("--authorization-report", required=True)
    start_receipt.add_argument("--receipt", required=True)
    terminal_receipt = commands.add_parser(
        "verify-deployment-completion-receipt",
    )
    terminal_receipt.add_argument(
        "--require-outcome",
        choices=("COMPLETED", "ROLLED_BACK"),
        required=True,
    )
    terminal_receipt.add_argument("--deployment-attestation", required=True)
    terminal_receipt.add_argument("--release-handoff", required=True)
    terminal_receipt.add_argument("--release-report", required=True)
    terminal_receipt.add_argument("--start-receipt", required=True)
    terminal_receipt.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "replay":
        return _replay(args)
    if args.command == "verify-family-report":
        verify_family_report(
            args.report,
            family=CapabilityFamily(args.family),
            release_dir=args.release_dir,
        )
        return 0
    if args.command == "release-handoff":
        payload = build_release_handoff(
            legacy_state=args.legacy_state,
            release_dir=args.release_dir,
            rollback_report=args.rollback_report,
            family_reports=_parse_family_reports(args.family_report),
            bridge_pre_root=args.bridge_pre_root,
            bridge_post_root=args.bridge_post_root,
        )
        write_atomic_report(args.report, payload)
        return 0
    if args.command == "retirement-gate":
        payload = retirement_gate(
            args.release_handoff,
            args.deployment_attestation,
            args.rollback_report,
            args.report,
        )
        return 0 if payload["outcome"] == "AUTHORIZED" else 1
    if args.command == "verify-retirement-report":
        verify_retirement_report(
            args.report,
            args.release_handoff,
            args.deployment_attestation,
            args.rollback_report,
            max_age_seconds=args.max_age_seconds,
        )
        return 0
    if args.command == "verify-legacy-inventory":
        verify_legacy_inventory(
            args.release_handoff,
            args.source_root,
            mode=args.mode,
        )
        return 0
    if args.command == "bridge-symbol-inventory":
        bridge_symbol_inventory(
            source_root=args.source_root,
            phase=args.phase,
            pre_root=args.pre_root,
            release_handoff=args.release_handoff,
            baseline_source_root=args.baseline_source_root,
            report=args.report,
        )
        return 0
    if args.command == "verify-bridge-symbol-manifest":
        verify_bridge_symbol_manifest(
            report=args.report,
            source_root=args.source_root,
            mode=args.mode,
            pre_root=args.pre_root,
            release_handoff=args.release_handoff,
            baseline_source_root=args.baseline_source_root,
        )
        return 0
    if args.command == "verify-deployment-start-receipt":
        verify_deployment_start_receipt(
            args.receipt,
            args.deployment_attestation,
            args.release_report,
            args.authorization_report,
        )
        return 0
    if args.command == "verify-deployment-completion-receipt":
        verify_deployment_completion_receipt(
            args.receipt,
            args.deployment_attestation,
            args.release_handoff,
            args.release_report,
            args.start_receipt,
            require_outcome=args.require_outcome,
        )
        return 0
    verify_release_handoff(
        args.report,
        legacy_state=args.legacy_state,
        release_dir=args.release_dir,
        rollback_report=args.rollback_report,
        bridge_pre_root=args.bridge_pre_root,
        bridge_post_root=args.bridge_post_root,
    )
    return 0


def _run(args: argparse.Namespace) -> int:
    family = CapabilityFamily(args.family)
    artifact = None
    if args.gate == "pre-release":
        if not args.release_dir:
            raise ValueError("pre-release gate requires --release-dir")
        artifact = release_artifact_identity(args.release_dir)
    case_ids = (args.case,) if args.case else registered_case_ids(family)
    reports = []
    for case_id in case_ids:
        case = build_case(family=family, case_id=case_id, seed=args.seed)
        reports.append(
            case_report(case, run_case(case), from_report=args.report),
        )
    if artifact is not None:
        for report in reports:
            report["artifact_sha256"] = artifact["sha256"]
    payload = {
        "schema_version": "browser-core-lab-v1",
        "outcome": (
            "PASS"
            if reports
            and all(
                item["outcome"] == CaseOutcome.PASS.value for item in reports
            )
            else "FAIL"
        ),
        "build": os.environ.get(
            "QWENPAW_BUILD",
            current_build_fingerprints()["build"],
        ),
        "gate": args.gate,
        "family": family.value,
        "release_dir": args.release_dir,
        "artifact": artifact,
        "build_fingerprints": current_build_fingerprints(),
        "cases": reports,
    }
    write_report(args.report, payload)
    if (
        args.gate != "pre-release"
        and family is CapabilityFamily.STATE_APPROVAL_EFFECT
    ):
        update_s6_support_from_report(
            payload,
            manifest_path=(
                "src/qwenpaw/browser/sdk/generated/browser-support.json"
            ),
        )
    if args.gate != "pre-release" and family in {
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
    if args.gate != "pre-release" and family in {
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
    if args.gate != "pre-release" and family is CapabilityFamily.VISUAL_CANVAS:
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


def _parse_family_reports(
    values: Sequence[str],
) -> dict[CapabilityFamily | str, str | Path]:
    reports: dict[CapabilityFamily | str, str | Path] = {}
    for value in values:
        family_name, separator, raw_path = value.partition("=")
        if not separator or not raw_path:
            raise ValueError("family report must use FAMILY=PATH")
        family = CapabilityFamily(family_name)
        if family in reports:
            raise ValueError("duplicate family report")
        reports[family] = Path(raw_path)
    if set(reports) != set(CapabilityFamily):
        raise ValueError("exactly ten family reports are required")
    return reports


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
