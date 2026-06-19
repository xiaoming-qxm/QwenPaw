# -*- coding: utf-8 -*-
"""Built-in slash command adapters.

Wraps the four existing command mechanisms (daemon, control,
conversation, skill) as :class:`CommandSpec` instances registered
into a single :class:`SlashCommandRegistry`.  Each adapter reads
from :class:`HookContext` (``ctx.workspace``, ``ctx.agent``, etc.)
and delegates to the original handler.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._state_utils import StateProxy
from .slash_command_registry import CommandSpec, FallbackHandler

if TYPE_CHECKING:
    from agentscope.message import Msg

logger = logging.getLogger(__name__)


# ======================================================================
# Daemon command adapters
# ======================================================================


def _make_daemon_adapter(subcommand: str) -> CommandSpec:
    """Create a :class:`CommandSpec` for one daemon subcommand."""

    async def _handler(ctx: Any, args: str) -> "Msg | None":
        from .commands.daemon import (
            DaemonCommandHandlerMixin,
            DaemonContext,
        )
        from ..config.config import load_agent_config

        agent_id = getattr(ctx, "agent_id", None) or "default"
        workspace = getattr(ctx, "workspace", None)

        try:
            cfg = load_agent_config(agent_id)
            agent_name = cfg.name if cfg and cfg.name else "QwenPaw"
        except Exception:
            agent_name = "QwenPaw"

        daemon_ctx = DaemonContext(
            load_config_fn=lambda: load_agent_config(agent_id),
            memory_manager=getattr(workspace, "memory_manager", None),
            context_manager=getattr(
                workspace,
                "context_manager",
                None,
            ),
            manager=getattr(workspace, "_manager", None),
            agent_id=agent_id,
            session_id=getattr(ctx, "session_id", "") or "",
            agent_name=agent_name,
        )

        full_query = f"/{subcommand} {args}".strip()
        handler_mixin = DaemonCommandHandlerMixin()
        return await handler_mixin.handle_daemon_command(
            full_query,
            daemon_ctx,
        )

    return CommandSpec(
        name=subcommand,
        handler=_handler,
        category="daemon",
    )


def _make_daemon_compound_adapter() -> CommandSpec:
    """``/daemon <sub>`` compound entry.

    Delegates via ``parse_daemon_query``.
    """

    async def _handler(ctx: Any, args: str) -> "Msg | None":
        from .commands.daemon import (
            DaemonCommandHandlerMixin,
            DaemonContext,
            parse_daemon_query,
        )
        from ..config.config import load_agent_config

        full_query = f"/daemon {args}".strip()
        parsed = parse_daemon_query(full_query)
        if parsed is None:
            from agentscope.message import Msg, TextBlock

            return Msg(
                name="assistant",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text="Unknown daemon command.",
                    ),
                ],
            )

        agent_id = getattr(ctx, "agent_id", None) or "default"
        workspace = getattr(ctx, "workspace", None)

        try:
            cfg = load_agent_config(agent_id)
            agent_name = cfg.name if cfg and cfg.name else "QwenPaw"
        except Exception:
            agent_name = "QwenPaw"

        daemon_ctx = DaemonContext(
            load_config_fn=lambda: load_agent_config(agent_id),
            memory_manager=getattr(
                workspace,
                "memory_manager",
                None,
            ),
            context_manager=getattr(
                workspace,
                "context_manager",
                None,
            ),
            manager=getattr(workspace, "_manager", None),
            agent_id=agent_id,
            session_id=getattr(ctx, "session_id", "") or "",
            agent_name=agent_name,
        )

        handler_mixin = DaemonCommandHandlerMixin()
        return await handler_mixin.handle_daemon_command(
            full_query,
            daemon_ctx,
        )

    return CommandSpec(
        name="daemon",
        handler=_handler,
        category="daemon",
    )


def _collect_daemon_specs() -> list[CommandSpec]:
    specs = [
        _make_daemon_adapter("restart"),
        _make_daemon_adapter("status"),
        _make_daemon_adapter("version"),
        _make_daemon_adapter("logs"),
    ]
    # reload-config has an underscore alias
    rc_spec = _make_daemon_adapter("reload-config")
    specs.append(
        CommandSpec(
            name=rc_spec.name,
            handler=rc_spec.handler,
            aliases=("reload_config",),
            category=rc_spec.category,
        ),
    )
    specs.append(_make_daemon_compound_adapter())
    return specs


# ======================================================================
# Control command adapters
# ======================================================================


def _make_control_adapter(
    handler: Any,
    command_name: str,
) -> CommandSpec:
    """Wrap a :class:`BaseControlCommandHandler` as
    a :class:`CommandSpec`.
    """

    async def _handler(ctx: Any, args: str) -> "Msg | None":
        from .commands.control import parse_args
        from .commands.control.base import ControlContext
        from agentscope.message import Msg, TextBlock

        workspace = getattr(ctx, "workspace", None)
        request = getattr(ctx, "request", None)

        if workspace is None:
            return Msg(
                name="assistant",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text="**Error**\n\nControl command "
                        "unavailable (workspace not initialized)",
                    ),
                ],
            )

        channel = None
        channel_mgr = getattr(workspace, "channel_manager", None)
        if channel_mgr is not None:
            channel_id = getattr(request, "channel", None) or "console"
            try:
                channel = await channel_mgr.get_channel(
                    channel_id,
                )
            except Exception:
                pass

        full_query = f"/{command_name} {args}".strip() if args else f"/{command_name}"
        parsed_args = parse_args(
            full_query,
            f"/{command_name}",
        )

        ctrl_ctx = ControlContext(
            workspace=workspace,
            payload=request,
            channel=channel,
            session_id=getattr(ctx, "session_id", "") or "",
            user_id=(getattr(request, "user_id", "") if request else "") or "",
            agent_id=getattr(ctx, "agent_id", "") or "",
            args=parsed_args,
        )

        try:
            text = await handler.handle(ctrl_ctx)
        except Exception as e:
            logger.exception(
                "Control command failed: /%s",
                command_name,
            )
            text = f"**Command Failed**\n\n{e}"

        return Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )

    return CommandSpec(
        name=command_name,
        handler=_handler,
        category="control",
    )


def _collect_control_specs() -> list[CommandSpec]:
    from .commands.control import _COMMAND_REGISTRY

    specs = []
    seen_names: set[str] = set()
    for raw_name, handler in _COMMAND_REGISTRY.items():
        name = raw_name.lstrip("/")
        if name in seen_names:
            continue
        seen_names.add(name)
        specs.append(_make_control_adapter(handler, name))
    return specs


# ======================================================================
# Conversation command adapters
# ======================================================================

_CONVERSATION_COMMANDS = frozenset(
    {
        "compact",
        "new",
        "clear",
        "history",
        "compact_str",
        "summarize_status",
        "message",
        "dump_history",
        "load_history",
        "proactive",
        "plan",
    },
)


async def _load_agent_state(ctx: Any) -> "Any":
    """Load AgentState from workspace.session without building the agent."""
    from agentscope.state import AgentState

    workspace = getattr(ctx, "workspace", None)
    if workspace is None:
        return None
    session = getattr(workspace, "session", None)
    if session is None:
        return None

    request = getattr(ctx, "request", None)
    user_id = (getattr(request, "user_id", "") if request else "") or ""
    channel = (getattr(request, "channel", "") if request else "") or ""

    proxy = StateProxy()
    await session.load_session_state(
        session_id=ctx.session_id,
        user_id=user_id or ctx.session_id,
        channel=channel,
        agent=proxy,
    )
    if not proxy.data:
        return AgentState()

    raw = proxy.data.get("state")
    if raw is not None:
        return AgentState.model_validate(raw)

    # Legacy 1.x format
    memory_raw = proxy.data.get("memory")
    if isinstance(memory_raw, dict):
        from ..app.chats.utils import parse_legacy_memory_state

        msgs, summary = parse_legacy_memory_state(memory_raw)
        state = AgentState()
        state.context.extend(msgs)
        state.summary = summary
        return state

    return AgentState()


async def _save_agent_state(ctx: Any, state: "Any") -> None:
    """Save AgentState back to workspace.session."""
    workspace = getattr(ctx, "workspace", None)
    if workspace is None:
        return
    session = getattr(workspace, "session", None)
    if session is None:
        return

    request = getattr(ctx, "request", None)
    user_id = (getattr(request, "user_id", "") if request else "") or ""
    channel = (getattr(request, "channel", "") if request else "") or ""

    proxy = StateProxy()
    proxy.data = {"state": state.model_dump(mode="json")}
    await session.save_session_state(
        session_id=ctx.session_id,
        user_id=user_id or ctx.session_id,
        channel=channel,
        agent=proxy,
    )


def _make_conversation_adapter(name: str) -> CommandSpec:
    """Wrap one conversation command via standalone CommandHandler.

    Loads AgentState directly from session — no agent instance required.
    """

    async def _handler(ctx: Any, args: str) -> "Msg | None":
        from ..agents.command_handler import CommandHandler

        # /plan with arguments is NOT a command — fall through to model
        if name == "plan" and args.strip():
            return None

        workspace = getattr(ctx, "workspace", None)
        if workspace is None:
            return None

        state = await _load_agent_state(ctx)
        if state is None:
            return None

        agent_id = getattr(ctx, "agent_id", None) or "default"
        cmd_handler = CommandHandler(
            agent_name="QwenPaw",
            state=state,
            agent_id=agent_id,
            memory_manager=getattr(workspace, "memory_manager", None),
            context_manager=getattr(workspace, "context_manager", None),
        )

        full_query = f"/{name} {args}".strip() if args else f"/{name}"
        result = await cmd_handler.handle_command(full_query)

        await _save_agent_state(ctx, state)
        return result

    return CommandSpec(
        name=name,
        handler=_handler,
        category="conversation",
    )


def _collect_conversation_specs() -> list[CommandSpec]:
    return [_make_conversation_adapter(n) for n in sorted(_CONVERSATION_COMMANDS)]


# ======================================================================
# Browser control command adapter
# ======================================================================


def _browser_control_prompt(user_input: str) -> str:
    task = user_input.strip() or "Open a new browser control session."
    return (
        "The user invoked /browser-control. This request must use the user's "
        "real Chrome browser through QwenPaw Browser Control.\n\n"
        "Required behavior:\n"
        '- Use browser_use with mode="control" for browser actions.\n'
        "- Turn the user's real-world browser goal into an observe-act-verify "
        "loop: observe the page, choose the next browser action, then verify "
        "the visible result before continuing or answering.\n"
        '- When opening a website, start with browser_use(action="claim_tab", '
        'mode="control", url=...). If the user names a site without a URL, '
        "resolve a concrete URL from general knowledge or search; ask only "
        "when the target is genuinely ambiguous.\n"
        "- For the first URL or site the user explicitly requested in this "
        "/browser-control command, pass user_initiated=True.\n"
        "- A successful claim_tab/open response with ok=true and tab_id means "
        "the tab is already opened and claimed. Treat that step as complete. "
        "Your next browser tool call after a successful claim_tab/open MUST "
        "be wait_for or snapshot; do not call claim_tab/open again for the "
        "same URL/tab.\n"
        '- If the tool response includes next_action="snapshot", follow it. '
        "If you are unsure whether the page loaded, observe with snapshot "
        "or wait_for then snapshot; never repeat open/claim to check.\n"
        "- Do not use shell commands, HTTP clients, local files, or other "
        "non-browser tools as substitutes for waiting, observing, or verifying "
        "the real Chrome page. Use browser_use wait_for, snapshot, and "
        "screenshot for browser state.\n"
        "- The user must be able to watch, assist, pause, or stop the work. "
        "Keep the active control tab visible and use browser_use click, type, "
        "press_key, wait_for, snapshot, and screenshot so mouse and keyboard "
        "actions remain visible in the user's Chrome window.\n"
        "- When the user refers to an existing or current tab, call "
        'browser_use(action="tabs", mode="control") first, then select it '
        'with browser_use(action="claim_tab", mode="control", page_id=...).\n'
        "- Keep a single active claimed tab for one browsing target unless "
        "the user's task explicitly needs multiple tabs. Do not open duplicate "
        "tabs for the same target; navigate or click within the claimed tab.\n"
        "- To change the current control tab URL, use "
        'browser_use(action="navigate", mode="control", page_id=..., '
        'url=...). You may also use action="open" with page_id to navigate '
        "an already claimed tab.\n"
        "- After every material navigation, click, type, or wait, call "
        'browser_use(action="snapshot", mode="control", ...) before '
        "deciding the next step or reporting results. Use "
        'browser_use(action="wait_for", mode="control", wait_time=...) '
        "before snapshot when the page is loading or changing.\n"
        "- Observation ladder: first use snapshot as structured page evidence "
        "(accessibility/DOM text, refs, roles, names). Use refs/selectors from "
        "that structured evidence for clicks and typing when possible.\n"
        '- Visual fallback: call browser_use(action="screenshot", '
        'mode="control", page_id=...) when snapshot is empty, only shows a '
        "generic RootWebArea, misses key visual state, the page is mostly "
        "image/canvas based, layout/position matters, or structured evidence "
        "does not explain what to do next. The screenshot tool output already "
        "includes the image as visual evidence; inspect that image directly "
        "from the tool result to decide the next browser action or verify "
        "completion.\n"
        '- Do not call browser_use(action="eval"), action="evaluate", '
        "run_code, JavaScript snippets, arbitrary CDP Runtime calls, or "
        "local shell/code tools to inspect the page. To check URLs or tabs, "
        'use browser_use(action="tabs", mode="control").\n'
        "- Do not call view_image, view_video, read_file, desktop_screenshot, "
        "or send_file_to_user to inspect a browser screenshot. The visual "
        "fallback must remain inside the browser_use control observe-act-"
        "verify loop.\n"
        "- If structured and visual evidence disagree, trust the more recent "
        "observation and gather another snapshot/screenshot after the next "
        "action.\n"
        "- Never report success from intent alone. Only answer as complete "
        "after the requested state is visible in snapshot/screenshot output "
        "or after a browser tool returns a concrete result.\n"
        "- If a page is still loading, authentication is required, a CAPTCHA "
        "or risk check appears, or the site blocks automation, report that "
        "specific blocker and what user action is needed. Do not invent page "
        "contents.\n"
        "- For control click, prefer ref or selector. If only visible text "
        'is available, browser_use(action="click", mode="control", '
        "text=...) is supported.\n"
        "- Prefer snapshot for reading page text and reporting results. "
        "Only use screenshot when the user explicitly asks for a screenshot "
        "or text snapshot is not enough to determine the page state.\n"
        "- Do not call send_file_to_user unless a tool returned a real local "
        "file path.\n"
        "- Supported control actions include: claim_tab, tabs, open, "
        "navigate, snapshot, screenshot, click, type, press_key, wait_for, "
        "release_tab, and stop.\n"
        "- If the user asks to stop, cancel, end, or release Chrome control, "
        'call browser_use(action="stop", mode="control") immediately and '
        "then report that control has been released.\n"
        "- Do not use the default/headless/managed-CDP browser for this "
        "request.\n"
        "- If the Chrome bridge is disconnected or setup is missing, explain "
        "that to the user and ask them to enable the QwenPaw Chrome "
        "extension.\n\n"
        f"User task: {task}"
    )


def _inject_internal_browser_control_prompt(ctx: Any, text: str) -> bool:
    from agentscope.message import Msg, TextBlock

    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return False

    guidance = Msg(
        name="system",
        role="system",
        content=[TextBlock(type="text", text=text)],
    )
    msgs.insert(max(len(msgs) - 1, 0), guidance)
    return True


def _make_browser_control_adapter() -> CommandSpec:
    async def _handler(ctx: Any, args: str) -> "Msg | None":
        from agentscope.message import Msg, TextBlock

        if not args.strip():
            return Msg(
                name="assistant",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Usage: `/browser-control <task>`\n\n"
                            "Example: `/browser-control open xiaohongshu "
                            "in my Chrome browser`"
                        ),
                    ),
                ],
            )

        _inject_internal_browser_control_prompt(
            ctx,
            _browser_control_prompt(args),
        )
        return None

    return CommandSpec(
        name="browser-control",
        handler=_handler,
        category="browser",
        help_text="Use the user's real Chrome browser for this request.",
    )


# ======================================================================
# Skill fallback handler
# ======================================================================


def _parse_skill_query(query: str) -> tuple[str, str] | None:
    """Parse ``/name [input]`` or ``/[name with spaces] [input]``."""
    stripped = query.strip()
    if not stripped.startswith("/"):
        return None
    rest = stripped[1:]
    if rest.startswith("["):
        close = rest.find("]")
        if close < 0:
            return None
        name = rest[1:close].strip().lower()
        user_input = rest[close + 1 :].strip()
        return (name, user_input) if name else None
    parts = rest.split(None, 1)
    if not parts:
        return None
    name = parts[0].lower()
    user_input = parts[1] if len(parts) > 1 else ""
    return (name, user_input) if name else None


# pylint: disable-next=too-many-return-statements
async def _skill_fallback_handler(
    raw_text: str,
    ctx: Any,
) -> "Msg | None":
    """Fallback handler for ``/<skill_name>`` dispatch.

    Resolves skills directly from the filesystem (workspace/skills/
    directory) — no agent or toolkit required.
    """
    from agentscope.message import Msg, TextBlock

    workspace = getattr(ctx, "workspace", None)
    if workspace is None:
        return None

    workspace_dir = getattr(workspace, "workspace_dir", None)
    if not workspace_dir:
        return None

    parsed = _parse_skill_query(raw_text)
    if not parsed:
        return None
    skill_name, user_input = parsed

    from ..agents.skill_system.registry import (
        get_workspace_skills_dir,
        resolve_effective_skills,
    )

    request = getattr(ctx, "request", None)
    channel = (getattr(request, "channel", "") if request else "") or "console"

    try:
        effective_skills = resolve_effective_skills(
            Path(workspace_dir),
            channel,
        )
    except Exception:
        return None

    skills_dir = get_workspace_skills_dir(Path(workspace_dir))
    skill_dir = next(
        (skills_dir / sn for sn in effective_skills if sn.lower() == skill_name),
        None,
    )
    if skill_dir is None or not skill_dir.exists():
        return None

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    from ..agents.utils.file_handling import (
        read_text_file_with_encoding_fallback,
    )

    import frontmatter as fm

    raw = read_text_file_with_encoding_fallback(skill_md)
    post = fm.loads(raw)
    display_name = post.get("name") or skill_name

    if not user_input:
        desc = post.get("description") or "No description."
        return Msg(
            name="assistant",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"**{skill_name}**\n\n"
                        f"- **command**: `/{skill_name} <input>` to invoke\n"
                        f"- **name**: {display_name}\n"
                        f"- **description**: {desc}\n"
                        f"- **path**: `{skill_dir}`"
                    ),
                ),
            ],
        )

    # Rewrite last message with skill body — agent will execute with it
    merged = (
        f"Use the [{display_name}] skill in "
        f"`{skill_dir}` to fulfill "
        f"user's task: {user_input}\n\n"
        f"{post.content}"
    )
    msgs = getattr(ctx, "input_msgs", None)
    if msgs:
        last = msgs[-1]
        content = getattr(last, "content", None)
        if isinstance(content, list):
            for i, block in enumerate(content):
                btype = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if btype == "text":
                    content[i] = TextBlock(type="text", text=merged)
                    return None
            content.insert(0, TextBlock(type="text", text=merged))
        elif isinstance(content, str):
            last.content = merged
    return None


# ======================================================================
# Factory
# ======================================================================


def collect_builtin_command_specs() -> list[CommandSpec]:
    """Return all built-in command specs (daemon, control, conversation).

    These are registered into each workspace's :class:`SlashCommandRegistry`
    via ``bootstrap_plugins(builtin_command_specs=...)``.
    """
    specs: list[CommandSpec] = []
    specs.extend(_collect_daemon_specs())
    specs.extend(_collect_control_specs())
    specs.extend(_collect_conversation_specs())
    specs.append(_make_browser_control_adapter())
    return specs


def get_skill_fallback_handler() -> FallbackHandler:
    """Return the ``/<skill_name>`` fallback dispatch handler."""
    return _skill_fallback_handler


__all__ = [
    "collect_builtin_command_specs",
    "get_skill_fallback_handler",
]
