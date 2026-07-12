# -*- coding: utf-8 -*-
"""S0 vertical migration-fence integration over release-shape seams."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from qwenpaw.browser.sdk.canonical.tabs import TabActions
from qwenpaw.browser.sdk.runtime.executor import InProcessBrowserCodeExecutor
from qwenpaw.browser.sdk.runtime.kernel import BrowserExecutionContext
from qwenpaw.browser.sdk.runtime.session_owner import (
    BrowserSessionOwnerRegistry,
    ContractMode,
    RootTaskOutcome,
)


def _context(binding, request_scope: str) -> BrowserExecutionContext:
    return BrowserExecutionContext(
        session_id=request_scope,
        context="auto",
        root_session_id=binding.root_session_id,
        root_task_id=binding.root_task_id,
        browser_owner_id=binding.browser_owner_id,
        contract_mode=binding.contract_mode,
        lease_generation=binding.lease_generation,
        request_scope_key=request_scope,
    )


@pytest.mark.asyncio
async def test_owner_survives_request_scope_and_terminal_clears() -> None:
    registry = BrowserSessionOwnerRegistry()
    executor = InProcessBrowserCodeExecutor()
    first = await registry.begin_request(
        root_session_id="chat-s0",
        source="user",
        rollout_default=ContractMode.CANONICAL,
    )
    await executor.execute(
        "owner_state = {'selected_tab': 'tab-7'}",
        execution_context=_context(first, "request-a"),
    )
    await registry.release_request_lease(first)
    continuation = await registry.begin_request(
        root_session_id="chat-s0",
        source="continuation",
        inherited_binding=first,
    )
    selected = await executor.execute(
        "owner_state['selected_tab']",
        execution_context=_context(continuation, "request-b"),
    )
    assert selected == "tab-7"
    await registry.release_request_lease(continuation)
    await registry.finish_root_task(continuation, RootTaskOutcome.COMPLETE)
    assert not registry.has_owner(continuation.owner_key)


@pytest.mark.asyncio
async def test_resume_race_and_blocked_write_never_double_dispatch() -> None:
    registry = BrowserSessionOwnerRegistry()
    first = await registry.begin_request(
        root_session_id="chat-race",
        source="user",
        rollout_default=ContractMode.CANONICAL,
    )
    token = await registry.retain(first, reason="HANDOFF", ttl_seconds=60)
    results = await asyncio.gather(
        registry.begin_request(
            root_session_id="chat-race",
            source="resume",
            resume_token=token.value,
        ),
        registry.begin_request(
            root_session_id="chat-race",
            source="resume",
            resume_token=token.value,
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert sum(isinstance(item, Exception) for item in results) == 1

    native_effects = []

    async def dispatch(*args, **kwargs):
        native_effects.append((args, kwargs))

    with pytest.raises(Exception) as caught:
        await TabActions(dispatch=dispatch).click("e1")
    assert caught.value.metadata["backend_dispatch_count"] == 0
    assert len(native_effects) == 0


@pytest.mark.asyncio
async def test_capture_only_mode_namespace_has_no_shadow_effect() -> None:
    executor = InProcessBrowserCodeExecutor()
    legacy = BrowserExecutionContext(
        "legacy-request",
        "auto",
        "chat-shadow",
        "task-shadow",
        "owner-shadow",
        ContractMode.LEGACY,
        1,
    )
    canonical = BrowserExecutionContext(
        "canonical-request",
        "auto",
        "chat-shadow",
        "task-shadow",
        "owner-shadow",
        ContractMode.CANONICAL,
        1,
    )
    await executor.execute("native_effect_count = 1", execution_context=legacy)
    await executor.execute(
        "native_effect_count = 0",
        execution_context=canonical,
    )
    assert (
        await executor.execute(
            "native_effect_count",
            execution_context=legacy,
        )
        == 1
    )
    assert (
        await executor.execute(
            "native_effect_count",
            execution_context=canonical,
        )
        == 0
    )


def test_legacy_generated_golden_is_byte_identical() -> None:
    expected = {
        "src/qwenpaw/browser/sdk/generated/api_catalog.json": (
            "24e8e77d70ac879d0d0a6668aac39b8914176b8945b82960daaede02cc5e278e"
        ),
        "src/qwenpaw/browser/sdk/generated/capabilities.json": (
            "d5ab97a94115f0694a5e82ef422051a1993955a579e368810e08b21af0e688a5"
        ),
        "src/qwenpaw/browser/sdk/generated/help/index.md": (
            "5ccab803e6f46a41d1aa1125d2a9dcd1d6d869783ba447ad9d228524b34d6abc"
        ),
    }
    assert {
        path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in expected
    } == expected
