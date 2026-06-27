# -*- coding: utf-8 -*-
"""Browser Control mission-style iteration loop."""

from __future__ import annotations

import json
import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Any, AsyncGenerator

from agentscope.event import TextBlockDeltaEvent
from agentscope.message import Msg, TextBlock

from .mission_protocols import (
    BlockerDetector,
    ContinuationBuilder,
    GoalChecker,
)

DEFAULT_BROWSER_MISSION_MAX_ITERATIONS = 20
DEFAULT_BROWSER_MISSION_STREAM_TIMEOUT_SECONDS = 90.0
_PHASE0_TIMEOUT_SECONDS = 30.0
_PHASE0_PLANNING_PROMPT = """\
Decompose the following browser task into 2-5 sequential stories.
Write ONLY a JSON object to the file at: {prd_path}

Required JSON structure:
{{
  "task": "<original task>",
  "stories": [
    {{"id": "B1", "title": "<step 1 description>", "passes": false}},
    {{"id": "B2", "title": "<step 2 description>", "passes": false}}
  ]
}}

Rules:
- Each story should be a verifiable browser sub-goal
- Stories should be sequential (B2 depends on B1 completion)
- Preserve all user constraints, including price ranges, quantities, brands,
  categories, dates, locations, and required attributes, as verifiable story
  criteria
- Phase 0 is planning only; every story must have "passes": false
- Do not use memory, chat history, prior runs, or assumptions as completion evidence
- Do NOT call browser_use or any browser tool in this turn
- ONLY write the prd.json file using edit_file or write_file

Task: {task}
"""
logger = logging.getLogger(__name__)
_MISSION_COMPLETE_TEXT = "Browser mission complete. All stories passed in prd.json."


class BrowserMissionTimeout(RuntimeError):
    """Raised when a Browser Control mission stream becomes inactive."""


@dataclass(frozen=True)
class StagnationConfig:
    """Configurable thresholds for browser mission stagnation detection."""

    window_size: int = 3
    min_action_diversity: int = 2
    min_url_diversity: int = 3
    soft_intervention_threshold: int = 3
    hard_intervention_threshold: int = 5
    abort_threshold: int = 7


class StagnationDetector:
    """Detect repeated browser-control strategies without PRD progress."""

    def __init__(self, config: StagnationConfig | None = None) -> None:
        self._config = config or StagnationConfig()
        self._iterations: list[dict[str, Any]] = []

    def record_iteration(
        self,
        action_types: set[str],
        urls: set[str],
        prd_updated: bool,
    ) -> None:
        self._iterations.append(
            {
                "action_types": {
                    str(action).strip().lower()
                    for action in action_types
                    if str(action).strip()
                },
                "urls": {str(url).strip() for url in urls if str(url).strip()},
                "prd_updated": bool(prd_updated),
            },
        )

    @property
    def is_stagnant(self) -> bool:
        if len(self._iterations) < self._config.window_size:
            return False
        return self._records_are_stagnant(
            self._iterations[-self._config.window_size :],
        )

    @property
    def stagnant_iterations(self) -> int:
        if not self.is_stagnant:
            return 0
        for start in range(
            max(len(self._iterations) - self._config.window_size, 0),
            -1,
            -1,
        ):
            records = self._iterations[start:]
            if not self._records_are_stagnant(records):
                return len(self._iterations) - start - 1
        return len(self._iterations)

    @property
    def failed_action_types(self) -> list[str]:
        records = self._stagnant_records()
        actions: set[str] = set()
        for record in records:
            actions.update(record["action_types"])
        return sorted(actions)

    @property
    def intervention_level(self) -> str:
        stagnant_iterations = self.stagnant_iterations
        if stagnant_iterations >= self._config.abort_threshold:
            return "abort"
        if stagnant_iterations >= self._config.hard_intervention_threshold:
            return "hard"
        if stagnant_iterations >= self._config.soft_intervention_threshold:
            return "soft"
        return "none"

    def _stagnant_records(self) -> list[dict[str, Any]]:
        count = self.stagnant_iterations
        if count <= 0:
            return []
        return self._iterations[-count:]

    def _records_are_stagnant(self, records: list[dict[str, Any]]) -> bool:
        if len(records) < self._config.window_size:
            return False
        action_types: set[str] = set()
        urls: set[str] = set()
        for record in records:
            if record["prd_updated"]:
                return False
            action_types.update(record["action_types"])
            urls.update(record["urls"])
        return (
            len(action_types) < self._config.min_action_diversity
            and len(urls) < self._config.min_url_diversity
        )


def _read_prd(prd_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(prd_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_prd_text(prd_path: Path) -> str:
    try:
        return prd_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _stories(prd: dict[str, Any]) -> list[dict[str, Any]]:
    raw = prd.get("stories")
    if raw is None:
        raw = prd.get("userStories")
    if not isinstance(raw, list):
        return []
    return [story for story in raw if isinstance(story, dict)]


def _all_passed(prd: dict[str, Any]) -> bool:
    stories = _stories(prd)
    return bool(stories) and all(bool(story.get("passes")) for story in stories)


def _incomplete_stories(prd: dict[str, Any]) -> list[dict[str, Any]]:
    return [story for story in _stories(prd) if not story.get("passes")]


class PRDGoalChecker:
    """Default GoalChecker backed by prd.json on disk."""

    def __init__(self, prd_path: Path) -> None:
        self._path = prd_path

    def is_complete(self) -> bool:
        return _all_passed(_read_prd(self._path))

    def has_stories(self) -> bool:
        return bool(_stories(_read_prd(self._path)))

    def incomplete_stories(self) -> list[dict[str, Any]]:
        return _incomplete_stories(_read_prd(self._path))

    def read_snapshot(self) -> str:
        return _read_prd_text(self._path)


class BrowserContinuationBuilder:
    """Default ContinuationBuilder using existing continuation text."""

    def __init__(self, prd_path: Path) -> None:
        self._path = prd_path

    def build(
        self,
        iteration: int,
        max_iterations: int,
        incomplete_stories: list[dict[str, Any]],
        detector: Any,
    ) -> str:
        del incomplete_stories
        return _continuation_text(
            self._path,
            _read_prd(self._path),
            iteration,
            max_iterations,
            detector,
        )


class ExplicitBlockerDetector:
    """Default BlockerDetector using explicit mission-blocked signals."""

    def is_blocked(self, message: Any) -> bool:
        return _reports_unrecoverable_blocker(message)


PhraseBlockerDetector = ExplicitBlockerDetector


def _should_run_phase0_planning(
    *,
    task: str,
    prd_path: Path,
) -> bool:
    if not task:
        return False
    prd = _read_prd(prd_path)
    stories = _stories(prd)
    if _all_passed(prd):
        return False
    return len(stories) <= 1


def _reset_phase0_story_passes(prd_path: Path) -> bool:
    """Ensure Phase 0 produces only an executable plan, not completion state."""
    prd = _read_prd(prd_path)
    stories = _stories(prd)
    if not stories:
        return False

    changed = False
    for story in stories:
        if story.get("passes") is not False:
            story["passes"] = False
            changed = True

    if changed:
        prd_path.write_text(
            json.dumps(prd, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return True


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


def _get_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _message_content(message: Any) -> list[Any]:
    content = _get_field(message, "content", [])
    return content if isinstance(content, list) else []


def _parse_tool_input(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tool_call_name(value: Any) -> str:
    name = _get_field(value, "name", "")
    if name:
        return str(name)
    function = _get_field(value, "function", None)
    return str(_get_field(function, "name", "") or "")


def _tool_call_input(value: Any) -> dict[str, Any]:
    raw = _get_field(value, "input", None)
    if raw is None:
        raw = _get_field(value, "arguments", None)
    if raw is None:
        function = _get_field(value, "function", None)
        raw = _get_field(function, "arguments", None)
    return _parse_tool_input(raw)


def _record_browser_tool_call(
    tool_call: Any,
    action_types: set[str],
    urls: set[str],
) -> None:
    if _tool_call_name(tool_call) != "browser_use":
        return
    args = _tool_call_input(tool_call)
    action = str(args.get("action") or "").strip().lower()
    if action:
        action_types.add(action)
    url = str(args.get("url") or "").strip()
    if url:
        urls.add(url)


def _record_browser_tool_text(
    text: str,
    action_types: set[str],
    urls: set[str],
) -> None:
    for call_match in re.finditer(r"browser_use\s*\(([^)]*)\)", text):
        call_text = call_match.group(1)
        action_match = re.search(
            r"action\s*=\s*['\"]([^'\"]+)['\"]",
            call_text,
        )
        if action_match:
            action_types.add(action_match.group(1).strip().lower())
        url_match = re.search(r"url\s*=\s*['\"]([^'\"]+)['\"]", call_text)
        if url_match:
            urls.add(url_match.group(1).strip())


def _browser_iteration_signals(
    message: Msg | None,
) -> tuple[set[str], set[str]]:
    action_types: set[str] = set()
    urls: set[str] = set()
    if message is None:
        return action_types, urls

    for block in _message_content(message):
        if _get_field(block, "type") == "tool_call":
            _record_browser_tool_call(block, action_types, urls)
        text = str(_get_field(block, "text", "") or "")
        if text:
            _record_browser_tool_text(text, action_types, urls)

    metadata = _get_field(message, "metadata", {})
    if isinstance(metadata, dict):
        raw_tool_calls = metadata.get("tool_calls") or metadata.get(
            "tool_call",
        )
        if isinstance(raw_tool_calls, dict):
            raw_tool_calls = [raw_tool_calls]
        if isinstance(raw_tool_calls, list):
            for tool_call in raw_tool_calls:
                _record_browser_tool_call(tool_call, action_types, urls)

    return action_types, urls


def _reports_unrecoverable_blocker(message: Msg | None) -> bool:
    if message is None:
        return False
    metadata = _get_field(message, "metadata", {})
    if isinstance(metadata, dict):
        if metadata.get("browser_mission_blocked") is True:
            return True
        status = (
            str(
                metadata.get("browser_mission_status")
                or metadata.get("browser_mission_state")
                or "",
            )
            .strip()
            .lower()
        )
        if status in {"blocked", "unrecoverable_blocker"}:
            return True

    text = _message_text(message).lower()
    explicit_markers = (
        "[browser_mission:blocked]",
        "browser mission blocked:",
        "browser mission blocked -",
        "unrecoverable browser mission blocker:",
    )
    return any(marker in text for marker in explicit_markers)


def _assistant_msg(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> Msg:
    message_metadata = {"browser_mission": True}
    if metadata:
        message_metadata.update(metadata)
    return Msg(
        name="system",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
        metadata=message_metadata,
    )


def _mission_complete_msg() -> Msg:
    return _assistant_msg(
        _MISSION_COMPLETE_TEXT,
        metadata={"browser_mission_status": "complete"},
    )


async def _call_banner_callback(
    banner_callback: Callable[[str, str], Any] | None,
    status_text: str,
    phase: str,
) -> None:
    if banner_callback is None:
        return
    result = banner_callback(status_text, phase)
    if isawaitable(result):
        await result


def _first_meaningful_delta(item: Any) -> str:
    if not isinstance(item, TextBlockDeltaEvent):
        return ""
    text = str(getattr(item, "delta", "") or "").strip()
    return text if len(text) >= 5 else ""


async def _stream_with_inactivity_timeout(
    gen: Any,
    timeout: float = DEFAULT_BROWSER_MISSION_STREAM_TIMEOUT_SECONDS,
) -> AsyncGenerator[Any, None]:
    """Yield async-generator items while enforcing a per-item deadline."""
    aiter = gen.__aiter__()
    while True:
        try:
            yield await asyncio.wait_for(
                aiter.__anext__(),
                timeout=timeout,
            )
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError as exc:
            raise BrowserMissionTimeout(
                f"LLM stream inactive for {timeout}s",
            ) from exc


def _user_msg(text: str) -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


def _internal_msg(text: str) -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
        metadata={
            "browser_mission": True,
            "browser_mission_internal": True,
        },
    )


async def _run_phase0_planning(
    agent: Any,
    task: str,
    prd_path: Path,
) -> bool:
    """Iteration 0: ask the agent to decompose a browser task."""
    result = {"success": False}
    async for _item in _stream_phase0_planning(agent, task, prd_path, result):
        pass
    return result["success"]


async def _stream_phase0_planning(
    agent: Any,
    task: str,
    prd_path: Path,
    result: dict[str, bool],
) -> AsyncGenerator[Any, None]:
    """Stream Phase 0 planning events while recording planning success."""
    prompt = _PHASE0_PLANNING_PROMPT.format(
        prd_path=str(prd_path),
        task=task,
    )
    try:
        async for item in _stream_with_inactivity_timeout(
            agent._reply(  # pylint: disable=protected-access
                inputs=[_user_msg(prompt)],
            ),
            timeout=_PHASE0_TIMEOUT_SECONDS,
        ):
            yield item
    except BrowserMissionTimeout:
        logger.warning(
            "Phase 0 planning timed out after %ss",
            _PHASE0_TIMEOUT_SECONDS,
        )
        return

    if not _reset_phase0_story_passes(prd_path):
        return
    result["success"] = len(_stories(_read_prd(prd_path))) >= 2


def _continuation_text(
    prd_path: Path,
    prd: dict[str, Any],
    iteration: int,
    max_iterations: int,
    detector: StagnationDetector | None = None,
) -> str:
    incomplete = _incomplete_stories(prd)
    lines = [
        (
            f"[Browser mission iteration {iteration + 1}/{max_iterations}] "
            f"{len(incomplete)} story/stories remain incomplete."
        ),
        (
            "This is an internal Browser Mission continuation instruction. "
            "Do not treat this as a new user request."
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
            ("Do not abandon the task while a recoverable browser route " "remains."),
            (
                "After completing a story, use edit_file to set its passes "
                "field to true."
            ),
            (
                "Do not relax, substitute, or reinterpret user constraints. "
                "Keep a story incomplete unless browser evidence satisfies "
                "its price ranges, quantities, categories, and required "
                "attributes."
            ),
        ],
    )
    level = detector.intervention_level if detector is not None else "none"
    if level in {"soft", "hard", "abort"}:
        lines.extend(
            [
                "",
                (
                    "Stagnation guard: take a fresh screenshot before the "
                    "next browser action and use it to reassess visible page "
                    "state."
                ),
            ],
        )
    if detector is not None and level in {"hard", "abort"}:
        failed_actions = ", ".join(detector.failed_action_types) or "unknown"
        lines.extend(
            [
                "",
                (
                    "Avoid repeating failed action types: "
                    f"{failed_actions}. Choose a different strategy unless "
                    "new page evidence proves one is necessary."
                ),
            ],
        )
    return "\n".join(lines)


async def run_browser_mission(
    agent: Any,
    msgs: list[Any],
    prd_path: str | Path,
    max_iterations: int = DEFAULT_BROWSER_MISSION_MAX_ITERATIONS,
    banner_callback: Callable[[str, str], Any] | None = None,
    goal_checker: GoalChecker | None = None,
    continuation_builder: ContinuationBuilder | None = None,
    blocker_detector: BlockerDetector | None = None,
    enable_phase0: bool = True,
    task: str = "",
) -> AsyncGenerator[Any, None]:
    """Run a Browser Control task until prd.json stories pass or limit hits."""
    path = Path(prd_path)
    goal = goal_checker or PRDGoalChecker(path)
    continuation = continuation_builder or BrowserContinuationBuilder(path)
    blocker = blocker_detector or ExplicitBlockerDetector()

    if enable_phase0 and _should_run_phase0_planning(
        task=task,
        prd_path=path,
    ):
        yield _assistant_msg("正在拆解浏览器任务...")
        phase0_result = {"success": False}
        async for item in _stream_phase0_planning(
            agent,
            task,
            path,
            phase0_result,
        ):
            yield item
        success = phase0_result["success"]
        if not success:
            logger.info("Phase 0 failed, using single-story fallback")

    if goal.is_complete():
        yield _mission_complete_msg()
        return

    current_msgs = list(msgs or [])
    detector = StagnationDetector()

    for iteration in range(1, max_iterations + 1):
        if goal.is_complete():
            yield _mission_complete_msg()
            return

        goal_before = goal.read_snapshot()
        yield _assistant_msg("正在思考下一步浏览器操作...")
        await _call_banner_callback(
            banner_callback,
            "正在思考...",
            "thinking",
        )
        last_msg: Msg | None = None
        first_streamed_text_seen = False
        try:
            async for item in _stream_with_inactivity_timeout(
                agent._reply(  # pylint: disable=protected-access
                    inputs=current_msgs,
                ),
            ):
                if not first_streamed_text_seen:
                    streamed_text = _first_meaningful_delta(item)
                    if streamed_text:
                        first_streamed_text_seen = True
                        await _call_banner_callback(
                            banner_callback,
                            streamed_text,
                            "acting",
                        )
                if isinstance(item, Msg):
                    last_msg = item
                yield item
        except BrowserMissionTimeout:
            logger.warning(
                "Browser Control mission stream timed out on iteration %s",
                iteration,
            )

        if not goal.has_stories():
            yield _assistant_msg(
                ("Browser mission cannot continue because " f"{path} has no stories."),
            )
            return

        if goal.is_complete():
            yield _mission_complete_msg()
            return

        if blocker.is_blocked(last_msg):
            return

        action_types, urls = _browser_iteration_signals(last_msg)
        detector.record_iteration(
            action_types,
            urls,
            prd_updated=goal.read_snapshot() != goal_before,
        )
        if detector.intervention_level == "abort":
            stories = _stories(_read_prd(path))
            passed = sum(1 for story in stories if story.get("passes"))
            failed_actions = ", ".join(detector.failed_action_types)
            action_summary = failed_actions or "unknown"
            yield _assistant_msg(
                (
                    "Browser mission stalled after repeated low-diversity "
                    f"browser actions. {passed}/{len(stories)} stories "
                    f"passed. Failed action types: {action_summary}."
                ),
            )
            return

        if iteration < max_iterations:
            current_msgs = [
                _internal_msg(
                    continuation.build(
                        iteration,
                        max_iterations,
                        goal.incomplete_stories(),
                        detector,
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
    "BrowserContinuationBuilder",
    "BrowserMissionTimeout",
    "DEFAULT_BROWSER_MISSION_MAX_ITERATIONS",
    "DEFAULT_BROWSER_MISSION_STREAM_TIMEOUT_SECONDS",
    "ExplicitBlockerDetector",
    "PRDGoalChecker",
    "PhraseBlockerDetector",
    "StagnationConfig",
    "StagnationDetector",
    "_run_phase0_planning",
    "_stream_with_inactivity_timeout",
    "run_browser_mission",
]
