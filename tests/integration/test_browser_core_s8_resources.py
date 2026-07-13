# -*- coding: utf-8 -*-
"""S8 ResourceFile Core Lab and current-build report integration gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scripts.verify.browser.core_lab.model import CapabilityFamily
from scripts.verify.browser.core_lab.reports import (
    case_report,
    current_build_fingerprints,
)
from scripts.verify.browser.core_lab.runner import (
    build_case,
    registered_case_ids,
    run_case,
)
from qwenpaw.browser.sdk.runtime import resources


def test_resource_file_current_build_case_report_binding_exists() -> None:
    case_ids = registered_case_ids(CapabilityFamily.RESOURCE_FILE)
    assert "resource.upload.selected-accepted" in case_ids
    assert len(case_ids) == len(set(case_ids))
    case = build_case(
        family=CapabilityFamily.RESOURCE_FILE,
        case_id="resource.upload.selected-accepted",
        seed=7,
    )
    report = case_report(case, run_case(case), from_report="report.json")
    build = current_build_fingerprints()["build"]
    assert report["outcome"] == "PASS"
    assert report["validation_evidence"].endswith(f"@{build}")
    assert report["oracle"]["provenance"] == (
        "native_transfer_effect_and_stored_byte_log"
    )


@pytest.mark.parametrize(
    ("family", "required_case"),
    (
        (
            CapabilityFamily.RESOURCE_FILE,
            "resource.condition.created-download",
        ),
        (
            CapabilityFamily.SYNCHRONIZE,
            "synchronize.resource-available-current",
        ),
        (
            CapabilityFamily.RESULT_DELIVERY,
            "result.artifact-promotion",
        ),
    ),
)
def test_s8_primary_family_cases_pass_independent_oracle(
    family: CapabilityFamily,
    required_case: str,
) -> None:
    case_ids = registered_case_ids(family)
    assert required_case in case_ids
    results = [
        run_case(build_case(family=family, case_id=case_id, seed=7))
        for case_id in case_ids
    ]
    assert results
    assert all(result.outcome.value == "PASS" for result in results)


@pytest.mark.asyncio
async def test_resource_owner_continuity_and_promoted_root_retention(
    tmp_path,
) -> None:
    now = datetime.now(UTC)
    owner = ("root-s8", "browser-owner-s8")
    store = resources.ResourceStore(
        owner_key=owner,
        limits=resources.ResourceLimits(1024, 4096, 4),
        storage_root=tmp_path / "resource-store",
        workspace_root=tmp_path,
        ttl_seconds=10,
        clock=lambda: now,
    )
    transient = await store.ingest_output(
        resources.TrustedOutputSource.from_bytes(b"transient"),
        media_type="application/octet-stream",
        name="transient.bin",
        required_delivery=False,
    )
    artifact = await store.ingest_output(
        resources.TrustedOutputSource.from_bytes(b"artifact"),
        media_type="application/pdf",
        name="artifact.pdf",
        required_delivery=True,
    )

    assert store.require(transient.id) is transient
    assert store.require(artifact.id) is artifact
    await store.promote_required((artifact,))
    cleanup = await store.cleanup_transient()

    assert cleanup.complete
    with pytest.raises(resources.ResourceStoreError):
        store.require(transient.id)
    assert resources.resolve_promoted_bytes(
        artifact.id,
        owner_key=owner,
        now=now + timedelta(seconds=1),
    ) == b"artifact"
    with pytest.raises(resources.ResourceStoreError):
        resources.resolve_promoted_bytes(
            artifact.id,
            owner_key=("other-root", "other-owner"),
            now=now + timedelta(seconds=1),
        )
