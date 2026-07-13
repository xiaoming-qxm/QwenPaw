# -*- coding: utf-8 -*-
"""Hello handshake helpers for browser-bridge backend connections."""

from __future__ import annotations

import asyncio
import json
from typing import Any


BUILD_FINGERPRINT = "build-1"
CONTRACT_FINGERPRINT = "contract-v1"
PROFILE_FINGERPRINT = "profile-v1"
EXTENSION_FINGERPRINT = "extension@build-1"
PROVIDER_FINGERPRINT = "provider-v1"
MAX_RETAINED_STATE_TTL_SECONDS = 3600
MAX_LEGACY_TOKEN_TTL_SECONDS = 3600


class HandshakeError(RuntimeError):
    """Raised when a backend hello handshake fails."""


async def send_hello(
    ws: Any,
    entry_id: str,
    protocol_version: int = 1,
) -> None:
    """Send bridge hello metadata to a backend websocket."""
    await ws.send(
        json.dumps(
            {
                "type": "hello",
                "entryId": entry_id,
                "protocolVersion": protocol_version,
                "capabilities": ["cdp", "tabs"],
                "buildFingerprint": BUILD_FINGERPRINT,
                "contractFingerprint": CONTRACT_FINGERPRINT,
                "profileFingerprint": PROFILE_FINGERPRINT,
                "extensionFingerprint": EXTENSION_FINGERPRINT,
                "providerFingerprint": PROVIDER_FINGERPRINT,
                "maxRetainedStateTtlSeconds": (MAX_RETAINED_STATE_TTL_SECONDS),
                "maxLegacyTokenTtlSeconds": MAX_LEGACY_TOKEN_TTL_SECONDS,
            },
            separators=(",", ":"),
        ),
    )


async def wait_hello_ack(ws: Any, timeout: float = 5.0) -> dict:
    """Wait for and validate hello_ack."""
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise HandshakeError("Hello ack timeout") from exc

    message = json.loads(
        raw.decode("utf-8") if isinstance(raw, bytes) else raw,
    )
    if message.get("type") != "hello_ack" or message.get("status") != "ok":
        raise HandshakeError(f"Hello rejected: {message}")
    return message


__all__ = ["HandshakeError", "send_hello", "wait_hello_ack"]
