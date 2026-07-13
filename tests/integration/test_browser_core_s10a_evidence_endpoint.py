# -*- coding: utf-8 -*-
"""S10A authenticated live retirement evidence endpoint contract."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import httpx
import pytest
from fastapi import FastAPI


ROUTE = "/api/browser-core/retirement-evidence"
NONCE = "s10a-retirement-nonce-0123456789abcdef"


def test_exact_retirement_evidence_route_is_registered(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["QWENPAW_WORKING_DIR"] = str(tmp_path / "work")
    env["QWENPAW_SECRET_DIR"] = str(tmp_path / "secret")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; from qwenpaw.app._app import app; "
                "print(json.dumps([(r.path, sorted(r.methods)) "
                "for r in app.routes if r.path == "
                "'/api/browser-core/retirement-evidence']))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    matches = json.loads(probe.stdout.strip().splitlines()[-1])
    assert matches == [[ROUTE, ["GET"]]]


def _assert_frozen_schema(body: dict[str, object]) -> None:
    assert set(body) == {
        "schema_version",
        "request_nonce",
        "observed_at",
        "process_instance_id",
        "process_uptime_seconds",
        "sample",
        "fingerprints",
        "host_default",
        "legacy_admission",
        "canonical_admission_age_seconds",
        "required_quiet_window_seconds",
        "legacy_quiet_seconds",
        "bridge_legacy_quiet_seconds",
        "host_counts",
        "bridge_counts",
        "legacy_usage",
        "unknown_reasons",
    }
    assert set(body["sample"]) == {
        "consistent",
        "host_revision_before",
        "host_revision_after",
        "bridge_revision_before",
        "bridge_revision_after",
    }
    assert set(body["fingerprints"]) == {
        "build",
        "contract",
        "profile",
        "extension",
        "provider",
    }
    assert set(body["legacy_admission"]) == {
        "closed",
        "closed_age_seconds",
    }
    assert set(body["host_counts"]) == {
        "legacy_mode_bindings",
        "active_legacy_root_sessions",
        "active_legacy_calls",
        "retained_or_handoff_states",
        "active_legacy_leases",
        "unexpired_legacy_tokens",
        "unresolved_prompts",
        "pending_actions",
        "pending_approvals",
        "uncertain_effects",
    }
    assert set(body["bridge_counts"]) == {
        "legacy_holders",
        "legacy_sessions",
        "legacy_pending_receipts",
    }


@pytest.mark.asyncio
async def test_route_self_authenticates_and_returns_fail_closed_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        browser_core = importlib.import_module(
            "qwenpaw.app.routers.browser_core",
        )
    except ModuleNotFoundError:
        pytest.skip("retirement endpoint module is not implemented yet")

    monkeypatch.setattr(
        browser_core.auth,
        "verify_token",
        lambda token: "registered-user" if token == "valid-token" else None,
    )
    app = FastAPI()
    app.include_router(browser_core.router, prefix="/api")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        missing = await client.get(
            ROUTE,
            params={"token": "valid-token"},
            headers={"X-QwenPaw-Retirement-Nonce": NONCE},
        )
        assert missing.status_code == 401

        invalid = await client.get(
            ROUTE,
            headers={
                "Authorization": "Bearer invalid-token",
                "X-QwenPaw-Retirement-Nonce": NONCE,
            },
        )
        assert invalid.status_code == 401

        response = await client.get(
            ROUTE,
            headers={
                "Authorization": "Bearer valid-token",
                "X-QwenPaw-Retirement-Nonce": NONCE,
            },
        )
        replay = await client.get(
            ROUTE,
            headers={
                "Authorization": "Bearer valid-token",
                "X-QwenPaw-Retirement-Nonce": NONCE,
            },
        )

    assert response.status_code == 200, response.text
    assert replay.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    _assert_frozen_schema(body)
    assert body["schema_version"] == 1
    assert body["request_nonce"] == NONCE
    assert body["host_default"] in {"LEGACY", "CANONICAL"}
    assert body["required_quiet_window_seconds"] == 3600
    assert body["sample"]["consistent"] is False
    assert body["unknown_reasons"]
    assert "valid-token" not in json.dumps(body)


@pytest.mark.asyncio
async def test_changed_host_sample_becomes_unknown_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_core = importlib.import_module("qwenpaw.app.routers.browser_core")
    owner_calls = 0

    async def changed_owner_snapshot() -> dict[str, object]:
        nonlocal owner_calls
        owner_calls += 1
        return {
            "revision": owner_calls,
            "counts": {
                "legacy_mode_bindings": 0,
                "active_legacy_root_sessions": 0,
                "retained_or_handoff_states": 0,
                "active_legacy_leases": 0,
                "unexpired_legacy_tokens": 0,
                "unresolved_prompts": 0,
                "pending_actions": 0,
                "pending_approvals": 0,
                "uncertain_effects": 0,
            },
            "legacy_admission": {
                "closed": False,
                "closed_age_seconds": None,
            },
            "canonical_admission_age_seconds": 0,
        }

    class StableBackend:
        def retirement_snapshot(self) -> dict[str, object]:
            return {
                "revision": 9,
                "counts": {
                    "legacy_holders": 0,
                    "legacy_sessions": 0,
                    "legacy_pending_receipts": 0,
                },
                "legacy_quiet_seconds": 3600,
                "reason": None,
            }

    class ExactRegistry:
        def get(self, backend_id: str) -> StableBackend:
            assert backend_id == "user.chrome_extension"
            return StableBackend()

    monkeypatch.setattr(
        browser_core._OWNER_REGISTRY,
        "retirement_snapshot",
        changed_owner_snapshot,
    )
    monkeypatch.setattr(
        browser_core,
        "get_default_backend_registry",
        ExactRegistry,
    )
    body = await browser_core.collect_retirement_evidence("z" * 43)

    assert owner_calls == 2
    assert body["sample"]["consistent"] is False
    assert set(body["host_counts"].values()) == {None}
    assert body["legacy_quiet_seconds"] is None
    assert set(body["unknown_reasons"].values()) == {"SAMPLE_CHANGED"}
