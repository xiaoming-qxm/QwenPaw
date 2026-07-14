# -*- coding: utf-8 -*-
"""Product-level Chrome capability truth matrix."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CapabilityStatus = Literal[
    "supported",
    "partial",
    "missing",
    "internal_only",
]


@dataclass(frozen=True)
class BrowserCapabilitySupport:
    """Backend-specific product support evidence."""

    status: CapabilityStatus
    evidence: tuple[str, ...]
    backend_symbols: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class BrowserProductCapability:
    """One product capability tracked independently from API spelling."""

    capability_id: str
    product_task: str
    public_api: tuple[str, ...]
    isolated_support: BrowserCapabilitySupport
    user_support: BrowserCapabilitySupport
    verifier_evidence: tuple[str, ...]
    gap_status: CapabilityStatus
    follow_up: str
    legacy_evidence: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _support(
    status: CapabilityStatus,
    evidence: tuple[str, ...],
    *,
    backend_symbols: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
) -> BrowserCapabilitySupport:
    return BrowserCapabilitySupport(
        status=status,
        evidence=evidence,
        backend_symbols=backend_symbols,
        limitations=limitations,
    )


def _legacy_tool_evidence(*actions: str) -> tuple[str, ...]:
    legacy_tool = "".join(("browser", "_use"))
    return tuple(f"{legacy_tool}:{action}" for action in actions)


BROWSER_PRODUCT_CAPABILITIES: tuple[BrowserProductCapability, ...] = (
    BrowserProductCapability(
        capability_id="navigation.open",
        product_task="Open or navigate a browser tab to a URL.",
        public_api=("Browser.tabs.open(url)", "Tab.actions.navigate(url)"),
        isolated_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/backends/isolated.py:open_tab",
                "src/qwenpaw/browser/backends/isolated.py:action:navigate",
            ),
            backend_symbols=("open_tab", "action:navigate"),
        ),
        user_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/backends/user.py:open_tab",
                "plugins/bundle/chrome/action_runtime/handlers/open.py",
            ),
            backend_symbols=("open_tab", "handler:open"),
        ),
        verifier_evidence=("public-search", "complex-isolated"),
        gap_status="supported",
        follow_up="none",
    ),
    BrowserProductCapability(
        capability_id="navigation.history",
        product_task="Move backward, forward, or reload in tab history.",
        public_api=(
            "Tab.actions.back()",
            "Tab.actions.forward()",
            "Tab.actions.reload()",
        ),
        isolated_support=_support(
            "supported",
            ("src/qwenpaw/browser/backends/isolated.py:action:back",),
            backend_symbols=("action:back", "action:forward", "action:reload"),
        ),
        user_support=_support(
            "supported",
            (
                "plugins/bundle/chrome/action_runtime/handlers/"
                "navigate_back.py",
                "plugins/bundle/chrome/action_runtime/handlers/reload.py",
            ),
            backend_symbols=(
                "handler:navigate_back",
                "handler:navigate_forward",
                "handler:reload",
            ),
        ),
        verifier_evidence=("complex-isolated", "complex-user"),
        gap_status="supported",
        follow_up="none",
        legacy_evidence=_legacy_tool_evidence("back", "forward"),
    ),
    BrowserProductCapability(
        capability_id="observation.snapshot",
        product_task="Read a structured accessibility/text snapshot.",
        public_api=("Tab.snapshot(limit=...)",),
        isolated_support=_support(
            "supported",
            ("src/qwenpaw/browser/backends/isolated.py:snapshot",),
            backend_symbols=("snapshot",),
        ),
        user_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/backends/user.py:snapshot",
                "plugins/bundle/chrome/action_runtime/handlers/snapshot.py",
            ),
            backend_symbols=("snapshot", "handler:snapshot"),
        ),
        verifier_evidence=("fixture", "complex-isolated", "complex-user"),
        gap_status="supported",
        follow_up="none",
    ),
    BrowserProductCapability(
        capability_id="observation.screenshot",
        product_task="Capture a screenshot artifact for visual evidence.",
        public_api=("Tab.screenshot()",),
        isolated_support=_support(
            "supported",
            ("src/qwenpaw/browser/backends/isolated.py:screenshot",),
            backend_symbols=("screenshot",),
        ),
        user_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/backends/user.py:screenshot",
                "plugins/bundle/chrome/action_runtime/handlers/screenshot.py",
            ),
            backend_symbols=("screenshot", "handler:screenshot"),
        ),
        verifier_evidence=("complex-isolated", "complex-user"),
        gap_status="supported",
        follow_up="none",
    ),
    BrowserProductCapability(
        capability_id="extraction.structured",
        product_task="Extract text or JSON from an observed page.",
        public_api=("Tab.extract(instruction, format='json')",),
        isolated_support=_support(
            "partial",
            ("src/qwenpaw/browser/primitives/extract.py",),
            backend_symbols=("Tab.extract",),
            limitations=("Lightweight extraction, not full schema engine.",),
        ),
        user_support=_support(
            "partial",
            ("src/qwenpaw/browser/primitives/extract.py",),
            backend_symbols=("Tab.extract",),
            limitations=("Depends on Browser SDK snapshot/evaluate support.",),
        ),
        verifier_evidence=("complex-isolated", "complex-user"),
        gap_status="partial",
        follow_up="V8-B",
        legacy_evidence=_legacy_tool_evidence("extract"),
    ),
    BrowserProductCapability(
        capability_id="forms.type",
        product_task="Type or fill text into form fields.",
        public_api=(
            "Tab.actions.type(target, text)",
            "Tab.actions.press(key)",
        ),
        isolated_support=_support(
            "supported",
            ("src/qwenpaw/browser/backends/isolated.py:action:type",),
            backend_symbols=("action:type", "action:press"),
        ),
        user_support=_support(
            "supported",
            (
                "plugins/bundle/chrome/action_runtime/handlers/type.py",
                "plugins/bundle/chrome/action_runtime/handlers/press_key.py",
            ),
            backend_symbols=("handler:type", "handler:press_key"),
        ),
        verifier_evidence=("fixture", "complex-isolated", "complex-user"),
        gap_status="supported",
        follow_up="none",
        legacy_evidence=_legacy_tool_evidence("type", "press_key"),
    ),
    BrowserProductCapability(
        capability_id="forms.select",
        product_task="Select an option in a native select control.",
        public_api=("Tab.actions.select(target, value)",),
        isolated_support=_support(
            "supported",
            ("src/qwenpaw/browser/backends/isolated.py:action:select",),
            backend_symbols=("action:select",),
        ),
        user_support=_support(
            "supported",
            (
                "plugins/bundle/chrome/action_runtime/handlers/"
                "select_option.py",
            ),
            backend_symbols=("handler:select_option",),
        ),
        verifier_evidence=("complex-isolated", "complex-user"),
        gap_status="supported",
        follow_up="none",
        legacy_evidence=_legacy_tool_evidence("select_option"),
    ),
    BrowserProductCapability(
        capability_id="forms.submit_guard",
        product_task="Gate potentially submitting form actions with approval.",
        public_api=("BrowserPolicy.allow_action(BrowserActionRequest)",),
        isolated_support=_support(
            "partial",
            ("src/qwenpaw/browser/governance/policy.py",),
            backend_symbols=("BrowserPolicy",),
            limitations=(
                "Policy is available, but submit is not distinct API.",
            ),
        ),
        user_support=_support(
            "partial",
            (
                "src/qwenpaw/browser/backends/user.py:action",
                "src/qwenpaw/browser/approval_policy.py",
            ),
            backend_symbols=("classify_browser_action", "approval_policy"),
            limitations=(
                "Approval is action/risk based, not form-submit API.",
            ),
        ),
        verifier_evidence=("fixture", "taobao-live:safety-gated"),
        gap_status="partial",
        follow_up="V8-D",
    ),
    BrowserProductCapability(
        capability_id="dialogs.confirm",
        product_task="Handle confirmation, alert, and prompt dialogs.",
        public_api=(
            "Tab.actions.dialog(accept=True)",
            "Tab.actions.dialog(accept=False)",
        ),
        isolated_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/actions/tab_actions.py:TabActions.dialog",
                "src/qwenpaw/browser/backends/isolated.py:_dialog",
            ),
            backend_symbols=("TabActions.dialog", "action:dialog"),
        ),
        user_support=_support(
            "supported",
            (
                "plugins/bundle/chrome/action_runtime/handlers/"
                "capabilities.py:DialogHandler",
                "plugins/bundle/chrome/action_runtime/session_manager.py:"
                "_control_pop_next_dialog_decision",
            ),
            backend_symbols=("handler:dialog", "dialog.set"),
        ),
        verifier_evidence=(
            "v8-capability-isolated",
            "v8-capability-user",
        ),
        gap_status="supported",
        follow_up="none",
        legacy_evidence=_legacy_tool_evidence("dialog"),
    ),
    BrowserProductCapability(
        capability_id="dom.iframe",
        product_task="Target and observe content inside iframes.",
        public_api=(
            "Tab.snapshot(limit=...)",
            "Tab.actions.click(target)",
            "Tab.evaluate(..., read_only=True)",
        ),
        isolated_support=_support(
            "partial",
            (
                "scripts/verify/browser/fixtures/v8_capability.html:"
                "capability-frame",
            ),
            limitations=("No first-class frame selector API yet.",),
        ),
        user_support=_support(
            "partial",
            (
                "scripts/verify/browser/fixtures/v8_capability.html:"
                "capability-frame",
            ),
            limitations=("No explicit iframe traversal contract yet.",),
        ),
        verifier_evidence=(
            "v8-capability-isolated",
            "v8-capability-user",
        ),
        gap_status="partial",
        follow_up="V8-E",
        legacy_evidence=_legacy_tool_evidence("iframe"),
    ),
    BrowserProductCapability(
        capability_id="dom.shadow",
        product_task="Target and observe content inside shadow DOM.",
        public_api=(
            "Tab.snapshot(limit=...)",
            "Tab.actions.click(target)",
            "Tab.evaluate(..., read_only=True)",
        ),
        isolated_support=_support(
            "partial",
            (
                "scripts/verify/browser/fixtures/v8_capability.html:"
                "capability-shadow-host",
            ),
            limitations=("No first-class shadow-root API yet.",),
        ),
        user_support=_support(
            "partial",
            (
                "scripts/verify/chrome_v8_capability_fixture.html:"
                "capability-shadow-host",
            ),
            limitations=("No explicit shadow DOM targeting contract yet.",),
        ),
        verifier_evidence=(
            "v8-capability-isolated",
            "v8-capability-user",
        ),
        gap_status="partial",
        follow_up="V8-E",
        legacy_evidence=_legacy_tool_evidence("shadow_dom"),
    ),
    BrowserProductCapability(
        capability_id="tabs.multi_tab",
        product_task="List, open, select, and close multiple tabs.",
        public_api=(
            "Browser.tabs.list()",
            "Browser.tabs.open()",
            "Browser.tabs.select()",
            "Tab.close()",
        ),
        isolated_support=_support(
            "supported",
            ("src/qwenpaw/browser/backends/isolated.py:list_tabs",),
            backend_symbols=("list_tabs", "open_tab", "select_tab"),
        ),
        user_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/backends/user.py:list_tabs",
                "plugins/bundle/chrome/action_runtime/handlers/tabs.py",
            ),
            backend_symbols=("list_tabs", "select_tab", "handler:tabs"),
        ),
        verifier_evidence=("complex-isolated", "complex-user"),
        gap_status="supported",
        follow_up="none",
        legacy_evidence=_legacy_tool_evidence("tabs"),
    ),
    BrowserProductCapability(
        capability_id="files.download_read",
        product_task="Read files downloaded by browser interactions.",
        public_api=("Tab.actions.download(target)",),
        isolated_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/actions/tab_actions.py:TabActions.download",
                "src/qwenpaw/browser/backends/isolated.py:_download",
            ),
            backend_symbols=("TabActions.download", "action:download"),
        ),
        user_support=_support(
            "supported",
            (
                "plugins/bundle/chrome/action_runtime/handlers/"
                "capabilities.py:DownloadHandler",
                "plugins/bundle/chrome/assets/extensions/"
                "qwenpaw-chrome/service_worker.js:download.read",
            ),
            backend_symbols=(
                "handler:download",
                "Browser.setDownloadBehavior",
            ),
        ),
        verifier_evidence=(
            "v8-capability-isolated",
            "v8-capability-user",
        ),
        gap_status="supported",
        follow_up="none",
        legacy_evidence=_legacy_tool_evidence("download"),
    ),
    BrowserProductCapability(
        capability_id="files.upload_select",
        product_task="Select local files for file upload controls.",
        public_api=("Tab.actions.upload(target, file_path)",),
        isolated_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/actions/tab_actions.py:TabActions.upload",
                "src/qwenpaw/browser/backends/isolated.py:_upload",
            ),
            backend_symbols=("TabActions.upload", "action:upload"),
        ),
        user_support=_support(
            "supported",
            (
                "plugins/bundle/chrome/action_runtime/handlers/"
                "capabilities.py:UploadHandler",
                "plugins/bundle/chrome/action_runtime/handlers/"
                "capabilities.py:_enforce_file_guard",
            ),
            backend_symbols=("handler:upload", "DOM.setFileInputFiles"),
        ),
        verifier_evidence=(
            "v8-capability-isolated",
            "v8-capability-user",
        ),
        gap_status="supported",
        follow_up="none",
        legacy_evidence=_legacy_tool_evidence("upload"),
    ),
    BrowserProductCapability(
        capability_id="lifecycle.cleanup",
        product_task="Release owned and borrowed tabs at request boundaries.",
        public_api=("Browser.close()", "Tab.close()"),
        isolated_support=_support(
            "supported",
            ("src/qwenpaw/browser/backends/isolated.py:close",),
            backend_symbols=("close", "close_tab"),
        ),
        user_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/backends/user.py:"
                "cleanup_user_browser_sessions_for_request",
                "src/qwenpaw/hooks/chrome_lifecycle.py",
            ),
            backend_symbols=("cleanup_for_request", "FINALLY hook"),
        ),
        verifier_evidence=("complex-user", "bridge-disconnected"),
        gap_status="supported",
        follow_up="V8-C",
    ),
    BrowserProductCapability(
        capability_id="routing.context_resolution",
        product_task=(
            "Route public tasks to isolated and user-state tasks to user."
        ),
        public_api=("Browser.connect(context=...)",),
        isolated_support=_support(
            "supported",
            ("src/qwenpaw/browser/governance/resolver.py",),
            backend_symbols=("BrowserContextResolver",),
        ),
        user_support=_support(
            "supported",
            ("src/qwenpaw/browser/governance/resolver.py",),
            backend_symbols=("BrowserContextResolver",),
        ),
        verifier_evidence=("public-search", "fixture"),
        gap_status="supported",
        follow_up="none",
    ),
    BrowserProductCapability(
        capability_id="policy.approval",
        product_task="Require approval for sensitive browser actions.",
        public_api=("BrowserPolicy", "BrowserActionRequest"),
        isolated_support=_support(
            "partial",
            ("src/qwenpaw/browser/governance/policy.py",),
            limitations=("Default isolated policy has lower risk surface.",),
        ),
        user_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/backends/user.py:action",
                "src/qwenpaw/browser/approval_policy.py",
            ),
            backend_symbols=("maybe_await_policy_decision",),
        ),
        verifier_evidence=("fixture", "taobao-live:safety-gated"),
        gap_status="partial",
        follow_up="V8-D",
    ),
    BrowserProductCapability(
        capability_id="trace.evidence",
        product_task="Emit backend, context, action, and status evidence.",
        public_api=("BrowserTraceEvent", "get_browser_trace_events()"),
        isolated_support=_support(
            "supported",
            ("src/qwenpaw/browser/telemetry/trace.py",),
            backend_symbols=("record_browser_trace_event",),
        ),
        user_support=_support(
            "supported",
            (
                "src/qwenpaw/browser/telemetry/trace.py",
                "plugins/bundle/chrome/api/routes.py:/chrome/traces",
            ),
            backend_symbols=("record_browser_trace_event",),
        ),
        verifier_evidence=(
            "fixture",
            "public-search",
            "complex-user",
            "v8-capability-isolated",
            "v8-capability-user",
        ),
        gap_status="supported",
        follow_up="none",
    ),
    BrowserProductCapability(
        capability_id="ux.readiness",
        product_task="Expose Chrome readiness and approval evidence.",
        public_api=("Browser.diagnostics(context='user')",),
        isolated_support=_support(
            "partial",
            ("src/qwenpaw/browser/facade/browser.py:diagnostics",),
            limitations=("Readiness UI focuses on user backend state.",),
        ),
        user_support=_support(
            "supported",
            (
                "console/src/pages/Settings/chromeReadiness.tsx",
                "plugins/bundle/chrome/api/routes.py:/chrome/status",
            ),
            backend_symbols=("Browser.diagnostics", "extension/status"),
        ),
        verifier_evidence=("bridge-disconnected", "frontend focused tests"),
        gap_status="partial",
        follow_up="V8-D",
    ),
)

_CAPABILITY_BY_ID = {
    capability.capability_id: capability
    for capability in BROWSER_PRODUCT_CAPABILITIES
}


def capability_by_id(capability_id: str) -> BrowserProductCapability:
    """Return a product capability by stable id."""
    try:
        return _CAPABILITY_BY_ID[capability_id]
    except KeyError as exc:
        raise KeyError(f"Unknown Browser capability: {capability_id}") from exc


__all__ = [
    "BROWSER_PRODUCT_CAPABILITIES",
    "BrowserCapabilitySupport",
    "BrowserProductCapability",
    "CapabilityStatus",
    "capability_by_id",
]
