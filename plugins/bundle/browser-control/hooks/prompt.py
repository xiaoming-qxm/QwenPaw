# -*- coding: utf-8 -*-
"""Browser Control prompt and slash command integration."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from qwenpaw.runtime.prompt_manager import SyncPromptContributor
from qwenpaw.runtime.slash_command_registry import CommandSpec

PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "control_guidance.md"
)


def _read_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_browser_control_prompt(
    user_input: str,
    *,
    continuation: bool = False,
    prd_path: str | Path = "",
) -> str:
    """Render Browser Control guidance for one user task."""
    task = user_input.strip() or "Open a new browser control session."
    prd_path_text = str(prd_path or "").strip()
    intro = (
        "The user is continuing an active /browser-control session in this "
        "chat. This request must continue in the same real Chrome browser "
        "through QwenPaw Browser Control."
        if continuation
        else (
            "The user invoked /browser-control. This request must use the "
            "user's real Chrome browser through QwenPaw Browser Control."
        )
    )
    continuation_rules = (
        "- A plain follow-up in this chat can refer to the prior page, tab, "
        "login state, or browsing goal even when it does not repeat Chrome "
        "or browser wording.\n"
        '- For continuation turns, call browser_use(action="tabs", '
        'mode="control") first, claim/reuse the most relevant existing tab '
        "with page_id, and observe it before opening or navigating "
        "elsewhere.\n"
        "- Continue inside the same real Chrome browser and preserve the "
        "user's visible control surface."
        if continuation
        else ""
    )
    template = _read_prompt_template()
    return (
        template.replace("{{ intro }}", intro)
        .replace("{{ continuation_rules }}", continuation_rules)
        .replace(
            "{{ mission_prd_path }}",
            prd_path_text or "not initialized for this turn",
        )
        .replace("{{ task }}", task)
        .strip()
    )


def set_internal_browser_control_prompt(ctx: Any, text: str) -> bool:
    """Store Browser Control prompt data on the runtime hook context."""
    extras = getattr(ctx, "extras", None)
    if extras is None:
        extras = {}
        setattr(ctx, "extras", extras)
    extras["browser_control_prompt"] = text
    extras["browser_control_invocation"] = True

    request = getattr(ctx, "request", None)
    if request is not None:
        request_context = getattr(request, "request_context", None)
        if not isinstance(request_context, dict):
            request_context = {}
            setattr(request, "request_context", request_context)
        request_context["browser_control_invocation"] = True
    return True


def _safe_session_dir_name(session_id: str) -> str:
    raw = str(session_id or "default").strip() or "default"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)


def _browser_mission_root(ctx: Any) -> Path:
    workspace_dir = getattr(ctx, "workspace_dir", None)
    if workspace_dir:
        return Path(workspace_dir)
    return Path(tempfile.gettempdir()) / "qwenpaw-browser-control"


def initialize_browser_mission_prd(ctx: Any, user_task: str) -> Path:
    """Create the per-session browser mission prd.json."""
    session_id = (
        getattr(ctx, "root_session_id", "")
        or getattr(ctx, "session_id", "")
        or "default"
    )
    mission_dir = (
        _browser_mission_root(ctx)
        / "browser-missions"
        / _safe_session_dir_name(session_id)
    )
    mission_dir.mkdir(parents=True, exist_ok=True)
    prd_path = (mission_dir / "prd.json").resolve()
    task = user_task.strip()
    prd = {
        "task": task,
        "stories": [
            {
                "id": "B1",
                "title": task,
                "passes": False,
            },
        ],
    }
    prd_path.write_text(
        json.dumps(prd, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    extras = getattr(ctx, "extras", None)
    if extras is None:
        extras = {}
        setattr(ctx, "extras", extras)
    extras["browser_control_mission_prd_path"] = str(prd_path)

    request = getattr(ctx, "request", None)
    if request is not None:
        request_context = getattr(request, "request_context", None)
        if not isinstance(request_context, dict):
            request_context = {}
            setattr(request, "request_context", request_context)
        request_context["browser_control_mission_prd_path"] = str(prd_path)

    return prd_path


class BrowserControlPromptContributor(SyncPromptContributor):
    """Append request-time Browser Control guidance."""

    name = "browser_control"
    priority = 89

    def contribute_sync(self, ctx: Any) -> str | None:
        extras = getattr(ctx, "extras", {}) or {}
        prompt = extras.get("browser_control_prompt")
        return str(prompt).strip() if prompt else None


def create_browser_control_command() -> CommandSpec:
    """Return the slash command spec for /browser-control."""

    async def _handler(ctx: Any, args: str) -> Any:
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

        prd_path = initialize_browser_mission_prd(ctx, args)
        set_internal_browser_control_prompt(
            ctx,
            build_browser_control_prompt(args, prd_path=prd_path),
        )
        return None

    return CommandSpec(
        name="browser-control",
        handler=_handler,
        category="browser",
        help_text="Use the user's real Chrome browser for this request.",
    )


__all__ = [
    "BrowserControlPromptContributor",
    "build_browser_control_prompt",
    "create_browser_control_command",
    "initialize_browser_mission_prd",
    "set_internal_browser_control_prompt",
]
