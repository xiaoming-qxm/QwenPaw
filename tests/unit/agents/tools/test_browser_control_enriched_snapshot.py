# -*- coding: utf-8 -*-
"""Adaptive visual fallback for Browser Control snapshots."""
# pylint: disable=protected-access

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

import pytest
from agentscope.message import DataBlock

from qwenpaw.agents.tools import browser_control
from qwenpaw.browser.connection_manager import (
    clear_bridge_connection_manager,
    set_bridge_connection_manager,
)
from qwenpaw.browser.control_engine import (
    clear_control_engine,
    register_control_engine,
)
from qwenpaw.browser.control_plugin import load_browser_control_submodule

_engine_impl = load_browser_control_submodule("engine_impl")


@pytest.fixture(autouse=True)
def _register_control_engine() -> Generator[None, None, None]:
    register_control_engine(_engine_impl.ControlEngineImpl())
    yield
    clear_control_engine()


class _BridgeManager:
    def __init__(self, bridge: Any) -> None:
        self.bridge = bridge

    def get_connection(self) -> Any:
        return self.bridge


class _SnapshotBridge:
    connected = True

    def __init__(
        self,
        *,
        ax_tree: dict[str, Any],
        dom_snapshot: dict[str, Any] | None = None,
    ) -> None:
        self.ax_tree = ax_tree
        self.dom_snapshot = dom_snapshot or _dom_snapshot("Fallback text")
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.tabs = [{"id": 42, "url": "https://example.com/", "active": True}]

    async def discover_tabs(self) -> list[dict[str, Any]]:
        return list(self.tabs)

    async def request(
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
            return {"jsonrpc": "2.0", "result": self.ax_tree}
        if cdp_method == "DOMSnapshot.captureSnapshot":
            return {"jsonrpc": "2.0", "result": self.dom_snapshot}
        if cdp_method == "Page.captureScreenshot":
            return {"jsonrpc": "2.0", "result": {"data": "aGVsbG8="}}
        return {"jsonrpc": "2.0", "result": {}}


def _state() -> dict[str, Any]:
    return {
        "workspace_id": "snapshot-test",
        "current_page_id": "42",
        "control_tabs": {
            "42": {
                "tab_id": 42,
                "holder_id": "browser_sdk:snapshot-test",
                "url": "https://example.com/",
            },
        },
    }


def _payload(response) -> dict[str, Any]:
    return json.loads(response.content[0].text)


def _image_blocks(response) -> list[DataBlock]:
    return [
        block for block in response.content[1:] if isinstance(block, DataBlock)
    ]


def _root_only_ax_tree() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "nodeId": "1",
                "role": {"value": "RootWebArea"},
                "name": {"value": "Example"},
            },
        ],
    }


def _text_only_ax_tree() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "nodeId": "1",
                "role": {"value": "RootWebArea"},
                "name": {"value": "Example"},
                "childIds": ["2"],
            },
            {
                "nodeId": "2",
                "role": {"value": "heading"},
                "name": {"value": "Only text"},
                "backendDOMNodeId": 9,
            },
        ],
    }


def _interactive_ax_tree() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "nodeId": "1",
                "role": {"value": "RootWebArea"},
                "name": {"value": "Example"},
                "childIds": ["2"],
            },
            {
                "nodeId": "2",
                "role": {"value": "button"},
                "name": {"value": "Buy"},
                "backendDOMNodeId": 8,
            },
        ],
    }


def _dom_snapshot(text: str) -> dict[str, Any]:
    return {
        "strings": [text],
        "documents": [
            {
                "nodes": {
                    "backendNodeId": [77],
                    "nodeName": [],
                    "nodeValue": [],
                },
                "layout": {
                    "nodeIndex": [0],
                    "text": [0],
                    "bounds": [[10, 20, 100, 40]],
                },
            },
        ],
    }


async def _snapshot(bridge: _SnapshotBridge):
    clear_bridge_connection_manager()
    set_bridge_connection_manager(_BridgeManager(bridge))
    try:
        return await browser_control._action_control(
            _state(),
            "snapshot",
            page_id="42",
        )
    finally:
        clear_bridge_connection_manager()


async def test_degraded_dom_snapshot_fallback_includes_screenshot() -> None:
    bridge = _SnapshotBridge(ax_tree=_root_only_ax_tree())

    response = await _snapshot(bridge)

    assert "Fallback text" in _payload(response)["snapshot"]
    assert _image_blocks(response)


async def test_text_only_refs_include_screenshot() -> None:
    bridge = _SnapshotBridge(ax_tree=_text_only_ax_tree())

    response = await _snapshot(bridge)

    assert _payload(response)["refs"]
    assert _image_blocks(response)


async def test_interactive_snapshot_omits_screenshot() -> None:
    bridge = _SnapshotBridge(ax_tree=_interactive_ax_tree())

    response = await _snapshot(bridge)

    assert _payload(response)["refs"]["e1"]["role"] == "button"
    assert _image_blocks(response) == []


async def test_enriched_snapshot_uses_jpeg_quality_sixty() -> None:
    bridge = _SnapshotBridge(ax_tree=_root_only_ax_tree())

    await _snapshot(bridge)

    capture_requests = [
        params
        for method, params in bridge.requests
        if method == "cdp.send"
        and params.get("method") == "Page.captureScreenshot"
    ]
    assert capture_requests
    assert capture_requests[-1]["params"]["format"] == "jpeg"
    assert capture_requests[-1]["params"]["quality"] == 60
