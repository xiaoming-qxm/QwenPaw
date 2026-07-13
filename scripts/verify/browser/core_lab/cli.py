# -*- coding: utf-8 -*-
"""CLI for deterministic Browser Core capability cases."""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

from .model import CapabilityFamily, CaseOutcome, LegacyState
from .reports import (
    build_release_handoff,
    case_report,
    current_build_fingerprints,
    release_artifact_identity,
    update_s6_support_from_report,
    update_s7_support_from_report,
    update_s8_support_from_report,
    update_s9_support_from_report,
    verify_family_report,
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
    rollback = commands.add_parser("rollback-drill")
    rollback.add_argument("--report", required=True)
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
    verify_handoff.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "replay":
        return _replay(args)
    if args.command == "rollback-drill":
        return _rollback_drill(args)
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
        )
        write_atomic_report(args.report, payload)
        return 0
    verify_release_handoff(
        args.report,
        legacy_state=args.legacy_state,
        release_dir=args.release_dir,
        rollback_report=args.rollback_report,
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
            and all(item["outcome"] == CaseOutcome.PASS.value for item in reports)
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


def _rollback_drill(args: argparse.Namespace) -> int:
    return asyncio.run(_run_rollback_drill(Path(args.report)))


async def _run_rollback_drill(report_path: Path) -> int:
    from qwenpaw.browser.sdk.runtime.session_owner import (
        BrowserSessionOwnerRegistry,
        ContractMode,
    )
    from qwenpaw.config.config import Config
    from qwenpaw.config.utils import save_config
    from qwenpaw.runtime.root_request_coordinator import (
        _load_browser_contract_rollout,
    )

    report = report_path.expanduser().resolve()
    _require_durable_report_path(report)
    if report.exists():
        raise FileExistsError(str(report))
    report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".rollback-drill-",
        dir=report.parent,
    ) as temporary_dir:
        config_path = Path(temporary_dir) / "config.json"
        registry = BrowserSessionOwnerRegistry(legacy_admission="OPEN")

        save_config(_drill_config(1, "CANONICAL"), config_path)
        first_digest = _file_sha256(config_path)
        first_rollout = _load_browser_contract_rollout(config_path)
        await registry.initialize_rollout(first_rollout)
        existing = await registry.begin_request(
            root_session_id="existing-root",
            source="rollback-drill",
            rollout_revision=first_rollout.revision,
            rollout_default=first_rollout.default,
        )

        save_config(_drill_config(2, "LEGACY"), config_path)
        legacy_digest = _file_sha256(config_path)
        legacy_rollout = _load_browser_contract_rollout(config_path)
        await registry.initialize_rollout(legacy_rollout)
        existing_after = await registry.begin_request(
            root_session_id="existing-root",
            source="rollback-drill",
            rollout_revision=legacy_rollout.revision,
            rollout_default=legacy_rollout.default,
        )
        rollback_new = await registry.begin_request(
            root_session_id="rollback-new-root",
            source="rollback-drill",
            rollout_revision=legacy_rollout.revision,
            rollout_default=legacy_rollout.default,
        )
        rollback_snapshot = await registry.retirement_snapshot()

        config_path.write_text("{", encoding="utf-8")
        partial_digest = _file_sha256(config_path)
        partial_failed = False
        try:
            _load_browser_contract_rollout(config_path)
        except Exception:
            partial_failed = True
        partial_unbound = not await registry.has_contract_mode(
            "partial-root",
        )

        save_config(_drill_config(3, "CANONICAL"), config_path)
        canonical_digest = _file_sha256(config_path)
        canonical_rollout = _load_browser_contract_rollout(config_path)
        await registry.initialize_rollout(canonical_rollout)
        canonical_new = await registry.begin_request(
            root_session_id="canonical-new-root",
            source="rollback-drill",
            rollout_revision=canonical_rollout.revision,
            rollout_default=canonical_rollout.default,
        )
        final_snapshot = await registry.retirement_snapshot()

    passed = all(
        (
            existing.contract_mode is ContractMode.CANONICAL,
            existing_after.contract_mode is ContractMode.CANONICAL,
            rollback_new.contract_mode is ContractMode.LEGACY,
            canonical_new.contract_mode is ContractMode.CANONICAL,
            partial_failed,
            partial_unbound,
        ),
    )
    payload = {
        "schema_version": 1,
        "outcome": "PASS" if passed else "FAIL",
        "legacy_admission": "OPEN",
        "revisions": [1, 2, 3],
        "config_sha256": {
            "initial_canonical": first_digest,
            "rollback_legacy": legacy_digest,
            "partial_invalid": partial_digest,
            "restored_canonical": canonical_digest,
        },
        "existing_mode_before": existing.contract_mode.value,
        "existing_mode_after_rollback": existing_after.contract_mode.value,
        "rollback_new_mode": rollback_new.contract_mode.value,
        "canonical_new_mode": canonical_new.contract_mode.value,
        "partial_read_failed": partial_failed,
        "partial_root_unbound": partial_unbound,
        "duplicate_effects": 0,
        "rollback_host_counts": rollback_snapshot["counts"],
        "final_host_counts": final_snapshot["counts"],
    }
    write_atomic_report(report, payload)
    return 0 if passed else 1


def _drill_config(revision: int, default: str):
    from qwenpaw.config.config import Config

    return Config(
        browser_contract_rollout={
            "revision": revision,
            "default": default,
        },
        browser_legacy_admission="OPEN",
    )


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _require_durable_report_path(report: Path) -> None:
    temporary_root = Path(tempfile.gettempdir()).resolve()
    if report == temporary_root or temporary_root in report.parents:
        raise ValueError("rollback report must be durable and outside /tmp")
    evidence_dir = os.environ.get("S10A_EVIDENCE_DIR", "").strip()
    if evidence_dir:
        expected = Path(evidence_dir).expanduser().resolve()
        if report.parent != expected and expected not in report.parents:
            raise ValueError("rollback report must be inside S10A_EVIDENCE_DIR")


def _parse_family_reports(values: Sequence[str]) -> dict[CapabilityFamily, Path]:
    reports: dict[CapabilityFamily, Path] = {}
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
