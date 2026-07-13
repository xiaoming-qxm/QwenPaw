# -*- coding: utf-8 -*-
"""Controlled target paste without ambient clipboard access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.sdk.governance.errors import BrowserSDKError

from ..interactions import canonical_paste_control
from ..state import ControlState
from ..targets import _control_node_params
from .capabilities import _tab_session
from .protocol import ActionMeta


_PASTE_FUNCTION = """
function(content) {
  this.dispatchEvent(new InputEvent('beforeinput', {
    bubbles: true, inputType: 'insertText', data: content
  }));
  this.value = content;
  const cursor = content.length;
  if (typeof this.setSelectionRange === 'function') {
    this.setSelectionRange(cursor, cursor);
  }
  this.dispatchEvent(new InputEvent('input', {
    bubbles: true, inputType: 'insertText', data: content
  }));
  this.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}
""".strip()


@dataclass(frozen=True)
class PasteHandler:
    """Insert only bounded caller content into one prepared target."""

    meta: ActionMeta = ActionMeta(True, True, True)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        content = kwargs.get("_canonical_paste_content")
        if (
            not isinstance(content, str)
            or not content
            or len(content) > 100_000
        ):
            raise BrowserSDKError(
                "Canonical paste content is invalid",
                code="paste_content_invalid",
            )
        _, session = await _tab_session(
            state,
            holder_id=holder_id,
            bridge=bridge,
            kwargs=kwargs,
        )

        async def inject(prepared, arguments):
            del arguments
            if len(prepared) != 1:
                raise BrowserSDKError(
                    "Canonical paste target is invalid",
                    code="target_binding_invalid",
                )
            raw_identity = prepared[0].get("native_identity")
            if not isinstance(raw_identity, tuple):
                raise BrowserSDKError(
                    "Canonical paste target identity is invalid",
                    code="target_binding_invalid",
                )
            identity = {str(key): value for key, value in raw_identity}
            node_params = _control_node_params(identity)
            if node_params is None and len(identity) == 1:
                native_value = next(iter(identity.values()))
                if isinstance(native_value, int):
                    node_params = {"backendNodeId": native_value}
            if node_params is None:
                raise BrowserSDKError(
                    "Canonical paste target identity is invalid",
                    code="target_binding_invalid",
                )
            resolved = await session.send("DOM.resolveNode", node_params)
            remote = (
                resolved.get("object") if isinstance(resolved, dict) else {}
            )
            object_id = (
                remote.get("objectId") if isinstance(remote, dict) else ""
            )
            if not object_id:
                raise BrowserSDKError(
                    "Canonical paste target is unavailable",
                    code="target_unavailable",
                )
            return await session.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": object_id,
                    "functionDeclaration": _PASTE_FUNCTION,
                    "arguments": [{"value": content}],
                    "returnByValue": True,
                    "awaitPromise": False,
                },
            )

        return await canonical_paste_control(
            state,
            kwargs=kwargs,
            injector=inject,
        )


PASTE_HANDLER = PasteHandler()

__all__ = ["PASTE_HANDLER", "PasteHandler"]
