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
_MISSION_START_MARKER = "Starting Mission Mode:"
_MISSION_TASK_RE = re.compile(
    r"Task \(saved in `[^`]+`\):\n> (?P<task>.*?)(?:\n\n|\Z)",
    re.DOTALL,
)
_MISSION_LOOP_DIR_RE = re.compile(
    r"\| Loop dir \(= work dir\) \| `(?P<path>[^`]+)` \|",
)
_MISSION_LOOP_CONFIG_RE = re.compile(
    r"`(?P<path>[^`]+/loop_config\.json)`",
)
_MISSION_PRD_RE = re.compile(r"`(?P<path>[^`]+/prd\.json)`")
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
_MISSION_WEB_INTENT_TERMS = (
    "网上搜索",
    "去网上搜索",
    "网页搜索",
    "搜索网页",
    "打开网页",
    "打开网站",
    "访问网站",
    "用浏览器",
    "使用浏览器",
    "通过浏览器",
    "浏览器打开",
    "浏览器访问",
    "浏览器查看",
    "打开购物车页面",
    "淘宝购物车",
    "search the web",
    "search online",
    "open the web page",
    "open the website",
    "visit the website",
)
_MISSION_WEB_INTENT_PATTERNS = (
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\bwww\.", re.IGNORECASE),
    re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\b", re.IGNORECASE),
    re.compile(r"打开.{0,40}页面"),
)


def _get_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _message_content(message: Any) -> list[Any]:
    content = _get_field(message, "content", [])
    return content if isinstance(content, list) else []


def _message_metadata(message: Any) -> dict[str, Any]:
    metadata = _get_field(message, "metadata", {})
    return metadata if isinstance(metadata, dict) else {}


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
    return any("".join(term.split()) in compact for term in _BROWSER_REPL_TERMS)


def _is_browser_repl_release_code(code: str) -> bool:
    compact = "".join(str(code or "").split())
    return any("".join(term.split()) in compact for term in _BROWSER_REPL_RELEASE_TERMS)


def _is_non_mission_slash_command(text: str) -> bool:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return False
    command = stripped.split(None, 1)[0].casefold()
    return command != "/mission"


def _is_mission_command(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("/") and (
        stripped.split(None, 1)[0].casefold() == "/mission"
    )


def _has_mission_web_intent(text: str) -> bool:
    folded = text.casefold()
    compact = "".join(folded.split())
    for term in _MISSION_WEB_INTENT_TERMS:
        term_folded = term.casefold()
        if term_folded in folded:
            return True
        if "".join(term_folded.split()) in compact:
            return True
    return any(pattern.search(folded) for pattern in _MISSION_WEB_INTENT_PATTERNS)


def _has_real_browser_intent(text: str) -> bool:
    folded = text.casefold()
    compact = "".join(folded.split())
    for term in _REAL_BROWSER_INTENT_TERMS:
        term_folded = term.casefold()
        if term_folded in folded:
            return True
        if "".join(term_folded.split()) in compact:
            return True
    if _is_mission_command(text) and _has_mission_web_intent(text):
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
        blocked = {str(value).strip() for value in existing if str(value).strip()}
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


def _strip_mission_command(text: str) -> str:
    stripped = text.strip()
    if not _is_mission_command(stripped):
        return stripped
    return stripped.split(None, 1)[1].strip() if " " in stripped else ""


def _is_mission_prompt(text: str) -> bool:
    return (
        _MISSION_START_MARKER in text
        and "Task (saved in `" in text
        and "Mission Mode" in text
    )


def _mission_task_text(prompt: str, requested_text: str) -> str:
    match = _MISSION_TASK_RE.search(prompt)
    if match:
        return " ".join(match.group("task").split())
    return _strip_mission_command(requested_text)


def _mission_loop_dir(prompt: str) -> str:
    match = _MISSION_LOOP_DIR_RE.search(prompt)
    if match:
        return match.group("path")
    match = _MISSION_LOOP_CONFIG_RE.search(prompt)
    if match:
        return str(Path(match.group("path")).parent)
    return ""


def _browser_control_mission_prompt(prompt: str, requested_text: str) -> str:
    task_text = _mission_task_text(prompt, requested_text)
    loop_dir = _mission_loop_dir(prompt)
    if not loop_dir:
        return prompt

    prd_path = f"{loop_dir}/prd.json"
    loop_config_path = f"{loop_dir}/loop_config.json"
    task_path = f"{loop_dir}/task.md"
    return f"""Starting Browser Control Mission Mode.

Task (saved in `{task_path}`):
> {task_text}

Loop dir (= work dir): `{loop_dir}`
prd.json: `{prd_path}`
loop_config.json: `{loop_config_path}`

You are the browser operator for this mission, not a worker controller.
The user's `/mission` command is approval to execute this browser task now.

Required execution sequence:
1. Write `{prd_path}` with the exact Mission schema:
   `project`, `branchName`, `description`, and `userStories`.
   Each story must include `id`, `title`, `description`,
   `acceptanceCriteria`, `priority`, `passes`, and `notes`.
   Build the PRD as a Python object and serialize it with
   `json.dumps(prd, ensure_ascii=False, indent=2) + "\\n"` before writing.
   Never hand-write raw JSON text; unescaped quotes in evidence notes make
   `prd.json` invalid.
   Use `write_file` for PRD writes; do not use shell commands to generate
   or update mission files.
2. Immediately read `{loop_config_path}`, set `current_phase` to
   `"execution_confirmed"`, set `"browser_control_mission": true`,
   and write it back.
   Use `read_file` and `write_file` for loop_config updates.
3. Continue in this same turn. Do NOT report the PRD or wait for
   confirmation.
4. Execute the stories yourself with `python_repl` and the Browser SDK.
   Use observe-act-verify after every browser action.
5. After each story succeeds, update `{prd_path}` and set that story's
   `passes` to `true` with concise evidence in `notes`.
6. When all stories pass, set `current_phase` in `{loop_config_path}` to
   `"completed"` and report the result. If a login, CAPTCHA, payment,
   identity check, or other safety blocker appears, stop and report it.

Do NOT dispatch workers, call `spawn_subagent`, delegate to another agent,
use `browser_use`, use `execute_shell_command`, use shell commands, use
`curl`, or use HTTP/search APIs as substitutes for the real browser.
The only browser-action entrypoint is `python_repl` with the preloaded
Browser SDK (`browser.tabs`, `tab.navigate`, `tab.snapshot`, `tab.click`,
`tab.type`, and related SDK calls).
Do not call `desktop_screenshot`, `view_image`, or `view_video`; use
`tab.screenshot()` for CDP-backed page screenshots when a visual fallback
is needed.
"""


def _rewrite_browser_control_mission_prompt(
    ctx: HookContext,
    user_text: str,
) -> str:
    extras = getattr(ctx, "extras", {}) or {}
    requested_text = str(extras.get("browser_control_request_text") or "")
    if not requested_text:
        requested_text = user_text
    if not _is_mission_prompt(user_text):
        return user_text
    return _browser_control_mission_prompt(user_text, requested_text)


def _append_browser_control_skill(ctx: HookContext, user_text: str) -> None:
    user_text = _rewrite_browser_control_mission_prompt(ctx, user_text)
    block = f"{_SKILL_MARKER}\n" f"{_browser_control_skill_body()}\n" "</skill>"
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
        metadata = _message_metadata(message)
        if (
            metadata.get("browser_mission") is True
            and metadata.get("browser_mission_status") in {"complete", "completed"}
        ):
            active = False
            continue
        for block in _message_content(message):
            code = _python_repl_code(block)
            if not code or not _is_browser_repl_code(code):
                continue
            active = not _is_browser_repl_release_code(code)

    return active


def _ctx_text_values(ctx: HookContext) -> list[str]:
    messages: list[Any] = []
    input_msgs = getattr(ctx, "input_msgs", None)
    if isinstance(input_msgs, list):
        messages.extend(input_msgs)

    state = _agent_state(getattr(ctx, "session_state", None))
    context = state.get("context")
    if isinstance(context, list):
        messages.extend(context)

    values: list[str] = []
    for message in messages:
        for block in _message_content(message):
            if _is_text_block(block):
                values.append(_text_block_value(block))
    return values


def _path_value(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    return Path(text)


def _browser_control_mission_file_paths(
    ctx: HookContext,
    texts: list[str],
) -> tuple[Path, Path] | None:
    extras = getattr(ctx, "extras", {}) or {}
    prd_path = _path_value(extras.get("browser_control_mission_prd_path"))
    loop_config_path = _path_value(
        extras.get("browser_control_mission_loop_config_path"),
    )
    loop_dir = _path_value(extras.get("browser_control_mission_loop_dir"))

    for text in texts:
        if loop_dir is None:
            loop_dir = _path_value(_mission_loop_dir(text))
        if loop_config_path is None:
            match = _MISSION_LOOP_CONFIG_RE.search(text)
            if match:
                loop_config_path = _path_value(match.group("path"))
        if prd_path is None:
            match = _MISSION_PRD_RE.search(text)
            if match:
                prd_path = _path_value(match.group("path"))

    if loop_dir is not None:
        prd_path = prd_path or loop_dir / "prd.json"
        loop_config_path = loop_config_path or loop_dir / "loop_config.json"
    if prd_path is not None and loop_config_path is None:
        loop_config_path = prd_path.parent / "loop_config.json"
    if loop_config_path is not None and prd_path is None:
        prd_path = loop_config_path.parent / "prd.json"
    if prd_path is None or loop_config_path is None:
        return None
    if prd_path.name != "prd.json" or loop_config_path.name != "loop_config.json":
        return None
    if prd_path.parent != loop_config_path.parent:
        return None
    return prd_path, loop_config_path


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _all_mission_stories_passed(prd_path: Path) -> bool:
    prd = _read_json_object(prd_path)
    if prd is None:
        return False
    stories = prd.get("userStories")
    if not isinstance(stories, list) or not stories:
        return False
    return all(
        isinstance(story, dict) and story.get("passes") is True for story in stories
    )


def _is_browser_control_mission_context(
    ctx: HookContext,
    texts: list[str],
) -> bool:
    extras = getattr(ctx, "extras", {}) or {}
    if extras.get("browser_control_invocation"):
        return True
    if extras.get("browser_control_requested"):
        return True
    return any("Starting Browser Control Mission Mode." in text for text in texts)


def _mark_browser_control_mission_completed_if_ready(
    ctx: HookContext,
) -> bool:
    if getattr(ctx, "error", None) is not None:
        return False
    texts = _ctx_text_values(ctx)
    if not _is_browser_control_mission_context(ctx, texts):
        return False
    paths = _browser_control_mission_file_paths(ctx, texts)
    if paths is None:
        return False
    prd_path, loop_config_path = paths
    if not prd_path.exists() or not loop_config_path.exists():
        return False
    if not _all_mission_stories_passed(prd_path):
        return False

    loop_config = _read_json_object(loop_config_path)
    if loop_config is None:
        return False
    if loop_config.get("current_phase") != "completed":
        loop_config["current_phase"] = "completed"
        loop_config_path.write_text(
            json.dumps(loop_config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    extras = getattr(ctx, "extras", None)
    if extras is None:
        extras = {}
        setattr(ctx, "extras", extras)
    extras["browser_control_mission_completed"] = True
    return True


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
        if _is_non_mission_slash_command(user_text):
            return HookResult()
        if not real_browser_intent and not _session_has_active_browser_control(
            ctx.session_state
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
        if not user_text or _is_non_mission_slash_command(user_text):
            return HookResult()
        if _has_real_browser_intent(user_text):
            _mark_browser_control_requested(ctx, user_text)
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

        mission_completed = False
        try:
            mission_completed = _mark_browser_control_mission_completed_if_ready(ctx)
        except Exception:
            logger.warning(
                "browser control mission finalization failed session=%s",
                getattr(ctx, "session_id", ""),
                exc_info=True,
            )

        try:
            workspace_dir = getattr(ctx, "workspace_dir", None)
            workspace_id = Path(workspace_dir).name if workspace_dir else ""
            session_id = getattr(ctx, "session_id", "") or ""
            root_session_id = getattr(ctx, "root_session_id", "") or ""
            extras = getattr(ctx, "extras", {}) or {}
            mission_completed = mission_completed or bool(
                extras.get("browser_control_mission_completed"),
            )
            if getattr(ctx, "error", None) is not None or mission_completed:
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
