# -*- coding: utf-8 -*-
"""Select option Browser Bridge action handler."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.canonical.contracts import (
    Coverage,
    OptionChoice,
    OptionSummary,
)
from qwenpaw.browser.governance.errors import BrowserSDKError
from qwenpaw.browser.primitives.matching import normalize_visible_text
from ..errors import BrowserBridgeRecoverableError
from ..interactions import canonical_interaction_control
from ..state import ControlState
from .navigate import _json_response
from .protocol import ActionMeta


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
        del holder_id, bridge
        try:
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
        except (BrowserBridgeRecoverableError, ValueError, TypeError) as exc:
            return _json_response(
                {"ok": False, "mode": "control", "error": str(exc)},
            )


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
