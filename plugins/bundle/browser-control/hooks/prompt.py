# -*- coding: utf-8 -*-
"""Browser Control prompt and slash command integration."""

from __future__ import annotations

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
) -> str:
    """Render Browser Control guidance for one user task."""
    task = user_input.strip() or "Open a new browser control session."
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

        set_internal_browser_control_prompt(
            ctx,
            build_browser_control_prompt(args),
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
    "set_internal_browser_control_prompt",
]
