# -*- coding: utf-8 -*-
"""Deterministic Canonical User Chrome terminal projection evidence."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from qwenpaw.browser.canonical.contracts import ActionResult, Problem
from qwenpaw.browser.runtime.result_delivery import (
    BrowserExecutionCollector,
    BrowserResultProjector,
)


def _fingerprint(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_s7_canonical_user_chrome_flow_projects_terminal_and_build_facts() -> (
    None
):
    operation_id = "browser-op-s7-user-chrome"
    result = ActionResult(
        operation_id=operation_id,
        status="BLOCKED",
        retry="RECONCILE_ONLY",
        problem=Problem(
            code="prompt_required",
            phase="VERIFY",
            safe_message="A confirm prompt requires an exact response.",
        ),
        classified_effects=("DOM_INPUT",),
        dispatch={"state": "COMPLETED"},
        effect={"state": "OBSERVED"},
        postcondition={"state": "PROMPT_REQUIRED"},
    )
    collector = BrowserExecutionCollector()
    collector.record(result)
    envelope = collector.finalize(python_value=None, error=None)
    blocks = BrowserResultProjector().project(
        envelope,
        profile=SimpleNamespace(
            text=True,
            data=True,
            image=True,
            artifact=True,
        ),
    )

    assert envelope.terminal_result is result
    assert len(blocks) == 1
    assert blocks[0].operation_id == operation_id
    assert "BLOCKED" in blocks[0].text
    assert "problem=prompt_required" in blocks[0].text
    assert "retry=RECONCILE_ONLY" in blocks[0].text

    extension = Path(
        "plugins/bundle/chrome/assets/extensions/" "chrome/service_worker.js",
    )
    native = Path(
        "plugins/bundle/chrome/action_runtime/interactions.py",
    )
    assert len(_fingerprint(extension)) == 64
    assert len(_fingerprint(native)) == 64
