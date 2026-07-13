# -*- coding: utf-8 -*-
"""Select option Browser Bridge action handler."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.sdk.canonical.contracts import (
    Coverage,
    OptionChoice,
    OptionSummary,
)
from qwenpaw.browser.sdk.governance.errors import BrowserSDKError
from qwenpaw.browser.sdk.primitives.matching import normalize_visible_text
from ..errors import BrowserBridgeRecoverableError, TargetResolutionFailed
from ..interactions import (
    _canonical_runner_request,
    canonical_interaction_control,
)
from ..navigation import _control_tab_id
from ..ref_scope import _control_current_snapshot_ref
from ..session_manager import _control_get_session
from ..state import ControlState
from ..tab_manager import _control_ensure_tab_available, _control_page_id
from ..targets import _control_node_params, _control_selector_target
from .navigate import _json_response
from .protocol import ActionMeta

_SELECT_FUNCTION = (
    "function(value) { "
    "this.value = String(value); "
    'this.dispatchEvent(new Event("input", { bubbles: true })); '
    'this.dispatchEvent(new Event("change", { bubbles: true })); '
    "return this.value; "
    "}"
)


@dataclass(frozen=True)
class SelectOptionHandler:
    meta: ActionMeta = ActionMeta(True, True, True)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        try:
            request_context = kwargs.get("request_context") or {}
            if _canonical_runner_request(request_context):
                observed = kwargs.get("_canonical_options")
                current = kwargs.get("_canonical_current_options")
                choice = kwargs.get("option")
                if (
                    not isinstance(observed, tuple)
                    or not isinstance(current, tuple)
                    or not isinstance(choice, OptionChoice)
                ):
                    raise BrowserSDKError(
                        "Canonical complete option evidence is unavailable",
                        code="option_evidence_incomplete",
                    )

                async def inject(option: OptionSummary) -> None:
                    canonical_kwargs = {
                        **kwargs,
                        "selected_value": option.value,
                    }
                    await canonical_interaction_control(
                        state,
                        action="select_option",
                        target_labels=("target",),
                        kwargs=canonical_kwargs,
                    )

                await _dispatch_canonical_option(
                    observed=observed,
                    current=current,
                    coverage=str(
                        kwargs.get("_canonical_options_coverage") or "",
                    ),
                    choice=choice,
                    receiver_matches=bool(
                        kwargs.get("_canonical_receiver_matches"),
                    ),
                    select_enabled=bool(
                        kwargs.get("_canonical_select_enabled"),
                    ),
                    injector=inject,
                )
                return _json_response(
                    {
                        "ok": True,
                        "action": "select_option",
                        "raw_change_hint": True,
                        "condition_truth": "NOT_EVALUATED",
                    },
                )
            value = _select_value(kwargs)
            tab_id = _control_tab_id(
                _control_page_id(state, str(kwargs.get("page_id", ""))),
                kwargs.get("index", -1),
            )
            await _control_ensure_tab_available(bridge, tab_id)
            session = await _control_get_session(
                state,
                tab_id=tab_id,
                holder_id=holder_id,
                bridge=bridge,
                request_context=kwargs.get("request_context") or {},
            )
            node_params = await _select_node_params(
                state,
                session,
                tab_id,
                kwargs,
            )
            resolved = await session.send("DOM.resolveNode", node_params)
            remote_object = (
                resolved.get("object") if isinstance(resolved, dict) else {}
            )
            object_id = (
                remote_object.get("objectId")
                if isinstance(remote_object, dict)
                else ""
            )
            if not object_id:
                raise TargetResolutionFailed(
                    "Unable to resolve select element",
                )
            await session.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "functionDeclaration": _SELECT_FUNCTION,
                    "arguments": [{"value": value}],
                    "returnByValue": True,
                    "awaitPromise": False,
                },
            )
            return _json_response(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "selected": True,
                    "value": value,
                },
            )
        except (BrowserBridgeRecoverableError, ValueError, TypeError) as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


def _select_value(kwargs: dict[str, Any]) -> str:
    values_json = str(kwargs.get("values_json") or "").strip()
    if values_json:
        parsed = json.loads(values_json)
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else ""
        if parsed not in (None, ""):
            return str(parsed)
    value = kwargs.get("value", kwargs.get("text", ""))
    value = str(value or "").strip()
    if not value:
        raise ValueError("value required for select_option")
    return value


async def _select_node_params(
    state: ControlState,
    session: Any,
    tab_id: int,
    kwargs: dict[str, Any],
) -> dict[str, int]:
    ref = str(kwargs.get("ref") or "")
    selector = str(kwargs.get("selector") or "").strip()
    resolved_ref = _control_current_snapshot_ref(state, tab_id, ref)
    target = (
        state.refs.get(str(tab_id), {}).get(resolved_ref, {}) if ref else {}
    )
    if not target and selector:
        target = await _control_selector_target(session, selector)
    node_params = _control_node_params(target)
    if node_params is None:
        raise TargetResolutionFailed(
            "ref or selector required for select_option",
        )
    return node_params


SELECT_OPTION_HANDLER = SelectOptionHandler()
__all__ = ["SELECT_OPTION_HANDLER", "SelectOptionHandler"]


def _match_canonical_option(
    options: tuple[OptionSummary, ...],
    *,
    coverage: Coverage | str,
    choice: OptionChoice,
) -> OptionSummary:
    """Require one enabled match from a complete observed collection."""
    if coverage != "COMPLETE":
        raise BrowserSDKError(
            "Option collection is not complete",
            code="option_evidence_incomplete",
        )
    if not isinstance(choice, OptionChoice) or not all(
        isinstance(option, OptionSummary) for option in options
    ):
        raise BrowserSDKError(
            "Option evidence is invalid",
            code="option_evidence_invalid",
        )
    expected = (
        normalize_visible_text(choice.value)
        if choice.by == "label"
        else choice.value
    )
    matches = tuple(
        option
        for option in options
        if (
            normalize_visible_text(option.label)
            if choice.by == "label"
            else option.value
        )
        == expected
    )
    if len(matches) != 1:
        raise BrowserSDKError(
            "OptionChoice must match exactly one observed option",
            code="option_not_unique",
        )
    if not matches[0].enabled:
        raise BrowserSDKError(
            "Selected option is disabled",
            code="option_disabled",
        )
    return matches[0]


async def _dispatch_canonical_option(
    *,
    observed: tuple[OptionSummary, ...],
    current: tuple[OptionSummary, ...],
    coverage: Coverage | str,
    choice: OptionChoice,
    receiver_matches: bool,
    select_enabled: bool,
    injector: Callable[[OptionSummary], Awaitable[object]],
) -> str:
    """Final collection revalidation followed by one immediate injection."""
    observed_match = _match_canonical_option(
        observed,
        coverage=coverage,
        choice=choice,
    )
    if not receiver_matches or not select_enabled or observed != current:
        raise BrowserSDKError(
            "Select receiver or option collection changed before dispatch",
            code="option_collection_stale",
        )
    current_match = _match_canonical_option(
        current,
        coverage=coverage,
        choice=choice,
    )
    if current_match != observed_match:
        raise BrowserSDKError(
            "Selected option changed before dispatch",
            code="option_collection_stale",
        )
    await injector(current_match)
    return "INJECTED"
