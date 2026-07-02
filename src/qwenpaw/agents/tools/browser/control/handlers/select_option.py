# -*- coding: utf-8 -*-
"""Select option Browser Control action handler."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..errors import BrowserControlRecoverableError, TargetResolutionFailed
from ..navigation import _control_tab_id
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
        except (BrowserControlRecoverableError, ValueError, TypeError) as exc:
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
    target = state.refs.get(str(tab_id), {}).get(ref, {}) if ref else {}
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
