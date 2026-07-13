# -*- coding: utf-8 -*-
"""Shared approval data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class ApprovalBrief:
    """Generic user-facing decision material for approval requests."""

    subject: str
    target: str
    evidence: dict[str, Any] = field(default_factory=dict)
    uncertainties: tuple[str, ...] = ()
    possible_consequences: tuple[str, ...] = ()
    risk_kind: str = ""
    risk_level: str = ""
    confidence: float = 0.0
    why_approval_required: str = ""
    safe_alternative: str = ""


@dataclass(frozen=True)
class ApprovalRequestSummary:
    """Generic approval summary for non-ToolGuard approval sources."""

    source_type: str
    name: str
    severity: str = "medium"
    findings_count: int = 1
    result_summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    approval_brief: ApprovalBrief | None = None
    scope_policy: Literal["default", "exact_only"] = "default"

    def __post_init__(self) -> None:
        if (
            self.source_type == "browser_core_action"
            and self.scope_policy != "exact_only"
        ):
            raise ValueError(
                "browser_core_action requires exact_only scope policy",
            )
