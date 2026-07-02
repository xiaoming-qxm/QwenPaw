# -*- coding: utf-8 -*-
"""Browser Control runtime lifecycle hooks."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock

from qwenpaw.hooks.base import LifecycleHook
from qwenpaw.runtime.hooks import HookContext, HookResult
from qwenpaw.runtime.message_convert import _get_last_user_text
from qwenpaw.runtime.phases import Phase

logger = logging.getLogger(__name__)

_SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "browser-control"
_SKILL_BODY_FILES = ("ops.md", "blocker-report.md", "control-mode.md")
_SKILL_MARKER = '<skill name="browser-control">'
_REAL_BROWSER_INTENT_TERMS = (
    "用我的浏览器",
    "使用我的浏览器",
    "在我的浏览器",
    "通过我的浏览器",
    "用我浏览器",
    "使用我浏览器",
    "用我的chrome",
    "使用我的chrome",
    "在我的chrome",
    "用我的谷歌浏览器",
    "使用我的谷歌浏览器",
    "在我的谷歌浏览器",
    "用真实浏览器",
    "使用真实浏览器",
    "在真实浏览器",
    "用本地浏览器",
    "使用本地浏览器",
    "在本地浏览器",
    "用当前浏览器",
    "使用当前浏览器",
    "在当前浏览器",
    "浏览器登录态",
    "chrome登录态",
    "use my browser",
    "using my browser",
    "with my browser",
    "in my browser",
    "use my chrome",
    "using my chrome",
    "with my chrome",
    "in my chrome",
    "real browser",
    "real chrome",
    "local browser",
    "existing browser session",
    "logged-in browser",
    "logged in browser",
    "browser control",
    "浏览器控制",
)


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


def _tool_input(block: Any, tool_name: str) -> dict[str, Any]:
    if _get_field(block, "type") != "tool_call":
        return {}
    if _get_field(block, "name") != tool_name:
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


_BROWSER_REPL_TERMS = (
    "Browser.connect",
    "await browser",
    "browser.tabs",
    "browser.documentation",
    "browser.close",
    "tab.snapshot",
    "tab.click",
    "tab.type",
    "tab.press_key",
    "tab.navigate",
    "tab.wait_for",
    "tab.close",
    "tab.scroll",
    "tab.hover",
    "tab.select_option",
)

_BROWSER_REPL_RELEASE_TERMS = (
    "browser.close(",
    "tab.close(",
    ".release_all(",
)
_BROWSER_CONTROL_BLOCKED_TOOLS = (
    "execute_shell_command",
    "browser_use",
    "spawn_subagent",
    "delegate_external_agent",
    "list_agents",
    "chat_with_agent",
    "submit_to_agent",
    "check_agent_task",
    "python_repl_reset",
    "desktop_screenshot",
    "DesktopScreenshot",
    "view_image",
    "ViewImage",
    "view_video",
    "ViewVideo",
)


def _python_repl_code(block: Any) -> str:
    tool_input = _tool_input(block, "python_repl")
    return str(tool_input.get("code") or "").strip()


def _is_browser_repl_code(code: str) -> bool:
    compact = "".join(str(code or "").split())
    return any(
        "".join(term.split()) in compact for term in _BROWSER_REPL_TERMS
    )


def _is_browser_repl_release_code(code: str) -> bool:
    compact = "".join(str(code or "").split())
    return any(
        "".join(term.split()) in compact
        for term in _BROWSER_REPL_RELEASE_TERMS
    )


def _is_unrelated_slash_command(text: str) -> bool:
    """Return True if text is a slash command unrelated to browser control."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return False
    command = stripped.split(None, 1)[0].casefold()
    return command not in ("/goal",)


def _has_real_browser_intent(text: str) -> bool:
    folded = text.casefold()
    compact = "".join(folded.split())
    for term in _REAL_BROWSER_INTENT_TERMS:
        term_folded = term.casefold()
        if term_folded in folded:
            return True
        if "".join(term_folded.split()) in compact:
            return True
    return False


@lru_cache(maxsize=1)
def _browser_control_skill_body() -> str:
    sections = [
        "# Browser Control Skill",
        "Use the `python_repl` tool and its preloaded Browser SDK to operate "
        "the user's real Chrome through the QwenPaw extension.",
    ]
    for filename in _SKILL_BODY_FILES:
        path = _SKILL_DIR / filename
        text = path.read_text(encoding="utf-8").strip()
        if text:
            sections.append(text)
    return "\n\n".join(sections).strip()


def _mark_browser_control_invocation(ctx: HookContext) -> None:
    extras = getattr(ctx, "extras", None)
    if extras is None:
        extras = {}
        setattr(ctx, "extras", extras)
    extras["browser_control_invocation"] = True

    request = getattr(ctx, "request", None)
    if request is None:
        return
    request_context = getattr(request, "request_context", None)
    if not isinstance(request_context, dict):
        request_context = {}
        setattr(request, "request_context", request_context)
    request_context["browser_control_invocation"] = True
    _extend_request_blocked_tools(request_context)


def _extend_request_blocked_tools(request_context: dict[str, Any]) -> None:
    existing = request_context.get("blocked_tool_names")
    if isinstance(existing, str):
        blocked = {
            value.strip()
            for value in existing.replace(";", ",").split(",")
            if value.strip()
        }
    elif isinstance(existing, (list, tuple, set, frozenset)):
        blocked = {
            str(value).strip() for value in existing if str(value).strip()
        }
    else:
        blocked = set()
    blocked.update(_BROWSER_CONTROL_BLOCKED_TOOLS)
    request_context["blocked_tool_names"] = sorted(blocked)


def _mark_browser_control_requested(ctx: HookContext, user_text: str) -> None:
    extras = getattr(ctx, "extras", None)
    if extras is None:
        extras = {}
        setattr(ctx, "extras", extras)
    extras["browser_control_requested"] = True
    extras["browser_control_request_text"] = user_text


def _text_block_value(block: Any) -> str:
    if isinstance(block, dict):
        return str(block.get("text") or "")
    return str(getattr(block, "text", "") or "")


def _is_text_block(block: Any) -> bool:
    btype = block.get("type") if isinstance(block, dict) else None
    if btype is None:
        btype = getattr(block, "type", None)
    return btype == "text"


def _set_text_block_value(block: Any, text: str) -> Any:
    if isinstance(block, dict):
        block["text"] = text
        return block
    try:
        setattr(block, "text", text)
        return block
    except Exception:
        return TextBlock(type="text", text=text)


def _rewrite_to_goal_command(ctx: HookContext, original_text: str) -> None:
    """Rewrite user message to /goal to activate Goal mode loop."""
    goal_text = f"/goal {original_text}"
    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return
    last = msgs[-1]
    content = getattr(last, "content", None)
    if isinstance(content, list):
        for index, item in enumerate(content):
            if _is_text_block(item):
                content[index] = _set_text_block_value(item, goal_text)
                return
    elif isinstance(content, str):
        last.content = goal_text


def _append_browser_control_skill(ctx: HookContext, user_text: str) -> None:
    block = (
        f"{_SKILL_MARKER}\n" f"{_browser_control_skill_body()}\n" "</skill>"
    )
    merged = f"{user_text.rstrip()}\n\n{block}" if user_text else block

    msgs = getattr(ctx, "input_msgs", None) or []
    if not msgs:
        return
    last = msgs[-1]
    content = getattr(last, "content", None)
    if isinstance(content, list):
        for index, item in enumerate(content):
            if not _is_text_block(item):
                continue
            current = _text_block_value(item)
            if _SKILL_MARKER in current:
                return
            content[index] = _set_text_block_value(item, merged)
            return
        content.insert(0, TextBlock(type="text", text=merged))
        return
    if isinstance(content, str):
        if _SKILL_MARKER not in content:
            last.content = merged
        return
    setattr(last, "content", [TextBlock(type="text", text=merged)])


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
            code = _python_repl_code(block)
            if not code or not _is_browser_repl_code(code):
                continue
            active = not _is_browser_repl_release_code(code)

    return active


def _should_cleanup_session(ctx: HookContext) -> bool:
    """Determine if browser sessions should be fully cleaned up."""
    if getattr(ctx, "error", None) is not None:
        return True
    session_state = getattr(ctx, "session_state", None)
    if isinstance(session_state, dict):
        goal_state = session_state.get("goal_completed") or session_state.get(
            "goal_blocked",
        )
        if goal_state:
            return True
    return False


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
        if not user_text:
            return HookResult()

        real_browser_intent = bool(
            extras.get("browser_control_requested"),
        ) or _has_real_browser_intent(user_text)
        if _is_unrelated_slash_command(user_text):
            return HookResult()
        if (
            not real_browser_intent
            and not _session_has_active_browser_control(
                ctx.session_state,
            )
        ):
            return HookResult()

        _append_browser_control_skill(ctx, user_text)
        _mark_browser_control_invocation(ctx)
        return HookResult()


class BrowserControlIntentHook(LifecycleHook):
    """Remember browser intent before slash commands rewrite user text."""

    phase = Phase.PRE_DISPATCH
    name = "browser_control_intent"
    priority = 20

    async def run(self, ctx: HookContext) -> HookResult:
        user_text = (_get_last_user_text(ctx.input_msgs) or "").strip()
        if not user_text or _is_unrelated_slash_command(user_text):
            return HookResult()
        if not _has_real_browser_intent(user_text):
            return HookResult()
        _mark_browser_control_requested(ctx, user_text)
        if not user_text.startswith("/goal"):
            _rewrite_to_goal_command(ctx, user_text)
        return HookResult()


class BrowserControlFinalizeHook(LifecycleHook):
    """Release Browser Control resources at the end of each request."""

    phase = Phase.FINALLY
    name = "browser_control_finalize"
    priority = 80

    async def run(self, ctx: HookContext) -> HookResult:
        try:
            from ..tool_repl import shutdown_python_repl

            await shutdown_python_repl()
        except Exception:
            logger.warning(
                "browser control REPL finalization failed session=%s",
                getattr(ctx, "session_id", ""),
                exc_info=True,
            )

        should_cleanup = _should_cleanup_session(ctx)
        try:
            workspace_dir = getattr(ctx, "workspace_dir", None)
            workspace_id = Path(workspace_dir).name if workspace_dir else ""
            session_id = getattr(ctx, "session_id", "") or ""
            root_session_id = getattr(ctx, "root_session_id", "") or ""
            if should_cleanup:
                from qwenpaw.agents.tools.browser_control import (
                    cleanup_control_sessions_for_request,
                )

                await cleanup_control_sessions_for_request(
                    session_id=session_id,
                    root_session_id=root_session_id,
                    workspace_id=workspace_id,
                )
            else:
                from qwenpaw.agents.tools.browser_control import (
                    release_control_sessions_for_request,
                )

                await release_control_sessions_for_request(
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
    "BrowserControlIntentHook",
    "BrowserControlContinuationHook",
    "BrowserControlFinalizeHook",
]
