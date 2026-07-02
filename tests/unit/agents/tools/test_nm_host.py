# -*- coding: utf-8 -*-
"""Tests for the Chrome Native Messaging host helper."""

from __future__ import annotations

import io
import json

import pytest

from scripts import nm_host


def test_native_messaging_framing_round_trips_json() -> None:
    buffer = io.BytesIO()

    nm_host.write_nm_message(buffer, {"jsonrpc": "2.0", "id": 1})
    buffer.seek(0)

    assert nm_host.read_nm_message(buffer) == {"jsonrpc": "2.0", "id": 1}
    assert nm_host.read_nm_message(buffer) is None


def test_load_config_requires_token_and_ws_url(tmp_path) -> None:
    config_path = tmp_path / "nm-bridge.json"
    config_path.write_text(
        json.dumps(
            {"ws_url": "ws://127.0.0.1:8088/ws/nm-bridge", "token": "abc"},
        ),
        encoding="utf-8",
    )

    assert nm_host.load_config(config_path) == {
        "ws_url": "ws://127.0.0.1:8088/ws/nm-bridge",
        "token": "abc",
    }

    config_path.write_text(json.dumps({"ws_url": "ws://x", "token": ""}))
    with pytest.raises(nm_host.InvalidTokenError):
        nm_host.load_config(config_path)


@pytest.mark.asyncio
async def test_connect_websocket_adds_bearer_auth_header() -> None:
    calls = []

    async def connector(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    await nm_host.connect_websocket("ws://local/ws", "secret", connector)

    assert calls == [
        (
            ("ws://local/ws",),
            {"additional_headers": {"Authorization": "Bearer secret"}},
        ),
    ]


@pytest.mark.asyncio
async def test_native_messaging_pumps_between_stdio_and_websocket() -> None:
    stdin = io.BytesIO()
    stdout = io.BytesIO()
    nm_host.write_nm_message(stdin, {"id": 1, "method": "tabs.list"})
    stdin.seek(0)

    class WebSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send(self, message: str) -> None:
            self.sent.append(message)

        def __aiter__(self):
            self._messages = iter(['{"id":1,"result":[]}'])
            return self

        async def __anext__(self):
            try:
                return next(self._messages)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    ws = WebSocket()

    await nm_host.pump_stdin_to_ws(stdin, ws)
    await nm_host.pump_ws_to_stdout(ws, stdout)

    assert ws.sent == ['{"id":1,"method":"tabs.list"}']
    stdout.seek(0)
    assert nm_host.read_nm_message(stdout) == {"id": 1, "result": []}
