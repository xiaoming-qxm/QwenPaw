# -*- coding: utf-8 -*-
"""Shared Browser SDK runtime outcome taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class BrowserOutcome(StrEnum):
    """High-level outcome categories for browser runtime reports."""

    PASS = "pass"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    IN_PROGRESS = "in_progress"


class BrowserErrorCode(StrEnum):
    """Stable machine-readable Browser Bridge error codes."""

    NONE = "none"
    UNKNOWN = "unknown"
    BRIDGE_DISCONNECTED = "bridge_disconnected"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_DENIED = "approval_denied"
    LOGIN_REQUIRED = "login_required"
    CAPTCHA_OR_RISK_CONTROL = "captcha_or_risk_control"
    CANCELLED = "cancelled"
    NETWORK_TIMEOUT = "network_timeout"
    BRIDGE_REQUEST_TIMEOUT = "bridge_request_timeout"
    CDP_COMMAND_TIMEOUT = "cdp_command_timeout"
    DOM_SETTLE_TIMEOUT = "dom_settle_timeout"
    NETWORK_SETTLE_TIMEOUT = "network_settle_timeout"
    DOWNLOAD_TIMEOUT = "download_timeout"
    UPLOAD_TIMEOUT = "upload_timeout"
    OBSERVATION_STALE = "observation_stale"
    OBSERVATION_ENRICHMENT_DENIED = "observation_enrichment_denied"
    INVALID_SDK_USAGE = "invalid_sdk_usage"
    CLICK_WITHOUT_NAVIGATION = "click_without_navigation"
    CAPABILITY_MISSING = "capability_missing"


@dataclass(frozen=True)
class BrowserErrorInfo:
    """Structured browser runtime outcome and recovery guidance."""

    code: BrowserErrorCode
    outcome: BrowserOutcome
    recovery_hint: str

    @property
    def blocked_reason(self) -> str:
        return (
            self.code.value if self.outcome == BrowserOutcome.BLOCKED else ""
        )

    @property
    def failure_reason(self) -> str:
        return self.code.value if self.outcome == BrowserOutcome.FAILED else ""

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe taxonomy metadata."""
        return {
            "code": self.code.value,
            "outcome": self.outcome.value,
            "recovery_hint": self.recovery_hint,
            "blocked_reason": self.blocked_reason,
            "failure_reason": self.failure_reason,
        }


_ERROR_INFO: dict[BrowserErrorCode, BrowserErrorInfo] = {
    BrowserErrorCode.NONE: BrowserErrorInfo(
        code=BrowserErrorCode.NONE,
        outcome=BrowserOutcome.PASS,
        recovery_hint="Browser operation completed.",
    ),
    BrowserErrorCode.UNKNOWN: BrowserErrorInfo(
        code=BrowserErrorCode.UNKNOWN,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Inspect browser diagnostics and retry only after the runtime "
            "cause is clear."
        ),
    ),
    BrowserErrorCode.BRIDGE_DISCONNECTED: BrowserErrorInfo(
        code=BrowserErrorCode.BRIDGE_DISCONNECTED,
        outcome=BrowserOutcome.BLOCKED,
        recovery_hint=(
            "Reconnect the Chrome extension bridge, then run diagnostics "
            "before retrying."
        ),
    ),
    BrowserErrorCode.APPROVAL_REQUIRED: BrowserErrorInfo(
        code=BrowserErrorCode.APPROVAL_REQUIRED,
        outcome=BrowserOutcome.BLOCKED,
        recovery_hint=(
            "Wait for an explicit user approval decision before continuing "
            "the browser action."
        ),
    ),
    BrowserErrorCode.APPROVAL_DENIED: BrowserErrorInfo(
        code=BrowserErrorCode.APPROVAL_DENIED,
        outcome=BrowserOutcome.BLOCKED,
        recovery_hint=(
            "Stop this browser action because the user denied approval."
        ),
    ),
    BrowserErrorCode.LOGIN_REQUIRED: BrowserErrorInfo(
        code=BrowserErrorCode.LOGIN_REQUIRED,
        outcome=BrowserOutcome.BLOCKED,
        recovery_hint=(
            "Ask the user to sign in or provide an already authenticated "
            "browser context."
        ),
    ),
    BrowserErrorCode.CAPTCHA_OR_RISK_CONTROL: BrowserErrorInfo(
        code=BrowserErrorCode.CAPTCHA_OR_RISK_CONTROL,
        outcome=BrowserOutcome.BLOCKED,
        recovery_hint=(
            "Stop automation and ask the user to resolve the verification or "
            "risk-control challenge manually."
        ),
    ),
    BrowserErrorCode.CANCELLED: BrowserErrorInfo(
        code=BrowserErrorCode.CANCELLED,
        outcome=BrowserOutcome.CANCELLED,
        recovery_hint=(
            "Browser task was cancelled by the user or runtime; cleanup "
            "should release request-scoped browser resources."
        ),
    ),
    BrowserErrorCode.NETWORK_TIMEOUT: BrowserErrorInfo(
        code=BrowserErrorCode.NETWORK_TIMEOUT,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Report the timeout and retry later only if the network or page "
            "settles."
        ),
    ),
    BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT: BrowserErrorInfo(
        code=BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Protocol timeout bridge_request_timeout: the Chrome extension "
            "bridge did not answer before its request deadline."
        ),
    ),
    BrowserErrorCode.CDP_COMMAND_TIMEOUT: BrowserErrorInfo(
        code=BrowserErrorCode.CDP_COMMAND_TIMEOUT,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Protocol timeout cdp_command_timeout: the CDP command did not "
            "finish before its bounded command deadline."
        ),
    ),
    BrowserErrorCode.DOM_SETTLE_TIMEOUT: BrowserErrorInfo(
        code=BrowserErrorCode.DOM_SETTLE_TIMEOUT,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Protocol timeout dom_settle_timeout: DOM observation did not "
            "settle before its bounded observation deadline."
        ),
    ),
    BrowserErrorCode.NETWORK_SETTLE_TIMEOUT: BrowserErrorInfo(
        code=BrowserErrorCode.NETWORK_SETTLE_TIMEOUT,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Protocol timeout network_settle_timeout: network activity did "
            "not become quiet before its bounded settle deadline."
        ),
    ),
    BrowserErrorCode.DOWNLOAD_TIMEOUT: BrowserErrorInfo(
        code=BrowserErrorCode.DOWNLOAD_TIMEOUT,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Protocol timeout download_timeout: Chrome did not report a "
            "completed download before its bounded download deadline."
        ),
    ),
    BrowserErrorCode.UPLOAD_TIMEOUT: BrowserErrorInfo(
        code=BrowserErrorCode.UPLOAD_TIMEOUT,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Protocol timeout upload_timeout: Chrome did not finish the file "
            "upload command before its bounded upload deadline."
        ),
    ),
    BrowserErrorCode.OBSERVATION_STALE: BrowserErrorInfo(
        code=BrowserErrorCode.OBSERVATION_STALE,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Take a fresh browser observation before attempting another "
            "mutating action."
        ),
    ),
    BrowserErrorCode.OBSERVATION_ENRICHMENT_DENIED: BrowserErrorInfo(
        code=BrowserErrorCode.OBSERVATION_ENRICHMENT_DENIED,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Use an available visual observation source before attempting "
            "another mutating action."
        ),
    ),
    BrowserErrorCode.INVALID_SDK_USAGE: BrowserErrorInfo(
        code=BrowserErrorCode.INVALID_SDK_USAGE,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Retry with documented Browser SDK methods and arguments; do "
            "not invent browser APIs."
        ),
    ),
    BrowserErrorCode.CLICK_WITHOUT_NAVIGATION: BrowserErrorInfo(
        code=BrowserErrorCode.CLICK_WITHOUT_NAVIGATION,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Observe the page after the click before deciding whether to "
            "retry, wait, or choose a different strategy."
        ),
    ),
    BrowserErrorCode.CAPABILITY_MISSING: BrowserErrorInfo(
        code=BrowserErrorCode.CAPABILITY_MISSING,
        outcome=BrowserOutcome.FAILED,
        recovery_hint=(
            "Add or use a generic Browser SDK capability instead of a "
            "one-off workaround."
        ),
    ),
}


def classify_browser_error(error: object = None) -> BrowserErrorInfo:
    """Return taxonomy info for a code, exception, or error string."""
    code = _coerce_error_code(error)
    return _ERROR_INFO.get(code, _ERROR_INFO[BrowserErrorCode.UNKNOWN])


def _coerce_error_code(error: object = None) -> BrowserErrorCode:
    if error is None:
        return BrowserErrorCode.UNKNOWN
    if isinstance(error, BrowserErrorCode):
        return error
    if isinstance(error, str):
        return _coerce_error_string(error)
    code = getattr(error, "browser_error_code", None) or getattr(
        error,
        "code",
        None,
    )
    return _coerce_error_string(str(code or ""))


def _coerce_error_string(value: str) -> BrowserErrorCode:
    normalized = value.strip().casefold()
    if not normalized:
        return BrowserErrorCode.UNKNOWN
    normalized = normalized.replace("-", "_")
    for code in BrowserErrorCode:
        if normalized in {code.value.casefold(), code.name.casefold()}:
            return code
    legacy_map = {
        "browser_bridge_disconnected": BrowserErrorCode.BRIDGE_DISCONNECTED,
        "browser_action_approval_timeout": BrowserErrorCode.APPROVAL_REQUIRED,
        "browser_action_denied": BrowserErrorCode.APPROVAL_DENIED,
        "canceled": BrowserErrorCode.CANCELLED,
        "cancelled": BrowserErrorCode.CANCELLED,
        "browser_policy_denied": BrowserErrorCode.APPROVAL_DENIED,
        "browser_observation_required": BrowserErrorCode.OBSERVATION_STALE,
        "browser_observation_enrichment_denied": (
            BrowserErrorCode.OBSERVATION_ENRICHMENT_DENIED
        ),
        "browser_invalid_sdk_usage": BrowserErrorCode.INVALID_SDK_USAGE,
        "invalid_browser_sdk_usage": BrowserErrorCode.INVALID_SDK_USAGE,
        "browser_click_without_navigation": (
            BrowserErrorCode.CLICK_WITHOUT_NAVIGATION
        ),
        "browser_sdk_gap": BrowserErrorCode.CAPABILITY_MISSING,
        "browser_context_unavailable": BrowserErrorCode.CAPABILITY_MISSING,
        "browser_kernel_timeout": BrowserErrorCode.NETWORK_TIMEOUT,
        "request_timeout": BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT,
        "bridge_timeout": BrowserErrorCode.BRIDGE_REQUEST_TIMEOUT,
        "cdp_timeout": BrowserErrorCode.CDP_COMMAND_TIMEOUT,
        "dom_timeout": BrowserErrorCode.DOM_SETTLE_TIMEOUT,
        "network_quiescence_timeout": (
            BrowserErrorCode.NETWORK_SETTLE_TIMEOUT
        ),
    }
    return legacy_map.get(normalized, BrowserErrorCode.UNKNOWN)


__all__ = [
    "BrowserErrorCode",
    "BrowserErrorInfo",
    "BrowserOutcome",
    "classify_browser_error",
]
