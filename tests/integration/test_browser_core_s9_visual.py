# -*- coding: utf-8 -*-
"""S9 VisualCanvas Core Lab and current-build evidence gates."""

from __future__ import annotations

from dataclasses import replace
import json

from scripts.verify.browser.core_lab.model import CapabilityFamily
from scripts.verify.browser.core_lab.oracle import IndependentOracle
from scripts.verify.browser.core_lab.reports import (
    case_report,
    current_build_fingerprints,
    update_s9_support_from_report,
)
from scripts.verify.browser.core_lab.runner import (
    _visual_canvas_facts,
    build_case,
    registered_case_ids,
    run_case,
)


def test_visual_canvas_current_build_case_report_binding_exists() -> None:
    case_ids = registered_case_ids(CapabilityFamily.VISUAL_CANVAS)
    assert "visual.viewport-grounding-exact" in case_ids
    assert len(case_ids) == len(set(case_ids))
    case = build_case(
        family=CapabilityFamily.VISUAL_CANVAS,
        case_id="visual.viewport-grounding-exact",
        seed=7,
    )
    report = case_report(case, run_case(case), from_report="report.json")
    build = current_build_fingerprints()["build"]
    assert report["outcome"] == "PASS"
    assert report["validation_evidence"].endswith(f"@{build}")
    assert report["oracle"]["provenance"] == (
        "fixture_hit_event_and_target_identity_log"
    )


def test_visual_canvas_variants_and_faults_are_primary_and_pass() -> None:
    case_ids = registered_case_ids(CapabilityFamily.VISUAL_CANVAS)
    required_variants = {
        "visual.icon-only-exact",
        "visual.repeated-targets-multiple",
        "visual.overlapping-candidates-multiple",
        "visual.ref-churn-stale",
        "visual.frame-target-exact",
        "visual.open-shadow-target-exact",
        "visual.closed-shadow-host-exact",
        "visual.canvas-no-policy-handoff",
        "visual.map-no-policy-handoff",
        "visual.resize-stale",
        "visual.overlay-occluded-no-send",
        "visual.scroll-stale",
        "visual.zoom-stale",
        "visual.dpr-stale",
        "visual.layout-change-stale",
        "visual.full-page-evidence-only",
        "visual.policy-low-risk-action",
    }
    assert required_variants.issubset(case_ids)
    cases = [
        build_case(
            family=CapabilityFamily.VISUAL_CANVAS,
            case_id=case_id,
            seed=7,
        )
        for case_id in case_ids
    ]
    assert all(case.family is CapabilityFamily.VISUAL_CANVAS for case in cases)
    assert all(
        case.prerequisites == (CapabilityFamily.TARGET_CONTROL,)
        for case in cases
    )
    results = [run_case(case) for case in cases]
    assert results
    assert all(result.outcome.value == "PASS" for result in results)
    assert all(result.observed["raw_coordinate_dispatch_count"] == 0 for result in results)
    assert all(result.observed["proximity_choice_count"] == 0 for result in results)
    assert all(result.observed["effect_count_at_most_one"] is True for result in results)


def test_visual_canvas_transformations_and_fault_cuts_are_explicit() -> None:
    cases = [
        build_case(
            family=CapabilityFamily.VISUAL_CANVAS,
            case_id=case_id,
            seed=7,
        )
        for case_id in registered_case_ids(CapabilityFamily.VISUAL_CANVAS)
    ]
    transformations = {
        transformation
        for case in cases
        for transformation in case.transformations
    }
    assert {
        "rename_ids",
        "rename_classes",
        "rename_text",
        "reorder_repeated_candidates",
        "wrap_containers",
        "alter_viewport",
        "alter_dpr",
        "alter_zoom",
        "delay_layout",
        "replace_nodes_preserve_identity",
        "replace_nodes_change_identity",
    }.issubset(transformations)
    faults = {case.fault.value for case in cases if case.fault is not None}
    assert faults == {
        "visual.before_screenshot",
        "visual.after_screenshot",
        "visual.after_binding_issue",
        "visual.after_hit_test",
        "visual.after_ref_storage",
        "visual.after_preflight",
        "visual.after_final_revalidation",
        "visual.after_input_send",
        "visual.after_receipt",
        "visual.after_postcondition",
    }


def test_visual_canvas_oracle_rejects_wrong_native_event_identity() -> None:
    case = build_case(
        family=CapabilityFamily.VISUAL_CANVAS,
        case_id="visual.viewport-grounding-exact",
        seed=7,
    )
    facts = _visual_canvas_facts(case)
    forged = replace(
        facts,
        native_event_target_identities=("fixture-target-forged",),
    )
    result = IndependentOracle().evaluate_visual_canvas(forged)
    assert result.outcome.value == "PRODUCT_FAILURE"
    assert "event_targets_match_fixture" in result.diff


def test_visual_canvas_support_keeps_required_and_optional_separate(
    tmp_path,
) -> None:
    cases = []
    for case_id in registered_case_ids(CapabilityFamily.VISUAL_CANVAS):
        case = build_case(
            family=CapabilityFamily.VISUAL_CANVAS,
            case_id=case_id,
            seed=7,
        )
        cases.append(case_report(case, run_case(case), from_report="report.json"))
    payload = {"family": "VisualCanvas", "cases": cases}
    source = "src/qwenpaw/browser/sdk/generated/browser-support.json"
    manifest_path = tmp_path / "browser-support.json"
    manifest_path.write_text(open(source, encoding="utf-8").read(), encoding="utf-8")

    update_s9_support_from_report(payload, manifest_path=manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = {
        row["capability_id"]: row
        for row in manifest["capabilities"]
        if row["family"] == "VisualCanvas"
    }
    required = {
        "visual.viewport_grounding",
        "visual.occlusion_revalidation",
        "visual.opaque_canvas_handoff",
    }
    assert required.issubset(rows)
    assert all(rows[item]["requirement"] == "REQUIRED" for item in required)
    assert all(rows[item]["status"] == "READY" for item in required)
    optional = rows["visual.policy_scoped_low_risk_action"]
    assert optional["requirement"] == "OPTIONAL"
    assert optional["status"] == "READY"
    optional_evidence = set(optional["validation_evidence"])
    assert optional_evidence
    assert all(
        optional_evidence.isdisjoint(rows[item]["validation_evidence"])
        for item in required
    )
