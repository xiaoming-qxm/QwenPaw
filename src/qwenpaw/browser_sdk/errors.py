# -*- coding: utf-8 -*-
"""Typed errors for the unified Browser SDK."""

from __future__ import annotations

from typing import Any

from .error_codes import classify_browser_error


class BrowserSDKError(Exception):
    """Base error with a stable machine-readable code."""

    code = "browser_sdk_error"

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        backend_id: str = "",
        action: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        self.code = code or self.code
        self.backend_id = backend_id
        self.action = action
        self.metadata = dict(metadata or {})
        error_info = classify_browser_error(self.code)
        self.browser_error_code = error_info.code.value
        self.browser_outcome = error_info.outcome.value
        self.recovery_hint = str(
            self.metadata.get("recovery_hint") or error_info.recovery_hint,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly error payload."""
        payload: dict[str, Any] = {
            "ok": False,
            "error": self.browser_error_code,
            "code": self.browser_error_code,
            "outcome": self.browser_outcome,
            "recovery_hint": self.recovery_hint,
            "message": str(self),
        }
        if self.backend_id:
            payload["backend_id"] = self.backend_id
        if self.action:
            payload["action"] = self.action
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


class BrowserContextUnavailable(BrowserSDKError):
    """Raised when the requested browser context has no usable backend."""

    code = "browser_context_unavailable"


class BrowserContextConflict(BrowserSDKError):
    """Raised when request metadata conflicts with context selection."""

    code = "browser_context_conflict"


class BrowserPolicyDenied(BrowserSDKError):
    """Raised when browser policy denies context or action execution."""

    code = "browser_policy_denied"


class BrowserSDKGap(BrowserSDKError):
    """Raised when a legacy request has no Browser SDK equivalent."""

    code = "browser_sdk_gap"

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["sdk_gap"] = True
        return payload


class BrowserObservationRequired(BrowserSDKError):
    """Raised when an action would mutate without fresh observation."""

    code = "browser_observation_required"


__all__ = [
    "BrowserContextConflict",
    "BrowserContextUnavailable",
    "BrowserObservationRequired",
    "BrowserPolicyDenied",
    "BrowserSDKError",
    "BrowserSDKGap",
]
