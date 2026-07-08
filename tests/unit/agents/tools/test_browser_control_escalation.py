# -*- coding: utf-8 -*-
"""Browser Control click no-effect escalation."""
# pylint: disable=protected-access

from __future__ import annotations

import json
from typing import Any

from agentscope.message import DataBlock

from tests.unit.browser_bridge_plugin import load_browser_bridge_submodule

from tests.unit.agents.tools.test_browser_control_enriched_snapshot import (
    _BridgeManager,
    _interactive_ax_tree,
)

_engine_impl = load_browser_bridge_submodule("engine_impl")


class _EscalationBridge:
    connected = True

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.tabs = [{"id": 42, "url": "https://example.com/", "active": True}]
        self.button_name = "Buy"

    async def discover_tabs(self) -> list[dict[str, Any]]:
        return list(self.tabs)

    async def request(  # pylint: disable=too-many-return-statements
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        self.requests.append((method, params))
        if method == "tab.activate":
            return {"jsonrpc": "2.0", "result": {"ok": True}}
        if method != "cdp.send":
            return {"jsonrpc": "2.0", "result": {}}

        cdp_method = params.get("method")
        if cdp_method == "Accessibility.getFullAXTree":
            tree = _interactive_ax_tree()
            tree["nodes"][1]["name"]["value"] = self.button_name
            return {"jsonrpc": "2.0", "result": tree}
        if cdp_method == "DOM.getContentQuads":
            return {
                "jsonrpc": "2.0",
                "result": {"quads": [[10, 20, 30, 20, 30, 40, 10, 40]]},
            }
        if cdp_method == "Input.dispatchMouseEvent":
            return {"jsonrpc": "2.0", "result": {}}
        if cdp_method == "Page.captureScreenshot":
            return {"jsonrpc": "2.0", "result": {"data": "aGVsbG8="}}
        return {"jsonrpc": "2.0", "result": {}}


def _state() -> dict[str, Any]:
    owner_id = "browser_owner:escalation-test"
    return {
        "workspace_id": "escalation-test",
        "ownership_context": {
            "protocol_version": 2,
            "owner_id": owner_id,
            "workspace_id": "browser_workspace:escalation-test",
        },
        "current_page_id": "42",
        "control_tabs": {
            "42": {
                "tab_id": 42,
                "holder_id": owner_id,
                "owner_id": owner_id,
                "url": "https://example.com/",
            },
        },
    }


def _payload(response) -> dict[str, Any]:
    return json.loads(response.content[0].text)


async def _action(
    state: dict[str, Any],
    bridge: _EscalationBridge,
    action: str,
):
    engine = _engine_impl.ControlEngineImpl(
        bridge_manager=_BridgeManager(bridge),
    )
    return await engine.dispatch(
        state,
        action,
        page_id="42",
        ref="e1" if action == "click" else "",
    )


async def test_click_records_ref_and_snapshot_hash() -> None:
    state = _state()
    bridge = _EscalationBridge()

    await _action(state, bridge, "snapshot")
    await _action(state, bridge, "click")

    record = state["control_click_effects"]["42"]
    assert record["ref"] == "e1"
    assert record["snapshot_hash"]


async def test_second_no_effect_snapshot_escalates_with_screenshot() -> None:
    state = _state()
    bridge = _EscalationBridge()

    await _action(state, bridge, "snapshot")
    await _action(state, bridge, "click")
    await _action(state, bridge, "snapshot")
    await _action(state, bridge, "click")
    response = await _action(state, bridge, "snapshot")

    payload = _payload(response)
    assert payload["escalation"]["failed_ref"] == "e1"
    assert "screenshot" in payload["escalation"]["hint"].lower()
    assert any(isinstance(block, DataBlock) for block in response.content[1:])


async def test_changed_snapshot_resets_no_effect_counter() -> None:
    state = _state()
    bridge = _EscalationBridge()

    await _action(state, bridge, "snapshot")
    await _action(state, bridge, "click")
    bridge.button_name = "Changed"
    response = await _action(state, bridge, "snapshot")

    assert "escalation" not in _payload(response)
    assert "42" not in state.get("control_click_effects", {})
