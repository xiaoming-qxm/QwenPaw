# -*- coding: utf-8 -*-
"""S9 deterministic User Chrome VisualCanvas E2E evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify.browser.core_lab.model import CapabilityFamily
from scripts.verify.browser.core_lab.runner import build_case, run_case


@pytest.mark.parametrize(
    (
        "case_id",
        "grounding",
        "native_effect_count",
        "handoff",
        "exact_approval_count",
    ),
    (
        ("visual.viewport-grounding-exact", "EXACT", 1, False, 1),
        ("visual.repeated-targets-multiple", "MULTIPLE", 0, False, 0),
        ("visual.ref-churn-stale", "STALE", 0, False, 0),
        ("visual.canvas-no-policy-handoff", "NO_MATCH", 0, True, 0),
        ("visual.policy-low-risk-action", "EXACT", 1, False, 1),
    ),
)
def test_user_chrome_visual_grounding_and_action_truth(
    case_id: str,
    grounding: str,
    native_effect_count: int,
    handoff: bool,
    exact_approval_count: int,
) -> None:
    result = run_case(
        build_case(
            family=CapabilityFamily.VISUAL_CANVAS,
            case_id=case_id,
            seed=7,
        ),
    )
    assert result.outcome.value == "PASS"
    assert result.observed["grounding"] == grounding
    assert result.observed["native_effect_count"] == native_effect_count
    assert result.observed["handoff_visible"] is handoff
    assert result.observed["approval_request_count"] == exact_approval_count
    assert result.observed["approval_grant_count"] == exact_approval_count
    assert result.observed["duplicate_action_count"] == 0
    assert result.observed["raw_coordinate_dispatch_count"] == 0
    assert result.observed["false_success"] is False


def test_user_chrome_visual_path_uses_native_hit_geometry_and_input() -> None:
    targets = Path(
        "plugins/bundle/browser-bridge/action_runtime/targets.py",
    ).read_text(encoding="utf-8")
    interactions = Path(
        "plugins/bundle/browser-bridge/action_runtime/interactions.py",
    ).read_text(encoding="utf-8")
    user = Path(
        "plugins/bundle/browser-bridge/backend/user.py",
    ).read_text(encoding="utf-8")
    sources = "\n".join((targets, interactions, user))

    assert "DOM.getNodeForLocation" in sources
    assert "DOM.getContentQuads" in sources
    assert "Page.getLayoutMetrics" in sources
    assert "Input.dispatchMouseEvent" in sources
    assert "_canonical_surface_policy_facts" in sources
    assert "trusted_surface_rule_fingerprint" in sources
