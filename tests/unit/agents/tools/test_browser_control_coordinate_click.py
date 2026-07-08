# -*- coding: utf-8 -*-
"""Coordinate click fallback for Browser Control."""
# pylint: disable=protected-access

from __future__ import annotations

import json
from typing import Any

from tests.unit.browser_bridge_plugin import load_browser_bridge_submodule

from tests.unit.agents.tools.test_browser_control_enriched_snapshot import (
    _BridgeManager,
)

_engine_impl = load_browser_bridge_submodule("engine_impl")


class _CoordinateBridge:
    connected = True

    def __init__(
        self,
        *,
        quad: list[float] | None = None,
        fail_location: bool = False,
    ) -> None:
        self.quad = quad or [490, 290, 510, 290, 510, 310, 490, 310]
        self.fail_location = fail_location
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.tabs = [{"id": 42, "url": "https://example.com/", "active": True}]

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
        if method == "banner.show":
            return {"jsonrpc": "2.0", "result": {"ok": True}}
        if method != "cdp.send":
            return {"jsonrpc": "2.0", "result": {}}

        cdp_method = params.get("method")
        if cdp_method == "DOM.getNodeForLocation":
            if self.fail_location:
                return {"jsonrpc": "2.0", "error": {"message": "no node"}}
            return {"jsonrpc": "2.0", "result": {"backendNodeId": 77}}
        if cdp_method == "DOM.getContentQuads":
            return {"jsonrpc": "2.0", "result": {"quads": [self.quad]}}
        if cdp_method == "Page.getLayoutMetrics":
            return {
                "jsonrpc": "2.0",
                "result": {
                    "visualViewport": {
                        "clientWidth": 1000,
                        "clientHeight": 1000,
                    },
                },
            }
        if cdp_method == "Input.dispatchMouseEvent":
            return {"jsonrpc": "2.0", "result": {}}
        return {"jsonrpc": "2.0", "result": {}}


def _state() -> dict[str, Any]:
    owner_id = "browser_owner:coordinate-test"
    return {
        "workspace_id": "coordinate-test",
        "ownership_context": {
            "protocol_version": 2,
            "owner_id": owner_id,
            "workspace_id": "browser_workspace:coordinate-test",
        },
        "current_page_id": "42",
        "refs": {"42": {"e5": {"role": "button", "x": 111, "y": 222}}},
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


async def _click(
    state: dict[str, Any],
    bridge: _CoordinateBridge,
    **kwargs: Any,
):
    engine = _engine_impl.ControlEngineImpl(
        bridge_manager=_BridgeManager(bridge),
    )
    return await engine.dispatch(
        state,
        "click",
        page_id="42",
        **kwargs,
    )


def _mouse_points(bridge: _CoordinateBridge) -> list[tuple[float, float]]:
    points = []
    for method, params in bridge.requests:
        if (
            method != "cdp.send"
            or params.get("method") != "Input.dispatchMouseEvent"
        ):
            continue
        cdp_params = params.get("params") or {}
        points.append((cdp_params["x"], cdp_params["y"]))
    return points


async def test_coordinate_click_without_ref_dispatches_mouse_event() -> None:
    bridge = _CoordinateBridge()

    response = await _click(_state(), bridge, x=495, y=295)

    assert _payload(response)["ok"] is True
    assert _mouse_points(bridge)


async def test_coordinate_click_snaps_to_small_element_center() -> None:
    bridge = _CoordinateBridge(quad=[490, 290, 510, 290, 510, 310, 490, 310])

    await _click(_state(), bridge, x=495, y=295)

    assert _mouse_points(bridge)[0] == (500.0, 300.0)


async def test_coordinate_click_skips_snap_for_large_element() -> None:
    bridge = _CoordinateBridge(quad=[0, 0, 500, 0, 500, 500, 0, 500])

    await _click(_state(), bridge, x=123, y=234)

    assert _mouse_points(bridge)[0] == (123.0, 234.0)


async def test_coordinate_click_uses_raw_when_location_fails() -> None:
    bridge = _CoordinateBridge(fail_location=True)

    await _click(_state(), bridge, x=321, y=432)

    assert _mouse_points(bridge)[0] == (321.0, 432.0)


async def test_ref_click_still_uses_ref_coordinates() -> None:
    bridge = _CoordinateBridge()

    await _click(_state(), bridge, ref="e5")

    assert _mouse_points(bridge)[0] == (111.0, 222.0)
