# -*- coding: utf-8 -*-
"""State verification payloads for Browser Control write actions."""

from __future__ import annotations

from typing import Any

_RECOMMENDED_ACTIONS = [
    "wait_for_then_snapshot",
    "reload_then_snapshot",
    "authoritative_state_view",
]


def _control_state_verification_payload(
    *,
    status: str,
    reason: str,
    network_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build read-after-write guidance for possibly stale page state."""
    network_metadata = (
        network_metadata if isinstance(network_metadata, dict) else {}
    )
    payload: dict[str, Any] = {
        "status": status,
        "reason": reason,
        "verification_required": True,
        "recommended_actions": list(_RECOMMENDED_ACTIONS),
        "guidance": (
            "A state-changing browser action may have been accepted while the "
            "current local page state remains stale. Verify by reading the "
            "state back before declaring success or failure."
        ),
    }
    async_requests = int(network_metadata.get("async_requests_triggered") or 0)
    if async_requests > 0:
        payload["async_requests_triggered"] = async_requests
    if "settled" in network_metadata:
        payload["network_settled"] = bool(network_metadata.get("settled"))
    if "timed_out" in network_metadata:
        payload["network_timed_out"] = bool(network_metadata.get("timed_out"))
    return payload


__all__ = ["_control_state_verification_payload"]
