# -*- coding: utf-8 -*-
"""Focused coverage for Chrome browser control browser plumbing."""

# pylint: disable=protected-access

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

import pytest

from qwenpaw.agents.tools.browser_snapshot import from_cdp_ax_tree
from qwenpaw.agents.tools.cdp_permissions import (
    DEFAULT_POLICIES,
    PermissionsConfig,
    check_permission,
    load_permissions,
)
from tests.unit.browser_bridge_plugin import load_browser_bridge_submodule

_cdp_relay = load_browser_bridge_submodule("engine.cdp_relay")
CDPPermissionDenied = _cdp_relay.CDPPermissionDenied
CDPRelayError = _cdp_relay.CDPRelayError
CDPRelaySession = _cdp_relay.CDPRelaySession
_nm_bridge = load_browser_bridge_submodule("nm_bridge")
LEASE_TTL_SECONDS = _nm_bridge.LEASE_TTL_SECONDS
NMBridge = _nm_bridge.NMBridge
NMBridgeDisconnectedError = _nm_bridge.NMBridgeDisconnectedError
StaleLeaseError = _nm_bridge.StaleLeaseError
TabOccupiedError = _nm_bridge.TabOccupiedError


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent_json: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.sent_json.append(message)


class _FakeRelayBridge:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {"jsonrpc": "2.0", "result": {"ok": True}}
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.released: list[tuple[int, str]] = []

    def lease_version(self, _tab_id: int, _holder_id: str) -> int:
        return 1

    def validate_lease(
        self,
        _tab_id: int,
        _holder_id: str,
        _lease_version: int | None = None,
    ) -> None:
        return None

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.requests.append((method, params or {}))
        return self.response

    async def release(self, tab_id: int, holder_id: str) -> None:
        self.released.append((tab_id, holder_id))


class _EventBridge(_FakeRelayBridge):
    def __init__(self) -> None:
        super().__init__({"jsonrpc": "2.0", "result": {"nodes": []}})
        self.handlers: dict[str, list[Any]] = defaultdict(list)

    def add_event_listener(self, method: str, handler: Any) -> None:
        self.handlers[method].append(handler)

    def remove_event_listener(self, method: str, handler: Any) -> None:
        self.handlers[method].remove(handler)

    async def emit(self, method: str, params: dict[str, Any]) -> None:
        for handler in list(self.handlers[method]):
            await handler(params)


@pytest.mark.asyncio
async def test_nm_bridge_claims_renews_and_releases_leases() -> None:
    now = [100.0]
    bridge = NMBridge(time_fn=lambda: now[0])

    lease_version = await bridge.claim_tab(7, "holder-a")
    assert lease_version == 1
    assert bridge.tab_holder(7) == "holder-a"
    with pytest.raises(TabOccupiedError):
        await bridge.claim_tab(7, "holder-b")

    lease = bridge.get_lease(7)
    assert lease is not None
    renewed = await bridge.renew_lease(7, "holder-a", lease.version)
    assert renewed.expires_at == pytest.approx(now[0] + LEASE_TTL_SECONDS)

    with pytest.raises(StaleLeaseError):
        bridge.validate_lease(7, "holder-a", lease.version + 1)

    await bridge.release(7, "holder-a")
    assert bridge.tab_holder(7) is None


@pytest.mark.asyncio
async def test_nm_bridge_expires_stale_lease_and_forwards_cdp() -> None:
    now = [100.0]
    bridge = NMBridge(time_fn=lambda: now[0])
    ws = _FakeWebSocket()
    await bridge.attach_websocket(ws)

    await bridge.claim_tab(7, "holder-a")
    first_version = bridge.lease_version(7, "holder-a")
    now[0] += LEASE_TTL_SECONDS + 0.1
    with pytest.raises(TabOccupiedError):
        await bridge.claim_tab(7, "holder-b")
    reclaimed_version = await bridge.reclaim_tab(7, "holder-a")
    assert reclaimed_version == first_version + 1

    task = asyncio.create_task(
        bridge.send_cdp(
            7,
            "holder-a",
            "Accessibility.getFullAXTree",
            {"depth": -1},
            lease_version=reclaimed_version,
        ),
    )
    while not ws.sent_json:
        await asyncio.sleep(0)
    sent = ws.sent_json[0]
    assert sent["method"] == "cdp.send"
    assert sent["params"]["tabId"] == 7
    assert sent["params"]["method"] == "Accessibility.getFullAXTree"

    await bridge.handle_ws_message(
        {"jsonrpc": "2.0", "id": sent["id"], "result": {"nodes": []}},
    )
    assert await task == {"nodes": []}


@pytest.mark.asyncio
async def test_nm_bridge_disconnect_cancels_pending_requests() -> None:
    bridge = NMBridge()
    ws = _FakeWebSocket()
    await bridge.attach_websocket(ws)
    request_task = asyncio.create_task(bridge.request("tabs.list", {}))
    while not ws.sent_json:
        await asyncio.sleep(0)

    await bridge.detach_websocket(ws)

    with pytest.raises(NMBridgeDisconnectedError):
        await request_task
    assert not bridge.connected


@pytest.mark.asyncio
async def test_cdp_relay_sends_jsonrpc_and_returns_result() -> None:
    bridge = _FakeRelayBridge({"jsonrpc": "2.0", "result": {"nodes": []}})
    session = CDPRelaySession(
        3,
        "holder",
        bridge,
        heartbeat_interval=0,
        watchdog_interval=0,
    )

    result = await session.send("Accessibility.getFullAXTree")

    assert result == {"nodes": []}
    assert bridge.requests == [
        (
            "cdp.send",
            {
                "tabId": 3,
                "ownerId": "holder",
                "holderId": "holder",
                "method": "Accessibility.getFullAXTree",
                "params": {},
            },
        ),
    ]


@pytest.mark.asyncio
async def test_cdp_relay_raises_for_jsonrpc_error() -> None:
    bridge = _FakeRelayBridge(
        {"jsonrpc": "2.0", "error": {"message": "Debugger failed"}},
    )
    session = CDPRelaySession(
        3,
        "holder",
        bridge,
        heartbeat_interval=0,
        watchdog_interval=0,
    )

    with pytest.raises(CDPRelayError, match="Debugger failed"):
        await session.send("Accessibility.getFullAXTree")


@pytest.mark.asyncio
async def test_cdp_relay_denies_runtime_evaluate_by_default() -> None:
    bridge = _FakeRelayBridge()
    session = CDPRelaySession(
        3,
        "holder",
        bridge,
        heartbeat_interval=0,
        watchdog_interval=0,
    )

    with pytest.raises(CDPPermissionDenied):
        await session.send(
            "Runtime.evaluate",
            {"expression": "document.cookie"},
        )
    assert not bridge.requests


@pytest.mark.asyncio
async def test_cdp_relay_approval_callback_tracks_new_domain() -> None:
    approvals: list[dict[str, Any]] = []

    async def approve(request: dict[str, Any]) -> bool:
        approvals.append(request)
        return True

    bridge = _FakeRelayBridge()
    permissions = PermissionsConfig()
    session = CDPRelaySession(
        3,
        "holder",
        bridge,
        approval_callback=approve,
        permissions_config=permissions,
        heartbeat_interval=0,
        watchdog_interval=0,
    )

    await session.send("Page.navigate", {"url": "https://example.com/a"})

    assert approvals[0]["policy"] == "ask_new_domain"
    assert approvals[0]["domain"] == "example.com"
    assert "example.com" in permissions.approved_domains


@pytest.mark.asyncio
async def test_cdp_relay_does_not_register_hitl_pause_controls() -> None:
    bridge = _EventBridge()
    session = CDPRelaySession(
        3,
        "holder",
        bridge,
        heartbeat_interval=0,
        watchdog_interval=0,
    )

    assert "hitl.paused" not in bridge.handlers
    assert "hitl.resumed" not in bridge.handlers
    assert "hitl.stopped" not in bridge.handlers

    await bridge.emit("hitl.paused", {"tabId": 3})
    await bridge.emit("hitl.resumed", {"tabId": 3})
    result = await session.send("Accessibility.getFullAXTree")

    assert result == {"nodes": []}
    assert session.last_snapshot is None


@pytest.mark.asyncio
async def test_cdp_relay_watchdog_releases_idle_session() -> None:
    now = [100.0]
    bridge = NMBridge(time_fn=lambda: now[0])
    await bridge.claim_tab(3, "holder")
    session = CDPRelaySession(
        3,
        "holder",
        bridge,
        heartbeat_interval=0,
        watchdog_interval=0.01,
        idle_timeout=1,
    )

    now[0] += 2
    await asyncio.sleep(0.03)

    assert session.closed_by_watchdog is True
    assert bridge.get_lease(3) is None


@pytest.mark.asyncio
async def test_cdp_relay_watchdog_detaches_and_hides_banner() -> None:
    bridge = _FakeRelayBridge()
    session = CDPRelaySession(
        3,
        "holder",
        bridge,
        heartbeat_interval=0,
        watchdog_interval=0.01,
        idle_timeout=0.01,
    )

    await asyncio.sleep(0.03)

    assert session.closed_by_watchdog is True
    assert bridge.requests[:2] == [
        ("tab.detach", {"tabId": 3, "holderId": "holder"}),
        ("banner.hide", {"tabId": 3}),
    ]
    assert bridge.released == [(3, "holder")]


def test_cdp_permission_defaults_and_domain_severity(tmp_path) -> None:
    assert check_permission("Accessibility.getFullAXTree").decision == "allow"
    assert check_permission("Runtime.evaluate").decision == "deny"
    assert check_permission("Not.Real").decision == "deny"

    config = PermissionsConfig(
        capability_rules={"navigate": "allow"},
        domain_rules=[{"pattern": "*.danger.test", "policy": "deny"}],
    )
    result = check_permission(
        "Page.navigate",
        "https://app.danger.test",
        config,
    )
    assert result.decision == "deny"
    assert result.domain == "app.danger.test"

    config_path = tmp_path / "browser-permissions.yaml"
    config_path.write_text(
        "\n".join(
            [
                "capabilities:",
                "  storage: ask",
                "domains:",
                "  - pattern: '*.internal.test'",
                "    policy: deny",
                "approved_domains:",
                "  - example.com",
            ],
        ),
        encoding="utf-8",
    )

    loaded = load_permissions(config_path)
    assert loaded.capability_rules == {"storage": "ask"}
    assert loaded.domain_rules == [
        {"pattern": "*.internal.test", "policy": "deny"},
    ]
    assert loaded.approved_domains == {"example.com"}


def test_cdp_default_policies_deny_storage_and_browser_control() -> None:
    assert DEFAULT_POLICIES["storage"] == "deny"
    assert DEFAULT_POLICIES["browser_bridge"] == "deny"


def test_load_permissions_accepts_control_nested_schema(tmp_path) -> None:
    config_path = tmp_path / "browser-permissions.yaml"
    config_path.write_text(
        "\n".join(
            [
                "control:",
                "  capabilities:",
                "    storage: ask",
                "  domain_rules:",
                "    - pattern: '*.nested.test'",
                "      policy: deny",
                "  approved_domains:",
                "    - allowed.test",
            ],
        ),
        encoding="utf-8",
    )

    loaded = load_permissions(config_path)

    assert loaded.capability_rules == {"storage": "ask"}
    assert loaded.domain_rules == [
        {"pattern": "*.nested.test", "policy": "deny"},
    ]
    assert loaded.approved_domains == {"allowed.test"}


def test_from_cdp_ax_tree_builds_refs_and_prunes_ignored_nodes() -> None:
    snapshot, refs = from_cdp_ax_tree(
        {
            "nodes": [
                {
                    "nodeId": "1",
                    "role": {"value": "RootWebArea"},
                    "name": {"value": "Demo"},
                    "childIds": ["2", "3", "4"],
                },
                {
                    "nodeId": "2",
                    "role": {"value": "button"},
                    "name": {"value": "Save"},
                    "backendDOMNodeId": 42,
                },
                {
                    "nodeId": "3",
                    "role": {"value": "button"},
                    "name": {"value": "Save"},
                    "backendDOMNodeId": 43,
                },
                {
                    "nodeId": "4",
                    "ignored": True,
                    "role": {"value": "link"},
                    "name": {"value": "Hidden"},
                },
            ],
        },
    )

    assert '- button "Save" [ref=e1]' in snapshot
    assert '- button "Save" [ref=e2] [nth=1]' in snapshot
    assert "Hidden" not in snapshot
    assert refs["e1"]["backendNodeId"] == 42
    assert refs["e2"]["nth"] == 1
