# -*- coding: utf-8 -*-
"""Browser Control runtime lifecycle hooks."""

from __future__ import annotations

import json
import logging
import re
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
_BROWSER_CONTROL_GOAL_MAX_ITERATIONS = 40
_BROWSER_CONTROL_GOAL_GUIDANCE = """
# Browser Control Goal Discipline

- Keep a compact checklist for the current browser goal. After each browser
  observation, mark completed subtasks and move to the next unmet subtask;
  do not restart from the first subtask.
- Before starting any new search, navigation, or listing action, audit the
  latest authoritative state. If the current page already proves the
  requested item, category, count, or empty/non-empty state, advance to the
  next requested subtask instead of repeating the same write.
- State-based completion beats provenance. If an authoritative page already
  proves the requested state, count that subtask as satisfied even if you are
  unsure whether the current run created that state.
- For cart/list cleanup workflows, if a cart page already shows a matching
  requested item or category, do not leave the cart to add another matching
  item. Print/read the current cart contents, then continue to the requested
  clear/delete/final-state subtasks.
- A singular browser write is complete after the first authoritative
  read-back proves it. Do not add another matching item, delete another row,
  or repeat the same state-changing click unless the user explicitly asked
  for multiple distinct changes.
- Keep Browser SDK cells narrow: at most one mutating browser action per
  `python_repl` cell, optionally followed by a wait and a fresh observation.
- Treat select-all, delete, and confirm as separate browser writes in
  separate python_repl turns. If `ObservationRequired` appears, do not retry
  the same multi-action cell; observe once, then issue exactly one next
  state-changing action in a new python_repl turn.
- If a plausible action target cannot be activated after one fresh
  observation, choose a different real target or route. Do not loop on the
  same listing, screenshot, coordinate, or product candidate.
""".strip()
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
_URL_OR_DOMAIN_RE = re.compile(
    r"(?:https?://|www\.|[a-z0-9][a-z0-9.-]*\."
    r"(?:com|cn|net|org|io|ai|dev|app|shop|edu|gov|co|me)\b)",
    re.IGNORECASE,
)
_GOAL_BROWSER_TASK_PHRASES = (
    "网上搜索",
    "上网搜索",
    "在线搜索",
    "网页搜索",
    "网站搜索",
    "搜索网页",
    "打开网页",
    "打开网站",
    "打开网址",
    "访问网页",
    "访问网站",
    "访问网址",
    "浏览网页",
    "浏览网站",
    "加入购物车",
    "添加到购物车",
    "加到购物车",
    "清空购物车",
    "删除购物车",
    "购物车",
    "search the web",
    "search online",
    "web search",
    "open website",
    "open web page",
    "visit website",
    "visit web page",
    "shopping cart",
    "add to cart",
    "clear cart",
)
_GOAL_WEB_ACTION_TERMS = (
    "打开",
    "访问",
    "进入",
    "浏览",
    "查看",
    "搜索",
    "查询",
    "挑选",
    "勾选",
    "删除",
    "清空",
    "open",
    "visit",
    "navigate",
    "browse",
    "view",
    "check",
    "search",
    "look up",
    "select",
    "delete",
    "clear",
)
_GOAL_WEB_TARGET_TERMS = (
    "网页",
    "网站",
    "站点",
    "网址",
    "页面",
    "博客",
    "商品",
    "购物车",
    "互联网",
    "webpage",
    "web page",
    "website",
    "web site",
    "site",
    "url",
    "blog",
    "product",
    "cart",
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
    "read_file",
    "Read",
    "grep_search",
    "Grep",
    "glob_search",
    "Glob",
    "send_file_to_user",
    "SendFileToUser",
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
    return _contains_intent_term(text, _REAL_BROWSER_INTENT_TERMS)


def _contains_intent_term(text: str, terms: tuple[str, ...]) -> bool:
    folded = text.casefold()
    compact = "".join(folded.split())
    for term in terms:
        term_folded = term.casefold()
        if term_folded in folded:
            return True
        if "".join(term_folded.split()) in compact:
            return True
    return False


def _split_slash_command(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return "", stripped
    command, _, remainder = stripped.partition(" ")
    return command.casefold(), remainder.strip()


def _has_goal_browser_task_intent(text: str) -> bool:
    """Return True for explicit /goal tasks that require web UI control."""
    command, body = _split_slash_command(text)
    if command != "/goal" or not body:
        return False
    if _has_real_browser_intent(body):
        return True
    if _URL_OR_DOMAIN_RE.search(body):
        return True
    if _contains_intent_term(body, _GOAL_BROWSER_TASK_PHRASES):
        return True
    return _contains_intent_term(
        body,
        _GOAL_WEB_ACTION_TERMS,
    ) and _contains_intent_term(body, _GOAL_WEB_TARGET_TERMS)


def _has_browser_control_intent(text: str) -> bool:
    return _has_real_browser_intent(text) or _has_goal_browser_task_intent(
        text,
    )


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
    extras["goal_max_iterations"] = _BROWSER_CONTROL_GOAL_MAX_ITERATIONS


def _inject_browser_control_goal_guidance(ctx: HookContext) -> None:
    extras = getattr(ctx, "extras", None)
    if extras is None:
        extras = {}
        setattr(ctx, "extras", extras)
    if extras.get("_browser_control_goal_guidance_injected"):
        return
    extras["_browser_control_goal_guidance_injected"] = True

    inject_context = getattr(ctx, "inject_context", None)
    if callable(inject_context):
        inject_context(
            _BROWSER_CONTROL_GOAL_GUIDANCE,
            priority=30,
            source="browser_control_goal",
        )
        return

    injections = getattr(ctx, "context_injections", None)
    if injections is None:
        injections = []
        setattr(ctx, "context_injections", injections)
    if isinstance(injections, list):
        injections.append(
            {
                "content": _BROWSER_CONTROL_GOAL_GUIDANCE,
                "priority": 30,
                "source": "browser_control_goal",
            },
        )


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
            _inject_browser_control_goal_guidance(ctx)
            return HookResult()

        user_text = (_get_last_user_text(ctx.input_msgs) or "").strip()
        if not user_text:
            return HookResult()

        browser_control_intent = bool(
            extras.get("browser_control_requested"),
        ) or _has_browser_control_intent(user_text)
        if _is_unrelated_slash_command(user_text):
            return HookResult()
        if (
            not browser_control_intent
            and not _session_has_active_browser_control(
                ctx.session_state,
            )
        ):
            return HookResult()

        _append_browser_control_skill(ctx, user_text)
        _inject_browser_control_goal_guidance(ctx)
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
        if not _has_browser_control_intent(user_text):
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
