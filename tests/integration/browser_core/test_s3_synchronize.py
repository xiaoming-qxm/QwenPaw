# -*- coding: utf-8 -*-
"""S3 Synchronize Core Lab registry and canonical integration gate."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import pytest

from scripts.verify.browser.core_lab.model import CapabilityFamily
from scripts.verify.browser.core_lab.runner import registered_case_ids
from qwenpaw.browser.sdk.backends.protocols import BackendProfile
from qwenpaw.browser.sdk.canonical import contracts
from qwenpaw.browser.sdk.canonical.tabs import Tab
from qwenpaw.browser.sdk.condition_evaluator import ConditionEvaluator
from qwenpaw.browser.sdk.runtime.observation_store import ObservationStore
from qwenpaw.browser.sdk.runtime.result_delivery import (
    BrowserExecutionCollector,
    install_result_collector,
    reset_result_collector,
)


user_backend = import_module("plugins.bundle.browser-bridge.backend.user")


def test_synchronize_required_cases_and_current_build_evidence_exist() -> None:
    assert "Synchronize" in {family.value for family in CapabilityFamily}
    family = CapabilityFamily.SYNCHRONIZE
    case_ids = set(registered_case_ids(family))
    required = {
        "synchronize.page-url",
        "synchronize.page-title",
        "synchronize.page-document-changed",
        "synchronize.page-ready",
        "synchronize.region-text",
        "synchronize.region-item-count",
        "synchronize.region-changed",
        "synchronize.subscribe-race",
        "synchronize.poll-only",
        "synchronize.stable-reset",
        "synchronize.timeout-complete",
        "synchronize.timeout-partial",
        "synchronize.cancel-cleanup",
        "synchronize.url-adversarial",
        "synchronize.url-credential",
        "synchronize.url-idna-default-port",
        "synchronize.url-path-boundary",
        "synchronize.event-reorder-duplicate",
        "synchronize.unicode-visible-text",
        "synchronize.baseline-invalid-stale",
        "synchronize.inactive-atom",
        "synchronize.prearmed-consumer",
    }
    assert required <= case_ids
    manifest = json.loads(
        Path(
            "src/qwenpaw/browser/sdk/generated/browser-support.json",
        ).read_text(encoding="utf-8"),
    )
    build = manifest["build_fingerprint"]
    rows = [
        row
        for row in manifest["capabilities"]
        if row["family"] == "Synchronize"
    ]
    assert len(rows) == 7
    assert all(row["status"] == "READY" for row in rows)
    assert all(
        row["validation_evidence"]
        and all(
            evidence.endswith(f"@{build}")
            for evidence in row["validation_evidence"]
        )
        for row in rows
    )
    backend = object.__new__(user_backend.ChromeExtensionBrowserBackend)
    profile = backend.profile()
    assert all(
        profile.variants[row["capability_id"]] == "READY" for row in rows
    )
    assert profile.hard_limits["max_wait_ms"] == 30_000
    assert profile.hard_limits["max_stable_ms"] == 5_000
    assert profile.hard_limits["max_condition_atoms"] == 16


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep_until(self, deadline: float) -> None:
        self.value = max(self.value, deadline)


class Transport:
    def __init__(
        self,
        clock: FakeClock,
        observations: list[dict[str, object]],
        *,
        hints: list[int] | None = None,
        fail_startup: bool = False,
    ) -> None:
        self.clock = clock
        self.observations = observations
        self.hints = list(hints or [])
        self.fail_startup = fail_startup
        self.calls: list[str] = []
        self.active = 0

    async def action(
        self,
        name: str,
        tab_id: str,
        *,
        apply_aliases: bool = True,
        **kwargs: object,
    ) -> dict[str, object]:
        del apply_aliases
        assert (name, tab_id) == ("wait_for", "tab-1")
        operation = str(kwargs["probe_operation"])
        self.calls.append(operation)
        if operation == "check":
            if self.fail_startup:
                raise RuntimeError("transport startup")
            if len(self.observations) > 1:
                return self.observations.pop(0)
            return self.observations[0]
        if operation == "subscribe":
            self.active += 1
            return {"ok": True, "subscription": "sub-1", "watermark": 0}
        if operation == "next_hint":
            self.clock.value += 0.1
            sequence = self.hints.pop(0) if self.hints else None
            return {"ok": True, "sequence": sequence}
        if operation == "unsubscribe":
            self.active -= 1
            return {"ok": True}
        raise AssertionError(operation)


def _observation(
    *,
    title: str = "Loading",
    state: str = "AVAILABLE",
    coverage: str = "COMPLETE",
) -> dict[str, object]:
    return {
        "ok": True,
        "state": state,
        "coverage": coverage,
        "page": {
            "url": "https://example.test/app",
            "title": title,
            "document_generation": "loader-1",
            "ready_state": "load",
        },
        "regions": [],
    }


def _runtime_tab(
    clock: FakeClock,
    transport: Transport,
) -> Tab:
    # pylint: disable-next=protected-access
    context = contracts._issue_opaque_value(
        contracts.ContextVersion,
        contracts._RUNTIME_VALUE_ISSUER,  # pylint: disable=protected-access
        value="loader-1",
    )
    assert isinstance(context, contracts.ContextVersion)
    store = ObservationStore(
        owner_key=("task-1", "owner-1"),
        root_session_id="session-1",
        tab_id="tab-1",
        context=context,
        generation=1,
        clock=lambda: datetime(2026, 7, 13, tzinfo=UTC),
    )
    session = object.__new__(user_backend.ChromeExtensionBrowserSession)
    # pylint: disable=protected-access
    session._control_engine = object()
    session._condition_region_baselines = {}
    session._bridge_or_engine_action = transport.action
    # pylint: enable=protected-access
    profile = BackendProfile(
        variants={},
        hard_limits={
            "max_wait_ms": 1000,
            "max_stable_ms": 200,
            "max_condition_atoms": 8,
        },
        contract_fingerprint="contract-v1",
        profile_fingerprint="profile-v1",
        build_fingerprint="build-1",
        extension_fingerprint="extension@build-1",
    )
    return Tab(
        id="tab-1",
        _session=session,
        _observations=store,
        _condition_evaluator=ConditionEvaluator(clock=clock),
        _profile=profile,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("observations", "expected"),
    [
        ([_observation(title="Ready")], ("SUCCEEDED", "SATISFIED", True)),
        ([_observation()], ("SUCCEEDED", "TIMED_OUT", True)),
        (
            [_observation(state="STALE", coverage="STALE")],
            ("PARTIAL", "STALE", True),
        ),
        (
            [_observation(state="UNAVAILABLE", coverage="UNAVAILABLE")],
            ("BLOCKED", "UNAVAILABLE", True),
        ),
    ],
)
async def test_real_canonical_user_probe_terminal_mapping_and_cleanup(
    observations: list[dict[str, object]],
    expected: tuple[str, str, bool],
) -> None:
    clock = FakeClock()
    transport = Transport(clock, observations)
    tab = _runtime_tab(clock, transport)
    collector = BrowserExecutionCollector()
    token = install_result_collector(collector)
    try:
        result = await tab.wait_for(
            contracts.BrowserCondition.all(
                contracts.PageCondition.title("Ready"),
            ),
            timeout_ms=200,
        )
    finally:
        reset_result_collector(token)
    assert (
        result.status,
        result.outcome,
        result.evidence is not None,
    ) == expected
    assert transport.active == 0
    envelope = collector.finalize(python_value=result, error=None)
    assert envelope.records[-1].result is result


@pytest.mark.asyncio
async def test_event_recheck_and_startup_none_evidence_boundary() -> None:
    clock = FakeClock()
    transport = Transport(
        clock,
        [
            _observation(),
            _observation(),
            _observation(title="Ready"),
        ],
        hints=[1],
    )
    tab = _runtime_tab(clock, transport)
    collector = BrowserExecutionCollector()
    token = install_result_collector(collector)
    try:
        result = await tab.wait_for(
            contracts.BrowserCondition.all(
                contracts.PageCondition.title("Ready"),
            ),
            timeout_ms=500,
        )
    finally:
        reset_result_collector(token)
    assert result.outcome == "SATISFIED"
    assert transport.calls[:5] == [
        "check",
        "subscribe",
        "check",
        "next_hint",
        "check",
    ]
    assert transport.active == 0

    failed_transport = Transport(clock, [_observation()], fail_startup=True)
    failed_tab = _runtime_tab(clock, failed_transport)
    collector = BrowserExecutionCollector()
    token = install_result_collector(collector)
    try:
        failed = await failed_tab.wait_for(
            contracts.BrowserCondition.all(
                contracts.PageCondition.title("Ready"),
            ),
            timeout_ms=100,
        )
    finally:
        reset_result_collector(token)
    assert (failed.status, failed.outcome, failed.evidence) == (
        "FAILED",
        None,
        None,
    )


@pytest.mark.asyncio
async def test_inactive_atom_has_zero_user_probe_transport_calls() -> None:
    clock = FakeClock()
    transport = Transport(clock, [_observation(title="Ready")])
    tab = _runtime_tab(clock, transport)
    context = tab._observations.context  # pylint: disable=protected-access
    collector = BrowserExecutionCollector()
    token = install_result_collector(collector)
    try:
        result = await tab.wait_for(
            contracts.BrowserCondition.all(
                contracts.SurfaceCondition.tab_opened(context),
            ),
            timeout_ms=100,
        )
    finally:
        reset_result_collector(token)
    assert (result.status, result.outcome) == ("BLOCKED", "UNAVAILABLE")
    assert not transport.calls
