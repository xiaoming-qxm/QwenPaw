# -*- coding: utf-8 -*-
"""S7 owner-bound tab and prompt SurfaceCondition integration evidence."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.browser.sdk.canonical.contracts import SurfaceCondition
from qwenpaw.browser.sdk.condition_evaluator import _surface_condition_matches
from qwenpaw.browser.sdk.runtime.session_owner import (
    BrowserSessionOwnerRegistry,
    ContractMode,
    NativeContextVersion,
)


@pytest.mark.asyncio
async def test_s7_surface_conditions_require_owner_bound_event_facts() -> None:
    now = [1.0]
    registry = BrowserSessionOwnerRegistry(clock=lambda: now[0])
    owner = await registry.begin_request(
        root_session_id="s7-surface-owner-a",
        source="user",
        rollout_default=ContractMode.CANONICAL,
    )
    other = await registry.begin_request(
        root_session_id="s7-surface-owner-b",
        source="user",
        rollout_default=ContractMode.CANONICAL,
    )

    def tab(binding, receiver):
        return registry.issue_tab_summary(
            binding,
            receiver_tab=receiver,
            origin="https://example.test",
            state_revision="document-1",
            layout_revision="layout-1",
            safe_url="https://example.test/",
            provenance="BORROWED",
            expires_at=100.0,
        )

    selected = tab(owner, "native-7")
    foreign = tab(other, "native-9")
    registry.select_tab_summary(owner, selected)
    prompt = registry.capture_browser_prompt(
        owner,
        tab=selected,
        prompt_type="confirm",
        origin="https://example.test",
        safe_message="Continue?",
        allows_text=False,
        native_identity="native-prompt-1",
        parent_operation_id=None,
        expires_at=10.0,
    )
    receiver = SimpleNamespace(
        target_registry=registry,
        owner_binding=owner,
        tab_id="native-7",
    )
    wrong_owner = SimpleNamespace(
        target_registry=registry,
        owner_binding=other,
        tab_id="native-9",
    )
    context = registry.issue_context(
        owner,
        receiver_tab="native-7",
        native=NativeContextVersion(1, 1, 1, 1, 1, 1),
        expires_at=100.0,
    )

    assert _surface_condition_matches(
        SurfaceCondition.tab_selected(selected),
        receiver,
    )
    assert not _surface_condition_matches(
        SurfaceCondition.tab_selected(foreign),
        receiver,
    )
    assert _surface_condition_matches(
        SurfaceCondition.prompt_present("confirm"),
        receiver,
    )
    assert not _surface_condition_matches(
        SurfaceCondition.prompt_absent(prompt),
        receiver,
    )
    assert not _surface_condition_matches(
        SurfaceCondition.prompt_present("confirm"),
        wrong_owner,
    )
    assert _surface_condition_matches(
        SurfaceCondition.tab_opened(context),
        receiver,
    )

    registry.prove_tab_closed(owner, selected)
    assert _surface_condition_matches(
        SurfaceCondition.tab_closed(selected),
        receiver,
    )
    assert not _surface_condition_matches(
        SurfaceCondition.tab_selected(selected),
        receiver,
    )
    now[0] = 11.0
    assert _surface_condition_matches(
        SurfaceCondition.prompt_absent(prompt),
        receiver,
    )
