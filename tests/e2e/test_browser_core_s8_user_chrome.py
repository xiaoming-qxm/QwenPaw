# -*- coding: utf-8 -*-
"""S8 deterministic User Chrome resource-flow E2E evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify.browser.core_lab.model import CapabilityFamily
from scripts.verify.browser.core_lab.runner import build_case, run_case


@pytest.mark.parametrize(
    ("case_id", "operation_kind"),
    (
        ("resource.upload.selected-accepted", "upload"),
        ("resource.download.progress-completed", "download"),
        ("resource.pdf.context-stable", "pdf"),
        ("resource.paste.exact-target-content", "paste"),
    ),
)
def test_user_chrome_generic_resource_flow_has_one_native_effect(
    case_id: str,
    operation_kind: str,
) -> None:
    case = build_case(
        family=CapabilityFamily.RESOURCE_FILE,
        case_id=case_id,
        seed=7,
    )
    result = run_case(case)

    assert result.outcome.value == "PASS"
    assert result.observed["operation_kind"] == operation_kind
    assert result.observed["native_effect_count"] == 1
    assert result.observed["effect_count_at_most_one"] is True
    assert result.observed["owner_bound"] is True
    assert result.observed["path_free"] is True
    assert result.observed["false_success"] is False


def test_user_chrome_native_resource_paths_avoid_clipboard() -> None:
    capabilities = Path(
        "plugins/bundle/chrome/action_runtime/handlers/" "capabilities.py",
    ).read_text(encoding="utf-8")
    paste = Path(
        "plugins/bundle/chrome/action_runtime/handlers/paste.py",
    ).read_text(encoding="utf-8")
    interactions = Path(
        "plugins/bundle/chrome/action_runtime/interactions.py",
    ).read_text(encoding="utf-8")
    sources = "\n".join((capabilities, paste, interactions)).lower()

    assert "dom.setfileinputfiles" in sources
    assert "page.printtopdf" in sources
    assert "runtime.callfunctionon" in sources
    assert "navigator.clipboard" not in sources
    assert "readtext" not in sources
    assert "writetext" not in sources
