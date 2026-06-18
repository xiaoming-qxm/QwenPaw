# -*- coding: utf-8 -*-
"""Built-in slash command adapters.

Wraps the four existing command mechanisms (daemon, control,
conversation, skill) as :class:`CommandSpec` instances registered
into a single :class:`SlashCommandRegistry`.  Each adapter reads
from :class:`HookContext` (``ctx.workspace``, ``ctx.agent``, etc.)
and delegates to the original handler.
"""

from __future__ import annotations

import json
import logging
import re
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

        full_query = (
            f"/{command_name} {args}".strip() if args else f"/{command_name}"
        )
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
    return [
        _make_conversation_adapter(n) for n in sorted(_CONVERSATION_COMMANDS)
    ]


# ======================================================================
# Browser takeover command adapter
# ======================================================================

_TAKEOVER_SITE_ALIASES: tuple[tuple[str, str, str], ...] = (
    ("小红书", "小红书", "https://www.xiaohongshu.com"),
    ("xiaohongshu", "小红书", "https://www.xiaohongshu.com"),
    ("xhs", "小红书", "https://www.xiaohongshu.com"),
    ("rednote", "小红书", "https://www.xiaohongshu.com"),
)

_TAKEOVER_READ_WORDS = (
    "看",
    "查看",
    "看看",
    "有什么",
    "有哪些",
    "读取",
    "告诉我",
    "show",
    "inspect",
    "read",
    "what",
)

_TAKEOVER_CART_WORDS = (
    "购物车",
    "购物栏",
    "shopping cart",
    "cart",
)

_TAKEOVER_TAOBAO_WORDS = (
    "淘宝",
    "taobao",
    "www.taobao.com",
    "cart.taobao.com",
)


def _takeover_extract_url(user_input: str) -> tuple[str, str] | None:
    text = user_input.strip()
    match = re.search(r"https?://[^\s\]\)）>]+", text)
    if not match:
        return None
    url = match.group(0).rstrip("。.,，、")
    return url, url


def _takeover_contains_any(text: str, words: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(word.lower() in lower for word in words)


def _takeover_requested_url(user_input: str) -> tuple[str, str] | None:
    extracted = _takeover_extract_url(user_input)
    if extracted is not None:
        return extracted

    lower = user_input.strip().lower()
    for keyword, label, url in _TAKEOVER_SITE_ALIASES:
        if keyword in lower:
            return url, label
    return None


def _takeover_inspection_target(user_input: str) -> tuple[str, str] | None:
    if not _takeover_contains_any(user_input, _TAKEOVER_READ_WORDS):
        return None

    extracted = _takeover_extract_url(user_input)
    if extracted is not None:
        return extracted

    if (
        _takeover_contains_any(user_input, _TAKEOVER_CART_WORDS)
        and _takeover_contains_any(user_input, _TAKEOVER_TAOBAO_WORDS)
    ):
        return "https://cart.taobao.com", "淘宝购物车"

    return None


def _prepare_takeover_tool_context(ctx: Any) -> None:
    try:
        from ..app.agent_context import (
            set_current_agent_id,
            set_current_root_session_id,
            set_current_session_id,
        )

        agent_id = getattr(ctx, "agent_id", None) or "default"
        session_id = getattr(ctx, "session_id", None) or ""
        root_session_id = (
            getattr(ctx, "root_session_id", None) or session_id
        )
        set_current_agent_id(agent_id)
        set_current_session_id(session_id)
        set_current_root_session_id(root_session_id)
    except Exception:
        logger.debug("takeover: failed to seed app context", exc_info=True)

    workspace_dir = getattr(ctx, "workspace_dir", None)
    if workspace_dir is not None:
        try:
            from ..config.context import set_current_workspace_dir

            set_current_workspace_dir(workspace_dir)
        except Exception:
            logger.debug(
                "takeover: failed to seed workspace context",
                exc_info=True,
            )


def _tool_payload_text(tool_response: Any) -> str:
    content = getattr(tool_response, "content", None) or []
    if not content:
        return ""
    first = content[0]
    return str(getattr(first, "text", "") or "")


def _tool_payload(tool_response: Any) -> dict[str, Any]:
    payload_text = _tool_payload_text(tool_response)
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return {"ok": False, "error": payload_text or "Unknown error"}
    if isinstance(payload, dict):
        return payload
    return {"ok": False, "error": "Unexpected tool response"}


def _takeover_failure_text(label: str, payload: dict[str, Any]) -> str:
    error = str(payload.get("error") or payload.get("message") or "")
    if "bridge is not connected" in error:
        return (
            "还没有连上 Chrome。请确认 QwenPaw Browser Bridge "
            "扩展已启用并显示已连接。"
        )
    return f"没能打开{label}：{error or '未知错误'}"


def _takeover_snapshot_excerpt(snapshot: str, *, max_lines: int = 90) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in snapshot.splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip())
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return "\n".join(lines)


def _takeover_snapshot_text_lines(snapshot: str) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for raw_line in snapshot.splitlines():
        line = re.sub(r"\s+", " ", raw_line.strip())
        if not line:
            continue
        match = re.match(r'^-\s*text\s+"(.*)"$', line)
        if match:
            line = match.group(1)
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def _takeover_join_price_fragments(lines: list[str], start: int) -> str:
    fragments: list[str] = []
    for value in lines[start + 1 : start + 5]:
        if re.fullmatch(r"\d+(?:\.\d+)?|\.", value):
            fragments.append(value)
            if (
                len(fragments) >= 3
                and fragments[-2] == "."
                and fragments[-1].isdigit()
            ):
                break
            continue
        break
    price = "".join(fragments).strip(".")
    return f"¥{price}" if price else ""


def _takeover_taobao_cart_summary(snapshot: str) -> str:
    lines = _takeover_snapshot_text_lines(snapshot)
    if not lines:
        return ""

    start = next(
        (
            idx
            for idx, line in enumerate(lines)
            if line.startswith("全部商品") or line == "全选"
        ),
        0,
    )
    end = next(
        (
            idx
            for idx, line in enumerate(lines[start + 1 :], start + 1)
            if line == "猜你喜欢"
        ),
        len(lines),
    )
    cart_lines = lines[start:end]
    if not cart_lines:
        return ""

    count = ""
    for line in cart_lines:
        match = re.search(r"全部商品\((\d+)\)", line)
        if match:
            count = match.group(1)
            break

    skip_exact = {
        "降价",
        "0",
        "全选",
        "移入收藏",
        "删除",
        "分类",
        "状态",
        "信用卡支付",
        "消费券",
        "15天价保",
        "假一赔十",
        "破损包退",
        "平台加补后",
        "￥",
        ".",
    }

    store = ""
    product = ""
    specs: list[str] = []
    price = ""
    for idx, line in enumerate(cart_lines):
        if not store and line in {"天猫超市"}:
            store = line
            continue
        if (
            not product
            and len(line) >= 6
            and line not in skip_exact
            and not line.startswith("- RootWebArea")
            and not line.startswith("全部商品")
            and not line.startswith("直降")
            and not line.endswith("前送达")
        ):
            product = line
            continue
        if line.startswith(("净含量：", "套餐类型：", "购买规格：")):
            specs.append(line)
        if line == "￥" and not price:
            price = _takeover_join_price_fragments(cart_lines, idx)

    if not product:
        return ""

    title = (
        f"我在购物车里看到 {count} 件商品："
        if count
        else "我在购物车里看到："
    )
    details = product
    if store:
        details = f"{store}：{details}"
    parts = [f"- {details}"]
    if specs:
        parts.append(f"  规格：{'；'.join(specs)}")
    if price:
        parts.append(f"  当前显示价格：{price}")
    return "\n".join([title, *parts])


async def _open_takeover_url(ctx: Any, url: str, label: str) -> "Msg":
    from agentscope.message import Msg, TextBlock

    _prepare_takeover_tool_context(ctx)

    from ..agents.tools.browser_control import browser_use

    tool_response = await browser_use(
        action="claim_tab",
        mode="takeover",
        url=url,
        user_initiated=True,
    )
    payload = _tool_payload(tool_response)

    if payload.get("ok"):
        text = f"已在你的 Chrome 中打开{label}。"
    else:
        text = _takeover_failure_text(label, payload)

    return Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
    )


async def _inspect_takeover_url(ctx: Any, url: str, label: str) -> "Msg":
    from agentscope.message import Msg, TextBlock

    _prepare_takeover_tool_context(ctx)

    from ..agents.tools.browser_control import browser_use

    claim_payload = _tool_payload(
        await browser_use(
            action="claim_tab",
            mode="takeover",
            url=url,
            user_initiated=True,
        ),
    )
    if not claim_payload.get("ok"):
        text = _takeover_failure_text(label, claim_payload)
        return Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )

    tab_id = claim_payload.get("tab_id")
    await browser_use(action="wait_for", mode="takeover", wait_time=8)
    snapshot_payload = _tool_payload(
        await browser_use(
            action="snapshot",
            mode="takeover",
            page_id=str(tab_id) if tab_id is not None else "default",
        ),
    )
    snapshot = str(snapshot_payload.get("snapshot") or "")
    excerpt = _takeover_snapshot_excerpt(snapshot)
    if not snapshot_payload.get("ok"):
        error = str(
            snapshot_payload.get("error")
            or snapshot_payload.get("message")
            or "未知错误",
        )
        text = f"已打开{label}，但读取页面内容失败：{error}"
    elif excerpt:
        summary = ""
        if label == "淘宝购物车":
            summary = _takeover_taobao_cart_summary(snapshot)
        if summary:
            text = (
                f"已在你的 Chrome 中打开{label}，并读取了当前可见页面。\n\n"
                f"{summary}"
            )
        else:
            text = (
                f"已在你的 Chrome 中打开{label}，并读取了当前可见页面。\n\n"
                f"页面可见内容摘录：\n{excerpt}"
            )
    else:
        text = (
            f"已在你的 Chrome 中打开{label}，但当前页面快照没有读到"
            "可见内容。页面可能仍在加载、需要登录或需要人工验证。"
        )

    return Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
    )


def _takeover_prompt(user_input: str) -> str:
    task = user_input.strip() or "Open a new browser takeover session."
    return (
        "The user invoked /takeover. This request must use the user's real "
        "Chrome browser through QwenPaw Browser Takeover.\n\n"
        "Required behavior:\n"
        '- Use browser_use with mode="takeover" for browser actions.\n'
        '- When opening a website, start with browser_use(action="claim_tab", '
        'mode="takeover", url=...).\n'
        "- For the first URL or site the user explicitly requested in this "
        "/takeover command, pass user_initiated=True.\n"
        '- When the user refers to an existing or current tab, call '
        'browser_use(action="tabs", mode="takeover") first, then select it '
        'with browser_use(action="claim_tab", mode="takeover", page_id=...).\n'
        '- To change the current takeover tab URL, use '
        'browser_use(action="navigate", mode="takeover", page_id=..., '
        'url=...). You may also use action="open" with page_id to navigate '
        "an already claimed tab.\n"
        '- If the user asks for Taobao cart, shopping cart, 购物车, or '
        '购物栏, open/claim Taobao once, then navigate the claimed tab to '
        'https://cart.taobao.com instead of opening another Taobao tab or '
        "stopping on the Taobao homepage.\n"
        '- After navigation, call browser_use(action="wait_for", '
        'mode="takeover", wait_time=...) and then action="snapshot" before '
        "deciding what to click or report.\n"
        "- Do not stop after saying that a page is loading; continue with "
        "wait_for and snapshot until you can report page contents or a real "
        "tool error.\n"
        '- For takeover click, prefer ref or selector. If only visible text '
        'is available, browser_use(action="click", mode="takeover", '
        'text=...) is supported.\n'
        "- Prefer snapshot for reading page text and reporting results. "
        "Only use screenshot when the user explicitly asks for a screenshot "
        "or text snapshot is not enough.\n"
        "- Do not call send_file_to_user unless a tool returned a real local "
        "file path.\n"
        "- Supported takeover actions include: claim_tab, tabs, open, "
        "navigate, snapshot, screenshot, click, type, wait_for, release_tab, "
        "and stop.\n"
        "- Do not use the default/headless/managed-CDP browser for this "
        "request.\n"
        "- If the Chrome bridge is disconnected or setup is missing, explain "
        "that to the user and ask them to enable the QwenPaw Browser Bridge "
        "extension.\n\n"
        f"User task: {task}"
    )


def _rewrite_last_input_text(ctx: Any, text: str) -> bool:
    from agentscope.message._block import TextBlock

    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return False

    last = msgs[-1]
    content = getattr(last, "content", None)
    if isinstance(content, list):
        for idx, block in enumerate(content):
            btype = (
                block.get("type")
                if isinstance(block, dict)
                else getattr(block, "type", None)
            )
            if btype == "text":
                if isinstance(block, dict):
                    block["text"] = text
                else:
                    content[idx] = TextBlock(type="text", text=text)
                return True
        content.insert(0, TextBlock(type="text", text=text))
        return True

    if isinstance(content, str):
        last.content = text
        return True

    return False


def _make_takeover_adapter() -> CommandSpec:
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
                            "Usage: `/takeover <task>`\n\n"
                            "Example: `/takeover open xiaohongshu in my "
                            "Chrome browser`"
                        ),
                    ),
                ],
            )

        inspection_target = _takeover_inspection_target(args)
        if inspection_target is not None:
            url, label = inspection_target
            return await _inspect_takeover_url(ctx, url, label)

        requested = _takeover_requested_url(args)
        if requested is not None:
            url, label = requested
            return await _open_takeover_url(ctx, url, label)

        _rewrite_last_input_text(ctx, _takeover_prompt(args))
        return None

    return CommandSpec(
        name="takeover",
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
        (
            skills_dir / sn
            for sn in effective_skills
            if sn.lower() == skill_name
        ),
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
    specs.append(_make_takeover_adapter())
    return specs


def get_skill_fallback_handler() -> FallbackHandler:
    """Return the ``/<skill_name>`` fallback dispatch handler."""
    return _skill_fallback_handler


__all__ = [
    "collect_builtin_command_specs",
    "get_skill_fallback_handler",
]
