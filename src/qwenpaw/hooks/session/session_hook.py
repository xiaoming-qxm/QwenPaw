# -*- coding: utf-8 -*-
"""Session load/save lifecycle hooks.

Loads persisted session state into ``ctx.session_state`` (PRE_AGENT_BUILD)
so the builder can inject it into the newly-constructed agent. Saves
agent state back to session storage after the response completes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..base import LifecycleHook
from ...runtime._state_utils import StateProxy
from ...runtime.hooks import HookContext, HookResult
from ...runtime.message_convert import _get_last_user_text
from ...runtime.phases import Phase

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


def _session_has_active_browser_control(session_state: dict | None) -> bool:
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


class SessionLoadHook(LifecycleHook):
    """Load persisted session state before agent construction."""

    phase = Phase.PRE_AGENT_BUILD
    name = "session_load"
    priority = 10

    async def run(self, ctx: HookContext) -> HookResult:
        if ctx.workspace is None:
            return HookResult()
        session = getattr(ctx.workspace, "session", None)
        if session is None:
            return HookResult()
        try:
            request = ctx.request
            user_id = getattr(request, "user_id", "") or ctx.session_id
            channel = getattr(request, "channel", "") or ""

            proxy = StateProxy()
            await session.load_session_state(
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
                agent=proxy,
            )
            if proxy.data:
                ctx.session_state = proxy.data
        except KeyError as e:
            logger.debug(
                "session_load: skipped (schema mismatch): %s",
                e,
            )
        except Exception:
            logger.debug("session_load: failed", exc_info=True)
        return HookResult()


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

        from ...runtime.builtin_commands import (
            _browser_control_prompt,
            _set_internal_browser_control_prompt,
        )

        _set_internal_browser_control_prompt(
            ctx,
            _browser_control_prompt(user_text, continuation=True),
        )
        return HookResult()


class SessionSaveHook(LifecycleHook):
    """Persist agent state after response completion."""

    phase = Phase.POST_RESPONSE
    name = "session_save"
    priority = 90

    async def run(self, ctx: HookContext) -> HookResult:
        if ctx.workspace is None or ctx.agent is None:
            return HookResult()
        session = getattr(ctx.workspace, "session", None)
        if session is None:
            return HookResult()
        try:
            request = ctx.request
            user_id = getattr(request, "user_id", "") or ctx.session_id
            channel = getattr(request, "channel", "") or ""

            proxy = StateProxy()
            proxy.data = ctx.agent.state_dict()
            await session.save_session_state(
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
                agent=proxy,
            )
        except Exception:
            logger.debug("session_save: failed", exc_info=True)
        return HookResult()


__all__ = [
    "BrowserControlContinuationHook",
    "SessionLoadHook",
    "SessionSaveHook",
]
