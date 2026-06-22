# -*- coding: utf-8 -*-
"""Browser Control runtime lifecycle hooks."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from qwenpaw.hooks.base import LifecycleHook
from qwenpaw.runtime.hooks import HookContext, HookResult
from qwenpaw.runtime.message_convert import _get_last_user_text
from qwenpaw.runtime.phases import Phase

from .prompt import (
    build_browser_control_prompt,
    set_internal_browser_control_prompt,
)

logger = logging.getLogger(__name__)


def _get_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _message_content(message: Any) -> list[Any]:
    content = _get_field(message, "content", [])
    return content if isinstance(content, list) else []


def _block_text(block: Any) -> str:
    value = _get_field(block, "text", "")
    return str(value or "")


def _browser_tool_input(block: Any) -> dict[str, Any]:
    if _get_field(block, "type") != "tool_call":
        return {}
    if _get_field(block, "name") != "browser_use":
        return {}
    raw = _get_field(block, "input", {})
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _is_browser_control_command(text: str) -> bool:
    return text.strip().lower().startswith("/browser-control")


def _is_other_slash_command(text: str) -> bool:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return False
    return not _is_browser_control_command(stripped)


def _agent_state(session_state: dict | None) -> dict[str, Any]:
    if not isinstance(session_state, dict):
        return {}
    nested = session_state.get("state")
    if isinstance(nested, dict):
        return nested
    return session_state


def _session_has_active_browser_control(
    session_state: dict | None,
) -> bool:
    state = _agent_state(session_state)
    context = state.get("context")
    if not isinstance(context, list):
        return False

    active = False
    for message in context:
        for block in _message_content(message):
            if _get_field(block, "type") == "text":
                text = _block_text(block)
                if _is_browser_control_command(text):
                    active = True
                continue

            tool_input = _browser_tool_input(block)
            if not tool_input:
                continue
            mode = str(tool_input.get("mode") or "").strip().lower()
            action = str(tool_input.get("action") or "").strip().lower()
            if mode != "control":
                continue
            active = action not in {"release_tab", "stop"}

    return active


class BrowserControlContinuationHook(LifecycleHook):
    """Continue an active Browser Control session across chat turns."""

    phase = Phase.PRE_AGENT_BUILD
    name = "browser_control_continuation"
    priority = 20
    after = ("session_load",)

    async def run(self, ctx: HookContext) -> HookResult:
        extras = getattr(ctx, "extras", {}) or {}
        if extras.get("browser_control_invocation"):
            return HookResult()

        user_text = (_get_last_user_text(ctx.input_msgs) or "").strip()
        if not user_text or _is_other_slash_command(user_text):
            return HookResult()
        if not _session_has_active_browser_control(ctx.session_state):
            return HookResult()

        set_internal_browser_control_prompt(
            ctx,
            build_browser_control_prompt(user_text, continuation=True),
        )
        return HookResult()


class BrowserControlFinalizeHook(LifecycleHook):
    """Release Browser Control resources at the end of each request."""

    phase = Phase.FINALLY
    name = "browser_control_finalize"
    priority = 80

    async def run(self, ctx: HookContext) -> HookResult:
        try:
            workspace_dir = getattr(ctx, "workspace_dir", None)
            workspace_id = Path(workspace_dir).name if workspace_dir else ""
            session_id = getattr(ctx, "session_id", "") or ""
            root_session_id = getattr(ctx, "root_session_id", "") or ""
            if ctx.error is None:
                from qwenpaw.agents.tools.browser_control import (
                    release_control_sessions_for_request,
                )

                await release_control_sessions_for_request(
                    session_id=session_id,
                    root_session_id=root_session_id,
                    workspace_id=workspace_id,
                )
            else:
                from qwenpaw.agents.tools.browser_control import (
                    cleanup_control_sessions_for_request,
                )

                await cleanup_control_sessions_for_request(
                    session_id=session_id,
                    root_session_id=root_session_id,
                    workspace_id=workspace_id,
                )
        except Exception:
            logger.warning(
                "browser control finalization failed session=%s",
                getattr(ctx, "session_id", ""),
                exc_info=True,
            )
        return HookResult()


__all__ = [
    "BrowserControlContinuationHook",
    "BrowserControlFinalizeHook",
]
