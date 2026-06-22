# -*- coding: utf-8 -*-
"""Browser Control runtime lifecycle hooks."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from agentscope.event import (
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
)
from agentscope.message import Msg
from qwenpaw.hooks.base import LifecycleHook
from qwenpaw.runtime.hooks import HookContext, HookResult
from qwenpaw.runtime.message_convert import _get_last_user_text
from qwenpaw.runtime.phases import Phase

from ..browser_mission_runner import (
    DEFAULT_BROWSER_MISSION_MAX_ITERATIONS,
    run_browser_mission,
)
from ..nm_bridge import get_nm_bridge
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


def _input_list(inputs: Any) -> list[Any]:
    if inputs is None:
        return []
    return inputs if isinstance(inputs, list) else [inputs]


def _is_browser_mission_message(item: Any) -> bool:
    if not isinstance(item, Msg):
        return False
    metadata = getattr(item, "metadata", None)
    return (
        isinstance(metadata, dict) and metadata.get("browser_mission") is True
    )


def _browser_mission_message_text(item: Msg) -> str:
    return "\n".join(
        _block_text(block)
        for block in _message_content(item)
        if _block_text(block)
    )


def _browser_mission_text_events(item: Msg) -> list[Any]:
    text = _browser_mission_message_text(item)
    if not text:
        return []
    reply_id = uuid.uuid4().hex
    block_id = uuid.uuid4().hex
    return [
        TextBlockStartEvent(reply_id=reply_id, block_id=block_id),
        TextBlockDeltaEvent(
            reply_id=reply_id,
            block_id=block_id,
            delta=text,
        ),
        TextBlockEndEvent(reply_id=reply_id, block_id=block_id),
    ]


def _browser_mission_prd_path(ctx: HookContext) -> str:
    extras = getattr(ctx, "extras", {}) or {}
    value = str(extras.get("browser_control_mission_prd_path") or "")
    if value:
        return value
    request = getattr(ctx, "request", None)
    request_context = getattr(request, "request_context", None)
    if isinstance(request_context, dict):
        return str(
            request_context.get("browser_control_mission_prd_path") or "",
        )
    return ""


def _active_control_tab_id(bridge: Any) -> int | None:
    leases = getattr(bridge, "_leases", None)
    if not isinstance(leases, dict):
        return None

    get_lease = getattr(bridge, "get_lease", None)
    for raw_tab_id, raw_lease in reversed(list(leases.items())):
        tab_id = getattr(raw_lease, "tab_id", raw_tab_id)
        try:
            tab_id = int(tab_id)
        except (TypeError, ValueError):
            continue
        lease = get_lease(tab_id) if callable(get_lease) else raw_lease
        if lease is not None:
            return tab_id
    return None


async def _send_banner_status(status_text: str, phase: str) -> None:
    try:
        bridge = get_nm_bridge()
        tab_id = _active_control_tab_id(bridge)
        if tab_id is None:
            return
        await bridge.request(
            "banner.show",
            {
                "tabId": tab_id,
                "status_text": status_text,
                "phase": phase,
            },
        )
    except Exception:
        logger.debug(
            "browser control banner status update failed",
            exc_info=True,
        )


class BrowserControlMissionHook(LifecycleHook):
    """Run /browser-control requests inside a mission-style loop."""

    phase = Phase.POST_AGENT_BUILD
    name = "browser_control_mission"
    priority = 70

    async def run(self, ctx: HookContext) -> HookResult:
        extras = getattr(ctx, "extras", {}) or {}
        if not extras.get("browser_control_invocation"):
            return HookResult()

        prd_path = _browser_mission_prd_path(ctx)
        agent = getattr(ctx, "agent", None)
        if not prd_path or agent is None:
            return HookResult()
        if getattr(agent, "_browser_control_mission_wrapped", False):
            return HookResult()

        try:
            max_iterations = int(
                extras.get("browser_control_mission_max_iterations")
                or DEFAULT_BROWSER_MISSION_MAX_ITERATIONS,
            )
        except (TypeError, ValueError):
            max_iterations = DEFAULT_BROWSER_MISSION_MAX_ITERATIONS

        original_reply_stream = getattr(agent, "reply_stream", None)
        setattr(
            agent,
            "_browser_control_original_reply_stream",
            original_reply_stream,
        )
        setattr(agent, "_browser_control_mission_wrapped", True)

        async def mission_reply_stream(*, inputs=None, **_kwargs):
            async for item in run_browser_mission(
                agent,
                _input_list(inputs),
                prd_path,
                max_iterations=max_iterations,
                banner_callback=_send_banner_status,
            ):
                if _is_browser_mission_message(item):
                    for event in _browser_mission_text_events(item):
                        yield event
                    yield item
                    continue
                if not isinstance(item, Msg):
                    yield item

        setattr(agent, "reply_stream", mission_reply_stream)
        return HookResult()


class BrowserControlFinalizeHook(LifecycleHook):
    """Release Browser Control resources at the end of each request."""

    phase = Phase.FINALLY
    name = "browser_control_finalize"
    priority = 80

    async def run(self, ctx: HookContext) -> HookResult:
        agent = getattr(ctx, "agent", None)
        if agent is not None and getattr(
            agent,
            "_browser_control_mission_wrapped",
            False,
        ):
            original = getattr(
                agent,
                "_browser_control_original_reply_stream",
                None,
            )
            if original is not None:
                setattr(agent, "reply_stream", original)
            setattr(agent, "_browser_control_mission_wrapped", False)

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
    "BrowserControlMissionHook",
]
