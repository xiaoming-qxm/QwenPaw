# -*- coding: utf-8 -*-
"""Deterministic S1 result delivery through collector and provider prepare."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from qwenpaw.agents.provider_blocks import (
    build_provider_block_profile,
    prepare_required_blocks,
)
from qwenpaw.browser.sdk.canonical.contracts import (
    EvidenceRef,
    ScreenshotResult,
    VisualContextRef,
    _RUNTIME_VALUE_ISSUER,
    _issue_opaque_value,
    issue_operation_id,
)
from qwenpaw.browser.sdk.runtime.resources import (
    ResourceLimits,
    ResourceStore,
    TrustedOutputSource,
)
from qwenpaw.browser.sdk.runtime.result_delivery import (
    BrowserExecutionCollector,
    BrowserResultProjector,
    RequiredBlock,
)


class _Model:
    model_key = "integration-model@build-1"
    supported_blocks = frozenset({"text", "data", "image"})
    image_media_types = frozenset({"image/png"})
    artifact_media_types = frozenset()


class _Formatter:
    formatter_fingerprint = "integration-formatter@build-1"
    supported_blocks = frozenset({"text", "data", "image"})
    image_media_types = frozenset({"image/png"})
    artifact_media_types = frozenset()

    def prepare_blocks(self, blocks):
        return tuple(
            {"kind": block.kind, "resource_id": block.resource_id}
            for block in blocks
        )


@pytest.mark.asyncio
async def test_collector_projects_required_image_in_stable_order(
    tmp_path,
) -> None:
    store = ResourceStore(
        owner_key=("task-s1", "owner-s1"),
        limits=ResourceLimits(1024, 4096, 4),
        storage_root=tmp_path,
        clock=lambda: datetime(2030, 1, 1, tzinfo=UTC),
    )
    handle = await store.ingest_output(
        TrustedOutputSource.from_bytes(b"image-bytes"),
        media_type="image/png",
        name="shot.png",
        required_delivery=True,
    )
    evidence = _issue_opaque_value(
        EvidenceRef,
        _RUNTIME_VALUE_ISSUER,
        id="evidence-s1",
    )
    visual = _issue_opaque_value(
        VisualContextRef,
        _RUNTIME_VALUE_ISSUER,
        id="visual-s1",
    )
    result = ScreenshotResult(
        operation_id=issue_operation_id(),
        status="SUCCEEDED",
        retry="NONE",
        evidence=evidence,
        image=handle,
        visual_context=visual,
    )
    collector = BrowserExecutionCollector()
    collector.record(
        result,
        required_blocks=(
            RequiredBlock(
                kind="image",
                resource_id=handle.id,
                media_type=handle.media_type,
                payload=handle,
            ),
        ),
    )
    profile = build_provider_block_profile(_Model(), _Formatter())
    projected = BrowserResultProjector().project(
        collector.finalize(python_value="discarded", error=None),
        profile=profile,
    )
    required = tuple(block for block in projected if block.kind == "image")
    prepared = prepare_required_blocks(required, profile, _Formatter())

    assert [block.kind for block in projected] == ["text", "image"]
    assert required[0].resource_id == handle.id
    assert prepared.problem is None
    assert prepared.blocks == ({"kind": "image", "resource_id": handle.id},)
    assert "discarded" not in projected[0].text
    assert "path" not in str(prepared.blocks).lower()


def test_provider_mapping_drop_is_transport_failure() -> None:
    formatter = _Formatter()
    profile = build_provider_block_profile(_Model(), formatter)
    block = SimpleNamespace(
        kind="image",
        operation_id="op-drop",
        resource_id="resource-drop",
        media_type="image/png",
        protected=True,
    )

    formatter.prepare_blocks = lambda _blocks: ()
    prepared = prepare_required_blocks((block,), profile, formatter)

    assert prepared.problem.phase == "TRANSPORT"
    assert not prepared.blocks
