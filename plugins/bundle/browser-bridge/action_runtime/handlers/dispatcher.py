# -*- coding: utf-8 -*-
"""Dispatcher for typed Browser Bridge action handlers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from agentscope.tool import ToolChunk

from qwenpaw.browser.sdk.runtime.responses import _tool_response
from qwenpaw.browser.sdk.governance.errors import BrowserSDKError
from ..navigation import _control_tab_id
from ..observation import (
    _control_mark_observation_required,
    _control_require_observation_before_action,
)
from ..state import ControlState
from ..tab_manager import _control_int_tab_id, _control_page_id
from ..transitions import _control_consume_pending_action_transition
from .misc import unsupported_control_action_response
from .protocol import (
    ActionHandler,
    TrustedCommandEnvelope,
    is_trusted_command_envelope,
)

_REGISTRY: dict[str, ActionHandler] = {}

_ENVELOPE_FREE_CANONICAL_ACTIONS = {
    "start",
    "tabs",
    "claim_tab",
    "release_tab",
    "snapshot",
    "screenshot",
    "wait_for",
    "stop",
}

_TRANSITION_OBSERVATION_ACTIONS = {
    "snapshot",
    "screenshot",
    "click",
    "type",
    "press_key",
    "wait_for",
}


@dataclass(frozen=True)
class _TrustedHandlerGuard:
    """Prevent Canonical callers from bypassing the dispatcher gate."""

    action: str
    handler: ActionHandler

    @property
    def meta(self):
        return self.handler.meta

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ) -> ToolChunk:
        request_context = kwargs.get("request_context") or {}
        if str(request_context.get("contract_mode") or "").upper() != (
            "CANONICAL"
        ):
            raise BrowserSDKError(
                "Handler calls require a Canonical request context",
                code="canonical_dispatch_context_missing",
            )
        envelope = kwargs.get("trusted_envelope")
        if (
            self.action not in _ENVELOPE_FREE_CANONICAL_ACTIONS
            and not is_trusted_command_envelope(envelope)
        ):
            raise BrowserSDKError(
                "Direct Canonical handler call lacks a trusted envelope",
                code="trusted_command_envelope_missing",
            )
        if is_trusted_command_envelope(envelope):
            trusted = cast(TrustedCommandEnvelope, envelope)
            if (
                trusted.action != self.action
                or trusted.dispatch_context.command_kind == "STATUS_QUERY"
            ):
                raise BrowserSDKError(
                    "Trusted envelope cannot execute this mutation handler",
                    code="trusted_command_envelope_mismatch",
                )
        return await self.handler.execute(
            state,
            holder_id=holder_id,
            bridge=bridge,
            **kwargs,
        )


def register_handler(name: str, handler: ActionHandler) -> None:
    """Register a typed action handler by action name."""
    action = str(name or "").strip().lower()
    _REGISTRY[action] = _TrustedHandlerGuard(action, handler)


def _bridge_unavailable_response() -> ToolChunk:
    return _tool_response(
        json.dumps(
            {
                "ok": False,
                "mode": "control",
                "error": "Chrome extension bridge is not connected",
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def _tab_id_from_kwargs(kwargs: dict[str, Any]) -> int | None:
    value = kwargs.get("tab_id", kwargs.get("page_id"))
    tab_id = _control_int_tab_id(value)
    if tab_id is not None:
        return tab_id
    page_id = str(kwargs.get("page_id") or "")
    if page_id.startswith("tab_"):
        return _control_int_tab_id(page_id[4:])
    index = kwargs.get("index")
    return _control_int_tab_id(index)


def _resolved_tab_id(
    state: ControlState,
    kwargs: dict[str, Any],
) -> int | None:
    try:
        return _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
    except (RuntimeError, ValueError, TypeError):
        return _tab_id_from_kwargs(kwargs)


def _response_ok(response: ToolChunk) -> bool:
    try:
        text = getattr(response.content[0], "text", "")
        return json.loads(text).get("ok") is True
    except (
        AttributeError,
        IndexError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ):
        return False


async def dispatch(
    state: ControlState,
    action: str,
    *,
    holder_id: str,
    bridge: Any,
    **kwargs: Any,
) -> ToolChunk:
    """Dispatch a Browser Bridge action through typed handlers."""
    action_name = str(action or "").strip().lower()
    handler = _REGISTRY.get(action_name)
    if handler is None:
        return unsupported_control_action_response(action_name)

    request_context = kwargs.get("request_context") or {}
    envelope = kwargs.get("trusted_envelope")
    if str(request_context.get("contract_mode") or "").upper() != (
        "CANONICAL"
    ):
        raise BrowserSDKError(
            "Bridge dispatch requires a Canonical request context",
            code="canonical_dispatch_context_missing",
        )
    if (
        action_name not in _ENVELOPE_FREE_CANONICAL_ACTIONS
        and not is_trusted_command_envelope(envelope)
    ):
        raise BrowserSDKError(
            "Canonical handler requires a trusted command envelope",
            code="trusted_command_envelope_missing",
        )
    if is_trusted_command_envelope(envelope):
        envelope = cast(TrustedCommandEnvelope, envelope)
        context = envelope.dispatch_context
        if envelope.action != action_name:
            raise BrowserSDKError(
                "trusted envelope action does not match handler",
                code="trusted_command_envelope_mismatch",
            )
        if context.command_kind == "STATUS_QUERY":
            raise BrowserSDKError(
                "status query cannot enter a mutation handler",
                code="status_query_mutation_forbidden",
            )
        kwargs["request_context"] = {
            **request_context,
            "contract_mode": "CANONICAL",
            "canonical_dispatch_context": context,
        }

    if handler.meta.requires_tab_claimed and (
        bridge is None or not bool(getattr(bridge, "connected", False))
    ):
        return _bridge_unavailable_response()

    if action_name in _TRANSITION_OBSERVATION_ACTIONS:
        pending_payload = await _control_consume_pending_action_transition(
            state,
            bridge=bridge,
            holder_id=holder_id,
            request_context=kwargs.get("request_context") or {},
        )
        if pending_payload is not None:
            return _tool_response(
                json.dumps(pending_payload, ensure_ascii=False, indent=2),
            )

    tab_id = _resolved_tab_id(state, kwargs)
    if handler.meta.requires_observation and tab_id is not None:
        pending_response = _control_require_observation_before_action(
            state,
            action=action_name,
            tab_id=tab_id,
        )
        if pending_response is not None:
            return pending_response

    response = await handler.execute(
        state,
        holder_id=holder_id,
        bridge=bridge,
        **kwargs,
    )
    if (
        handler.meta.invalidates_snapshot
        and tab_id is not None
        and _response_ok(response)
    ):
        _control_mark_observation_required(state, tab_id, action=action_name)
    return response


__all__ = ["_REGISTRY", "dispatch", "register_handler"]
