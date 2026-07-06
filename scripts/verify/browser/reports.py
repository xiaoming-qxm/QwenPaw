# -*- coding: utf-8 -*-
"""Report helpers for Browser product verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProductGateReport:
    """Small report object used by V10-D product gates."""

    scenario: str
    status: str
    failure_category: str = ""
    recovery_hint: str = ""
    cleanup_result: dict[str, Any] = field(default_factory=dict)
    reconnect_delta: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "status": self.status,
            "failure_category": self.failure_category,
            "recovery_hint": self.recovery_hint,
            "cleanup_result": dict(self.cleanup_result),
            "reconnect_delta": self.reconnect_delta,
            "evidence": dict(self.evidence),
        }


def summarize_reports(reports: list[ProductGateReport]) -> dict[str, Any]:
    """Summarize product gate reports for CLI output."""
    return {
        "status": (
            "passed"
            if all(report.status == "passed" for report in reports)
            else "failed"
        ),
        "reports": [report.to_dict() for report in reports],
    }


__all__ = ["ProductGateReport", "summarize_reports"]
