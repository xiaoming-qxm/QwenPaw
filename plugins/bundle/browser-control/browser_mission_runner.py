# -*- coding: utf-8 -*-
"""Browser Control mission-style iteration loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncGenerator

from agentscope.message import Msg, TextBlock


DEFAULT_BROWSER_MISSION_MAX_ITERATIONS = 20


def _read_prd(prd_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(prd_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _stories(prd: dict[str, Any]) -> list[dict[str, Any]]:
    raw = prd.get("stories")
    if raw is None:
        raw = prd.get("userStories")
    if not isinstance(raw, list):
        return []
    return [story for story in raw if isinstance(story, dict)]


def _all_passed(prd: dict[str, Any]) -> bool:
    stories = _stories(prd)
    return bool(stories) and all(
        bool(story.get("passes")) for story in stories
    )


def _incomplete_stories(prd: dict[str, Any]) -> list[dict[str, Any]]:
    return [story for story in _stories(prd) if not story.get("passes")]


def _message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _reports_unrecoverable_blocker(message: Msg | None) -> bool:
    if message is None:
        return False
    text = _message_text(message).lower()
    blocker_phrases = (
        "unrecoverable blocker",
        "explicit blocker",
        "captcha",
        "authentication required",
        "login required",
        "need user help",
        "cannot proceed",
        "requires human",
    )
    return any(phrase in text for phrase in blocker_phrases)


def _assistant_msg(text: str) -> Msg:
    return Msg(
        name="system",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
        metadata={"browser_mission": True},
    )


def _user_msg(text: str) -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


def _continuation_text(
    prd_path: Path,
    prd: dict[str, Any],
    iteration: int,
    max_iterations: int,
) -> str:
    incomplete = _incomplete_stories(prd)
    lines = [
        (
            f"[Browser mission iteration {iteration + 1}/{max_iterations}] "
            f"{len(incomplete)} story/stories remain incomplete."
        ),
        f"Continue the browser task. Update prd.json at: {prd_path}",
        "Incomplete stories:",
    ]
    for story in incomplete:
        story_id = str(story.get("id") or "?")
        title = str(story.get("title") or story_id)
        lines.append(f"- {story_id}: {title}")
    lines.extend(
        [
            "",
            (
                "Do not abandon the task while a recoverable browser route "
                "remains."
            ),
            (
                "After completing a story, use edit_file to set its passes "
                "field to true."
            ),
        ],
    )
    return "\n".join(lines)


async def run_browser_mission(
    agent: Any,
    msgs: list[Any],
    prd_path: str | Path,
    max_iterations: int = DEFAULT_BROWSER_MISSION_MAX_ITERATIONS,
) -> AsyncGenerator[Any, None]:
    """Run a Browser Control task until prd.json stories pass or limit hits."""
    path = Path(prd_path)
    current_msgs = list(msgs or [])

    for iteration in range(1, max_iterations + 1):
        last_msg: Msg | None = None
        async for item in agent._reply(  # pylint: disable=protected-access
            inputs=current_msgs,
        ):
            if isinstance(item, Msg):
                last_msg = item
            yield item

        prd = _read_prd(path)
        stories = _stories(prd)
        if not stories:
            yield _assistant_msg(
                (
                    "Browser mission cannot continue because "
                    f"{path} has no stories."
                ),
            )
            return

        if _all_passed(prd):
            yield _assistant_msg(
                "Browser mission complete. All stories passed in prd.json.",
            )
            return

        if _reports_unrecoverable_blocker(last_msg):
            return

        if iteration < max_iterations:
            current_msgs = [
                _user_msg(
                    _continuation_text(
                        path,
                        prd,
                        iteration,
                        max_iterations,
                    ),
                ),
            ]

    prd = _read_prd(path)
    stories = _stories(prd)
    passed = sum(1 for story in stories if story.get("passes"))
    yield _assistant_msg(
        (
            f"Browser mission reached max iterations ({max_iterations}). "
            f"{passed}/{len(stories)} stories passed."
        ),
    )


__all__ = [
    "DEFAULT_BROWSER_MISSION_MAX_ITERATIONS",
    "run_browser_mission",
]
