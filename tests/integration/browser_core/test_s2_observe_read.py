# -*- coding: utf-8 -*-
"""Deterministic S2 observe/read/screenshot through the real collector."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qwenpaw.agents.provider_blocks import build_provider_block_profile
from qwenpaw.browser.canonical import contracts
from qwenpaw.browser.canonical.tabs import Tab
from qwenpaw.browser.runtime import observation_store, resources, snapshot
from qwenpaw.browser.runtime.result_delivery import (
    BrowserExecutionCollector,
    BrowserResultProjector,
    install_result_collector,
    reset_result_collector,
)


class _Model:
    model_key = "s2-model@build-1"
    supported_blocks = frozenset({"text", "data", "image"})
    image_media_types = frozenset({"image/png"})
    artifact_media_types = frozenset()


class _Formatter:
    formatter_fingerprint = "s2-formatter@build-1"
    supported_blocks = frozenset({"text", "data", "image"})
    image_media_types = frozenset({"image/png"})
    artifact_media_types = frozenset()


def _context():
    return contracts._issue_opaque_value(  # pylint: disable=protected-access
        contracts.ContextVersion,
        contracts._RUNTIME_VALUE_ISSUER,  # pylint: disable=protected-access
        value="s2-context",
    )


class _Session:
    def __init__(self, context):
        self.context = context
        self.calls = []

    async def capture_snapshot(self, tab_id, *, scope, budget):
        del budget
        self.calls.append(("snapshot", tab_id))
        return snapshot.SnapshotCapture(
            context=self.context,
            scope=scope,
            generation="loader-s2",
            coverage="PARTIAL",
            gaps=(
                contracts.CoverageGap(
                    stage="CAPTURE",
                    detail=contracts.CaptureGap(
                        source="DOM",
                        reason="BUDGET_EXHAUSTED",
                        examined=1,
                        omitted=2,
                        frontier="frame:main",
                    ),
                ),
            ),
            sources=(
                snapshot.SourceOutcome("AX", True, 1),
                snapshot.SourceOutcome("DOM", True, 1),
            ),
            targets=(
                snapshot.SnapshotTarget(
                    native_identity="backend:41",
                    owner="main",
                    owner_chain=("main",),
                    role="button",
                    name="Continue",
                    states=(),
                    sources=("AX", "DOM"),
                    identity_conflict=False,
                    executable=True,
                ),
            ),
        )

    async def capture_read(self, tab_id, *, scope, budget):
        del budget
        self.calls.append(("read", tab_id))
        return snapshot.ReadCapture(
            context=self.context,
            scope=scope,
            generation="loader-s2",
            coverage="COMPLETE",
            gaps=(),
            segments=(
                contracts.ReadSegment(kind="heading", text="Account"),
                contracts.ReadSegment(kind="text", text="Bounded content"),
            ),
        )

    async def screenshot_exact(self, tab_id, *, scope):
        self.calls.append(("screenshot", tab_id))
        invariant = resources.ScreenshotInvariant(
            generation="loader-s2",
            scroll_offset=(0.0, 0.0),
            focused_backend_node=41,
            viewport=(800, 600),
            layout=(800, 1200),
            event_watermark=2,
        )
        return resources.ScreenshotCapture(
            scope=scope,
            data=b"\x89PNG\r\ns2",
            media_type="image/png",
            name="s2.png",
            width=800,
            height=600,
            complete=True,
            before=invariant,
            after=invariant,
        )


@pytest.mark.asyncio
async def test_observe_read_and_viewport_image_preserve_truth_and_block_order(
    tmp_path,
) -> None:
    context = _context()
    session = _Session(context)
    tab = Tab(
        id="tab-s2",
        _session=session,
        _resources=resources.ResourceStore(
            owner_key=("root-s2", "owner-s2"),
            limits=resources.ResourceLimits(4096, 8192, 4),
            storage_root=tmp_path,
            clock=lambda: datetime(2030, 1, 1, tzinfo=UTC),
        ),
        _observations=observation_store.ObservationStore(
            owner_key=("root-s2", "owner-s2"),
            root_session_id="session-s2",
            tab_id="tab-s2",
            context=context,
            generation=1,
            clock=lambda: datetime(2030, 1, 1, tzinfo=UTC),
        ),
    )
    collector = BrowserExecutionCollector()
    token = install_result_collector(collector)
    try:
        snap = await tab.snapshot()
        read = await tab.read(limit=2)
        shot = await tab.screenshot()
    finally:
        reset_result_collector(token)
    envelope = collector.finalize(python_value="discarded", error=None)
    profile = build_provider_block_profile(_Model(), _Formatter())
    blocks = BrowserResultProjector().project(envelope, profile=profile)

    assert snap.status == "PARTIAL"
    assert snap.observation.gaps[0].detail.omitted == 2
    assert read.status == "SUCCEEDED" and read.end_of_collection is True
    assert shot.status == "SUCCEEDED" and shot.image is not None
    assert [block.kind for block in blocks] == [
        "text",
        "text",
        "text",
        "image",
    ]
    assert blocks[-1].resource_id == shot.image.id
    assert "path" not in str(blocks).lower()
    assert session.calls == [
        ("snapshot", "tab-s2"),
        ("read", "tab-s2"),
        ("screenshot", "tab-s2"),
    ]


def test_observe_read_support_evidence_ids_are_lab_registered() -> None:
    from scripts.verify.browser.core_lab.model import CapabilityFamily
    from scripts.verify.browser.core_lab.runner import registered_case_ids

    registered = set(registered_case_ids(CapabilityFamily.OBSERVE_READ))
    assert {
        "observe.snapshot-neutral",
        "observe.read-immutable",
        "observe.viewport-invariant",
        "observe.full-page-invariant",
    } <= registered
