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
    collect_browser_request_evidence,
)
from ..telemetry.trace import BrowserTraceStore


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
                action=StopAction.TERMINATE,
                reason=decision.reason,
                final_message=_final_message(decision),
            )
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
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
