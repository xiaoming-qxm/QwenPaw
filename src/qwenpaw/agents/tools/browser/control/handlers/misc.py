# -*- coding: utf-8 -*-
"""Miscellaneous Browser Control action handlers."""

from __future__ import annotations

import json
from typing import Any

from ...runtime import _tool_response


def unsupported_control_action_response(action: str):
    guidance = (
        "JavaScript evaluation is not available in control mode. "
        'Use browser_use(action="tabs", mode="control") to inspect '
        "current tab URLs, and use snapshot or screenshot to observe page "
        "state before choosing the next browser action."
    )
    unsupported_actions = {
        "eval",
        "evaluate",
        "run_code",
        "runtime.evaluate",
    }
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
                "use_instead": ["tabs", "snapshot", "screenshot"],
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
