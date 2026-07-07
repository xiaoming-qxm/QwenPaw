# -*- coding: utf-8 -*-
"""Browser SDK React Loop gate provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qwenpaw.loop.gate_providers import register_loop_gate_provider
from qwenpaw.loop.gates.base import StopAction, StopGate, StopHandlerResult

from ..recovery import (
    BrowserRecoveryAction,
    BrowserRecoveryDecision,
    BrowserProductPolicy,
    BrowserRecoveryPolicy,
    BrowserRequestEvidence,
    collect_browser_request_evidence,
)
from ..telemetry.trace import BrowserTraceEvent, BrowserTraceStore


class BrowserGate(StopGate):
    """React Loop gate backed by Browser SDK recovery decisions."""

    def __init__(
        self,
        *,
        policy: BrowserRecoveryPolicy | None = None,
        product_policy: BrowserProductPolicy | None = None,
        trace_store: BrowserTraceStore | None = None,
    ) -> None:
        self._policy = policy or BrowserRecoveryPolicy(
            product_policy=product_policy,
        )
        self._trace_store = trace_store

    @property
    def name(self) -> str:
        return "browser"

    @property
    def priority(self) -> int:
        return 80

    async def check(
        self,
        ctx: Any,
    ) -> StopHandlerResult | None:
        agent = ctx.get("agent") if isinstance(ctx, dict) else None
        if agent is None:
            return None
        evidence = collect_browser_request_evidence(
            agent,
            trace_store=self._trace_store,
        )
        decision = self._policy.decide(evidence)
        if decision.action == BrowserRecoveryAction.NO_OP:
            return None
        if decision.action in {
            BrowserRecoveryAction.BLOCKED,
            BrowserRecoveryAction.FAILED,
        }:
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=decision.reason,
                final_message=_final_message(decision),
            )
        budget = _retry_budget(decision, self._policy.product_policy)
        if not _consume_budget(
            agent,
            _retry_budget_key(evidence, decision),
            budget,
        ):
            exhausted = _budget_exhausted(decision)
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=exhausted.reason,
                final_message=_final_message(exhausted),
            )
        return StopHandlerResult(
            action=StopAction.CONTINUE,
            reason=decision.reason,
            continuation_message=_continuation_message(decision),
        )


@dataclass
class BrowserLoopGateProvider:
    """Generic loop provider exposed by Browser SDK."""

    name: str = "browser-sdk"

    def gates(
        self,
        workspace: Any,
        running_config: Any,
    ) -> tuple[StopGate, ...]:
        del workspace, running_config
        return (BrowserGate(),)


def register_browser_loop_gate_provider_once() -> None:
    """Register BrowserGate through the generic React Loop provider API."""

    register_loop_gate_provider(BrowserLoopGateProvider())


def _consume_budget(agent: Any, key: str, budget: int) -> bool:
    if budget <= 0:
        return False
    state = getattr(agent, "_browser_gate_retry_budget", None)
    if not isinstance(state, dict):
        state = {}
        setattr(agent, "_browser_gate_retry_budget", state)
    used = int(state.get(key, 0))
    if used >= budget:
        return False
    state[key] = used + 1
    return True


def _retry_budget(
    decision: BrowserRecoveryDecision,
    product_policy: BrowserProductPolicy,
) -> int:
    if decision.action == BrowserRecoveryAction.RETRY_WITH_CONTEXT:
        return 1
    if decision.action == BrowserRecoveryAction.WAIT_FOR_APPROVAL:
        return 1
    if decision.reason == "fresh_observation_required":
        return 2
    if decision.reason in {"no_progress", "network_timeout"}:
        return product_policy.strategy_shift_budget
    return 0


def _retry_budget_key(
    evidence: BrowserRequestEvidence,
    decision: BrowserRecoveryDecision,
) -> str:
    event = evidence.trace_events[-1] if evidence.trace_events else None
    return "|".join(
        (
            evidence.request_scope_key,
            decision.action.value,
            decision.reason,
            decision.requested_context,
            decision.selected_context,
            _event_value(event, "action"),
            _event_value(event, "tab_id") or _event_value(event, "domain"),
        ),
    )


def _event_value(event: BrowserTraceEvent | None, key: str) -> str:
    if event is None:
        return ""
    return str(getattr(event, key, "") or "")


def _budget_exhausted(
    decision: BrowserRecoveryDecision,
) -> BrowserRecoveryDecision:
    return BrowserRecoveryDecision(
        action=BrowserRecoveryAction.BLOCKED,
        reason="retry_budget_exhausted",
        requested_context=decision.requested_context,
        selected_context=decision.selected_context,
        next_context=decision.next_context,
        required_next_step="stop_or_ask_user",
        forbidden=decision.forbidden,
        metadata=dict(decision.metadata),
    )


def _continuation_message(decision: BrowserRecoveryDecision) -> str:
    current_context = (
        decision.selected_context or decision.requested_context or "unknown"
    )
    return (
        "Browser recovery required:\n"
        f"recovery_action: {decision.action.value}\n"
        f"reason: {decision.reason}\n"
        f"current_context: {current_context}\n"
        f"next_context: {decision.next_context}\n"
        f"required_next_step: {decision.required_next_step}\n"
        f"forbidden: {', '.join(decision.forbidden)}"
    )


def _final_message(decision: BrowserRecoveryDecision) -> str:
    if decision.final_message:
        return decision.final_message
    current_context = (
        decision.selected_context or decision.requested_context or "unknown"
    )
    return (
        "Browser task blocked:\n"
        f"reason: {decision.reason}\n"
        f"context: {current_context}\n"
        f"backend: {decision.metadata.get('backend_id', 'unknown')}\n"
        f"required_user_action: {decision.required_next_step or 'none'}\n"
        f"status: {decision.action.value}"
    )


__all__ = [
    "BrowserGate",
    "BrowserLoopGateProvider",
    "register_browser_loop_gate_provider_once",
]
