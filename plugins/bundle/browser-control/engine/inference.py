# -*- coding: utf-8 -*-
"""Browser Control mode inference and claim helpers."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .navigation import _control_remember_approved_navigation
from .state import StateMapping
from .tab_manager import (
    _control_close_other_owned_tabs,
    _control_matching_control_or_browser_tab,
)


def _control_holder_has_claimed_tab(
    state: StateMapping,
    holder_id: str,
) -> bool:
    control_tabs = state.get("control_tabs") or {}
    if not isinstance(control_tabs, dict):
        return False
    return any(
        isinstance(tab, dict) and str(tab.get("holder_id") or "") == holder_id
        for tab in control_tabs.values()
    )


def _control_should_infer_user_initiated(
    *,
    state: StateMapping,
    action: str,
    url: str,
    holder_id: str,
    request_context: dict[str, Any],
    user_initiated: bool,
) -> bool:
    if user_initiated:
        return True
    if action not in {"claim_tab", "open"} or not url:
        return False
    if not request_context.get("browser_control_invocation"):
        return False
    return not _control_holder_has_claimed_tab(state, holder_id)


def _control_jsonrpc_result(response: Any) -> Any:
    if isinstance(response, dict) and response.get("jsonrpc") == "2.0":
        return response.get("result", {})
    return response


def _control_jsonrpc_error(response: Any) -> str | None:
    if not isinstance(response, dict) or "error" not in response:
        return None
    error = response["error"]
    if isinstance(error, dict):
        return str(error.get("message") or "JSON-RPC error")
    return str(error)


def _control_created_tab_id(response: Any) -> int:
    error = _control_jsonrpc_error(response)
    if error:
        raise ValueError(error)
    result = _control_jsonrpc_result(response)
    if isinstance(result, dict):
        value = result.get("id") or result.get("tabId")
    else:
        value = None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError("tab.create did not return a tab id")


def _control_claim_success_payload(
    tab_id: int,
    tab_url: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "mode": "control",
        "tab_id": tab_id,
        "ready_for_observation": True,
        "next_action": "snapshot",
        "next_instruction": (
            "The tab is already opened and claimed. Do not repeat "
            "claim_tab/open for the same URL; observe it with snapshot next."
        ),
    }
    if tab_url:
        payload["url"] = tab_url
    return payload


async def _control_request_domain_approval(
    request_context: dict[str, Any],
    request: dict[str, Any],
) -> bool:
    session_id = str(request_context.get("session_id") or "")
    if not session_id:
        return False

    from qwenpaw.app.approvals import get_approval_service
    from qwenpaw.app.approvals.models import ApprovalRequestSummary
    from qwenpaw.constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    svc = get_approval_service()
    pending = await svc.create_pending_summary(
        session_id=session_id,
        root_session_id=str(
            request_context.get("root_session_id") or session_id,
        ),
        owner_agent_id=str(request_context.get("root_agent_id") or ""),
        user_id=str(request_context.get("user_id") or ""),
        channel=str(request_context.get("channel") or ""),
        agent_id=str(request_context.get("agent_id") or "unknown"),
        summary=ApprovalRequestSummary(
            source_type="browser_sdk_cdp",
            name="browser",
            severity="medium",
            findings_count=1,
            result_summary=(
                "Chrome browser control wants to open a new tab on domain "
                f"{request['domain']}."
            ),
            payload=request,
        ),
        timeout_seconds=TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
        extra={
            "tool_call": {
                "id": str(request_context.get("tool_call_id") or ""),
                "name": "browser",
                "input": request,
            },
        },
    )
    decision = await svc.wait_for_approval(
        pending.request_id,
        TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
    )
    return decision == ApprovalDecision.APPROVED


async def _control_tab_create_denial_reason(
    url: str,
    request_context: dict[str, Any],
    *,
    user_initiated: bool = False,
) -> str | None:
    from qwenpaw.agents.tools.cdp_permissions import (
        check_permission,
        load_permissions,
    )

    permissions = load_permissions()
    result = check_permission("Page.navigate", url, permissions)
    if result.decision == "allow":
        return None
    if result.decision == "ask_new_domain" and user_initiated:
        return None

    domain = result.domain or (urlparse(url).hostname or "").lower() or url
    if result.decision == "deny":
        return f"Domain '{domain}' denied by browser-permissions policy"

    request = {
        "policy": result.decision,
        "method": "Page.navigate",
        "url": url,
        "domain": domain,
    }
    if await _control_request_domain_approval(request_context, request):
        if result.domain:
            permissions.approved_domains.add(result.domain)
        return None

    return f"Domain '{domain}' not approved by user"


async def _control_select_or_create_url_tab(
    state: StateMapping,
    bridge: Any,
    url: str,
    request_context: dict[str, Any],
    holder_id: str,
    *,
    user_initiated: bool = False,
) -> tuple[int | None, str, str | None, bool]:
    existing = await _control_matching_control_or_browser_tab(
        state,
        bridge,
        url,
        holder_id,
    )
    if existing is not None:
        tab_id, discovered_tab_url = existing
        if user_initiated:
            _control_remember_approved_navigation(state, url)
        return tab_id, discovered_tab_url, None, False

    denial_reason = await _control_tab_create_denial_reason(
        url,
        request_context,
        user_initiated=user_initiated,
    )
    if denial_reason:
        return None, "", denial_reason, False

    _control_remember_approved_navigation(state, url)
    response = await bridge.request(
        "tab.create",
        {"url": url, "active": False},
    )
    tab_id = _control_created_tab_id(response)
    await _control_close_other_owned_tabs(
        state,
        bridge=bridge,
        keep_tab_id=tab_id,
        holder_id=holder_id,
    )
    return tab_id, "", None, True


__all__ = [
    "_control_claim_success_payload",
    "_control_created_tab_id",
    "_control_holder_has_claimed_tab",
    "_control_jsonrpc_error",
    "_control_jsonrpc_result",
    "_control_request_domain_approval",
    "_control_select_or_create_url_tab",
    "_control_should_infer_user_initiated",
    "_control_tab_create_denial_reason",
]
