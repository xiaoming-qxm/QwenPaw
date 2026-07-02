# -*- coding: utf-8 -*-
"""Miscellaneous Browser Control action handlers."""

from __future__ import annotations

import json
from typing import Any

from ...runtime import _tool_response


def unsupported_control_action_response(action: str):
    guidance = (
        "JavaScript evaluation is not available in control mode. "
        "Use the Browser Control Python REPL SDK to inspect current tab URLs, "
        "and use snapshot or screenshot to observe page "
        "state before choosing the next browser action."
    )
    unsupported_actions = {
        "eval",
        "evaluate",
        "run_code",
        "runtime.evaluate",
    }
    use_instead = ["tabs", "snapshot", "screenshot"]
    if action in {"connect_cdp", "list_cdp_targets"}:
        use_instead = ["tabs", "claim_tab", "open", "snapshot"]
    return _tool_response(
        json.dumps(
            {
                "ok": False,
                "mode": "control",
                "error": (
                    f"Unsupported control action: {action}"
                    if action in unsupported_actions
                    else f"Unknown action: {action}"
                ),
                "use_instead": use_instead,
                "guidance": guidance,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


async def handle_unsupported(
    state: dict[str, Any],
    action: str,
    **kwargs: Any,
):
    del state, kwargs
    return unsupported_control_action_response(action)


__all__ = [
    "handle_unsupported",
    "unsupported_control_action_response",
]
