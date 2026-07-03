# -*- coding: utf-8 -*-
"""Rubric evaluation strategies for loop completion.

Architecture:
    RubricStrategy (ABC)
    ├── DefaultRubric     — always SATISFIED (no rubric)
    ├── GoalStatusRubric  — checks session.active
    └── SubAgentRubric    — placeholder for subagent eval
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from .base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)

logger = logging.getLogger(__name__)


class RubricVerdict(str, Enum):
    """Grader verdicts."""

    SATISFIED = "satisfied"
    NEEDS_REVISION = "needs_revision"
    FAILED = "failed"
    GRADER_ERROR = "grader_error"
    MAX_ITERATIONS = "max_iterations_reached"


@dataclass
class RubricEvaluation:
    """Result of one rubric evaluation pass."""

    iteration: int
    verdict: RubricVerdict
    explanation: str = ""
    feedback: str = ""


# ---- Abstract Strategy ----


class RubricStrategy(ABC):
    """Base class for rubric evaluation strategies."""

    @abstractmethod
    async def evaluate(
        self,
        goal: str,
        agent_output: str,
        iteration: int,
    ) -> RubricEvaluation:
        """Evaluate whether the goal is met."""


# ---- Concrete Strategies ----


class DefaultRubric(RubricStrategy):
    """No rubric — always SATISFIED.

    Used for loops that have no rubric requirement.
    The loop terminates normally after each turn.
    """

    async def evaluate(
        self,
        goal: str,
        agent_output: str,
        iteration: int,
    ) -> RubricEvaluation:
        return RubricEvaluation(
            iteration=iteration,
            verdict=RubricVerdict.SATISFIED,
            explanation="No rubric registered",
        )


class GoalStatusRubric(RubricStrategy):
    """Hardcoded status check for GoalMode.

    Accepts a ``get_session_fn`` callback that retrieves
    the current GoalSession via ContextVar (no scan).
    Returns SATISFIED when session.active is False
    (set by update_goal tool), NEEDS_REVISION otherwise.
    """

    def __init__(
        self,
        get_session_fn: Callable[[], Optional[Any]],
    ) -> None:
        self._get_session = get_session_fn

    async def evaluate(
        self,
        goal: str,
        agent_output: str,
        iteration: int,
    ) -> RubricEvaluation:
        session = self._get_session()
        if session is None or not session.active:
            return RubricEvaluation(
                iteration=iteration,
                verdict=RubricVerdict.SATISFIED,
                explanation=("Goal completed via update_goal"),
            )
        return RubricEvaluation(
            iteration=iteration,
            verdict=RubricVerdict.NEEDS_REVISION,
            explanation="Goal still active",
        )


class SubAgentRubric(RubricStrategy):
    """Placeholder for subagent-based verification.

    Concrete implementation should follow the
    oh-my-claudecode/ralph pattern: spawn a subagent
    to verify, then check state file key-values for
    the verdict (not LLM output parsing).

    TODO: implement file-based state verification.
    """

    def __init__(
        self,
        spawn_fn: Any = None,
        fork: bool = False,
    ) -> None:
        self._spawn_fn = spawn_fn
        self._fork = fork

    async def evaluate(
        self,
        goal: str,
        agent_output: str,
        iteration: int,
    ) -> RubricEvaluation:
        """Placeholder — returns GRADER_ERROR."""
        return RubricEvaluation(
            iteration=iteration,
            verdict=RubricVerdict.GRADER_ERROR,
            explanation=("SubAgentRubric not yet implemented"),
        )


class PrematureStopGate(StopGate):
    """Re-prompt on text-only responses.

    Prevents premature stop when the LLM outputs text
    without any tool calls.  Counts interventions per
    request cycle; stops re-prompting after
    ``max_interventions``.
    """

    def __init__(
        self,
        prompt: str = "",
        max_interventions: int = 1,
    ) -> None:
        self._prompt = prompt
        self._max = max_interventions
        self._count = 0
        self._ever_used_tools = False
        self._last_iteration: int | None = None

    @property
    def name(self) -> str:
        return "premature_stop"

    @property
    def priority(self) -> int:
        return 90

    async def check(
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        """Return CONTINUE up to max_interventions.

        Only triggers on text-only responses after the
        current loop cycle has used tools.
        """
        self._reset_cycle_if_needed(ctx)
        if isinstance(ctx, dict) and ctx.get(
            "has_tool_calls",
        ):
            self._ever_used_tools = True
            return None

        # Pure dialogue can legitimately finish with text immediately.
        # Only intervene after the agent has already used tools in this
        # loop cycle and then tries to stop with a text-only response.
        if not self._ever_used_tools:
            return None

        if self._count >= self._max:
            self._count = 0
            return None

        self._count += 1
        logger.debug(
            "PrematureStopGate: intervene %d/%d",
            self._count,
            self._max,
        )
        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self._prompt,
            reason="premature text-only stop re-prompt",
        )

    def _reset_cycle_if_needed(self, ctx: Any) -> None:
        """Reset per-cycle state when the ReAct iteration counter restarts."""
        if not isinstance(ctx, dict):
            return
        iteration = ctx.get("iteration")
        if not isinstance(iteration, int):
            return
        if (
            self._last_iteration is not None
            and iteration <= self._last_iteration
        ):
            self._count = 0
            self._ever_used_tools = False
        self._last_iteration = iteration


__all__ = [
    "PrematureStopGate",
    "DefaultRubric",
    "GoalStatusRubric",
    "RubricEvaluation",
    "RubricStrategy",
    "RubricVerdict",
    "SubAgentRubric",
]
