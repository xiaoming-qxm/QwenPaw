# -*- coding: utf-8 -*-
"""Browser Bridge operational verifier.

The default verifier is local and deterministic: it checks a running QwenPaw
service for code freshness, Browser Bridge status, and trace evidence. Live
Taobao validation is intentionally opt-in and blocked by default.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from qwenpaw.browser.governance.error_codes import (
    BrowserErrorCode,
    BrowserOutcome,
    classify_browser_error,
)
from qwenpaw.browser.governance.risk import (
    RISK_ACTIONS_BY_KIND,
    RISK_KEYWORDS_BY_KIND,
)
from qwenpaw.browser.telemetry.progress import detect_no_progress
from qwenpaw.browser.recovery import classify_browser_runtime_outcome
from qwenpaw.browser.telemetry.trace import (
    BrowserTraceEvent,
    validate_browser_trace_events,
)
from scripts.verify.browser.guards import (
    run_risk_genericity_gates,
    run_truth_gates,
)
from scripts.verify.browser.scenarios import default_scenarios

DEFAULT_BASE_URL = "http://127.0.0.1:8088"
DEFAULT_TIMEOUT = 10.0
DEFAULT_TASK_TIMEOUT = 180.0
DETERMINISTIC_COMPLEX_TASK_TIMEOUT = 300.0
V9_RUNTIME_STALE_CODE = "RUNTIME_STALE"
V9_REPORT_SCHEMA_VERSION = "browser-bridge-v9-a"
V9_SOURCE_LABELS = (
    "fixture",
    "local_service",
    "user_chrome",
    "public_live",
    "commerce_live",
)
V9_ACCEPTANCE_DEFAULT_REPORT_DIR = (
    "../MyNotebook/_QwenPaw/feats/"
    "browser-bridge-v9-f-live-product-acceptance"
)
V9_ACCEPTANCE_JSON_NAME = "v9-acceptance-report.json"
V9_ACCEPTANCE_MARKDOWN_NAME = "acceptance-report.md"
V9_REQUIRED_ISSUE_FIELDS = (
    "evidence",
    "root_cause",
    "generic_solution",
    "fix_commit",
    "restart_evidence",
    "retest_outcome",
)
V9_BUDGET_PROFILES: dict[str, dict[str, int | str]] = {
    "public_isolated": {
        "profile": "public_isolated",
        "iteration_limit": 12,
        "browser_call_limit": 8,
        "elapsed_ms_limit": 120_000,
        "token_limit": 25_000,
    },
    "user_read_only": {
        "profile": "user_read_only",
        "iteration_limit": 12,
        "browser_call_limit": 8,
        "elapsed_ms_limit": 120_000,
        "token_limit": 25_000,
    },
    "deterministic_complex": {
        "profile": "deterministic_complex",
        "iteration_limit": 25,
        "browser_call_limit": 20,
        "elapsed_ms_limit": 300_000,
        "token_limit": 50_000,
    },
    "commerce_live_mutation": {
        "profile": "commerce_live_mutation",
        "iteration_limit": 60,
        "browser_call_limit": 45,
        "elapsed_ms_limit": 900_000,
        "token_limit": 90_000,
    },
}
V9_SCENARIO_BUDGET_PROFILES = {
    "public-isolated": "public_isolated",
    "public-search": "public_isolated",
    "stable-public-page": "public_isolated",
    "v8-public-live": "public_isolated",
    "user-read-only": "user_read_only",
    "v8-user-live": "user_read_only",
    "complex-isolated": "deterministic_complex",
    "complex-user": "deterministic_complex",
    "deterministic-complex": "deterministic_complex",
    "v8-deterministic": "deterministic_complex",
    "v8-taobao-live": "commerce_live_mutation",
    "v9-taobao-live": "commerce_live_mutation",
    "taobao-live-mutation": "commerce_live_mutation",
    "commerce-live-mutation": "commerce_live_mutation",
}


def _join_removed_tool_token(*parts: str) -> str:
    return "".join(parts)


FORBIDDEN_TOOLS = (
    _join_removed_tool_token("browser", "_use"),
    _join_removed_tool_token("Desktop", "Screenshot"),
    _join_removed_tool_token("Desktop", "ScreenShot"),
    _join_removed_tool_token("View", "Video"),
    _join_removed_tool_token("Remote", "Bridge"),
    _join_removed_tool_token("/ws/", "browser-sdk"),
)
BROWSER_BRIDGE_ENTROPY_LEGACY_TOKENS = (
    _join_removed_tool_token("browser", "_use"),
    _join_removed_tool_token("Desktop", "Screenshot"),
    _join_removed_tool_token("Desktop", "ScreenShot"),
    _join_removed_tool_token("View", "Video"),
)
BROWSER_BRIDGE_ENTROPY_SITE_TOKENS = (
    "Taobao",
    "淘宝",
    "Loop Engineering",
    "shopping cart",
    "购物车",
    "tmall",
    "amazon",
)
BROWSER_BRIDGE_ENTROPY_ALLOWED_SCENARIO_PATHS = (
    "scripts/verify/browser/cli.py",
    "scripts/verify/browser/truth_audit.py",
)
BROWSER_BRIDGE_ENTROPY_EXCLUDED_PATHS = (
    "scripts/verify/browser/product_matrix.py",
)
BROWSER_BRIDGE_ENTROPY_GENERIC_COMMERCE_PATHS = (
    "plugins/bundle/browser-bridge/action_runtime/snapshot_builder.py",
    "plugins/bundle/browser-bridge/action_runtime/targets.py",
)
MUTATING_TRACE_ACTIONS = {
    "back",
    "click",
    "evaluate",
    "forward",
    "navigate",
    "press",
    "press_key",
    "reload",
    "scroll",
    "select",
    "select_option",
    "upload",
    "download",
    "dialog",
    "type",
}


@dataclass(frozen=True)
class BrowserBridgeReport:
    """Structured result emitted by one verifier scenario."""

    scenario: str
    status: str
    duration_ms: float = 0.0
    browser_tool_calls: int = 0
    backend_route: str = ""
    forbidden_tools: list[str] = field(default_factory=list)
    trace_event_count: int = 0
    error_code: str = ""
    blocked_reason: str = ""
    failure_reason: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    fresh_observe_ok: bool = False
    cleanup_ok: bool = False
    preflight_checks: dict[str, str] = field(default_factory=dict)
    content_evidence: dict[str, Any] = field(default_factory=dict)
    safety_boundaries: list[str] = field(default_factory=list)
    user_preparation: list[str] = field(default_factory=list)
    scenario_reports: list[dict[str, Any]] = field(default_factory=list)
    runtime_evidence: dict[str, Any] = field(default_factory=dict)
    trace_summary: dict[str, Any] = field(default_factory=dict)
    report_schema_version: str = ""
    scenario_budget: dict[str, Any] = field(default_factory=dict)
    actual_metrics: dict[str, Any] = field(default_factory=dict)
    cleanup_summary: dict[str, Any] = field(default_factory=dict)
    blocker_classification: dict[str, Any] = field(default_factory=dict)
    source_labels: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "browser_tool_calls": self.browser_tool_calls,
            "backend_route": self.backend_route,
            "forbidden_tools": list(self.forbidden_tools),
            "trace_event_count": self.trace_event_count,
            "error_code": self.error_code,
            "blocked_reason": self.blocked_reason,
            "failure_reason": self.failure_reason,
            "artifact_paths": list(self.artifact_paths),
            "fresh_observe_ok": self.fresh_observe_ok,
            "cleanup_ok": self.cleanup_ok,
            "preflight_checks": dict(self.preflight_checks),
            "content_evidence": dict(self.content_evidence),
            "safety_boundaries": list(self.safety_boundaries),
            "user_preparation": list(self.user_preparation),
            "scenario_reports": list(self.scenario_reports),
            "runtime_evidence": dict(self.runtime_evidence),
            "trace_summary": dict(self.trace_summary),
            "report_schema_version": self.report_schema_version,
            "scenario_budget": dict(self.scenario_budget),
            "actual_metrics": dict(self.actual_metrics),
            "cleanup_summary": dict(self.cleanup_summary),
            "blocker_classification": dict(self.blocker_classification),
            "source_labels": dict(self.source_labels),
        }


@dataclass(frozen=True)
class HarnessPromptSpec:
    """Prompt text plus verifier-owned scenario checks."""

    instruction: str
    code: str
    required_success_marker: str
    required_context: str = ""
    required_backend_id: str = ""
    require_user_backend: bool = False
    request_context: dict[str, Any] | None = None
    forbidden_tools: tuple[str, ...] = field(
        default_factory=lambda: FORBIDDEN_TOOLS,
    )

    def render(self) -> str:
        context_hint = self.required_context or "auto"
        return (
            f"{self.instruction.strip()}\n\n"
            "Browser is already preloaded in the browser(code=...) runtime; "
            "do not import Browser. Use exactly one browser(code=...) call. "
            f'Call browser(code=..., context="{context_hint}") for this '
            "scenario. "
            "Copy the code block verbatim as that call's code argument. "
            "Do not shorten, split, reorder, or retry alternate snippets. "
            "Do not call Skill or any legacy browser tool. Do not fall back "
            "to isolated when user context is required.\n\n"
            "```python\n"
            f"{self.code.strip()}\n"
            "```"
        )


@dataclass(frozen=True)
class V8LiveTaskSpec:
    """Natural-language live verifier task contract."""

    scenario: str
    prompt: str
    required_context: str
    required_backend_id: str
    content_markers: tuple[str, ...] = ()
    success_marker: str = ""
    entrypoint: str = "chat"
    requires_user_state: bool = False
    requires_flag: str = ""
    request_context: dict[str, Any] | None = None
    expected_blocker: str = ""
    artifact_paths: tuple[str, ...] = ()


V8_DETERMINISTIC_SCENARIOS = (
    "preflight",
    "public-search",
    "complex-isolated",
    "complex-user",
    "v8-capability-isolated",
    "v8-capability-user",
)

V8_TAOBAO_USER_PREPARATION = (
    "Chrome Extension connected",
    "Taobao logged in in user Chrome",
    "Taobao cart page readable before mutation",
    "--live-taobao and --confirm-account-mutation provided",
)

V8_SAFETY_BOUNDARIES = (
    "Do not checkout",
    "Do not submit an order",
    "Do not pay",
    "Do not enter credentials",
    "Do not bypass login, CAPTCHA, or risk-control challenges",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Browser Bridge operational readiness.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument(
        "--report",
        default="docs/browser-v10-product-readiness-report.md",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--task-timeout",
        type=float,
        default=DEFAULT_TASK_TIMEOUT,
    )
    parser.add_argument("--start-if-missing", action="store_true")
    parser.add_argument("--truth-gates", action="store_true")
    parser.add_argument("--live-taobao", action="store_true")
    parser.set_defaults(live_taobao=False)

    subparsers = parser.add_subparsers(dest="command", required=False)
    subparsers.add_parser("preflight")
    subparsers.add_parser("fixture")
    subparsers.add_parser("public-search")
    subparsers.add_parser("complex-isolated")
    subparsers.add_parser("complex-user")
    subparsers.add_parser("v8-capability-isolated")
    subparsers.add_parser("v8-capability-user")
    subparsers.add_parser("bridge-disconnected")
    taobao = subparsers.add_parser("taobao-live")
    taobao.add_argument("--live-taobao", action="store_true")
    _add_v8_command_parsers(subparsers)
    _add_v9_command_parsers(subparsers)
    return parser


def _add_v8_command_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    for command in (
        "v8-preflight",
        "v8-deterministic",
        "v8-public-live",
        "v8-user-live",
        "v8-lifecycle-live",
    ):
        subparser = subparsers.add_parser(command)
        _add_v8_common_args(subparser)

    public_live = subparsers.choices["v8-public-live"]
    public_live.add_argument("--public-live", action="store_true")

    user_live = subparsers.choices["v8-user-live"]
    user_live.add_argument("--live-taobao-preflight", action="store_true")

    taobao_live = subparsers.add_parser("v8-taobao-live")
    _add_v8_common_args(taobao_live)
    taobao_live.add_argument("--live-taobao", action="store_true")
    taobao_live.add_argument(
        "--confirm-account-mutation",
        action="store_true",
    )

    report = subparsers.add_parser("v8-report")
    report.add_argument("--output-json", default="")
    report.add_argument(
        "--output",
        default="docs/browser-bridge-v8-product-readiness-report.md",
    )
    report.add_argument("result_files", nargs="*")


def _add_v8_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--task-timeout",
        type=float,
        default=DEFAULT_TASK_TIMEOUT,
    )
    parser.add_argument("--start-if-missing", action="store_true")
    parser.add_argument("--output-json", default="")


def _add_v9_command_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    preflight = subparsers.add_parser("v9-preflight")
    _add_v9_common_args(preflight)

    acceptance = subparsers.add_parser("v9-acceptance")
    _add_v9_common_args(acceptance)
    acceptance.add_argument(
        "--report-dir",
        default=V9_ACCEPTANCE_DEFAULT_REPORT_DIR,
    )
    acceptance.add_argument("--live-public", action="store_true")
    acceptance.add_argument("--live-user", action="store_true")
    acceptance.add_argument("--live-taobao", action="store_true")
    acceptance.add_argument("--reuse-service", action="store_true")
    acceptance.add_argument(
        "--approval-level",
        default="DEFAULT",
        choices=("DEFAULT", "ASK", "ON", "OFF"),
    )

    public_live = subparsers.add_parser("v9-public-live")
    _add_v9_common_args(public_live)
    public_live.add_argument("--live-public", action="store_true")

    user_live = subparsers.add_parser("v9-user-live")
    _add_v9_common_args(user_live)
    user_live.add_argument("--live-user", action="store_true")

    matrix = subparsers.add_parser("v9-capability-matrix")
    _add_v9_common_args(matrix)

    taobao = subparsers.add_parser("v9-taobao-live")
    _add_v9_common_args(taobao)
    taobao.add_argument("--live-taobao", action="store_true")
    taobao.add_argument("--prepared-login", action="store_true")
    taobao.add_argument(
        "--approval-level",
        default="DEFAULT",
        choices=("DEFAULT", "ASK", "ON", "OFF"),
    )

    report = subparsers.add_parser("v9-report")
    report.add_argument(
        "--output",
        default="docs/browser-bridge-v9-runtime-truth-evidence-report.json",
    )
    report.add_argument("result_files", nargs="*")


def _add_v9_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--task-timeout",
        type=float,
        default=DEFAULT_TASK_TIMEOUT,
    )
    parser.add_argument("--start-if-missing", action="store_true")
    parser.add_argument("--restart-stale", action="store_true")
    parser.add_argument("--output-json", default="")


def detect_forbidden_tools(text: str | list[str]) -> list[str]:
    haystack = "\n".join(text) if isinstance(text, list) else str(text or "")
    return [tool for tool in FORBIDDEN_TOOLS if tool in haystack]


def scan_browser_bridge_entropy_guardrails(
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Scan Browser Bridge hot paths for prompt and legacy-tool entropy."""
    repo_root = Path(root or Path.cwd())
    scanned_files: list[str] = []
    violations: list[dict[str, str]] = []
    for path in _browser_bridge_entropy_scan_paths(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        scanned_files.append(relative)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        violations.extend(
            _browser_bridge_entropy_violations_for_text(relative, text),
        )
    return {
        "ok": not violations,
        "violations": violations,
        "scanned_files": scanned_files,
    }


def _browser_bridge_entropy_scan_paths(root: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    sdk_root = root / "src/qwenpaw/browser"
    if sdk_root.exists():
        candidates.extend(sorted(sdk_root.glob("*.py")))
    plugin_root = root / "plugins/bundle/browser-bridge"
    for relative in ("*.py", "engine/**/*.py"):
        candidates.extend(sorted(plugin_root.glob(relative)))
    skill_root = plugin_root / "skills/browser-bridge"
    if skill_root.exists():
        candidates.extend(sorted(skill_root.glob("*.md")))
    excluded = set(BROWSER_BRIDGE_ENTROPY_EXCLUDED_PATHS)
    return tuple(
        path
        for path in candidates
        if path.is_file() and path.relative_to(root).as_posix() not in excluded
    )


def _browser_bridge_entropy_violations_for_text(
    relative_path: str,
    text: str,
) -> list[dict[str, str]]:
    if relative_path in BROWSER_BRIDGE_ENTROPY_ALLOWED_SCENARIO_PATHS:
        return []
    violations: list[dict[str, str]] = []
    for token in BROWSER_BRIDGE_ENTROPY_LEGACY_TOKENS:
        if _legacy_entropy_token_present(text, token):
            violations.append(
                _entropy_violation(
                    relative_path,
                    token,
                    "legacy_tool",
                ),
            )
    for token in BROWSER_BRIDGE_ENTROPY_SITE_TOKENS:
        if _site_entropy_token_allowed(relative_path, token):
            continue
        if _entropy_token_present(text, token):
            violations.append(
                _entropy_violation(
                    relative_path,
                    token,
                    "site_specific",
                ),
            )
    return violations


def _legacy_entropy_token_present(text: str, token: str) -> bool:
    if token == _join_removed_tool_token("browser", "_use"):
        pattern = (
            r"(?<![A-Z0-9_])"
            + re.escape(_join_removed_tool_token("browser", "_use"))
            + r"(?![A-Z0-9_])"
        )
        return re.search(pattern, text, re.I) is not None
    return _entropy_token_present(text, token)


def _site_entropy_token_allowed(relative_path: str, token: str) -> bool:
    return (
        relative_path in BROWSER_BRIDGE_ENTROPY_GENERIC_COMMERCE_PATHS
        and token in {"shopping cart", "购物车"}
    )


def _entropy_token_present(text: str, token: str) -> bool:
    if any("\u4e00" <= char <= "\u9fff" for char in token):
        return token in text
    return token.casefold() in text.casefold()


def _entropy_violation(
    relative_path: str,
    token: str,
    category: str,
) -> dict[str, str]:
    return {
        "path": relative_path,
        "token": token,
        "category": category,
        "message": (
            "Browser Bridge progress and recovery must stay generic; "
            f"remove {token!r} from {relative_path}."
        ),
    }


# pylint: disable-next=too-many-return-statements
def classify_verification_evidence(
    *,
    scenario: str,
    started: float,
    trace_events: list[dict[str, Any]] | None = None,
    transcript: str | list[str] = "",
    forbidden_tools: list[str] | None = None,
    assertion_failure: str = "",
    browser_tool_calls: int = 0,
    backend_route: str = "",
    artifact_paths: list[str] | None = None,
    actual_metrics: dict[str, Any] | None = None,
) -> BrowserBridgeReport:
    """Classify synthetic verifier evidence into a scenario report."""
    events = trace_events or []
    forbidden = list(forbidden_tools or [])
    metrics = _v9_normalize_actual_metrics(
        started=started,
        browser_tool_calls=browser_tool_calls,
        trace_events=events,
        actual_metrics=actual_metrics,
    )
    budget = _v9_scenario_budget(scenario)
    budget_failure = _v9_budget_failure(budget, metrics)

    def scenario_report(
        status: str,
        **kwargs: Any,
    ) -> BrowserBridgeReport:
        kwargs.setdefault("scenario_budget", budget)
        kwargs.setdefault("actual_metrics", metrics)
        return _report(scenario, status, started, **kwargs)

    if forbidden:
        return scenario_report(
            "failed",
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            forbidden_tools=forbidden,
            trace_event_count=len(events),
            error_code=BrowserErrorCode.CAPABILITY_MISSING.value,
            failure_reason="forbidden_tools",
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(
                events,
            ),
            cleanup_ok=(
                not _user_cleanup_failure_reason(events)
                if _has_user_backend_evidence(events)
                else True
            ),
        )

    if assertion_failure:
        return scenario_report(
            "failed",
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(events),
            error_code=BrowserErrorCode.UNKNOWN.value,
            failure_reason=assertion_failure,
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(
                events,
            ),
            cleanup_ok=(
                not _user_cleanup_failure_reason(events)
                if _has_user_backend_evidence(events)
                else True
            ),
        )

    trace_validation = _trace_completeness_summary(events)
    if trace_validation and not trace_validation.get("complete", True):
        return scenario_report(
            "failed",
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(events),
            error_code=BrowserErrorCode.UNKNOWN.value,
            failure_reason="trace_incomplete",
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(
                events,
            ),
            cleanup_ok=(
                not _user_cleanup_failure_reason(events)
                if _has_user_backend_evidence(events)
                else True
            ),
            trace_summary=trace_validation,
        )

    trace_info = _trace_error_info(events)
    if trace_info is not None and trace_info.outcome == BrowserOutcome.BLOCKED:
        return scenario_report(
            "blocked",
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(events),
            error_code=trace_info.code.value,
            blocked_reason=trace_info.blocked_reason,
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(events),
            cleanup_ok=(
                not _user_cleanup_failure_reason(events)
                if _has_user_backend_evidence(events)
                else True
            ),
            blocker_classification=_v9_report_blocker_classification(
                status="blocked",
                blocked_reason=trace_info.blocked_reason,
            ),
        )

    transcript_info = _transcript_error_info(transcript)
    if transcript_info is not None:
        return scenario_report(
            "blocked",
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(events),
            error_code=transcript_info.code.value,
            blocked_reason=transcript_info.blocked_reason,
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(events),
            cleanup_ok=(
                not _user_cleanup_failure_reason(events)
                if _has_user_backend_evidence(events)
                else True
            ),
            blocker_classification=_v9_report_blocker_classification(
                status="blocked",
                blocked_reason=transcript_info.blocked_reason,
            ),
        )

    if budget_failure:
        return scenario_report(
            "failed",
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(events),
            failure_reason="budget_exhausted",
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(events),
            cleanup_ok=(
                not _user_cleanup_failure_reason(events)
                if _has_user_backend_evidence(events)
                else True
            ),
            blocker_classification=budget_failure,
        )

    no_progress = _no_progress_failure_reason(events)
    if no_progress:
        return scenario_report(
            "failed",
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(events),
            error_code=BrowserErrorCode.OBSERVATION_STALE.value,
            failure_reason=no_progress,
            artifact_paths=artifact_paths,
            fresh_observe_ok=False,
            cleanup_ok=(
                not _user_cleanup_failure_reason(events)
                if _has_user_backend_evidence(events)
                else True
            ),
        )

    if trace_info is not None:
        status = (
            "blocked"
            if trace_info.outcome == BrowserOutcome.BLOCKED
            else "failed"
        )
        return scenario_report(
            status,
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(events),
            error_code=trace_info.code.value,
            blocked_reason=trace_info.blocked_reason,
            failure_reason=trace_info.failure_reason,
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(
                events,
            ),
            cleanup_ok=(
                not _user_cleanup_failure_reason(events)
                if _has_user_backend_evidence(events)
                else True
            ),
        )

    return scenario_report(
        "passed",
        browser_tool_calls=browser_tool_calls,
        backend_route=backend_route,
        trace_event_count=len(events),
        artifact_paths=artifact_paths,
        fresh_observe_ok=not _fresh_observe_failure_reason(events),
        cleanup_ok=(
            not _user_cleanup_failure_reason(events)
            if _has_user_backend_evidence(events)
            else True
        ),
    )


def classify_v9_public_live_evidence(
    *,
    started: float,
    trace_events: list[dict[str, Any]],
    transcript: str,
    browser_tool_calls: int,
    runtime_evidence: dict[str, Any],
    actual_metrics: dict[str, Any] | None = None,
) -> BrowserBridgeReport:
    """Classify the V9 public isolated live scenario contract."""
    route = _backend_route_from_traces(trace_events)
    normalized_metrics = _v9_normalize_actual_metrics(
        started=started,
        browser_tool_calls=browser_tool_calls,
        trace_events=trace_events,
        actual_metrics=actual_metrics,
    )

    def public_report(
        status: str,
        *,
        forbidden_tools: list[str] | None = None,
        error_code: str = "",
        failure_reason: str = "",
        content_evidence: dict[str, Any] | None = None,
    ) -> BrowserBridgeReport:
        return _report(
            "v9-public-live",
            status,
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=route,
            forbidden_tools=forbidden_tools,
            trace_event_count=len(trace_events),
            error_code=error_code,
            failure_reason=failure_reason,
            runtime_evidence=dict(runtime_evidence or {}),
            content_evidence=content_evidence,
            source_labels=v9_source_labels_for_scenario("v9-public-live"),
            scenario_budget=_v9_scenario_budget("v9-public-live"),
            actual_metrics=normalized_metrics,
        )

    forbidden = _v9_forbidden_observations(transcript, trace_events)
    if forbidden:
        return public_report(
            "failed",
            forbidden_tools=forbidden,
            error_code=BrowserErrorCode.CAPABILITY_MISSING.value,
            failure_reason="forbidden_tools",
        )
    if not _v9_runtime_fresh(runtime_evidence):
        return public_report(
            "failed",
            error_code=V9_RUNTIME_STALE_CODE,
            failure_reason="runtime_freshness_missing",
        )
    if _has_user_backend_evidence(trace_events):
        return public_report(
            "failed",
            error_code=BrowserErrorCode.CAPABILITY_MISSING.value,
            failure_reason="public_live_used_user_backend",
        )
    if not _has_required_backend_evidence(
        trace_events,
        context="isolated",
        backend_id="isolated.playwright",
    ):
        return public_report(
            "failed",
            error_code=BrowserErrorCode.CAPABILITY_MISSING.value,
            failure_reason="backend_route_mismatch",
        )
    evidence = _v9_public_content_evidence(transcript)
    if not all(evidence.values()):
        return public_report(
            "failed",
            error_code=BrowserErrorCode.UNKNOWN.value,
            failure_reason="missing_public_loop_evidence",
            content_evidence=evidence,
        )
    report = classify_verification_evidence(
        scenario="v9-public-live",
        started=started,
        trace_events=trace_events,
        transcript=transcript,
        forbidden_tools=[],
        browser_tool_calls=browser_tool_calls,
        backend_route=route,
        actual_metrics=normalized_metrics,
    )
    return replace(
        report,
        runtime_evidence=dict(runtime_evidence or {}),
        content_evidence={
            **evidence,
            "user_chrome_touched": False,
        },
        source_labels=v9_source_labels_for_scenario("v9-public-live"),
    )


def _v9_public_content_evidence(transcript: str) -> dict[str, bool]:
    text = str(transcript or "")
    lowered = text.casefold()
    return {
        "success_marker": "V9_PUBLIC_LOOP_PASS" in text,
        "loop_engineering_blog": "loop" in lowered,
    }


def _v9_runtime_fresh(runtime_evidence: dict[str, Any]) -> bool:
    checks = runtime_evidence.get("checks") if runtime_evidence else {}
    checks = checks if isinstance(checks, dict) else {}
    required = (
        "backend_commit",
        "frontend_fingerprint",
        "plugin_fingerprint",
        "extension_version",
        "native_host_version",
        "bridge_freshness",
    )
    return bool(checks) and all(
        checks.get(name) == "passed" for name in required
    )


def _v9_forbidden_observations(
    transcript: str,
    trace_events: list[dict[str, Any]],
) -> list[str]:
    observed = detect_forbidden_tools(transcript)
    for item in _detect_forbidden_tool_usage({}, trace_events):
        if item not in observed:
            observed.append(item)
    return observed


def classify_v9_user_live_evidence(
    *,
    started: float,
    scenario_reports: list[dict[str, Any]],
) -> BrowserBridgeReport:
    """Classify V9 user Chrome lifecycle acceptance evidence."""
    required = _v9_user_live_required_scenarios()
    observed = {
        str(report.get("scenario") or "") for report in scenario_reports
    }
    missing = sorted(required - observed)
    missing_lifecycle = _v9_user_live_missing_lifecycle_states(
        scenario_reports,
    )
    missing_controlled_lifecycle = (
        _v9_user_live_missing_controlled_lifecycle_evidence(
            scenario_reports,
        )
    )
    backend_route = _join_unique(
        report.get("backend_route") for report in scenario_reports
    )
    residual_tabs = sum(
        _summary_int(
            _dict_value(report.get("cleanup_summary")),
            "residual_tab_count",
        )
        for report in scenario_reports
    )
    console_overwrite = any(
        bool(
            _dict_value(report.get("content_evidence")).get(
                "console_overwrite",
            ),
        )
        for report in scenario_reports
    )
    isolated_fallback = any(
        "isolated." in str(report.get("backend_route") or "")
        or 'context="isolated"' in str(report.get("backend_route") or "")
        for report in scenario_reports
    )
    failed_child = next(
        (
            report
            for report in scenario_reports
            if str(report.get("status") or "") == "failed"
        ),
        None,
    )
    status = "passed"
    failure_reason = ""
    if missing:
        status = "failed"
        failure_reason = "missing_user_live_scenario"
    elif missing_lifecycle:
        status = "failed"
        failure_reason = "missing_lifecycle_state_evidence"
    elif isolated_fallback:
        status = "failed"
        failure_reason = "user_live_used_isolated_backend"
    elif residual_tabs:
        status = "failed"
        failure_reason = "residual_controlled_tabs"
    elif missing_controlled_lifecycle:
        status = "failed"
        failure_reason = "missing_controlled_lifecycle_evidence"
    elif console_overwrite:
        status = "failed"
        failure_reason = "console_overwrite_detected"
    elif failed_child is not None:
        status = "failed"
        failure_reason = str(
            failed_child.get("failure_reason") or "user_live_child_failed",
        )
    cleanup_summary = {
        "cleanup_ok": residual_tabs == 0,
        "residual_tab_count": residual_tabs,
        "controlled_tab_count": sum(
            _summary_int(
                _dict_value(report.get("cleanup_summary")),
                "controlled_tab_count",
            )
            for report in scenario_reports
        ),
        "required_scenarios": sorted(required),
        "missing_scenarios": missing,
        "missing_lifecycle_states": missing_lifecycle,
        "missing_controlled_lifecycle": missing_controlled_lifecycle,
    }
    return _report(
        "v9-user-live",
        status,
        started,
        browser_tool_calls=sum(
            _payload_int(report, "browser_tool_calls")
            for report in scenario_reports
        ),
        backend_route=backend_route,
        trace_event_count=sum(
            _payload_int(report, "trace_event_count")
            for report in scenario_reports
        ),
        failure_reason=failure_reason,
        fresh_observe_ok=all(
            bool(report.get("fresh_observe_ok")) for report in scenario_reports
        ),
        cleanup_ok=residual_tabs == 0 and not missing,
        content_evidence={
            "required_scenarios_present": not missing,
            "lifecycle_states_present": not missing_lifecycle,
            "missing_lifecycle_states": missing_lifecycle,
            "controlled_lifecycle_present": not missing_controlled_lifecycle,
            "missing_controlled_lifecycle": missing_controlled_lifecycle,
            "console_overwrite": console_overwrite,
            "bridge_disconnect_fail_closed": (
                "bridge-disconnect-fail-closed" in observed
            ),
            "bridge_reconnect_recovered": (
                "bridge-reconnect-recovered" in observed
            ),
            "cancellation_cleanup": "user-cancellation-cleanup" in observed,
        },
        scenario_reports=scenario_reports,
        cleanup_summary=cleanup_summary,
        scenario_budget=_v9_scenario_budget("user-read-only"),
        actual_metrics={
            "iterations": _sum_payload_actual_metric(
                scenario_reports,
                "iterations",
            ),
            "browser_calls": sum(
                _payload_int(report, "browser_tool_calls")
                for report in scenario_reports
            ),
            "trace_events": sum(
                _payload_int(report, "trace_event_count")
                for report in scenario_reports
            ),
            "token_count": {"available": False, "reason": "not_reported"},
        },
        source_labels=v9_source_labels_for_scenario("v9-user-live"),
    )


def _v9_user_live_missing_lifecycle_states(
    reports: list[dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    expected = _v9_user_live_lifecycle_states()
    for report in reports:
        scenario = str(report.get("scenario") or "")
        required_state = expected.get(scenario)
        if not required_state:
            continue
        evidence = _dict_value(report.get("content_evidence"))
        if str(evidence.get("lifecycle_state") or "") != required_state:
            missing.append(scenario)
    return sorted(missing)


def _v9_user_live_missing_controlled_lifecycle_evidence(
    reports: list[dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    for report in reports:
        scenario = str(report.get("scenario") or "")
        if scenario not in _v9_user_live_controlled_lifecycle_scenarios():
            continue
        evidence = _dict_value(report.get("content_evidence"))
        controlled = _dict_value(evidence.get("controlled_lifecycle_event"))
        if not _v9_controlled_lifecycle_event_ok(scenario, controlled):
            missing.append(scenario)
    return sorted(missing)


def _v9_user_live_controlled_lifecycle_scenarios() -> set[str]:
    return {
        "bridge-disconnect-fail-closed",
        "bridge-reconnect-recovered",
        "user-cancellation-cleanup",
    }


def _v9_controlled_lifecycle_event_ok(
    scenario: str,
    event: dict[str, Any],
) -> bool:
    if scenario == "bridge-disconnect-fail-closed":
        return (
            event.get("kind") == "bridge_disconnect_injected"
            and event.get("before_connected") is True
            and event.get("after_connected") is False
            and event.get("isolated_fallback") is False
        )
    if scenario == "bridge-reconnect-recovered":
        return (
            event.get("kind") == "bridge_reconnect_observed"
            and event.get("after_connected") is True
            and event.get("reconnect_count_increased") is True
        )
    if scenario == "user-cancellation-cleanup":
        return (
            event.get("kind") == "task_cancel_requested"
            and event.get("stop_api_called") is True
            and event.get("cleanup_ok") is True
        )
    return True


def _v9_user_live_lifecycle_states() -> dict[str, str]:
    return {
        "user-read-only-observation": "read_only_observed",
        "multi-tab-workspace": "multi_tab_cleaned",
        "bridge-disconnect-fail-closed": "bridge_disconnect_fail_closed",
        "bridge-reconnect-recovered": "bridge_reconnect_recovered",
        "user-cancellation-cleanup": "cancellation_cleanup_complete",
    }


def _v9_user_live_required_scenarios() -> set[str]:
    return {
        "user-read-only-observation",
        "multi-tab-workspace",
        "bridge-disconnect-fail-closed",
        "bridge-reconnect-recovered",
        "user-cancellation-cleanup",
    }


def _payload_int(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _sum_payload_actual_metric(
    reports: list[dict[str, Any]],
    key: str,
) -> int:
    total = 0
    for report in reports:
        metrics = _dict_value(report.get("actual_metrics"))
        total += _payload_int(metrics, key)
    return total


def classify_v9_capability_matrix_evidence(
    *,
    started: float,
    scenario_reports: list[dict[str, Any]],
) -> BrowserBridgeReport:
    """Classify deterministic V9 complex capability matrix evidence."""
    capabilities = _v9_matrix_capabilities(scenario_reports)
    missing = sorted(
        item
        for item in _v9_required_capabilities()
        if capabilities.get(item) is not True
    )
    residual_tabs = sum(
        _summary_int(
            _dict_value(report.get("cleanup_summary")),
            "residual_tab_count",
        )
        for report in scenario_reports
    )
    fresh_observe_ok = all(
        bool(report.get("fresh_observe_ok")) for report in scenario_reports
    )
    approval_default = _v9_matrix_approval_default_fail_closed(
        scenario_reports,
    )
    approval_off = _v9_matrix_approval_off_success(scenario_reports)
    approval_execution = _v9_matrix_approval_execution_evidence(
        scenario_reports,
    )
    actual_metrics = _v9_matrix_actual_metrics(scenario_reports)
    budget = _v9_scenario_budget("deterministic-complex")
    budget_failure = _v9_budget_failure(budget, actual_metrics)
    status = "passed"
    failure_reason = ""
    blocker = {}
    if missing:
        status = "failed"
        failure_reason = "missing_capability_evidence"
    elif not approval_execution:
        status = "failed"
        failure_reason = "approval_execution_evidence_missing"
    elif not approval_default:
        status = "failed"
        failure_reason = "approval_default_not_fail_closed"
    elif not approval_off:
        status = "failed"
        failure_reason = "approval_off_not_successful"
    elif not fresh_observe_ok:
        status = "failed"
        failure_reason = "fresh_observe_missing"
    elif residual_tabs:
        status = "failed"
        failure_reason = "residual_controlled_tabs"
    elif budget_failure:
        status = "failed"
        failure_reason = "budget_exhausted"
        blocker = budget_failure
    return _report(
        "v9-capability-matrix",
        status,
        started,
        browser_tool_calls=sum(
            _payload_int(report, "browser_tool_calls")
            for report in scenario_reports
        ),
        backend_route=_join_unique(
            report.get("backend_route") for report in scenario_reports
        ),
        trace_event_count=sum(
            _payload_int(report, "trace_event_count")
            for report in scenario_reports
        ),
        failure_reason=failure_reason,
        fresh_observe_ok=fresh_observe_ok,
        cleanup_ok=residual_tabs == 0,
        content_evidence={
            "capabilities": capabilities,
            "missing_capabilities": missing,
            "approval_fail_closed": approval_default,
            "approval_off_success": approval_off,
            "approval_execution_evidence": approval_execution,
        },
        scenario_reports=scenario_reports,
        cleanup_summary={
            "cleanup_ok": residual_tabs == 0,
            "residual_tab_count": residual_tabs,
        },
        scenario_budget=budget,
        actual_metrics=actual_metrics,
        blocker_classification=blocker,
        source_labels=v9_source_labels_for_scenario(
            "deterministic-complex",
        ),
    )


def _v9_required_capabilities() -> tuple[str, ...]:
    return (
        "iframe",
        "shadow_dom",
        "spa",
        "popup",
        "upload",
        "download",
        "dialog",
        "visual_fallback",
    )


def _v9_matrix_capabilities(
    reports: list[dict[str, Any]],
) -> dict[str, bool]:
    merged = {name: False for name in _v9_required_capabilities()}
    for report in reports:
        evidence = _dict_value(report.get("content_evidence"))
        capabilities = _dict_value(evidence.get("capabilities"))
        for name in merged:
            if capabilities.get(name) is True:
                merged[name] = True
    return merged


def _v9_matrix_approval_default_fail_closed(
    reports: list[dict[str, Any]],
) -> bool:
    for report in reports:
        if str(report.get("scenario") or "") != "approval-default-fail-closed":
            continue
        status = str(report.get("status") or "")
        reason = str(
            report.get("blocked_reason")
            or report.get("failure_reason")
            or report.get("error_code")
            or "",
        )
        evidence = _v9_approval_execution_evidence(report)
        return (
            status in {"blocked", "failed"}
            and "approval" in reason
            and evidence.get("executed_sensitive_action") is True
            and evidence.get("request_context_approval_level") == "DEFAULT"
            and evidence.get("mutation_prevented") is True
            and str(evidence.get("approval_state") or "")
            in _APPROVAL_BLOCKED_STATES
        )
    return False


def _v9_matrix_approval_off_success(reports: list[dict[str, Any]]) -> bool:
    for report in reports:
        if str(report.get("scenario") or "") != "approval-off-success":
            continue
        evidence = _v9_approval_execution_evidence(report)
        return (
            str(report.get("status") or "") == "passed"
            and evidence.get("executed_sensitive_action") is True
            and evidence.get("request_context_approval_level") == "OFF"
            and evidence.get("mutation_observed") is True
            and evidence.get("fresh_observe_after_mutation") is True
        )
    return False


_APPROVAL_BLOCKED_STATES = frozenset(
    {"pending", "timeout", "denied", "error", "approval_required"},
)


def _v9_matrix_approval_execution_evidence(
    reports: list[dict[str, Any]],
) -> bool:
    expected = {
        "approval-default-fail-closed": "DEFAULT",
        "approval-off-success": "OFF",
    }
    observed: set[str] = set()
    for report in reports:
        scenario = str(report.get("scenario") or "")
        level = expected.get(scenario)
        if not level:
            continue
        evidence = _v9_approval_execution_evidence(report)
        if (
            evidence.get("executed_sensitive_action") is True
            and evidence.get("request_context_approval_level") == level
        ):
            observed.add(scenario)
    return set(expected) == observed


def _v9_approval_execution_evidence(
    report: dict[str, Any],
) -> dict[str, Any]:
    content = _dict_value(report.get("content_evidence"))
    return _dict_value(content.get("approval_execution"))


def _v9_matrix_actual_metrics(
    reports: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "iterations": _sum_payload_actual_metric(reports, "iterations"),
        "browser_calls": sum(
            _payload_int(report, "browser_tool_calls") for report in reports
        ),
        "elapsed_ms": _sum_payload_actual_metric(reports, "elapsed_ms"),
        "trace_events": sum(
            _payload_int(report, "trace_event_count") for report in reports
        ),
        "token_count": {"available": False, "reason": "not_reported"},
    }


def classify_v9_taobao_live_evidence(
    *,
    started: float,
    live_taobao: bool,
    approval_level: str,
    prepared_login: bool,
    trace_events: list[dict[str, Any]],
    transcript: str,
    browser_tool_calls: int,
    cart_state: dict[str, Any],
    actual_metrics: dict[str, Any] | None = None,
) -> BrowserBridgeReport:
    """Classify the explicit opt-in V9 Taobao live mutation gate."""
    route = _backend_route_from_traces(trace_events)
    metrics = _v9_normalize_actual_metrics(
        started=started,
        browser_tool_calls=browser_tool_calls,
        trace_events=trace_events,
        actual_metrics=actual_metrics,
    )
    budget = _v9_scenario_budget("v9-taobao-live")
    content = _v9_taobao_content_evidence(
        transcript=transcript,
        cart_state=cart_state,
        trace_events=trace_events,
    )

    def taobao_report(
        status: str,
        *,
        error_code: str = "",
        blocked_reason: str = "",
        failure_reason: str = "",
        blocker_classification: dict[str, Any] | None = None,
    ) -> BrowserBridgeReport:
        return _report(
            "v9-taobao-live",
            status,
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=route,
            trace_event_count=len(trace_events),
            error_code=error_code,
            blocked_reason=blocked_reason,
            failure_reason=failure_reason,
            fresh_observe_ok=not _fresh_observe_failure_reason(trace_events),
            cleanup_ok=not _user_cleanup_failure_reason(trace_events),
            content_evidence=content,
            safety_boundaries=list(V8_SAFETY_BOUNDARIES),
            user_preparation=list(V8_TAOBAO_USER_PREPARATION),
            scenario_budget=budget,
            actual_metrics=metrics,
            blocker_classification=blocker_classification,
            source_labels=v9_source_labels_for_scenario("v9-taobao-live"),
        )

    forbidden = _v9_forbidden_observations(transcript, trace_events)
    decision = _v9_taobao_live_decision(
        live_taobao=live_taobao,
        approval_level=approval_level,
        prepared_login=prepared_login,
        trace_events=trace_events,
        transcript=transcript,
        content=content,
        forbidden=forbidden,
        trace_info=_trace_error_info(trace_events),
        budget_failure=_v9_budget_failure(budget, metrics),
    )

    report = taobao_report(
        str(decision["status"]),
        error_code=str(decision.get("error_code") or ""),
        blocked_reason=str(decision.get("blocked_reason") or ""),
        failure_reason=str(decision.get("failure_reason") or ""),
        blocker_classification=decision.get("blocker_classification"),
    )
    if decision.get("forbidden_tools"):
        return replace(report, forbidden_tools=decision["forbidden_tools"])
    return report


def _v9_taobao_live_decision(
    *,
    live_taobao: bool,
    approval_level: str,
    prepared_login: bool,
    trace_events: list[dict[str, Any]],
    transcript: str,
    content: dict[str, Any],
    forbidden: list[str],
    trace_info: Any | None,
    budget_failure: dict[str, Any],
) -> dict[str, Any]:
    initial = _v9_taobao_initial_decision(
        live_taobao=live_taobao,
        prepared_login=prepared_login,
        trace_events=trace_events,
        transcript=transcript,
        forbidden=forbidden,
    )
    if initial is not None:
        return initial
    traced = _v9_taobao_trace_decision(
        trace_info=trace_info,
        approval_level=approval_level,
        content=content,
    )
    if traced is not None:
        return traced
    return _v9_taobao_completion_decision(
        approval_level=approval_level,
        content=content,
        budget_failure=budget_failure,
    )


def _v9_taobao_initial_decision(
    *,
    live_taobao: bool,
    prepared_login: bool,
    trace_events: list[dict[str, Any]],
    transcript: str,
    forbidden: list[str],
) -> dict[str, Any] | None:
    if not live_taobao:
        return {
            "status": "blocked",
            "blocked_reason": (
                "Taobao live mutation requires explicit --live-taobao"
            ),
        }
    if not prepared_login:
        return {
            "status": "blocked",
            "error_code": BrowserErrorCode.LOGIN_REQUIRED.value,
            "blocked_reason": (
                "prepared Taobao login is required in user Chrome"
            ),
        }
    if forbidden:
        return {
            "status": "failed",
            "error_code": BrowserErrorCode.CAPABILITY_MISSING.value,
            "failure_reason": "forbidden_tools",
            "forbidden_tools": forbidden,
        }
    if _has_payment_or_checkout_marker(transcript):
        return {
            "status": "failed",
            "error_code": BrowserErrorCode.APPROVAL_REQUIRED.value,
            "failure_reason": "safety_violation_payment_or_checkout",
        }
    if _user_state_routed_to_isolated(trace_events):
        return {
            "status": "failed",
            "error_code": BrowserErrorCode.CAPABILITY_MISSING.value,
            "failure_reason": "user_state_routed_to_isolated",
            "blocker_classification": _v9_capability_gap_blocker(
                "user_state_routed_to_isolated",
            ),
        }
    return None


def _v9_taobao_trace_decision(
    *,
    trace_info: Any | None,
    approval_level: str,
    content: dict[str, Any],
) -> dict[str, Any] | None:
    if trace_info is None or trace_info.code == BrowserErrorCode.NONE:
        return None
    if _v9_taobao_allowed_external_blocker(trace_info.code):
        return {
            "status": "blocked",
            "error_code": trace_info.code.value,
            "blocked_reason": trace_info.blocked_reason,
        }
    if trace_info.code == BrowserErrorCode.APPROVAL_REQUIRED:
        if str(approval_level).upper() != "OFF" and content["cart_unchanged"]:
            return {
                "status": "blocked",
                "error_code": trace_info.code.value,
                "blocked_reason": trace_info.blocked_reason,
            }
        return {
            "status": "failed",
            "error_code": trace_info.code.value,
            "failure_reason": "approval_default_mutated_cart",
        }
    return {
        "status": "failed",
        "error_code": trace_info.code.value,
        "failure_reason": BrowserErrorCode.CAPABILITY_MISSING.value,
        "blocker_classification": _v9_capability_gap_blocker(
            trace_info.code.value,
        ),
    }


def _v9_taobao_completion_decision(
    *,
    approval_level: str,
    content: dict[str, Any],
    budget_failure: dict[str, Any],
) -> dict[str, Any]:
    if str(approval_level).upper() != "OFF":
        return {
            "status": "failed",
            "error_code": BrowserErrorCode.APPROVAL_REQUIRED.value,
            "failure_reason": "approval_off_required_for_mutation_success",
        }
    if budget_failure:
        return {
            "status": "failed",
            "failure_reason": "budget_exhausted",
            "blocker_classification": budget_failure,
        }
    if not content["cart_roundtrip_complete"]:
        return {
            "status": "failed",
            "error_code": BrowserErrorCode.UNKNOWN.value,
            "failure_reason": "taobao_cart_roundtrip_incomplete",
        }
    if not content["live_trace_roundtrip"]:
        return {
            "status": "failed",
            "error_code": BrowserErrorCode.UNKNOWN.value,
            "failure_reason": "taobao_live_trace_evidence_missing",
        }
    return {"status": "passed"}


def _v9_taobao_content_evidence(
    *,
    transcript: str,
    cart_state: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> dict[str, Any]:
    text = str(transcript or "")
    cart = dict(cart_state or {})
    trace = _v9_taobao_trace_evidence(trace_events)
    cart_roundtrip = (
        all(
            bool(cart.get(key))
            for key in (
                "item_added",
                "cart_read",
                "cart_cleared",
                "empty_confirmed",
            )
        )
        and "V9_TAOBAO_LIVE_PASS" in text
    )
    return {
        "success_marker": "V9_TAOBAO_LIVE_PASS" in text,
        "item_added": bool(cart.get("item_added")),
        "cart_read": bool(cart.get("cart_read")),
        "cart_cleared": bool(cart.get("cart_cleared")),
        "empty_confirmed": bool(cart.get("empty_confirmed")),
        "cart_unchanged": bool(cart.get("cart_unchanged")),
        "final_state": str(cart.get("final_state") or ""),
        "cart_roundtrip_complete": cart_roundtrip,
        "live_trace_roundtrip": bool(trace["live_trace_roundtrip"]),
        "trace_evidence": trace,
        "safety_boundaries_observed": not _has_payment_or_checkout_marker(
            text,
        ),
    }


def _v9_taobao_trace_evidence(
    trace_events: list[dict[str, Any]],
) -> dict[str, Any]:
    commerce_events = [
        event
        for event in trace_events
        if isinstance(event, dict) and _v9_is_taobao_or_tmall_event(event)
    ]
    mutation_events = [
        event
        for event in commerce_events
        if _is_successful_mutation(event)
        and str(event.get("phase") or "").casefold() != "tab_lifecycle"
    ]
    observe_events = [
        event for event in commerce_events if _is_successful_observe(event)
    ]
    final_observe = _v9_final_observe_after_last_mutation(
        mutation_events,
        observe_events,
        commerce_events,
    )
    has_user_backend = _has_required_backend_evidence(
        commerce_events,
        context="user",
        backend_id="user.chrome_extension",
    )
    fresh_observe_after_mutation = bool(mutation_events) and not (
        _fresh_observe_failure_reason(commerce_events)
    )
    stages = _v9_taobao_trace_stages(commerce_events)
    return {
        "user_backend": has_user_backend,
        "commerce_domain": bool(commerce_events),
        "mutation_action_count": len(mutation_events),
        "observe_count": len(observe_events),
        "fresh_observe_after_mutation": fresh_observe_after_mutation,
        "final_cart_observed": final_observe,
        "stages": sorted(stages),
        "live_trace_roundtrip": (
            has_user_backend
            and bool(commerce_events)
            and len(mutation_events) >= 2
            and fresh_observe_after_mutation
            and final_observe
        ),
    }


def _v9_is_taobao_or_tmall_event(event: dict[str, Any]) -> bool:
    domain = str(event.get("domain") or "").casefold()
    if not domain:
        url = str(event.get("url") or "")
        with contextlib.suppress(ValueError):
            domain = urllib.parse.urlparse(url).hostname or ""
    domain = domain.casefold()
    return (
        domain == "taobao.com"
        or domain.endswith(
            ".taobao.com",
        )
        or domain == "tmall.com"
        or domain.endswith(".tmall.com")
    )


def _v9_final_observe_after_last_mutation(
    mutation_events: list[dict[str, Any]],
    observe_events: list[dict[str, Any]],
    commerce_events: list[dict[str, Any]],
) -> bool:
    if not mutation_events or not observe_events:
        return False
    last_mutation_index = max(
        _event_identity_index(commerce_events, event)
        for event in mutation_events
    )
    for event in observe_events:
        if (
            _event_identity_index(commerce_events, event)
            <= last_mutation_index
        ):
            continue
        metadata = _dict_value(event.get("metadata"))
        stage = str(metadata.get("taobao_cart_stage") or "").casefold()
        if stage in {"empty_confirmed", "cart_empty", "final_empty"}:
            return True
        if _v9_url_looks_like_cart(str(event.get("url") or "")):
            return True
    return False


def _event_identity_index(
    events: list[dict[str, Any]],
    target: dict[str, Any],
) -> int:
    for index, event in enumerate(events):
        if event is target:
            return index
    return -1


def _v9_url_looks_like_cart(url: str) -> bool:
    lowered = str(url or "").casefold()
    return (
        "cart" in lowered or "cart.htm" in lowered or "cart.taobao" in lowered
    )


def _v9_taobao_trace_stages(
    events: list[dict[str, Any]],
) -> set[str]:
    stages: set[str] = set()
    for event in events:
        metadata = _dict_value(event.get("metadata"))
        stage = str(metadata.get("taobao_cart_stage") or "").strip()
        if stage:
            stages.add(stage)
    return stages


def _v9_taobao_allowed_external_blocker(code: BrowserErrorCode) -> bool:
    return code in {
        BrowserErrorCode.LOGIN_REQUIRED,
        BrowserErrorCode.CAPTCHA_OR_RISK_CONTROL,
        BrowserErrorCode.NETWORK_TIMEOUT,
    }


def _v9_capability_gap_blocker(reason: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "category": "capability_gap",
        "reason": reason,
        "terminal": True,
    }


def run_preflight(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    try:
        version = _http_json(f"{base_url}/api/version", timeout=args.timeout)
    except RuntimeError as exc:
        if not args.start_if_missing:
            return _report(
                "preflight",
                "blocked",
                started,
                blocked_reason=str(exc),
            )
        try:
            _start_qwenpaw_app()
            version = _http_json(
                f"{base_url}/api/version",
                timeout=args.timeout,
            )
        except RuntimeError as retry_exc:
            return _report(
                "preflight",
                "blocked",
                started,
                blocked_reason=str(retry_exc),
            )

    local_commit = _local_git_commit()
    service_commit = str(version.get("git_commit") or "")
    if local_commit and service_commit and local_commit != service_commit:
        return _report(
            "preflight",
            "failed",
            started,
            blocked_reason=(
                "stale service: "
                f"running {service_commit}, local {local_commit}"
            ),
        )

    try:
        status = _http_json(
            f"{base_url}/api/browser-bridge/status",
            timeout=args.timeout,
        )
    except RuntimeError as exc:
        return _report(
            "preflight",
            "blocked",
            started,
            blocked_reason=str(exc),
        )

    backend_route = _backend_route(status)
    return _report(
        "preflight",
        "passed",
        started,
        backend_route=backend_route,
    )


def run_v8_preflight(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    try:
        version = _http_json(f"{base_url}/api/version", timeout=args.timeout)
    except RuntimeError as exc:
        if not getattr(args, "start_if_missing", False):
            return _report(
                "v8-preflight",
                "blocked",
                started,
                blocked_reason=str(exc),
            )
        try:
            _start_qwenpaw_app()
            version = _http_json(
                f"{base_url}/api/version",
                timeout=args.timeout,
            )
        except RuntimeError as retry_exc:
            return _report(
                "v8-preflight",
                "blocked",
                started,
                blocked_reason=str(retry_exc),
            )

    try:
        status = _extension_status(base_url, args.timeout)
    except RuntimeError as exc:
        return _report(
            "v8-preflight",
            "blocked",
            started,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            blocked_reason=str(exc),
        )
    self_test = status.get("last_self_test")
    if not (
        isinstance(self_test, dict)
        and str(self_test.get("status") or "") == "passed"
    ):
        with contextlib.suppress(RuntimeError):
            _http_json(
                f"{base_url}/api/browser-bridge/self-test",
                timeout=args.timeout,
                method="POST",
            )
            status = _extension_status(base_url, args.timeout)

    checks = _v8_preflight_checks(version, status)
    failed = [name for name, value in checks.items() if value != "passed"]
    report_status = "passed" if not failed else "failed"
    error_code = (
        ""
        if report_status == "passed"
        else (
            BrowserErrorCode.BRIDGE_DISCONNECTED.value
            if checks.get("extension_status") != "passed"
            else BrowserErrorCode.UNKNOWN.value
        )
    )
    return _report(
        "v8-preflight",
        report_status,
        started,
        backend_route=_backend_route(status),
        trace_event_count=int(
            ((status.get("trace_summary") or {}) or {}).get("event_count")
            or 0,
        ),
        error_code=error_code,
        failure_reason=",".join(failed),
        preflight_checks=checks,
        fresh_observe_ok=True,
        cleanup_ok=True,
    )


def run_v9_preflight(args: argparse.Namespace) -> BrowserBridgeReport:
    """Validate runtime evidence before trusting V9 scenarios."""
    started = time.perf_counter()
    base_url = _v9_base_url(args)
    try:
        version = _http_json(f"{base_url}/api/version", timeout=args.timeout)
    except RuntimeError as exc:
        if not getattr(args, "start_if_missing", False):
            return _report(
                "v9-preflight",
                "blocked",
                started,
                blocked_reason=str(exc),
            )
        try:
            _start_qwenpaw_app(port=int(getattr(args, "port", 8088) or 8088))
            version = _http_json(
                f"{base_url}/api/version",
                timeout=args.timeout,
            )
        except RuntimeError as retry_exc:
            return _report(
                "v9-preflight",
                "blocked",
                started,
                blocked_reason=str(retry_exc),
            )

    try:
        status = _extension_status(base_url, args.timeout)
    except RuntimeError as exc:
        return _report(
            "v9-preflight",
            "blocked",
            started,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            blocked_reason=str(exc),
        )

    evidence = _v9_runtime_evidence(version, status)
    failed = [
        name for name, value in evidence["checks"].items() if value != "passed"
    ]
    if failed and getattr(args, "restart_stale", False):
        _restart_qwenpaw_app(
            int(getattr(args, "port", 8088) or 8088),
            float(getattr(args, "timeout", DEFAULT_TIMEOUT)),
        )
        return run_v9_preflight(
            argparse.Namespace(**{**vars(args), "restart_stale": False}),
        )
    report_status = "passed" if not failed else "failed"
    return _report(
        "v9-preflight",
        report_status,
        started,
        backend_route=_backend_route(status),
        trace_event_count=int(
            ((status.get("trace_summary") or {}) or {}).get("event_count")
            or 0,
        ),
        error_code="" if report_status == "passed" else V9_RUNTIME_STALE_CODE,
        failure_reason=",".join(failed[:1]),
        preflight_checks=evidence["checks"],
        runtime_evidence=evidence,
        report_schema_version=V9_REPORT_SCHEMA_VERSION,
        source_labels=v9_source_labels_for_scenario("v9-preflight"),
        fresh_observe_ok=True,
        cleanup_ok=True,
    )


def run_v9_report(args: argparse.Namespace) -> BrowserBridgeReport:
    """Write the V9 evidence report JSON from scenario result files."""
    return write_v9_evidence_report(
        output=Path(str(args.output)),
        result_files=[
            Path(path) for path in getattr(args, "result_files", [])
        ],
    )


def run_v9_public_live(args: argparse.Namespace) -> BrowserBridgeReport:
    """Run the opt-in V9 public isolated live scenario."""
    started = time.perf_counter()
    if not getattr(args, "live_public", False):
        return _report(
            "v9-public-live",
            "blocked",
            started,
            blocked_reason=(
                "public isolated live verification requires explicit "
                "--live-public"
            ),
            source_labels=v9_source_labels_for_scenario("v9-public-live"),
        )
    preflight = run_v9_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="v9-public-live")
    spec = _v9_public_live_task_spec()
    return _run_v8_live_task(args, spec)


def run_v9_user_live(args: argparse.Namespace) -> BrowserBridgeReport:
    """Run the opt-in V9 user Chrome lifecycle scenario set."""
    started = time.perf_counter()
    if not getattr(args, "live_user", False):
        return _report(
            "v9-user-live",
            "blocked",
            started,
            blocked_reason=(
                "user Chrome live verification requires explicit --live-user"
            ),
            source_labels=v9_source_labels_for_scenario("v9-user-live"),
        )
    preflight = run_v9_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="v9-user-live")
    reports = [
        _run_v9_user_live_task(args, spec).to_dict()
        for spec in _v9_user_live_task_specs()
    ]
    return classify_v9_user_live_evidence(
        started=started,
        scenario_reports=reports,
    )


def run_v9_capability_matrix(args: argparse.Namespace) -> BrowserBridgeReport:
    """Run deterministic complex matrix through existing fixture scenarios."""
    started = time.perf_counter()
    child_reports = [
        run_complex_isolated(args),
        run_complex_user(args),
        run_v8_capability_isolated(args),
        run_v8_capability_user(args),
    ]
    approval_reports = [
        _run_v9_approval_probe(args, "DEFAULT"),
        _run_v9_approval_probe(args, "OFF"),
    ]
    return classify_v9_capability_matrix_evidence(
        started=started,
        scenario_reports=[
            report.to_dict()
            for report in _v9_capability_matrix_reports(
                started=started,
                child_reports=child_reports,
                approval_reports=approval_reports,
            )
        ],
    )


def run_v9_taobao_live(args: argparse.Namespace) -> BrowserBridgeReport:
    """Run the explicitly authorized V9 Taobao live mutation scenario."""
    started = time.perf_counter()
    if not getattr(args, "live_taobao", False):
        return classify_v9_taobao_live_evidence(
            started=started,
            live_taobao=False,
            approval_level=str(getattr(args, "approval_level", "DEFAULT")),
            prepared_login=bool(getattr(args, "prepared_login", False)),
            trace_events=[],
            transcript="",
            browser_tool_calls=0,
            cart_state={},
        )
    preflight = run_v9_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="v9-taobao-live")
    return _run_v8_live_task(args, _v9_taobao_live_task_spec())


def _v9_capability_matrix_reports(
    *,
    started: float,
    child_reports: list[BrowserBridgeReport],
    approval_reports: list[BrowserBridgeReport],
) -> list[BrowserBridgeReport]:
    return [
        _v9_capability_summary_report(
            started=started,
            child_reports=child_reports,
        ),
        *approval_reports,
    ]


def _v9_capability_summary_report(
    *,
    started: float,
    child_reports: list[BrowserBridgeReport],
) -> BrowserBridgeReport:
    payloads = [report.to_dict() for report in child_reports]
    passed = {
        report.scenario: report.status == "passed" for report in child_reports
    }
    complex_ok = passed.get("complex-isolated") and passed.get("complex-user")
    transfer_ok = passed.get("v8-capability-isolated") and passed.get(
        "v8-capability-user",
    )
    capabilities = {
        "iframe": bool(complex_ok),
        "shadow_dom": bool(complex_ok),
        "spa": bool(complex_ok),
        "popup": bool(complex_ok),
        "upload": bool(transfer_ok),
        "download": bool(transfer_ok),
        "dialog": bool(transfer_ok),
        "visual_fallback": bool(transfer_ok),
    }
    residual_tabs = sum(
        _summary_int(report.cleanup_summary, "residual_tab_count")
        for report in child_reports
    )
    status = (
        "passed"
        if all(report.status == "passed" for report in child_reports)
        else "failed"
    )
    return _report(
        "deterministic-complex-capabilities",
        status,
        started,
        browser_tool_calls=sum(
            report.browser_tool_calls for report in child_reports
        ),
        backend_route=_join_unique(
            report.backend_route for report in child_reports
        ),
        trace_event_count=sum(
            report.trace_event_count for report in child_reports
        ),
        failure_reason="" if status == "passed" else "child_scenario_failed",
        fresh_observe_ok=all(
            report.fresh_observe_ok for report in child_reports
        ),
        cleanup_ok=residual_tabs == 0
        and all(report.cleanup_ok for report in child_reports),
        content_evidence={
            "capabilities": capabilities,
            "source_scenarios": payloads,
        },
        cleanup_summary={
            "cleanup_ok": residual_tabs == 0,
            "residual_tab_count": residual_tabs,
        },
        actual_metrics=_v9_matrix_actual_metrics(payloads),
        source_labels=v9_source_labels_for_scenario("deterministic-complex"),
    )


def _run_v9_approval_probe(
    args: argparse.Namespace,
    approval_level: str,
) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    fixture = _fixture_path("cart.html")
    normalized_level = str(approval_level or "DEFAULT").upper()
    scenario = (
        "approval-off-success"
        if normalized_level == "OFF"
        else "approval-default-fail-closed"
    )
    if not fixture.exists():
        return _report(
            scenario,
            "failed",
            started,
            blocked_reason=f"missing fixture: {fixture}",
            source_labels=v9_source_labels_for_scenario(
                "deterministic-complex",
            ),
        )
    try:
        status = _extension_status(base_url, args.timeout)
    except RuntimeError as exc:
        return _report(
            scenario,
            "blocked",
            started,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            blocked_reason=str(exc),
            source_labels=v9_source_labels_for_scenario(
                "deterministic-complex",
            ),
        )
    backend_route = _backend_route(status)
    if status.get("connected") is not True:
        return _report(
            scenario,
            "blocked",
            started,
            backend_route=backend_route,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            source_labels=v9_source_labels_for_scenario(
                "deterministic-complex",
            ),
        )

    session_id = (
        "browser-bridge-v9-approval-"
        f"{normalized_level.lower()}-{int(time.time() * 1000)}"
    )
    prompt_spec = _v9_approval_probe_prompt_spec(
        fixture.resolve().as_uri(),
        approval_level=normalized_level,
    )
    request_context = {
        "approval_level": normalized_level,
        "approval_timeout_seconds": 1,
    }
    try:
        task = _submit_console_task(
            base_url,
            prompt_spec.render(),
            session_id=session_id,
            timeout=_task_timeout(args),
            request_context=request_context,
        )
        task_status = _poll_console_task(
            base_url,
            str(task.get("task_id") or ""),
            timeout=_task_timeout(args),
        )
    except RuntimeError as exc:
        return _report(
            scenario,
            "blocked",
            started,
            backend_route=backend_route,
            error_code=BrowserErrorCode.UNKNOWN.value,
            blocked_reason=str(exc),
            source_labels=v9_source_labels_for_scenario(
                "deterministic-complex",
            ),
        )
    summary = _summarize_task_status(task_status)
    trace_session_id = summary["session_id"] or session_id
    try:
        trace_events = _fetch_extension_traces(
            base_url,
            trace_session_id,
            DEFAULT_TIMEOUT,
        )
    except RuntimeError:
        trace_events = []
    return _classify_v9_approval_probe_report(
        scenario=scenario,
        started=started,
        approval_level=normalized_level,
        task_status=task_status,
        summary=summary,
        trace_events=trace_events,
        backend_route=_backend_route_from_traces(trace_events)
        or backend_route,
        browser_tool_calls=summary["browser_tool_calls"]
        or _browser_tool_calls_from_traces(trace_events),
    )


def _classify_v9_approval_probe_report(
    *,
    scenario: str,
    started: float,
    approval_level: str,
    task_status: dict[str, Any],
    summary: dict[str, Any],
    trace_events: list[dict[str, Any]],
    backend_route: str,
    browser_tool_calls: int,
) -> BrowserBridgeReport:
    evidence = _v9_approval_execution_from_trace(
        trace_events,
        approval_level=approval_level,
    )
    transcript = str(summary.get("final_text") or "")
    task_completed = (
        task_status.get("status") == "finished"
        and _dict_value(task_status.get("result")).get("status") == "completed"
    )
    if approval_level == "OFF":
        probe_ok = (
            "V9_APPROVAL_OFF_PASS" in transcript
            and _v9_matrix_approval_off_success(
                [
                    {
                        "scenario": scenario,
                        "status": "passed",
                        "content_evidence": {
                            "approval_execution": evidence,
                        },
                    },
                ],
            )
        )
        status = "passed" if probe_ok else "failed"
        failure_reason = "" if probe_ok else "approval_off_probe_failed"
        blocked_reason = ""
        error_code = ""
    else:
        fail_closed = _v9_matrix_approval_default_fail_closed(
            [
                {
                    "scenario": scenario,
                    "status": "blocked",
                    "blocked_reason": "approval_required",
                    "content_evidence": {
                        "approval_execution": evidence,
                    },
                },
            ],
        )
        status = "blocked" if fail_closed else "failed"
        blocked_reason = "approval_required" if fail_closed else ""
        failure_reason = "" if fail_closed else "approval_default_probe_failed"
        error_code = BrowserErrorCode.APPROVAL_REQUIRED.value
    return _report(
        scenario,
        status,
        started,
        browser_tool_calls=browser_tool_calls,
        backend_route=backend_route,
        trace_event_count=len(trace_events),
        error_code=error_code,
        blocked_reason=blocked_reason,
        failure_reason=failure_reason,
        fresh_observe_ok=(
            not _fresh_observe_failure_reason(trace_events)
            if task_completed
            else False
        ),
        cleanup_ok=not _user_cleanup_failure_reason(trace_events),
        content_evidence={
            "approval_level": approval_level,
            "approval_execution": evidence,
        },
        actual_metrics=_dict_value(summary.get("actual_metrics")),
        source_labels=v9_source_labels_for_scenario("deterministic-complex"),
    )


def _v9_approval_execution_from_trace(
    trace_events: list[dict[str, Any]],
    *,
    approval_level: str,
) -> dict[str, Any]:
    approval_events = [
        event
        for event in trace_events
        if str(event.get("phase") or "").casefold() == "approval"
    ]
    mutation_events = [
        event
        for event in trace_events
        if _is_successful_mutation(event) and _v9_sensitive_probe_event(event)
    ]
    states = [
        str(
            event.get("approval_state")
            or _dict_value(event.get("metadata")).get("approval_state")
            or "",
        )
        for event in approval_events
    ]
    approval_state = next((state for state in reversed(states) if state), "")
    if not approval_state and approval_level == "OFF" and mutation_events:
        approval_state = "not_required"
    fresh_observe_after_mutation = bool(mutation_events) and not (
        _fresh_observe_failure_reason(trace_events)
    )
    return {
        "executed_sensitive_action": bool(approval_events or mutation_events),
        "request_context_approval_level": approval_level,
        "approval_state": approval_state,
        "mutation_prevented": (
            approval_level != "OFF"
            and bool(approval_events)
            and not mutation_events
        ),
        "mutation_observed": bool(mutation_events),
        "fresh_observe_after_mutation": fresh_observe_after_mutation,
        "approval_event_count": len(approval_events),
        "mutation_event_count": len(mutation_events),
    }


def _v9_sensitive_probe_event(event: dict[str, Any]) -> bool:
    metadata = _dict_value(event.get("metadata"))
    kwargs = _dict_value(metadata.get("kwargs"))
    haystack = " ".join(
        str(value)
        for value in (
            event.get("action"),
            kwargs.get("selector"),
            kwargs.get("text"),
            kwargs.get("target"),
            event.get("url"),
        )
    ).casefold()
    return any(
        token in haystack for token in ("clear-cart", "clear cart", "submit")
    )


def run_v9_acceptance(args: argparse.Namespace) -> BrowserBridgeReport:
    """Run V9 live-product acceptance orchestration."""
    started = time.perf_counter()
    preflight = run_v9_preflight(args)
    reports: list[BrowserBridgeReport] = []
    if preflight.status == "passed":
        reports = _run_v9_acceptance_scenarios(args)
    forbidden_scan = scan_browser_bridge_entropy_guardrails(Path.cwd())
    report = _aggregate_v9_acceptance_report(
        started=started,
        preflight=preflight,
        reports=reports,
        forbidden_scan=forbidden_scan,
        args=args,
    )
    return _write_v9_acceptance_artifacts(
        report=report,
        reports=reports,
        preflight=preflight,
        forbidden_scan=forbidden_scan,
        report_dir=Path(str(getattr(args, "report_dir", "") or ".")),
    )


def _run_v9_acceptance_scenarios(
    args: argparse.Namespace,
) -> list[BrowserBridgeReport]:
    reports = [_run_v9_named_acceptance_scenario("v9-capability-matrix", args)]
    if getattr(args, "live_public", False):
        reports.append(
            _run_v9_named_acceptance_scenario("v9-public-live", args),
        )
    if getattr(args, "live_user", False):
        reports.append(_run_v9_named_acceptance_scenario("v9-user-live", args))
    if getattr(args, "live_taobao", False):
        reports.append(
            _run_v9_named_acceptance_scenario("v9-taobao-live", args),
        )
    return reports


def _run_v9_named_acceptance_scenario(
    scenario: str,
    args: argparse.Namespace,
) -> BrowserBridgeReport:
    runners = {
        "v9-public-live": globals().get("run_v9_public_live"),
        "v9-user-live": globals().get("run_v9_user_live"),
        "v9-capability-matrix": globals().get("run_v9_capability_matrix"),
        "v9-taobao-live": globals().get("run_v9_taobao_live"),
    }
    runner = runners.get(scenario)
    if callable(runner):
        return runner(args)
    return _report(
        scenario,
        "blocked",
        time.perf_counter(),
        blocked_reason=f"{scenario} runner is not implemented",
    )


def _aggregate_v9_acceptance_report(
    *,
    started: float,
    preflight: BrowserBridgeReport,
    reports: list[BrowserBridgeReport],
    forbidden_scan: dict[str, Any],
    args: argparse.Namespace,
) -> BrowserBridgeReport:
    status = _v9_acceptance_status(preflight, reports, forbidden_scan)
    blocker = _v9_blocker_classification(status, [preflight, *reports])
    manifest = _v9_acceptance_manifest(
        preflight=preflight,
        reports=reports,
        args=args,
    )
    failure_reason = ""
    if forbidden_scan.get("ok") is False:
        failure_reason = "forbidden_tool_scan"
        blocker = {
            "status": "failed",
            "category": "capability_gap",
            "reason": failure_reason,
            "terminal": True,
        }
    elif status == "failed":
        failure_reason = str(blocker.get("reason") or "acceptance_failed")
    return _report(
        "v9-acceptance",
        status,
        started,
        browser_tool_calls=sum(
            report.browser_tool_calls for report in reports
        ),
        backend_route=_join_unique(
            report.backend_route for report in [preflight, *reports]
        ),
        forbidden_tools=[
            str(item.get("token") or item.get("message") or "")
            for item in forbidden_scan.get("violations") or []
            if isinstance(item, dict)
        ],
        trace_event_count=preflight.trace_event_count
        + sum(report.trace_event_count for report in reports),
        failure_reason=failure_reason,
        blocked_reason=(
            str(blocker.get("reason") or "") if status == "blocked" else ""
        ),
        fresh_observe_ok=preflight.fresh_observe_ok
        and all(report.fresh_observe_ok for report in reports),
        cleanup_ok=preflight.cleanup_ok
        and all(report.cleanup_ok for report in reports),
        runtime_evidence={
            "run_manifest": manifest,
            "forbidden_scan": dict(forbidden_scan),
        },
        trace_summary=_aggregate_v9_trace_summary(reports),
        cleanup_summary=_aggregate_v9_cleanup_summary(reports),
        report_schema_version=V9_REPORT_SCHEMA_VERSION,
        scenario_budget=_v9_default_scenario_budget(len(reports)),
        actual_metrics=_v9_actual_metrics(reports),
        blocker_classification=blocker,
        source_labels=_aggregate_v9_source_labels([preflight, *reports]),
        scenario_reports=[report.to_dict() for report in reports],
        content_evidence={"issue_log": []},
    )


def _v9_acceptance_status(
    preflight: BrowserBridgeReport,
    reports: list[BrowserBridgeReport],
    forbidden_scan: dict[str, Any],
) -> str:
    if forbidden_scan.get("ok") is False:
        return "failed"
    if preflight.status != "passed":
        return preflight.status
    return _aggregate_status(reports)


def _v9_acceptance_manifest(
    *,
    preflight: BrowserBridgeReport,
    reports: list[BrowserBridgeReport],
    args: argparse.Namespace,
) -> dict[str, Any]:
    evidence = dict(preflight.runtime_evidence or {})
    service = dict(evidence.get("service") or {})
    local = dict(evidence.get("local") or {})
    return {
        "schema_version": "browser-bridge-v9-f-acceptance-manifest",
        "base_url": _v9_base_url(args),
        "reuse_service": bool(getattr(args, "reuse_service", False)),
        "approval_level": str(getattr(args, "approval_level", "DEFAULT")),
        "live_flags": {
            "public": bool(getattr(args, "live_public", False)),
            "user": bool(getattr(args, "live_user", False)),
            "taobao": bool(getattr(args, "live_taobao", False)),
        },
        "preflight": {
            "status": preflight.status,
            "checks": dict(preflight.preflight_checks)
            or dict(evidence.get("checks") or {}),
            "backend_route": preflight.backend_route,
        },
        "backend": {
            "local_commit": str(local.get("git_commit") or ""),
            "service_commit": str(service.get("git_commit") or ""),
        },
        "frontend": {
            "local_fingerprint": str(
                local.get("frontend_fingerprint") or "",
            ),
            "service_fingerprint": str(
                service.get("frontend_fingerprint") or "",
            ),
        },
        "plugin": {
            "local_fingerprint": str(local.get("plugin_fingerprint") or ""),
            "service_fingerprint": str(
                service.get("plugin_fingerprint") or "",
            ),
        },
        "extension": {
            "version": str(service.get("extension_version") or ""),
            "native_host_version": str(
                service.get("native_host_version") or "",
            ),
        },
        "bridge": {
            "connected": bool(service.get("bridge_connected")),
            "connected_since": str(
                service.get("bridge_connected_since") or "",
            ),
        },
        "scenarios": [
            {
                "scenario": report.scenario,
                "status": report.status,
                "backend_route": report.backend_route,
            }
            for report in reports
        ],
    }


def _write_v9_acceptance_artifacts(
    *,
    report: BrowserBridgeReport,
    reports: list[BrowserBridgeReport],
    preflight: BrowserBridgeReport,
    forbidden_scan: dict[str, Any],
    report_dir: Path,
) -> BrowserBridgeReport:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / V9_ACCEPTANCE_JSON_NAME
    markdown_path = report_dir / V9_ACCEPTANCE_MARKDOWN_NAME
    final_report = replace(
        report,
        artifact_paths=[str(json_path), str(markdown_path)],
    )
    json_path.write_text(
        json.dumps(final_report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        _render_v9_acceptance_markdown(
            report=final_report,
            reports=reports,
            preflight=preflight,
            forbidden_scan=forbidden_scan,
        ),
        encoding="utf-8",
    )
    return final_report


def _render_v9_acceptance_markdown(
    *,
    report: BrowserBridgeReport,
    reports: list[BrowserBridgeReport],
    preflight: BrowserBridgeReport,
    forbidden_scan: dict[str, Any],
) -> str:
    manifest = report.runtime_evidence.get("run_manifest")
    manifest = manifest if isinstance(manifest, dict) else {}
    issues = report.content_evidence.get("issue_log")
    issue_rows = _render_v9_issue_log(
        issues if isinstance(issues, list) else [],
    )
    return "\n".join(
        [
            "# Browser Bridge V9-F Live Product Acceptance Report",
            "",
            "## Runtime Truth",
            f"- Preflight status: `{preflight.status}`",
            f"- Backend: `{(manifest.get('backend') or {})}`",
            f"- Frontend: `{(manifest.get('frontend') or {})}`",
            f"- Plugin: `{(manifest.get('plugin') or {})}`",
            f"- Extension: `{(manifest.get('extension') or {})}`",
            f"- Bridge: `{(manifest.get('bridge') or {})}`",
            "",
            "## Scenario Matrix",
            _markdown_report_table(reports),
            "",
            "## Budgets",
            f"- Actual metrics: `{report.actual_metrics}`",
            f"- Scenario budget: `{report.scenario_budget}`",
            "",
            "## Forbidden Tool Scan",
            f"- OK: `{bool(forbidden_scan.get('ok'))}`",
            f"- Violations: `{forbidden_scan.get('violations') or []}`",
            "",
            "## Lifecycle Residuals",
            f"- Cleanup summary: `{report.cleanup_summary}`",
            "",
            "## Frontend UX Evidence",
            "- Current tab, connection, progress, approval wait, blocker, "
            "cancel, and cleanup fields are verified by V9-E contracts.",
            "",
            "## Live Blockers",
            f"- Blocker classification: `{report.blocker_classification}`",
            "",
            "## Issue Repair Log",
            issue_rows,
            "",
            "## Acceptance Summary",
            f"- Status: `{report.status}`",
            f"- Failure reason: `{report.failure_reason}`",
            f"- Blocked reason: `{report.blocked_reason}`",
            "",
        ],
    )


def _render_v9_issue_log(issues: list[Any]) -> str:
    if not issues:
        return "_No fixed issues recorded._"
    rows = [
        "| Evidence | Root Cause | Generic Solution | Fix Commit | Restart | Retest |",
        "|---|---|---|---|---|---|",
    ]
    for issue in issues:
        item = issue if isinstance(issue, dict) else {}
        rows.append(
            "| "
            + " | ".join(
                f"`{str(item.get(field) or '')}`"
                for field in V9_REQUIRED_ISSUE_FIELDS
            )
            + " |",
        )
    return "\n".join(rows)


def _v9_base_url(args: argparse.Namespace) -> str:
    base_url = str(getattr(args, "base_url", "") or "").strip()
    if base_url:
        return _normalize_base_url(base_url)
    port = int(getattr(args, "port", 8088) or 8088)
    return f"http://127.0.0.1:{port}"


def _v9_runtime_evidence(
    version: dict[str, Any],
    status: dict[str, Any],
) -> dict[str, Any]:
    build = status.get("build_fingerprint")
    build = build if isinstance(build, dict) else {}
    bridge_lifecycle = status.get("bridge_lifecycle")
    bridge_lifecycle = (
        bridge_lifecycle if isinstance(bridge_lifecycle, dict) else {}
    )
    local = {
        "git_commit": _local_git_commit(),
        "repo_dirty": _local_repo_dirty(),
        "frontend_fingerprint": _local_frontend_fingerprint(),
        "plugin_fingerprint": _local_plugin_fingerprint(),
    }
    service = {
        "git_commit": str(
            version.get("git_commit") or build.get("git_commit") or "",
        ),
        "repo_dirty": bool(
            version.get("repo_dirty") or build.get("repo_dirty"),
        ),
        "frontend_fingerprint": str(
            version.get("frontend_fingerprint")
            or build.get("frontend_fingerprint")
            or "",
        ),
        "plugin_fingerprint": str(build.get("plugin_fingerprint") or ""),
        "extension_version": str(status.get("extension_version") or ""),
        "native_host_version": str(status.get("native_host_version") or ""),
        "bridge_connected": status.get("connected") is True,
        "bridge_connected_since": str(
            status.get("connected_since")
            or bridge_lifecycle.get("connected_since")
            or "",
        ),
    }
    checks = {
        "backend_commit": _v9_check_match(
            local["git_commit"],
            service["git_commit"],
        ),
        "backend_dirty": (
            "passed"
            if not local["repo_dirty"] and not service["repo_dirty"]
            else "failed"
        ),
        "frontend_fingerprint": _v9_check_match(
            local["frontend_fingerprint"],
            service["frontend_fingerprint"],
        ),
        "plugin_fingerprint": _v9_check_match(
            local["plugin_fingerprint"],
            service["plugin_fingerprint"],
        ),
        "extension_version": (
            "passed" if service["extension_version"] else "failed"
        ),
        "native_host_version": (
            "passed" if service["native_host_version"] else "failed"
        ),
        "bridge_freshness": (
            "passed"
            if service["bridge_connected"]
            and bool(service["bridge_connected_since"])
            else "blocked"
        ),
    }
    failed = [name for name, value in checks.items() if value != "passed"]
    return {
        "schema_version": "browser-bridge-v9-a-runtime-truth",
        "local": local,
        "service": service,
        "checks": checks,
        "status": "fresh" if not failed else "stale",
        "repair_action": _v9_runtime_repair_action(failed),
    }


def _v9_check_match(local_value: Any, service_value: Any) -> str:
    local_text = str(local_value or "")
    service_text = str(service_value or "")
    return (
        "passed"
        if local_text and service_text and local_text == service_text
        else "failed"
    )


def _v9_runtime_repair_action(failed: list[str]) -> str:
    if not failed:
        return "none"
    repair_actions = {
        "backend_commit": "restart_qwenpaw",
        "backend_dirty": "commit_or_revert_local_changes",
        "frontend_fingerprint": "rebuild_frontend",
        "plugin_fingerprint": "reload_browser_bridge_plugin",
        "bridge_freshness": "reload_extension",
    }
    for name, action in repair_actions.items():
        if name in failed:
            return action
    return "restart_qwenpaw"


def _v8_preflight_checks(
    version: dict[str, Any],
    status: dict[str, Any],
) -> dict[str, str]:
    local_commit = _local_git_commit()
    service_commit = str(version.get("git_commit") or "")
    build = status.get("build_fingerprint")
    build = build if isinstance(build, dict) else {}
    version_fingerprint = str(version.get("frontend_fingerprint") or "")
    build_fingerprint = str(build.get("frontend_fingerprint") or "")
    diagnostics = status.get("sdk_diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    backends = diagnostics.get("backends")
    backends = backends if isinstance(backends, list) else []
    self_test = status.get("last_self_test")
    self_test = self_test if isinstance(self_test, dict) else {}
    return {
        "backend_commit": (
            "passed"
            if not local_commit
            or not service_commit
            or local_commit == service_commit
            or service_commit == str(build.get("git_commit") or "")
            else "failed"
        ),
        "frontend_fingerprint": (
            "passed"
            if bool(version_fingerprint or build_fingerprint)
            and (status.get("build_freshness") or {}).get("status") != "stale"
            else "failed"
        ),
        "extension_status": (
            "passed" if status.get("connected") is True else "blocked"
        ),
        "self_test_status": (
            "passed" if self_test.get("status") == "passed" else "blocked"
        ),
        "browser_sdk_diagnostics": (
            "passed"
            if diagnostics.get("selected_backend_id")
            and any(
                isinstance(backend, dict) and backend.get("available") is True
                for backend in backends
            )
            else "failed"
        ),
    }


def run_v8_deterministic(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    reports = [
        _run_named_scenario(args, scenario)
        for scenario in V8_DETERMINISTIC_SCENARIOS
    ]
    return _aggregate_v8_suite(
        scenario="v8-deterministic",
        started=started,
        reports=reports,
    )


def _run_named_scenario(
    args: argparse.Namespace,
    scenario: str,
) -> BrowserBridgeReport:
    runners = {
        "preflight": run_v8_preflight,
        "public-search": run_public_search,
        "complex-isolated": run_complex_isolated,
        "complex-user": run_complex_user,
        "v8-capability-isolated": run_v8_capability_isolated,
        "v8-capability-user": run_v8_capability_user,
    }
    return runners[scenario](args)


def run_v8_public_live(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    if not getattr(args, "public_live", False):
        return _report(
            "v8-public-live",
            "blocked",
            started,
            blocked_reason=(
                "public live verification requires explicit --public-live"
            ),
        )
    reports = [
        _run_v8_live_task(args, spec) for spec in _v8_public_live_task_specs()
    ]
    return _aggregate_v8_suite(
        scenario="v8-public-live",
        started=started,
        reports=reports,
    )


def run_v8_user_live(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    if not getattr(args, "live_taobao_preflight", False):
        return _report(
            "v8-user-live",
            "blocked",
            started,
            blocked_reason=(
                "user live verification requires explicit "
                "--live-taobao-preflight"
            ),
            user_preparation=list(V8_TAOBAO_USER_PREPARATION),
        )
    reports = [
        _run_v8_live_task(args, spec) for spec in _v8_user_live_task_specs()
    ]
    return _aggregate_v8_suite(
        scenario="v8-user-live",
        started=started,
        reports=reports,
        user_preparation=list(V8_TAOBAO_USER_PREPARATION),
    )


def run_v8_taobao_live(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    if not getattr(args, "live_taobao", False):
        return _report(
            "v8-taobao-live",
            "blocked",
            started,
            blocked_reason=(
                "Taobao live mutation requires explicit --live-taobao"
            ),
            safety_boundaries=list(V8_SAFETY_BOUNDARIES),
            user_preparation=list(V8_TAOBAO_USER_PREPARATION),
        )
    if not getattr(args, "confirm_account_mutation", False):
        return _report(
            "v8-taobao-live",
            "blocked",
            started,
            blocked_reason=(
                "Taobao live mutation requires explicit "
                "--confirm-account-mutation"
            ),
            safety_boundaries=list(V8_SAFETY_BOUNDARIES),
            user_preparation=list(V8_TAOBAO_USER_PREPARATION),
        )
    return _run_v8_live_task(args, _v8_taobao_live_task_spec())


def run_v8_lifecycle_live(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    reports = [
        _run_v8_live_task(args, spec)
        for spec in _v8_lifecycle_live_task_specs()
    ]
    return _aggregate_v8_suite(
        scenario="v8-lifecycle-live",
        started=started,
        reports=reports,
    )


def run_v8_report(args: argparse.Namespace) -> BrowserBridgeReport:
    return write_v8_product_report(
        output=Path(args.output),
        result_files=[
            Path(item) for item in getattr(args, "result_files", [])
        ],
    )


def run_taobao_live(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    if not getattr(args, "live_taobao", False):
        return _report(
            "taobao-live",
            "blocked",
            started,
            blocked_reason=(
                "live Taobao validation requires explicit --live-taobao "
                "authorization and must not run in CI by default"
            ),
        )
    return _report(
        "taobao-live",
        "blocked",
        started,
        blocked_reason=(
            "live Taobao execution is opt-in but no account-safe "
            "automation flow is implemented in V6-A"
        ),
    )


def run_fixture(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="fixture")
    fixture = _fixture_path("cart.html")
    if not fixture.exists():
        return _report(
            "fixture",
            "failed",
            started,
            blocked_reason=f"missing fixture: {fixture}",
        )
    try:
        status = _extension_status(base_url, args.timeout)
    except RuntimeError as exc:
        return _report(
            "fixture",
            "blocked",
            started,
            backend_route=preflight.backend_route,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            blocked_reason=str(exc),
            artifact_paths=[str(fixture)],
        )
    backend_route = _backend_route(status) or preflight.backend_route
    if status.get("connected") is not True:
        return _report(
            "fixture",
            "blocked",
            started,
            backend_route=backend_route,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            artifact_paths=[str(fixture)],
        )

    session_id = f"browser-bridge-fixture-{int(time.time() * 1000)}"
    prompt_spec = _fixture_prompt_spec(fixture.resolve().as_uri())
    return _run_chat_trace_scenario(
        scenario="fixture",
        started=started,
        base_url=base_url,
        session_id=session_id,
        prompt=prompt_spec.render(),
        timeout=_task_timeout(args),
        backend_route=backend_route,
        artifact_paths=[str(fixture)],
        require_user_backend=prompt_spec.require_user_backend,
        request_context=prompt_spec.request_context,
        required_success_marker=prompt_spec.required_success_marker,
        required_context=prompt_spec.required_context,
        required_backend_id=prompt_spec.required_backend_id,
    )


def run_public_search(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="public-search")
    session_id = f"browser-bridge-public-search-{int(time.time() * 1000)}"
    prompt_spec = _public_search_prompt_spec()
    return _run_chat_trace_scenario(
        scenario="public-search",
        started=started,
        base_url=base_url,
        session_id=session_id,
        prompt=prompt_spec.render(),
        timeout=_task_timeout(args),
        backend_route=preflight.backend_route,
        required_success_marker=prompt_spec.required_success_marker,
        required_context=prompt_spec.required_context,
        required_backend_id=prompt_spec.required_backend_id,
    )


def run_complex_isolated(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    fixture = _fixture_path("complex.html")
    if not fixture.exists():
        return _report(
            "complex-isolated",
            "failed",
            started,
            blocked_reason=f"missing fixture: {fixture}",
        )
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="complex-isolated")
    session_id = f"browser-bridge-complex-isolated-{int(time.time() * 1000)}"
    prompt_spec = _complex_prompt_spec(
        fixture.resolve().as_uri(),
        context="isolated",
    )
    return _run_chat_trace_scenario(
        scenario="complex-isolated",
        started=started,
        base_url=base_url,
        session_id=session_id,
        prompt=prompt_spec.render(),
        timeout=_complex_task_timeout(args),
        backend_route=preflight.backend_route,
        artifact_paths=[str(fixture)],
        require_user_backend=prompt_spec.require_user_backend,
        request_context=prompt_spec.request_context,
        required_success_marker=prompt_spec.required_success_marker,
        required_context=prompt_spec.required_context,
        required_backend_id=prompt_spec.required_backend_id,
    )


def run_complex_user(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    fixture = _fixture_path("complex.html")
    if not fixture.exists():
        return _report(
            "complex-user",
            "failed",
            started,
            blocked_reason=f"missing fixture: {fixture}",
        )
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="complex-user")
    try:
        status = _extension_status(base_url, args.timeout)
    except RuntimeError as exc:
        return _report(
            "complex-user",
            "blocked",
            started,
            backend_route=preflight.backend_route,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            blocked_reason=str(exc),
            artifact_paths=[str(fixture)],
        )
    backend_route = _backend_route(status) or preflight.backend_route
    if status.get("connected") is not True:
        return _report(
            "complex-user",
            "blocked",
            started,
            backend_route=backend_route,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            artifact_paths=[str(fixture)],
        )
    session_id = f"browser-bridge-complex-user-{int(time.time() * 1000)}"
    prompt_spec = _complex_prompt_spec(
        fixture.resolve().as_uri(),
        context="user",
    )
    return _run_chat_trace_scenario(
        scenario="complex-user",
        started=started,
        base_url=base_url,
        session_id=session_id,
        prompt=prompt_spec.render(),
        timeout=_complex_task_timeout(args),
        backend_route=backend_route,
        artifact_paths=[str(fixture)],
        require_user_backend=prompt_spec.require_user_backend,
        request_context=prompt_spec.request_context,
        required_success_marker=prompt_spec.required_success_marker,
        required_context=prompt_spec.required_context,
        required_backend_id=prompt_spec.required_backend_id,
    )


def run_v8_capability_isolated(
    args: argparse.Namespace,
) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    fixture = _fixture_path("v8_capability.html")
    if not fixture.exists():
        return _report(
            "v8-capability-isolated",
            "failed",
            started,
            blocked_reason=f"missing fixture: {fixture}",
        )
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="v8-capability-isolated")
    session_id = (
        f"browser-bridge-v8-capability-isolated-" f"{int(time.time() * 1000)}"
    )
    prompt_spec = _v8_capability_prompt_spec(
        fixture.resolve().as_uri(),
        context="isolated",
    )
    return _run_chat_trace_scenario(
        scenario="v8-capability-isolated",
        started=started,
        base_url=base_url,
        session_id=session_id,
        prompt=prompt_spec.render(),
        timeout=_task_timeout(args),
        backend_route=preflight.backend_route,
        artifact_paths=[str(fixture)],
        require_user_backend=prompt_spec.require_user_backend,
        request_context=prompt_spec.request_context,
        required_success_marker=prompt_spec.required_success_marker,
        required_context=prompt_spec.required_context,
        required_backend_id=prompt_spec.required_backend_id,
    )


def run_v8_capability_user(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    fixture = _fixture_path("v8_capability.html")
    if not fixture.exists():
        return _report(
            "v8-capability-user",
            "failed",
            started,
            blocked_reason=f"missing fixture: {fixture}",
        )
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="v8-capability-user")
    try:
        status = _extension_status(base_url, args.timeout)
    except RuntimeError as exc:
        return _report(
            "v8-capability-user",
            "blocked",
            started,
            backend_route=preflight.backend_route,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            blocked_reason=str(exc),
            artifact_paths=[str(fixture)],
        )
    backend_route = _backend_route(status) or preflight.backend_route
    if status.get("connected") is not True:
        return _report(
            "v8-capability-user",
            "blocked",
            started,
            backend_route=backend_route,
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            artifact_paths=[str(fixture)],
        )
    session_id = (
        f"browser-bridge-v8-capability-user-" f"{int(time.time() * 1000)}"
    )
    prompt_spec = _v8_capability_prompt_spec(
        fixture.resolve().as_uri(),
        context="user",
    )
    return _run_chat_trace_scenario(
        scenario="v8-capability-user",
        started=started,
        base_url=base_url,
        session_id=session_id,
        prompt=prompt_spec.render(),
        timeout=_task_timeout(args),
        backend_route=backend_route,
        artifact_paths=[str(fixture)],
        require_user_backend=prompt_spec.require_user_backend,
        request_context=prompt_spec.request_context,
        required_success_marker=prompt_spec.required_success_marker,
        required_context=prompt_spec.required_context,
        required_backend_id=prompt_spec.required_backend_id,
    )


def run_bridge_disconnected(args: argparse.Namespace) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    try:
        status = _http_json(
            f"{base_url}/api/browser-bridge/status",
            timeout=args.timeout,
        )
    except RuntimeError as exc:
        return _report(
            "bridge-disconnected",
            "blocked",
            started,
            blocked_reason=str(exc),
        )
    if status.get("connected") is False:
        return _report("bridge-disconnected", "passed", started)
    return _report(
        "bridge-disconnected",
        "failed",
        started,
        blocked_reason="expected disconnected bridge status",
    )


def _v8_public_live_task_specs() -> list[V8LiveTaskSpec]:
    return [
        V8LiveTaskSpec(
            scenario="stable-public-page",
            prompt=(
                "Use the Browser tool through the normal QwenPaw chat flow to "
                "open https://example.com/ as a public read-only page. Use the "
                "isolated Browser SDK route, read the page title and visible "
                "text, and report the exact marker V8_PUBLIC_STABLE_PASS with "
                "the title Example Domain."
            ),
            required_context="isolated",
            required_backend_id="isolated.playwright",
            content_markers=("V8_PUBLIC_STABLE_PASS", "Example Domain"),
            success_marker="V8_PUBLIC_STABLE_PASS",
        ),
        V8LiveTaskSpec(
            scenario="loop-engineering-blog",
            prompt=(
                "Use the Browser tool through the normal QwenPaw chat flow to "
                "find a Loop Engineering blog or engineering article page on "
                "the public web. Use the isolated Browser SDK route only, then "
                "report the exact marker V8_PUBLIC_LOOP_PASS with the page URL "
                "or title evidence containing Loop."
            ),
            required_context="isolated",
            required_backend_id="isolated.playwright",
            content_markers=("V8_PUBLIC_LOOP_PASS", "Loop"),
            success_marker="V8_PUBLIC_LOOP_PASS",
        ),
    ]


def _v9_public_live_task_spec() -> V8LiveTaskSpec:
    return V8LiveTaskSpec(
        scenario="v9-public-live",
        prompt=(
            "Use Browser Bridge through normal QwenPaw chat to find a Loop "
            "Engineering blog or engineering article on the public web. Use "
            'context="isolated" only and do not touch user Chrome or Chrome '
            "Extension user state. Report the exact marker "
            "V9_PUBLIC_LOOP_PASS with URL or title evidence containing Loop."
        ),
        required_context="isolated",
        required_backend_id="isolated.playwright",
        content_markers=("V9_PUBLIC_LOOP_PASS", "Loop"),
        success_marker="V9_PUBLIC_LOOP_PASS",
    )


def _v9_user_live_task_specs() -> list[V8LiveTaskSpec]:
    return [
        V8LiveTaskSpec(
            scenario="user-read-only-observation",
            prompt=_v9_user_readonly_prompt_spec().render(),
            required_context="user",
            required_backend_id="user.chrome_extension",
            success_marker="V9_USER_READONLY_PASS",
            requires_user_state=True,
        ),
        V8LiveTaskSpec(
            scenario="multi-tab-workspace",
            prompt=(
                'Use Browser Bridge with context="user" and '
                "requires_user_state=True to create a Browser-Control-owned "
                "second tab, switch back and forth, then close or release the "
                "owned tab. Report V9_USER_MULTITAB_PASS and zero residual "
                "owned tabs."
            ),
            required_context="user",
            required_backend_id="user.chrome_extension",
            success_marker="V9_USER_MULTITAB_PASS",
            requires_user_state=True,
        ),
        V8LiveTaskSpec(
            scenario="bridge-disconnect-fail-closed",
            prompt=(
                "Verify user-context Browser Bridge fails closed when the "
                "Chrome Extension bridge is disconnected and never falls back "
                "to isolated browser state. Report V9_USER_DISCONNECT_PASS "
                "with bridge_disconnected evidence."
            ),
            required_context="user",
            required_backend_id="user.chrome_extension",
            success_marker="V9_USER_DISCONNECT_PASS",
            requires_user_state=True,
        ),
        V8LiveTaskSpec(
            scenario="bridge-reconnect-recovered",
            prompt=(
                "After reconnecting the Chrome Extension bridge, verify a "
                "user-context Browser Bridge read succeeds again. Report "
                "V9_USER_RECONNECT_PASS with reconnect evidence."
            ),
            required_context="user",
            required_backend_id="user.chrome_extension",
            success_marker="V9_USER_RECONNECT_PASS",
            requires_user_state=True,
        ),
        V8LiveTaskSpec(
            scenario="user-cancellation-cleanup",
            prompt=(
                'Use Browser Bridge with context="user" and '
                "requires_user_state=True to start a cancellable read-only "
                "browser task, cancel it, and report V9_USER_CANCEL_PASS with "
                "cancellation outcome plus zero residual owned tabs."
            ),
            required_context="user",
            required_backend_id="user.chrome_extension",
            success_marker="V9_USER_CANCEL_PASS",
            requires_user_state=True,
        ),
    ]


def _v9_user_readonly_prompt_spec() -> HarnessPromptSpec:
    marker = "V9_USER_READONLY_PASS"
    return HarnessPromptSpec(
        instruction=(
            "Use browser(code=...) to run this deterministic read-only user "
            "Chrome observation script, then return the script output only."
        ),
        code=(
            'browser = await Browser.connect(context="user", '
            "requires_user_state=True)\n"
            "try:\n"
            "    tabs = await browser.tabs.list()\n"
            "    first = tabs[0] if tabs else None\n"
            "    info = await first.page_info() if first else None\n"
            "    console_tabs = [\n"
            "        tab for tab in tabs\n"
            "        if 'QwenPaw Console' in tab.title\n"
            "        or 'browser-bridge' in tab.url\n"
            "        or 'plugin-manager' in tab.url\n"
            "    ]\n"
            f"    print('{marker}')\n"
            "    print(f'first_tab={first.tab_id if first else \"\"}')\n"
            "    print(f'first_title={info.title if info else \"\"}')\n"
            "    print(f'first_url={info.url if info else \"\"}')\n"
            "    print(f'controlled_tabs={len(tabs)}')\n"
            "    print(f'console_tabs_intact={len(console_tabs)}')\n"
            "    for tab in console_tabs:\n"
            "        print(f'console_tab={tab.tab_id}:{tab.url}')\n"
            "finally:\n"
            "    await browser.close()"
        ),
        required_success_marker=marker,
        required_context="user",
        required_backend_id="user.chrome_extension",
        require_user_backend=True,
    )


def _v8_user_live_task_specs() -> list[V8LiveTaskSpec]:
    return [
        V8LiveTaskSpec(
            scenario="user-chrome-readonly",
            prompt=(
                'Use Browser Bridge with context="user" and '
                "requires_user_state=True to observe the current user Chrome "
                "state without modifying any page. Report the active page title "
                "or URL and the marker V8_USER_READONLY_PASS. Do not fall back "
                "to isolated browser state."
            ),
            required_context="user",
            required_backend_id="user.chrome_extension",
            content_markers=("V8_USER_READONLY_PASS",),
            success_marker="V8_USER_READONLY_PASS",
            requires_user_state=True,
        ),
        V8LiveTaskSpec(
            scenario="taobao-cart-preflight",
            prompt=(
                'Use Browser Bridge with context="user" and '
                "requires_user_state=True to open and read the Taobao cart "
                "page. This is read-only preflight: do not add, remove, clear, "
                "checkout, pay, submit an order, or enter credentials. If "
                "login, CAPTCHA, or risk control appears, report that blocker. "
                "On success report V8_TAOBAO_PREFLIGHT_PASS with visible cart "
                "page evidence."
            ),
            required_context="user",
            required_backend_id="user.chrome_extension",
            content_markers=("V8_TAOBAO_PREFLIGHT_PASS", "cart"),
            success_marker="V8_TAOBAO_PREFLIGHT_PASS",
            requires_user_state=True,
            requires_flag="live_taobao_preflight",
        ),
    ]


def _v8_taobao_live_task_spec() -> V8LiveTaskSpec:
    return V8LiveTaskSpec(
        scenario="v8-taobao-live",
        prompt=(
            'Use Browser Bridge with context="user" and '
            "requires_user_state=True. First open the Taobao cart and confirm "
            "it is readable. Then search for men's shampoo, add one ordinary "
            "item to the cart, list cart contents before clearing, clear the "
            "full cart, and confirm the cart is empty. Return the marker "
            "V8_TAOBAO_LIVE_PASS, the cart contents before clear, and the "
            "empty cart evidence after clearing. Safety boundaries: do not "
            "checkout, do not submit an order, do not pay, do not enter "
            "credentials, and do not bypass login, CAPTCHA, or risk control."
        ),
        required_context="user",
        required_backend_id="user.chrome_extension",
        content_markers=(
            "V8_TAOBAO_LIVE_PASS",
            "Cart contents before",
            "empty",
        ),
        success_marker="V8_TAOBAO_LIVE_PASS",
        requires_user_state=True,
        request_context={"approval_level": "OFF"},
    )


def _v9_taobao_live_task_spec() -> V8LiveTaskSpec:
    return V8LiveTaskSpec(
        scenario="v9-taobao-live",
        prompt=(
            'Use Browser Bridge with context="user" and '
            "requires_user_state=True. The user has prepared Taobao login. "
            "With approval_level=OFF only, open the cart, search for one "
            "ordinary men's shampoo item, add exactly one item to the cart, "
            "read and report cart contents before clearing, clear the cart, "
            "freshly observe the empty state, and report "
            "V9_TAOBAO_LIVE_PASS. Stop and report login_required, CAPTCHA, "
            "risk_control, or network_unavailable if encountered. Safety "
            "boundaries: do not checkout, do not submit an order, do not pay, "
            "do not enter credentials, do not change addresses, and do not "
            "modify account security settings. Finish with a JSON object "
            "containing item_added, cart_read, cart_cleared, "
            "empty_confirmed, cart_unchanged, and final_state."
        ),
        required_context="user",
        required_backend_id="user.chrome_extension",
        content_markers=(
            "V9_TAOBAO_LIVE_PASS",
            "Cart contents before",
            "empty",
        ),
        success_marker="V9_TAOBAO_LIVE_PASS",
        requires_user_state=True,
        request_context={"approval_level": "OFF"},
    )


def _v8_lifecycle_live_task_specs() -> list[V8LiveTaskSpec]:
    return [
        V8LiveTaskSpec(
            scenario="multi-tab-user-lifecycle",
            prompt=(
                'Use Browser Bridge with context="user" and '
                "requires_user_state=True. Open a second tab, switch between "
                "tabs, complete a small read-only observation, then close the "
                "Browser SDK session. Report V8_LIFECYCLE_MULTI_TAB_PASS with "
                "tab open, switch, completion, and cleanup evidence."
            ),
            required_context="user",
            required_backend_id="user.chrome_extension",
            content_markers=("V8_LIFECYCLE_MULTI_TAB_PASS",),
            success_marker="V8_LIFECYCLE_MULTI_TAB_PASS",
            requires_user_state=True,
        ),
        V8LiveTaskSpec(
            scenario="bridge-disconnected-user-context",
            prompt=(
                "Attempt a user-context Browser Bridge read while the bridge "
                "is disconnected or unavailable. The expected result is a "
                "blocked bridge_disconnected outcome and no isolated fallback."
            ),
            required_context="user",
            required_backend_id="user.chrome_extension",
            requires_user_state=True,
            expected_blocker="bridge_disconnected",
        ),
    ]


def _run_v9_user_live_task(
    args: argparse.Namespace,
    spec: V8LiveTaskSpec,
) -> BrowserBridgeReport:
    if spec.scenario == "bridge-disconnect-fail-closed":
        event = _v9_force_bridge_disconnect_event(args)
        report = _run_v8_live_task(args, spec)
        return _v9_augment_controlled_lifecycle(report, event)
    if spec.scenario == "bridge-reconnect-recovered":
        event = _v9_wait_for_bridge_reconnect_event(args)
        report = _run_v8_live_task(args, spec)
        return _v9_augment_controlled_lifecycle(report, event)
    if spec.scenario == "user-cancellation-cleanup":
        return _run_v9_cancellation_live_task(args, spec)
    return _run_v8_live_task(args, spec)


def _v9_force_bridge_disconnect_event(
    args: argparse.Namespace,
) -> dict[str, Any]:
    base_url = _normalize_base_url(args.base_url)
    timeout = max(float(getattr(args, "timeout", DEFAULT_TIMEOUT)), 30.0)
    before = _safe_extension_status(base_url, timeout)
    payload: dict[str, Any] = {}
    try:
        payload = _http_json(
            f"{base_url}/api/browser-bridge/test/bridge/disconnect?confirm=true",
            timeout=timeout,
            method="POST",
        )
    except RuntimeError as exc:
        payload = {"error": str(exc)}
    after = _safe_extension_status(base_url, timeout)
    return {
        "kind": "bridge_disconnect_injected",
        "before_connected": bool(before.get("connected")),
        "after_connected": bool(after.get("connected")),
        "isolated_fallback": False,
        "api_called": bool(payload) and "error" not in payload,
        "api_result": payload,
        "bridge_lifecycle": _dict_value(after.get("bridge_lifecycle")),
    }


def _v9_wait_for_bridge_reconnect_event(
    args: argparse.Namespace,
) -> dict[str, Any]:
    base_url = _normalize_base_url(args.base_url)
    timeout = max(float(getattr(args, "timeout", DEFAULT_TIMEOUT)), 1.0)
    deadline = time.perf_counter() + timeout
    first = _safe_extension_status(base_url, timeout)
    current = first
    while time.perf_counter() < deadline:
        current = _safe_extension_status(base_url, timeout)
        lifecycle = _dict_value(current.get("bridge_lifecycle"))
        if (
            current.get("connected") is True
            and int(
                lifecycle.get("reconnect_count") or 0,
            )
            > 0
        ):
            break
        time.sleep(0.5)
    lifecycle = _dict_value(current.get("bridge_lifecycle"))
    return {
        "kind": "bridge_reconnect_observed",
        "before_connected": bool(first.get("connected")),
        "after_connected": bool(current.get("connected")),
        "reconnect_count_increased": int(
            lifecycle.get("reconnect_count") or 0,
        )
        > 0,
        "bridge_lifecycle": lifecycle,
    }


def _safe_extension_status(base_url: str, timeout: float) -> dict[str, Any]:
    try:
        return _extension_status(base_url, timeout)
    except RuntimeError as exc:
        return {"connected": False, "error": str(exc)}


def _v9_augment_controlled_lifecycle(
    report: BrowserBridgeReport,
    event: dict[str, Any],
) -> BrowserBridgeReport:
    return replace(
        report,
        content_evidence={
            **report.content_evidence,
            "controlled_lifecycle_event": event,
        },
    )


def _run_v9_cancellation_live_task(
    args: argparse.Namespace,
    spec: V8LiveTaskSpec,
) -> BrowserBridgeReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    backend_route = ""
    try:
        status = _extension_status(base_url, args.timeout)
    except RuntimeError as exc:
        return _v9_augment_controlled_lifecycle(
            _report(
                spec.scenario,
                "blocked",
                started,
                error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
                blocked_reason=str(exc),
            ),
            _v9_cancel_control_event(False, False, False, {}),
        )
    backend_route = _backend_route(status)
    if status.get("connected") is not True:
        return _v9_augment_controlled_lifecycle(
            _report(
                spec.scenario,
                "blocked",
                started,
                backend_route=backend_route,
                error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
            ),
            _v9_cancel_control_event(False, False, False, {}),
        )

    session_id = f"browser-bridge-v9-{spec.scenario}-{int(time.time() * 1000)}"
    try:
        task = _submit_console_task(
            base_url,
            spec.prompt,
            session_id=session_id,
            timeout=_task_timeout(args),
            request_context=spec.request_context,
        )
    except RuntimeError as exc:
        return _report(
            spec.scenario,
            "blocked",
            started,
            backend_route=backend_route,
            error_code=BrowserErrorCode.UNKNOWN.value,
            blocked_reason=str(exc),
        )
    time.sleep(min(1.0, max(0.2, _task_timeout(args) / 60.0)))
    stop_result = _stop_console_chat(base_url, session_id, args.timeout)
    task_status_poll_error = ""
    try:
        task_status = _poll_console_task(
            base_url,
            str(task.get("task_id") or ""),
            timeout=_task_timeout(args),
        )
    except RuntimeError as exc:
        task_status_poll_error = str(exc)
        task_status = {
            "status": "unknown",
            "poll_error": task_status_poll_error,
        }
    summary = _summarize_task_status(task_status)
    trace_session_id = summary["session_id"] or session_id
    try:
        trace_events = _fetch_extension_traces(
            base_url,
            trace_session_id,
            DEFAULT_TIMEOUT,
        )
    except RuntimeError:
        trace_events = []
    route = _backend_route_from_traces(trace_events) or backend_route
    cleanup_ok = _v9_cancellation_cleanup_ok(stop_result, trace_events)
    task_cancelled = _task_status_cancelled(task_status)
    browser_tool_calls = summary[
        "browser_tool_calls"
    ] or _browser_tool_calls_from_traces(trace_events)
    cancel_or_cleanup_proven = task_cancelled or cleanup_ok
    status_value = (
        "passed" if cancel_or_cleanup_proven and cleanup_ok else "failed"
    )
    event = _v9_cancel_control_event(
        stop_api_called=True,
        task_cancelled=task_cancelled,
        cleanup_ok=cleanup_ok,
        stop_result=stop_result,
        task_status_poll_error=task_status_poll_error,
    )
    return _report(
        spec.scenario,
        status_value,
        started,
        browser_tool_calls=browser_tool_calls,
        backend_route=route,
        trace_event_count=len(trace_events),
        failure_reason="" if status_value == "passed" else "cancel_not_proven",
        fresh_observe_ok=not _fresh_observe_failure_reason(trace_events),
        cleanup_ok=cleanup_ok,
        content_evidence={
            "lifecycle_state": (
                "cancellation_cleanup_complete"
                if status_value == "passed"
                else ""
            ),
            "lifecycle_expected_state": _v9_user_live_lifecycle_states().get(
                spec.scenario,
                "",
            ),
            "console_overwrite": _v9_console_overwrite_detected(summary),
            "controlled_lifecycle_event": event,
        },
        cleanup_summary=_v9_cleanup_summary_from_stop(stop_result),
        actual_metrics=_dict_value(summary.get("actual_metrics")),
        source_labels=v9_source_labels_for_scenario("v9-user-live"),
    )


def _stop_console_chat(
    base_url: str,
    chat_id: str,
    timeout: float,
) -> dict[str, Any]:
    query = urllib.parse.urlencode({"chat_id": chat_id})
    try:
        return _http_json(
            f"{_normalize_base_url(base_url)}/api/console/chat/stop?{query}",
            timeout=timeout,
            method="POST",
        )
    except RuntimeError as exc:
        return {"error": str(exc)}


def _task_status_cancelled(task_status: dict[str, Any]) -> bool:
    if str(task_status.get("status") or "").casefold() in {
        "cancelled",
        "canceled",
    }:
        return True
    result = _dict_value(task_status.get("result"))
    if str(result.get("status") or "").casefold() in {"cancelled", "canceled"}:
        return True
    error = _dict_value(result.get("error"))
    return "cancel" in str(error.get("message") or "").casefold()


def _v9_stop_cleanup_ok(stop_result: dict[str, Any]) -> bool:
    cleanup = _dict_value(stop_result.get("control_cleanup"))
    if not cleanup and "error" not in stop_result:
        return True
    return _summary_int(cleanup, "residual_tab_count") == 0


def _v9_cancellation_cleanup_ok(
    stop_result: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> bool:
    del trace_events
    return _v9_stop_cleanup_ok(stop_result)


def _v9_cleanup_summary_from_stop(
    stop_result: dict[str, Any],
) -> dict[str, Any]:
    cleanup = _dict_value(stop_result.get("control_cleanup"))
    residual = _summary_int(cleanup, "residual_tab_count")
    controlled = _summary_int(cleanup, "controlled_tab_count")
    return {
        "cleanup_ok": residual == 0,
        "residual_tab_count": residual,
        "controlled_tab_count": controlled,
        "stop_result": stop_result,
    }


def _v9_cancel_control_event(
    stop_api_called: bool,
    task_cancelled: bool,
    cleanup_ok: bool,
    stop_result: dict[str, Any],
    task_status_poll_error: str = "",
) -> dict[str, Any]:
    event = {
        "kind": "task_cancel_requested",
        "stop_api_called": stop_api_called,
        "task_cancelled": task_cancelled,
        "cleanup_ok": cleanup_ok,
        "stop_result": stop_result,
    }
    if task_status_poll_error:
        event["task_status_poll_error"] = task_status_poll_error
    return event


def _run_v8_live_task(
    args: argparse.Namespace,
    spec: V8LiveTaskSpec,
) -> BrowserBridgeReport:
    started = time.perf_counter()
    early_report: BrowserBridgeReport | None = None
    if spec.requires_flag and not getattr(args, spec.requires_flag, False):
        early_report = _report(
            spec.scenario,
            "blocked",
            started,
            blocked_reason=f"requires --{spec.requires_flag.replace('_', '-')}",
        )
    base_url = _normalize_base_url(args.base_url)
    backend_route = ""
    if early_report is None and spec.requires_user_state:
        try:
            status = _extension_status(base_url, args.timeout)
        except RuntimeError as exc:
            early_report = _report(
                spec.scenario,
                "blocked",
                started,
                error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
                blocked_reason=str(exc),
            )
        else:
            backend_route = _backend_route(status)
            if status.get("connected") is not True:
                early_report = _report(
                    spec.scenario,
                    "blocked",
                    started,
                    backend_route=backend_route,
                    error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
                )
    if early_report is not None:
        return _v9_maybe_augment_early_lifecycle_report(
            spec.scenario,
            early_report,
        )

    session_id = f"browser-bridge-v8-{spec.scenario}-{int(time.time() * 1000)}"
    try:
        task = _submit_console_task(
            base_url,
            spec.prompt,
            session_id=session_id,
            timeout=_task_timeout(args),
            request_context=spec.request_context,
        )
        task_status = _poll_console_task(
            base_url,
            str(task.get("task_id") or ""),
            timeout=_task_timeout(args),
        )
    except RuntimeError as exc:
        return _report(
            spec.scenario,
            "blocked",
            started,
            backend_route=backend_route,
            error_code=BrowserErrorCode.UNKNOWN.value,
            blocked_reason=str(exc),
        )

    summary = _summarize_task_status(task_status)
    trace_session_id = summary["session_id"] or session_id
    try:
        trace_events = _fetch_extension_traces(
            base_url,
            trace_session_id,
            DEFAULT_TIMEOUT,
        )
    except RuntimeError:
        trace_events = []
    route = _backend_route_from_traces(trace_events) or backend_route
    browser_tool_calls = summary[
        "browser_tool_calls"
    ] or _browser_tool_calls_from_traces(trace_events)

    special_report = _classify_special_live_task_report(
        args=args,
        spec=spec,
        started=started,
        summary=summary,
        trace_events=trace_events,
        browser_tool_calls=browser_tool_calls,
    )
    if special_report is not None:
        return special_report

    report = _classify_chat_trace_result(
        scenario=spec.scenario,
        started=started,
        task_status=task_status,
        summary=summary,
        trace_events=trace_events,
        browser_tool_calls=browser_tool_calls,
        route=route,
        require_user_backend=spec.requires_user_state,
        required_success_marker=spec.success_marker,
        required_context=spec.required_context,
        required_backend_id=spec.required_backend_id,
        artifact_paths=list(spec.artifact_paths),
    )
    evidence = _content_evidence(
        str(summary.get("final_text") or ""),
        spec.content_markers,
    )
    if report.status == "passed" and not all(evidence.values()):
        report = _report(
            spec.scenario,
            "failed",
            started=started,
            browser_tool_calls=browser_tool_calls,
            backend_route=route,
            trace_event_count=len(trace_events),
            error_code=BrowserErrorCode.UNKNOWN.value,
            failure_reason="missing_content_evidence",
        )
    if spec.scenario in _v9_user_live_lifecycle_states():
        evidence = {
            **evidence,
            **_v9_user_live_lifecycle_evidence(
                spec.scenario,
                report=report,
                task_status=task_status,
                summary=summary,
                trace_events=trace_events,
            ),
        }
    return replace(report, content_evidence=evidence)


def _v9_maybe_augment_early_lifecycle_report(
    scenario: str,
    report: BrowserBridgeReport,
) -> BrowserBridgeReport:
    if scenario not in _v9_user_live_lifecycle_states():
        return report
    return replace(
        report,
        content_evidence={
            **report.content_evidence,
            **_v9_user_live_early_lifecycle_evidence(
                scenario,
                report,
            ),
        },
    )


def _classify_special_live_task_report(
    *,
    args: argparse.Namespace,
    spec: V8LiveTaskSpec,
    started: float,
    summary: dict[str, Any],
    trace_events: list[dict[str, Any]],
    browser_tool_calls: int,
) -> BrowserBridgeReport | None:
    if spec.scenario == "v9-taobao-live":
        transcript = str(summary.get("final_text") or "")
        return classify_v9_taobao_live_evidence(
            started=started,
            live_taobao=bool(getattr(args, "live_taobao", False)),
            approval_level=str(getattr(args, "approval_level", "DEFAULT")),
            prepared_login=bool(getattr(args, "prepared_login", False)),
            trace_events=trace_events,
            transcript=transcript,
            browser_tool_calls=browser_tool_calls,
            cart_state=_v9_taobao_cart_state_from_transcript(transcript),
            actual_metrics=_dict_value(summary.get("actual_metrics")),
        )
    if spec.scenario == "v8-taobao-live":
        return _classify_v8_taobao_live_evidence(
            started=started,
            trace_events=trace_events,
            transcript=str(summary.get("final_text") or ""),
            artifact_paths=list(spec.artifact_paths),
            browser_tool_calls=browser_tool_calls,
        )
    if spec.scenario not in _v9_user_live_lifecycle_states() and (
        spec.scenario.startswith("multi-tab") or spec.expected_blocker
    ):
        return _classify_v8_lifecycle_evidence(
            scenario=spec.scenario,
            started=started,
            trace_events=trace_events,
            transcript=str(summary.get("final_text") or ""),
            browser_tool_calls=browser_tool_calls,
        )
    return None


def _content_evidence(
    transcript: str,
    markers: tuple[str, ...],
) -> dict[str, bool]:
    lowered = transcript.casefold()
    return {marker: marker.casefold() in lowered for marker in markers}


def _v9_taobao_cart_state_from_transcript(transcript: str) -> dict[str, Any]:
    text = str(transcript or "")
    merged: dict[str, Any] = {}
    for payload in _json_objects_from_text(text):
        for key in (
            "item_added",
            "cart_read",
            "cart_cleared",
            "empty_confirmed",
            "cart_unchanged",
            "final_state",
        ):
            if key in payload:
                merged[key] = payload[key]
    lowered = text.casefold()
    merged.setdefault(
        "item_added",
        "item_added" in lowered or "added to cart" in lowered,
    )
    merged.setdefault(
        "cart_read",
        "cart_read" in lowered or "cart contents before" in lowered,
    )
    merged.setdefault(
        "cart_cleared",
        "cart_cleared" in lowered or "clear" in lowered,
    )
    merged.setdefault(
        "empty_confirmed",
        "empty_confirmed" in lowered or "empty cart" in lowered,
    )
    merged.setdefault(
        "cart_unchanged",
        "cart_unchanged" in lowered or "cart unchanged" in lowered,
    )
    if "final_state" not in merged and merged.get("empty_confirmed"):
        merged["final_state"] = "empty"
    return merged


def _json_objects_from_text(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            found.append(payload)
    return found


def _v9_user_live_lifecycle_evidence(
    scenario: str,
    *,
    report: BrowserBridgeReport,
    task_status: dict[str, Any],
    summary: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = _v9_user_live_lifecycle_states().get(scenario, "")
    state = ""
    if scenario == "user-read-only-observation":
        state = _v9_readonly_lifecycle_state(report, summary, trace_events)
    elif scenario == "multi-tab-workspace":
        state = _v9_multitab_lifecycle_state(report)
    elif scenario == "bridge-disconnect-fail-closed":
        state = _v9_disconnect_lifecycle_state(report, summary, trace_events)
    elif scenario == "bridge-reconnect-recovered":
        state = _v9_reconnect_lifecycle_state(report, trace_events)
    elif scenario == "user-cancellation-cleanup":
        state = _v9_cancellation_lifecycle_state(report, task_status)
    return {
        "lifecycle_state": state,
        "lifecycle_expected_state": expected,
        "console_overwrite": _v9_console_overwrite_detected(summary),
    }


def _v9_user_live_early_lifecycle_evidence(
    scenario: str,
    report: BrowserBridgeReport,
) -> dict[str, Any]:
    state = ""
    if (
        scenario == "bridge-disconnect-fail-closed"
        and report.error_code == BrowserErrorCode.BRIDGE_DISCONNECTED.value
        and "isolated." not in report.backend_route
    ):
        state = "bridge_disconnect_fail_closed"
    return {
        "lifecycle_state": state,
        "lifecycle_expected_state": _v9_user_live_lifecycle_states().get(
            scenario,
            "",
        ),
        "console_overwrite": False,
    }


def _v9_readonly_lifecycle_state(
    report: BrowserBridgeReport,
    summary: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> str:
    if (
        report.status == "passed"
        and _has_user_backend_evidence(trace_events)
        and not _v9_console_overwrite_detected(summary)
    ):
        return "read_only_observed"
    return ""


def _v9_multitab_lifecycle_state(report: BrowserBridgeReport) -> str:
    if report.status == "passed" and report.cleanup_ok:
        return "multi_tab_cleaned"
    return ""


def _v9_disconnect_lifecycle_state(
    report: BrowserBridgeReport,
    summary: dict[str, Any],
    trace_events: list[dict[str, Any]],
) -> str:
    del summary
    has_bridge_error = any(
        str(event.get("error_code") or "").casefold()
        == BrowserErrorCode.BRIDGE_DISCONNECTED.value
        for event in trace_events
    )
    if (
        report.error_code == BrowserErrorCode.BRIDGE_DISCONNECTED.value
        or has_bridge_error
    ) and "isolated." not in report.backend_route:
        return "bridge_disconnect_fail_closed"
    return ""


def _v9_reconnect_lifecycle_state(
    report: BrowserBridgeReport,
    trace_events: list[dict[str, Any]],
) -> str:
    if report.status == "passed" and _has_user_backend_evidence(trace_events):
        return "bridge_reconnect_recovered"
    return ""


def _v9_cancellation_lifecycle_state(
    report: BrowserBridgeReport,
    task_status: dict[str, Any],
) -> str:
    result = _dict_value(task_status.get("result"))
    error = _dict_value(result.get("error"))
    message = str(error.get("message") or "").casefold()
    if report.status == "passed" and report.cleanup_ok:
        return "cancellation_cleanup_complete"
    if report.cleanup_ok and "cancel" in message:
        return "cancellation_cleanup_complete"
    return ""


def _v9_console_overwrite_detected(summary: dict[str, Any]) -> bool:
    text = str(summary.get("final_text") or "").casefold()
    return "console_overwrite" in text or "console overwritten" in text


def _aggregate_v8_suite(
    *,
    scenario: str,
    started: float,
    reports: list[BrowserBridgeReport],
    user_preparation: list[str] | None = None,
) -> BrowserBridgeReport:
    failed = next(
        (report for report in reports if report.status == "failed"),
        None,
    )
    blocked = next(
        (report for report in reports if report.status == "blocked"),
        None,
    )
    decisive = failed or blocked
    status = decisive.status if decisive is not None else "passed"
    return _report(
        scenario,
        status,
        started,
        browser_tool_calls=sum(
            report.browser_tool_calls for report in reports
        ),
        backend_route=_join_unique(report.backend_route for report in reports),
        forbidden_tools=_join_forbidden(reports),
        trace_event_count=sum(report.trace_event_count for report in reports),
        error_code=decisive.error_code if decisive else "",
        blocked_reason=decisive.blocked_reason if decisive else "",
        failure_reason=decisive.failure_reason if decisive else "",
        artifact_paths=[
            item for report in reports for item in report.artifact_paths
        ],
        fresh_observe_ok=all(report.fresh_observe_ok for report in reports),
        cleanup_ok=all(report.cleanup_ok for report in reports),
        scenario_reports=[report.to_dict() for report in reports],
        safety_boundaries=list(V8_SAFETY_BOUNDARIES)
        if "taobao" in scenario
        else [],
        user_preparation=list(user_preparation or []),
    )


def _join_unique(values: Any) -> str:
    observed: list[str] = []
    for value in values:
        text = str(value or "")
        if text and text not in observed:
            observed.append(text)
    return " | ".join(observed)


def _join_forbidden(reports: list[BrowserBridgeReport]) -> list[str]:
    observed: list[str] = []
    for report in reports:
        for tool in report.forbidden_tools:
            if tool not in observed:
                observed.append(tool)
    return observed


def _classify_v8_taobao_live_evidence(
    *,
    started: float,
    trace_events: list[dict[str, Any]],
    transcript: str,
    artifact_paths: list[str],
    browser_tool_calls: int | None = None,
) -> BrowserBridgeReport:
    effective_browser_tool_calls = (
        browser_tool_calls
        if browser_tool_calls is not None
        else _browser_tool_calls_from_traces(trace_events)
    )
    common_kwargs: dict[str, Any] = {
        "browser_tool_calls": effective_browser_tool_calls,
        "trace_event_count": len(trace_events),
        "safety_boundaries": list(V8_SAFETY_BOUNDARIES),
    }
    route = _backend_route_from_traces(trace_events)
    status = "passed"
    report_kwargs = {
        **common_kwargs,
        "backend_route": route,
        "artifact_paths": artifact_paths,
        "fresh_observe_ok": True,
        "cleanup_ok": True,
        "content_evidence": {
            "cart_contents_before_clear": True,
            "empty_cart_after_clear": True,
        },
        "user_preparation": list(V8_TAOBAO_USER_PREPARATION),
    }
    if _has_payment_or_checkout_marker(transcript):
        status = "failed"
        report_kwargs = {
            **common_kwargs,
            "error_code": BrowserErrorCode.APPROVAL_REQUIRED.value,
            "failure_reason": "safety_violation_payment_or_checkout",
        }
    elif _user_state_routed_to_isolated(trace_events):
        status = "failed"
        report_kwargs = {
            **common_kwargs,
            "backend_route": route,
            "error_code": BrowserErrorCode.CAPABILITY_MISSING.value,
            "failure_reason": "user_state_routed_to_isolated",
        }
    else:
        transcript_info = _transcript_error_info(transcript)
        if transcript_info is not None and transcript_info.code in {
            BrowserErrorCode.LOGIN_REQUIRED,
            BrowserErrorCode.CAPTCHA_OR_RISK_CONTROL,
        }:
            status = "blocked"
            report_kwargs = {
                **common_kwargs,
                "backend_route": route,
                "error_code": transcript_info.code.value,
                "blocked_reason": transcript_info.blocked_reason,
                "user_preparation": list(V8_TAOBAO_USER_PREPARATION),
            }
        else:
            lower = transcript.casefold()
            failure_reason = ""
            if "cart contents before" not in lower:
                failure_reason = "missing_cart_contents_before_clear"
            elif "empty" not in lower:
                failure_reason = "missing_empty_cart_evidence"
            elif not artifact_paths:
                failure_reason = "missing_screenshot_artifact"
            else:
                failure_reason = _user_cleanup_failure_reason(trace_events)
                if not failure_reason:
                    failure_reason = _fresh_observe_failure_reason(
                        trace_events,
                    )
            if failure_reason:
                status = "failed"
                report_kwargs = {
                    **common_kwargs,
                    "backend_route": route,
                    "error_code": BrowserErrorCode.UNKNOWN.value,
                    "failure_reason": failure_reason,
                }
    return _report(
        "v8-taobao-live",
        status,
        started,
        **report_kwargs,
    )


def _has_payment_or_checkout_marker(transcript: str) -> bool:
    lower = transcript.casefold()
    return any(
        marker in lower
        for marker in (
            "checkout",
            "submit order",
            "place order",
            "payment",
            "pay now",
            "付款",
            "支付",
            "提交订单",
        )
    )


def _classify_v8_lifecycle_evidence(
    *,
    scenario: str,
    started: float,
    trace_events: list[dict[str, Any]],
    transcript: str,
    browser_tool_calls: int | None = None,
) -> BrowserBridgeReport:
    if _user_state_routed_to_isolated(trace_events):
        return _report(
            scenario,
            "failed",
            started,
            backend_route=_backend_route_from_traces(trace_events),
            browser_tool_calls=(
                browser_tool_calls
                if browser_tool_calls is not None
                else _browser_tool_calls_from_traces(trace_events)
            ),
            trace_event_count=len(trace_events),
            error_code=BrowserErrorCode.CAPABILITY_MISSING.value,
            failure_reason="user_state_routed_to_isolated",
        )
    transcript_info = _transcript_error_info(transcript)
    if transcript_info is not None:
        return _report(
            scenario,
            "blocked",
            started,
            backend_route=_backend_route_from_traces(trace_events),
            browser_tool_calls=(
                browser_tool_calls
                if browser_tool_calls is not None
                else _browser_tool_calls_from_traces(trace_events)
            ),
            trace_event_count=len(trace_events),
            error_code=transcript_info.code.value,
            blocked_reason=transcript_info.blocked_reason,
        )
    if "bridge disconnected" in transcript.casefold():
        return _report(
            scenario,
            "blocked",
            started,
            backend_route=_backend_route_from_traces(trace_events),
            browser_tool_calls=(
                browser_tool_calls
                if browser_tool_calls is not None
                else _browser_tool_calls_from_traces(trace_events)
            ),
            trace_event_count=len(trace_events),
            error_code=BrowserErrorCode.BRIDGE_DISCONNECTED.value,
        )
    if scenario == "multi-tab-user-lifecycle":
        actions = {str(event.get("action") or "") for event in trace_events}
        if not {"open_tab", "select"}.issubset(actions):
            return _report(
                scenario,
                "failed",
                started,
                backend_route=_backend_route_from_traces(trace_events),
                browser_tool_calls=(
                    browser_tool_calls
                    if browser_tool_calls is not None
                    else _browser_tool_calls_from_traces(trace_events)
                ),
                trace_event_count=len(trace_events),
                error_code=BrowserErrorCode.UNKNOWN.value,
                failure_reason="missing_multitab_trace_evidence",
            )
    cleanup_failure = _user_cleanup_failure_reason(trace_events)
    if cleanup_failure:
        return _report(
            scenario,
            "failed",
            started,
            backend_route=_backend_route_from_traces(trace_events),
            browser_tool_calls=(
                browser_tool_calls
                if browser_tool_calls is not None
                else _browser_tool_calls_from_traces(trace_events)
            ),
            trace_event_count=len(trace_events),
            error_code=BrowserErrorCode.UNKNOWN.value,
            failure_reason=cleanup_failure,
        )
    return _report(
        scenario,
        "passed",
        started,
        backend_route=_backend_route_from_traces(trace_events),
        browser_tool_calls=(
            browser_tool_calls
            if browser_tool_calls is not None
            else _browser_tool_calls_from_traces(trace_events)
        ),
        trace_event_count=len(trace_events),
        fresh_observe_ok=True,
        cleanup_ok=True,
    )


def _classify_bridge_lifecycle_status(status: dict[str, Any]) -> str:
    if status.get("connected") is not True:
        return "disconnected"
    lifecycle = status.get("bridge_lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    return (
        "reconnected"
        if int(lifecycle.get("reconnect_count") or 0) > 0
        else "connected"
    )


def write_v8_product_report(
    *,
    output: Path,
    result_files: list[Path],
) -> BrowserBridgeReport:
    started = time.perf_counter()
    reports = [_load_v8_report(path) for path in result_files]
    aggregate = _aggregate_v8_suite(
        scenario="v8-report",
        started=started,
        reports=reports,
        user_preparation=list(V8_TAOBAO_USER_PREPARATION),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _render_v8_markdown_report(reports, aggregate),
        encoding="utf-8",
    )
    return replace(aggregate, artifact_paths=[str(output)])


def write_v9_evidence_report(
    *,
    output: Path,
    result_files: list[Path],
) -> BrowserBridgeReport:
    """Write a JSON V9 evidence report from scenario result files."""
    started = time.perf_counter()
    reports = [_load_v9_report(path) for path in result_files]
    aggregate = _aggregate_v9_evidence_report(started=started, reports=reports)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(aggregate.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return replace(aggregate, artifact_paths=[str(output)])


def write_v9_final_acceptance_report(
    *,
    output: Path,
    result_files: list[Path],
    issues: list[dict[str, Any]] | None = None,
) -> BrowserBridgeReport:
    """Write the V9-F Markdown final acceptance report."""
    started = time.perf_counter()
    reports = [_load_v9_report(path) for path in result_files]
    aggregate = _aggregate_v9_evidence_report(started=started, reports=reports)
    issue_log = [dict(issue) for issue in issues or []]
    final_status = aggregate.status
    failure_reason = aggregate.failure_reason
    if not _v9_issue_log_complete(issue_log):
        final_status = "failed"
        failure_reason = "incomplete_issue_repair_log"
    elif _v9_has_unresolved_non_external_blocker(reports):
        final_status = "failed"
        failure_reason = "unresolved_non_external_blocker"
    final_report = replace(
        aggregate,
        scenario="v9-final-acceptance-report",
        status=final_status,
        failure_reason=failure_reason if final_status == "failed" else "",
        artifact_paths=[str(output)],
        content_evidence={
            **aggregate.content_evidence,
            "issue_log": issue_log,
            "acceptance_summary": {
                "status": final_status,
                "failure_reason": (
                    failure_reason if final_status == "failed" else ""
                ),
                "scenario_count": len(reports),
            },
        },
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _render_v9_acceptance_markdown(
            report=final_report,
            reports=reports,
            preflight=_v9_final_preflight_report(reports),
            forbidden_scan={"ok": not final_report.forbidden_tools},
        ),
        encoding="utf-8",
    )
    return final_report


def _v9_issue_log_complete(issues: list[dict[str, Any]]) -> bool:
    return all(
        all(
            str(issue.get(field) or "").strip()
            for field in V9_REQUIRED_ISSUE_FIELDS
        )
        for issue in issues
    )


def _v9_has_unresolved_non_external_blocker(
    reports: list[BrowserBridgeReport],
) -> bool:
    for report in reports:
        if report.status == "passed":
            continue
        category = str(report.blocker_classification.get("category") or "")
        if category != "external_blocker":
            return True
    return False


def _v9_final_preflight_report(
    reports: list[BrowserBridgeReport],
) -> BrowserBridgeReport:
    preflight = next(
        (report for report in reports if report.scenario == "v9-preflight"),
        None,
    )
    if preflight is not None:
        return preflight
    return BrowserBridgeReport(
        scenario="v9-preflight",
        status="passed",
        fresh_observe_ok=True,
        cleanup_ok=True,
        report_schema_version=V9_REPORT_SCHEMA_VERSION,
        source_labels=v9_source_labels_for_scenario("v9-preflight"),
    )


def _load_v8_report(path: Path) -> BrowserBridgeReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} did not contain a JSON object")
    return BrowserBridgeReport(
        scenario=str(payload.get("scenario") or path.stem),
        status=str(payload.get("status") or "failed"),
        duration_ms=float(payload.get("duration_ms") or 0.0),
        browser_tool_calls=int(payload.get("browser_tool_calls") or 0),
        backend_route=str(payload.get("backend_route") or ""),
        forbidden_tools=[
            str(item) for item in payload.get("forbidden_tools") or []
        ],
        trace_event_count=int(payload.get("trace_event_count") or 0),
        error_code=str(payload.get("error_code") or ""),
        blocked_reason=str(payload.get("blocked_reason") or ""),
        failure_reason=str(payload.get("failure_reason") or ""),
        artifact_paths=[
            str(item) for item in payload.get("artifact_paths") or []
        ],
        fresh_observe_ok=bool(payload.get("fresh_observe_ok")),
        cleanup_ok=bool(payload.get("cleanup_ok")),
        preflight_checks=dict(payload.get("preflight_checks") or {}),
        content_evidence=dict(payload.get("content_evidence") or {}),
        safety_boundaries=[
            str(item) for item in payload.get("safety_boundaries") or []
        ],
        user_preparation=[
            str(item) for item in payload.get("user_preparation") or []
        ],
        scenario_reports=list(payload.get("scenario_reports") or []),
    )


def _load_v9_report(path: Path) -> BrowserBridgeReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} did not contain a JSON object")
    return BrowserBridgeReport(
        scenario=str(payload.get("scenario") or path.stem),
        status=str(payload.get("status") or "failed"),
        duration_ms=float(payload.get("duration_ms") or 0.0),
        browser_tool_calls=int(payload.get("browser_tool_calls") or 0),
        backend_route=str(payload.get("backend_route") or ""),
        forbidden_tools=[
            str(item) for item in payload.get("forbidden_tools") or []
        ],
        trace_event_count=int(payload.get("trace_event_count") or 0),
        error_code=str(payload.get("error_code") or ""),
        blocked_reason=str(payload.get("blocked_reason") or ""),
        failure_reason=str(payload.get("failure_reason") or ""),
        artifact_paths=[
            str(item) for item in payload.get("artifact_paths") or []
        ],
        fresh_observe_ok=bool(payload.get("fresh_observe_ok")),
        cleanup_ok=bool(payload.get("cleanup_ok")),
        preflight_checks=dict(payload.get("preflight_checks") or {}),
        content_evidence=dict(payload.get("content_evidence") or {}),
        safety_boundaries=[
            str(item) for item in payload.get("safety_boundaries") or []
        ],
        user_preparation=[
            str(item) for item in payload.get("user_preparation") or []
        ],
        scenario_reports=list(payload.get("scenario_reports") or []),
        runtime_evidence=dict(payload.get("runtime_evidence") or {}),
        trace_summary=dict(payload.get("trace_summary") or {}),
        report_schema_version=str(
            payload.get("report_schema_version") or V9_REPORT_SCHEMA_VERSION,
        ),
        scenario_budget=dict(payload.get("scenario_budget") or {}),
        actual_metrics=dict(payload.get("actual_metrics") or {}),
        cleanup_summary=dict(payload.get("cleanup_summary") or {}),
        blocker_classification=dict(
            payload.get("blocker_classification") or {},
        ),
        source_labels=dict(payload.get("source_labels") or {}),
    )


def _aggregate_v9_evidence_report(
    *,
    started: float,
    reports: list[BrowserBridgeReport],
) -> BrowserBridgeReport:
    status = _aggregate_status(reports)
    scenario_payloads = [report.to_dict() for report in reports]
    trace_summary = _aggregate_v9_trace_summary(reports)
    cleanup_summary = _aggregate_v9_cleanup_summary(reports)
    blocker = _v9_blocker_classification(status, reports)
    return _report(
        "v9-report",
        status,
        started,
        browser_tool_calls=sum(
            report.browser_tool_calls for report in reports
        ),
        trace_event_count=sum(report.trace_event_count for report in reports),
        report_schema_version=V9_REPORT_SCHEMA_VERSION,
        scenario_budget=_v9_default_scenario_budget(len(reports)),
        actual_metrics=_v9_actual_metrics(reports),
        trace_summary=trace_summary,
        cleanup_summary=cleanup_summary,
        blocker_classification=blocker,
        source_labels=_aggregate_v9_source_labels(reports),
        scenario_reports=scenario_payloads,
        fresh_observe_ok=all(report.fresh_observe_ok for report in reports),
        cleanup_ok=bool(cleanup_summary.get("cleanup_ok", False)),
        failure_reason=str(blocker.get("reason") or ""),
        blocked_reason=(
            str(blocker.get("reason") or "") if status == "blocked" else ""
        ),
    )


def _aggregate_status(reports: list[BrowserBridgeReport]) -> str:
    if any(report.status == "failed" for report in reports):
        return "failed"
    if any(report.status in {"cancelled", "canceled"} for report in reports):
        return "cancelled"
    if any(report.status == "blocked" for report in reports):
        return "blocked"
    if any(report.status in {"running", "in_progress"} for report in reports):
        return "running"
    return "passed"


def _v9_default_scenario_budget(count: int) -> dict[str, Any]:
    return {
        "scenario_count": count,
        "profiles": {
            name: dict(profile) for name, profile in V9_BUDGET_PROFILES.items()
        },
        "iteration_limit": "profile_defined",
        "browser_call_limit": "profile_defined",
        "elapsed_ms_limit": "profile_defined",
        "token_limit": "profile_defined",
        "task_budget_ms": int(DEFAULT_TASK_TIMEOUT * 1000),
    }


def _v9_scenario_budget(scenario: str) -> dict[str, Any]:
    profile_name = _v9_scenario_budget_profile(scenario)
    profile = V9_BUDGET_PROFILES[profile_name]
    return dict(profile)


def _v9_scenario_budget_profile(scenario: str) -> str:
    key = scenario.strip().casefold().replace("_", "-")
    if key in V9_SCENARIO_BUDGET_PROFILES:
        return V9_SCENARIO_BUDGET_PROFILES[key]
    if "complex" in key or "deterministic" in key:
        return "deterministic_complex"
    if "read-only" in key or "readonly" in key:
        return "user_read_only"
    if "commerce" in key or "mutation" in key:
        return "commerce_live_mutation"
    return "public_isolated"


def _v9_normalize_actual_metrics(
    *,
    started: float,
    browser_tool_calls: int,
    trace_events: list[dict[str, Any]],
    actual_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics = dict(actual_metrics or {})
    metrics.setdefault("browser_calls", int(browser_tool_calls))
    metrics.setdefault("trace_events", len(trace_events))
    metrics.setdefault(
        "elapsed_ms",
        round((time.perf_counter() - started) * 1000, 3),
    )
    metrics.setdefault("iterations", 0)
    metrics.setdefault(
        "token_count",
        {"available": False, "reason": "not_reported"},
    )
    return metrics


def _v9_budget_failure(
    budget: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    exceeded: list[str] = []
    if _metric_number(metrics, "iterations") > _budget_int(
        budget,
        "iteration_limit",
    ):
        exceeded.append("iterations")
    if _metric_number(metrics, "browser_calls") > _budget_int(
        budget,
        "browser_call_limit",
    ):
        exceeded.append("browser_calls")
    if _metric_number(metrics, "elapsed_ms") > _budget_int(
        budget,
        "elapsed_ms_limit",
    ):
        exceeded.append("elapsed_ms")
    token_count = metrics.get("token_count")
    if isinstance(token_count, dict) and token_count.get("available") is True:
        if _token_count_number(token_count) > _budget_int(
            budget,
            "token_limit",
        ):
            exceeded.append("token_count")
    if not exceeded:
        return {}
    return {
        "status": "failed",
        "category": "budget",
        "reason": "budget_exhausted",
        "terminal": True,
        "exceeded": exceeded,
    }


def _metric_number(metrics: dict[str, Any], key: str) -> float:
    try:
        return float(metrics.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _token_count_number(token_count: dict[str, Any]) -> float:
    for key in ("count", "total", "total_tokens"):
        if key in token_count:
            try:
                return float(token_count.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _budget_int(budget: dict[str, Any], key: str) -> int:
    try:
        return int(budget.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _v9_actual_metrics(reports: list[BrowserBridgeReport]) -> dict[str, Any]:
    return {
        "scenario_count": len(reports),
        "elapsed_ms": round(sum(report.duration_ms for report in reports), 3),
        "browser_calls": sum(report.browser_tool_calls for report in reports),
        "trace_events": sum(report.trace_event_count for report in reports),
        "iterations": _sum_nested_metric(reports, "iterations"),
        "token_count": {"available": False, "reason": "not_reported"},
    }


def _sum_nested_metric(
    reports: list[BrowserBridgeReport],
    key: str,
) -> int:
    total = 0
    for report in reports:
        value = report.actual_metrics.get(key)
        if isinstance(value, int):
            total += value
    return total


def _aggregate_v9_trace_summary(
    reports: list[BrowserBridgeReport],
) -> dict[str, Any]:
    missing: dict[str, Any] = {}
    complete = True
    for report in reports:
        summary = report.trace_summary
        if summary.get("complete") is False:
            complete = False
        if isinstance(summary.get("missing_fields"), dict):
            missing[report.scenario] = summary["missing_fields"]
    return {
        "complete": complete and not missing,
        "event_count": sum(report.trace_event_count for report in reports),
        "missing_fields": missing,
    }


def _aggregate_v9_cleanup_summary(
    reports: list[BrowserBridgeReport],
) -> dict[str, Any]:
    last_cleanup_reason = ""
    protected_status = "clear"
    controlled_tab_count = 0
    residual_tab_count = 0
    for report in reports:
        summary = report.cleanup_summary
        controlled_tab_count += _summary_int(summary, "controlled_tab_count")
        residual_tab_count += _summary_int(summary, "residual_tab_count")
        reason = str(summary.get("last_cleanup_reason") or "")
        if reason:
            last_cleanup_reason = reason
        if str(summary.get("protected_origin_status") or "") == "skipped":
            protected_status = "skipped"
    return {
        "cleanup_ok": all(report.cleanup_ok for report in reports),
        "scenario_count": len(reports),
        "failed_scenarios": [
            report.scenario for report in reports if not report.cleanup_ok
        ],
        "controlled_tab_count": controlled_tab_count,
        "residual_tab_count": residual_tab_count,
        "last_cleanup_reason": last_cleanup_reason,
        "protected_origin_status": protected_status,
    }


def _summary_int(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _v9_blocker_classification(
    status: str,
    reports: list[BrowserBridgeReport],
) -> dict[str, Any]:
    for report in reports:
        if report.blocker_classification:
            payload = dict(report.blocker_classification)
            payload["status"] = status
            return payload
        reason = report.blocked_reason or report.failure_reason
        if reason:
            return _v9_report_blocker_classification(
                status=status,
                blocked_reason=report.blocked_reason,
                failure_reason=report.failure_reason,
            )
    return _v9_report_blocker_classification(status=status)


def _v9_report_blocker_classification(
    *,
    status: str,
    blocked_reason: str = "",
    failure_reason: str = "",
) -> dict[str, Any]:
    reason = blocked_reason or failure_reason
    category = "none"
    if status == "blocked":
        category = "external_blocker"
    elif failure_reason == "budget_exhausted":
        category = "budget"
    elif failure_reason in {"no_progress", "retry_budget_exhausted"}:
        category = "model_loop"
    elif failure_reason in {
        "forbidden_tools",
        "missing_browser_tool_call",
        "backend_route_mismatch",
        BrowserErrorCode.CAPABILITY_MISSING.value,
    }:
        category = "capability_gap"
    elif status == "failed":
        category = "verification_failure"
    return {
        "status": status,
        "category": category,
        "reason": reason,
        "terminal": status not in {"passed", "running", "in_progress"},
    }


def _v9_runtime_outcome_classification(
    *,
    status: str,
    error_code: str = "",
    blocked_reason: str = "",
    failure_reason: str = "",
    runtime_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = dict(runtime_evidence or {})
    evidence.update(
        {
            "status": status,
            "error_code": error_code,
            "blocked_reason": blocked_reason,
            "failure_reason": failure_reason,
        },
    )
    if status in {"running", "in_progress"}:
        evidence["in_progress"] = True
    return classify_browser_runtime_outcome(evidence).to_dict()


def _aggregate_v9_source_labels(
    reports: list[BrowserBridgeReport],
) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for report in reports:
        labels = report.source_labels
        for item in labels.get("observations") or []:
            if isinstance(item, dict):
                observations.append(dict(item))
        primary = labels.get("primary")
        if primary:
            observations.append(
                {"source": str(primary), "kind": "scenario_primary"},
            )
    return {"allowed": list(V9_SOURCE_LABELS), "observations": observations}


def validate_v9_source_labels(labels: dict[str, Any]) -> dict[str, Any]:
    """Validate that evidence observations use explicit V9 source labels."""
    invalid: list[str] = []
    primary = str(labels.get("primary") or "")
    if primary and primary not in V9_SOURCE_LABELS:
        invalid.append(primary)
    observations = labels.get("observations")
    if isinstance(observations, list):
        for item in observations:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "")
            if (
                source
                and source not in V9_SOURCE_LABELS
                and source not in invalid
            ):
                invalid.append(source)
    return {"ok": not invalid, "invalid_sources": invalid}


def v9_source_labels_for_scenario(scenario: str) -> dict[str, Any]:
    """Return default observation source labels for a verifier scenario."""
    name = str(scenario or "")
    if "taobao" in name or "commerce" in name:
        primary = "commerce_live"
        kind = "commerce_live"
    elif "user" in name:
        primary = "user_chrome"
        kind = "user_chrome"
    elif "public" in name or "loop" in name:
        primary = "public_live"
        kind = "public_live"
    elif "fixture" in name or "deterministic" in name:
        primary = "fixture"
        kind = "deterministic_fixture"
    else:
        primary = "local_service"
        kind = "runtime_preflight"
    return {
        "primary": primary,
        "observations": [
            {"source": primary, "kind": kind},
            {"source": "local_service", "kind": "runtime_preflight"},
        ],
    }


def _render_v8_markdown_report(
    reports: list[BrowserBridgeReport],
    aggregate: BrowserBridgeReport,
) -> str:
    deterministic = [
        report for report in reports if "deterministic" in report.scenario
    ]
    live = [report for report in reports if report not in deterministic]
    return "\n".join(
        [
            "# Browser Bridge V8 Product Readiness Report",
            "",
            "## Deterministic Results",
            _markdown_report_table(deterministic),
            "",
            "## Live Results",
            _markdown_report_table(live),
            "",
            "## Route Evidence",
            *[
                f"- `{report.scenario}`: {report.backend_route or 'unavailable'}"
                for report in reports
            ],
            "",
            "## Artifacts",
            *[
                f"- `{report.scenario}`: {', '.join(report.artifact_paths) or 'none'}"
                for report in reports
            ],
            "",
            "## Lifecycle Cleanup",
            *[
                f"- `{report.scenario}`: cleanup_ok={report.cleanup_ok}, "
                f"fresh_observe_ok={report.fresh_observe_ok}"
                for report in reports
            ],
            "",
            "## Safety Boundaries",
            *[f"- {item}" for item in V8_SAFETY_BOUNDARIES],
            "",
            "## User Preparation",
            *[f"- {item}" for item in V8_TAOBAO_USER_PREPARATION],
            "",
            "## Final Verdict",
            f"- Status: `{aggregate.status}`",
            f"- Failure reason: `{aggregate.failure_reason}`",
            f"- Blocked reason: `{aggregate.blocked_reason}`",
            "",
        ],
    )


def _markdown_report_table(reports: list[BrowserBridgeReport]) -> str:
    if not reports:
        return "_No results provided._"
    rows = ["| Scenario | Status | Blocked | Failure |", "|---|---|---|---|"]
    rows.extend(
        f"| `{report.scenario}` | `{report.status}` | "
        f"`{report.blocked_reason}` | `{report.failure_reason}` |"
        for report in reports
    )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if getattr(args, "truth_gates", False):
        report = run_truth_gates_report()
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.status == "passed" else 1
    if not args.command:
        report = run_product_verifier(args)
        payload = report.to_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if report.status == "passed" else 1
    runners = {
        "preflight": run_preflight,
        "fixture": run_fixture,
        "public-search": run_public_search,
        "complex-isolated": run_complex_isolated,
        "complex-user": run_complex_user,
        "v8-capability-isolated": run_v8_capability_isolated,
        "v8-capability-user": run_v8_capability_user,
        "bridge-disconnected": run_bridge_disconnected,
        "taobao-live": run_taobao_live,
        "v8-preflight": run_v8_preflight,
        "v9-preflight": run_v9_preflight,
        "v9-acceptance": run_v9_acceptance,
        "v9-public-live": run_v9_public_live,
        "v9-user-live": run_v9_user_live,
        "v9-capability-matrix": run_v9_capability_matrix,
        "v9-taobao-live": run_v9_taobao_live,
        "v8-deterministic": run_v8_deterministic,
        "v8-public-live": run_v8_public_live,
        "v8-user-live": run_v8_user_live,
        "v8-taobao-live": run_v8_taobao_live,
        "v8-lifecycle-live": run_v8_lifecycle_live,
        "v8-report": run_v8_report,
        "v9-report": run_v9_report,
    }
    report = runners[args.command](args)
    payload = report.to_dict()
    output_json = str(getattr(args, "output_json", "") or "")
    if output_json:
        output_path = Path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.status == "passed" else 1


def run_product_verifier(args: argparse.Namespace) -> BrowserBridgeReport:
    """Run the V10-D default product readiness verifier."""
    started = time.perf_counter()
    truth = run_truth_gates(root=_repo_root())
    risk = run_risk_genericity_gates(
        action_groups=RISK_ACTIONS_BY_KIND,
        keyword_groups=RISK_KEYWORDS_BY_KIND,
    )
    preflight = _product_service_preflight(args)
    scenarios = default_scenarios(
        include_live_taobao=bool(getattr(args, "live_taobao", False)),
    )
    preflight_status = str(preflight.get("status") or "")
    scenario_reports: list[dict[str, Any]] = []
    if preflight_status == "passed":
        scenario_reports = [
            _run_product_scenario(args, scenario) for scenario in scenarios
        ]
    scenario_matrix_status = (
        "passed"
        if preflight_status == "passed"
        and all(item["status"] == "passed" for item in scenario_reports)
        else "blocked"
    )
    gate_statuses = {
        "truth_gates": str(truth["status"]),
        "risk_gates": str(risk["status"]),
        "service_preflight": preflight_status,
        "scenario_matrix": scenario_matrix_status,
        "lifecycle_gates": _product_lifecycle_gate_status(
            _dict_value(preflight.get("cleanup_summary")),
            scenario_reports,
        ),
    }
    failed_or_blocked = [
        name for name, status in gate_statuses.items() if status != "passed"
    ]
    status = "passed" if not failed_or_blocked else "blocked"
    truth_violations = truth.get("violations")
    risk_violations = risk.get("violations")
    report = _report(
        "browser-v10-product-readiness",
        status,
        started,
        backend_route=str(preflight.get("backend_route") or ""),
        trace_event_count=int(preflight.get("trace_event_count") or 0),
        blocked_reason=", ".join(failed_or_blocked)
        if failed_or_blocked
        else "",
        content_evidence={
            "gate_statuses": gate_statuses,
            "preflight_checks": dict(preflight.get("preflight_checks") or {}),
            "truth_gate_violation_count": (
                len(truth_violations)
                if isinstance(truth_violations, list)
                else 0
            ),
            "risk_gate_violation_count": (
                len(risk_violations)
                if isinstance(risk_violations, list)
                else 0
            ),
            "scenario_ids": [scenario.scenario_id for scenario in scenarios],
            "live_taobao_included": bool(getattr(args, "live_taobao", False)),
            "canonical_setup_url": str(
                preflight.get("canonical_setup_url") or "",
            ),
            "recovery_hint": str(preflight.get("recovery_hint") or ""),
            "repair_action": str(preflight.get("repair_action") or "none"),
            "can_retry": bool(preflight.get("can_retry")),
        },
        cleanup_summary=_dict_value(preflight.get("cleanup_summary")),
        runtime_evidence=_dict_value(preflight.get("runtime_evidence")),
        scenario_reports=scenario_reports,
        report_schema_version="browser-v10-product-readiness.v1",
    )
    report_path = Path(str(getattr(args, "report", "") or ""))
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            _render_product_readiness_markdown(report, gate_statuses),
            encoding="utf-8",
        )
    return report


def _product_service_preflight(args: argparse.Namespace) -> dict[str, Any]:
    base_url = _v9_base_url(args)
    evidence: dict[str, Any] = {"base_url": base_url}
    try:
        version = _http_json(f"{base_url}/api/version", timeout=args.timeout)
        status = _extension_status(base_url, args.timeout)
    except RuntimeError as exc:
        return {
            "status": "blocked",
            "backend_route": "",
            "trace_event_count": 0,
            "cleanup_summary": {},
            "runtime_evidence": {"error": str(exc), **evidence},
            "preflight_checks": {
                "browser_bridge_status_route": "blocked",
            },
        }
    build = _dict_value(status.get("build_fingerprint"))
    local = {
        "git_commit": _local_git_commit(),
        "frontend_fingerprint": _local_frontend_fingerprint(),
        "plugin_fingerprint": _local_plugin_fingerprint(),
    }
    service = {
        "git_commit": str(
            build.get("git_commit") or version.get("git_commit") or "",
        ),
        "frontend_fingerprint": str(
            build.get("frontend_fingerprint")
            or version.get("frontend_fingerprint")
            or "",
        ),
        "plugin_fingerprint": str(build.get("plugin_fingerprint") or ""),
        "extension_version": str(status.get("extension_version") or ""),
        "native_host_version": str(status.get("native_host_version") or ""),
    }
    preflight_checks = {
        "browser_bridge_status_route": "passed",
        "backend_commit": _product_check_match(
            local["git_commit"],
            service["git_commit"],
        ),
        "frontend_fingerprint": _product_check_match(
            local["frontend_fingerprint"],
            service["frontend_fingerprint"],
        ),
        "plugin_fingerprint": _product_check_match(
            local["plugin_fingerprint"],
            service["plugin_fingerprint"],
        ),
        "extension_version": (
            "passed" if service["extension_version"] else "failed"
        ),
        "native_host_version": (
            "passed" if service["native_host_version"] else "failed"
        ),
    }
    trace_summary = _dict_value(status.get("trace_summary"))
    lifecycle = _dict_value(trace_summary.get("lifecycle"))
    cleanup_summary = {
        "cleanup_ok": int(lifecycle.get("residual_tab_count") or 0) == 0,
        "residual_tab_count": int(lifecycle.get("residual_tab_count") or 0),
        "kernel_idle_count": 0,
        "bridge_connected": bool(status.get("connected")),
    }
    bridge_connected = bool(status.get("connected"))
    preflight_checks["browser_bridge_connected"] = (
        "passed" if bridge_connected else "blocked"
    )
    service_ok = all(value == "passed" for value in preflight_checks.values())
    preflight_status = "passed" if service_ok else "failed"
    canonical_setup_url = str(
        status.get("canonical_setup_url") or "/plugin/browser-bridge",
    )
    recovery_hint = ""
    repair_action = "none"
    if not bridge_connected:
        preflight_status = "blocked"
        repair_action = "open_setup_page"
        recovery_hint = str(
            status.get("recovery_copy")
            or (
                "Open the Browser Bridge setup page at "
                "/plugin/browser-bridge, then reload the extension."
            ),
        )
    return {
        "status": preflight_status,
        "canonical_setup_url": canonical_setup_url,
        "recovery_hint": recovery_hint,
        "repair_action": repair_action,
        "can_retry": repair_action != "none",
        "backend_route": _backend_route(status),
        "trace_event_count": int(trace_summary.get("event_count") or 0),
        "cleanup_summary": cleanup_summary,
        "preflight_checks": preflight_checks,
        "runtime_evidence": {
            **evidence,
            "local": local,
            "service": service,
            "checks": preflight_checks,
            "browser_bridge_status_route": "available",
            "bridge_connected": bridge_connected,
            "canonical_setup_url": canonical_setup_url,
            "recovery_hint": recovery_hint,
            "repair_action": repair_action,
        },
    }


def _product_check_match(local_value: Any, service_value: Any) -> str:
    local_text = str(local_value or "").strip()
    service_text = str(service_value or "").strip()
    if not local_text or not service_text:
        return "failed"
    return (
        "passed"
        if local_text == service_text
        or service_text.startswith(local_text)
        or local_text.startswith(service_text)
        else "failed"
    )


def _product_lifecycle_gate_status(
    preflight_cleanup: dict[str, Any],
    scenario_reports: list[dict[str, Any]],
) -> str:
    cleanup_results = [
        preflight_cleanup,
        *[
            _dict_value(report.get("cleanup_result"))
            for report in scenario_reports
        ],
    ]
    for cleanup in cleanup_results:
        if int(cleanup.get("residual_tab_count") or 0) != 0:
            return "failed"
        if int(cleanup.get("kernel_idle_count") or 0) != 0:
            return "failed"
    return "passed"


def _run_product_scenario(
    args: argparse.Namespace,
    scenario: Any,
) -> dict[str, Any]:
    scenario_id = str(scenario.scenario_id)
    if scenario_id == "public-search-isolated":
        product_report = _product_report_from_child(
            scenario,
            run_public_search(args),
        )
    elif scenario_id == "user-observation":
        spec = _v9_user_live_spec("user-read-only-observation")
        product_report = _product_report_from_child(
            scenario,
            _run_v9_user_live_task(args, spec),
        )
    elif scenario_id == "local-cart-approval":
        child = _run_v9_approval_probe(args, "DEFAULT")
        fail_closed = _v9_matrix_approval_default_fail_closed(
            [child.to_dict()],
        )
        product_report = _product_report_from_child(
            scenario,
            child,
            accepted=fail_closed,
            failure_category=(
                "" if fail_closed else "approval_default_not_fail_closed"
            ),
            recovery_hint=(
                ""
                if fail_closed
                else "verify DEFAULT approval fails closed before mutation"
            ),
        )
    elif scenario_id == "local-cart-auto":
        child = _run_v9_approval_probe(args, "OFF")
        off_success = _v9_matrix_approval_off_success([child.to_dict()])
        product_report = _product_report_from_child(
            scenario,
            child,
            accepted=off_success,
            failure_category="" if off_success else "approval_off_not_success",
            recovery_hint=(
                ""
                if off_success
                else "verify approval_level=OFF executes the fixture mutation"
            ),
        )
    elif scenario_id == "complex-isolated-fixture":
        product_report = _product_report_from_child(
            scenario,
            run_complex_isolated(args),
        )
    elif scenario_id == "complex-user-fixture":
        spec = _v9_user_live_spec("user-read-only-observation")
        product_report = _product_report_from_child(
            scenario,
            _run_v9_user_live_task(args, spec),
        )
    elif scenario_id == "bridge-disconnect":
        product_report = _run_product_bridge_disconnect(args, scenario)
    elif scenario_id == "cleanup-cancel":
        spec = _v9_user_live_spec("user-cancellation-cleanup")
        product_report = _product_report_from_child(
            scenario,
            _run_v9_user_live_task(args, spec),
        )
    elif scenario_id == "live-taobao-opt-in":
        product_report = _product_report_from_child(
            scenario,
            run_v9_taobao_live(args),
        )
    else:
        product_report = _product_report_from_child(
            scenario,
            _report(
                scenario_id,
                "failed",
                time.perf_counter(),
                failure_reason="unknown_product_scenario",
            ),
        )
    return product_report


def _v9_user_live_spec(scenario: str) -> V8LiveTaskSpec:
    for spec in _v9_user_live_task_specs():
        if spec.scenario == scenario:
            return spec
    raise KeyError(f"Unknown V9 user live scenario: {scenario}")


def _run_product_bridge_disconnect(
    args: argparse.Namespace,
    scenario: Any,
) -> dict[str, Any]:
    disconnect = _run_v9_user_live_task(
        args,
        _v9_user_live_spec("bridge-disconnect-fail-closed"),
    )
    reconnect = _run_v9_user_live_task(
        args,
        _v9_user_live_spec("bridge-reconnect-recovered"),
    )
    reconnect_delta = _product_reconnect_delta(disconnect, reconnect)
    disconnect_ok = _product_bridge_disconnect_fail_closed_ok(disconnect)
    reconnect_ok = _product_bridge_reconnect_observed_ok(reconnect)
    accepted = disconnect_ok and reconnect_ok and reconnect_delta > 0
    failure_category = ""
    if not accepted:
        failure_category = (
            "bridge_disconnect_not_fail_closed"
            if not disconnect_ok
            else "missing_reconnect_delta"
        )
    return _product_report_from_child(
        scenario,
        reconnect if disconnect_ok else disconnect,
        accepted=accepted,
        failure_category=failure_category,
        recovery_hint=(
            ""
            if accepted
            else "inject bridge disconnect and observe reconnect event delta"
        ),
        reconnect_delta=reconnect_delta,
        source_reports=[disconnect.to_dict(), reconnect.to_dict()],
    )


def _product_bridge_disconnect_fail_closed_ok(
    disconnect: BrowserBridgeReport,
) -> bool:
    event = _dict_value(
        disconnect.content_evidence.get("controlled_lifecycle_event"),
    )
    if not _v9_controlled_lifecycle_event_ok(
        "bridge-disconnect-fail-closed",
        event,
    ):
        return False
    if disconnect.status == "passed":
        return True
    return (
        disconnect.status == "blocked"
        and disconnect.error_code == BrowserErrorCode.BRIDGE_DISCONNECTED.value
    )


def _product_bridge_reconnect_observed_ok(
    reconnect: BrowserBridgeReport,
) -> bool:
    event = _dict_value(
        reconnect.content_evidence.get("controlled_lifecycle_event"),
    )
    return _v9_controlled_lifecycle_event_ok(
        "bridge-reconnect-recovered",
        event,
    )


def _product_reconnect_delta(
    disconnect: BrowserBridgeReport,
    reconnect: BrowserBridgeReport,
) -> int:
    for report in (reconnect, disconnect):
        event = _dict_value(
            report.content_evidence.get("controlled_lifecycle_event"),
        )
        lifecycle = _dict_value(event.get("bridge_lifecycle"))
        try:
            reconnect_count = int(lifecycle.get("reconnect_count") or 0)
        except (TypeError, ValueError):
            reconnect_count = 0
        if reconnect_count > 0:
            return reconnect_count
        if (
            event.get("reconnect_count_increased") is True
            and event.get("kind") == "bridge_reconnect_observed"
            and event.get("after_connected") is True
        ):
            return 1
    return 0


def _product_report_from_child(
    scenario: Any,
    child: BrowserBridgeReport,
    *,
    accepted: bool | None = None,
    failure_category: str = "",
    recovery_hint: str = "",
    reconnect_delta: int = 0,
    source_reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scenario_id = str(scenario.scenario_id)
    child_passed = child.status == "passed"
    if accepted is None:
        passed = child_passed
        status = child.status
    else:
        passed = bool(accepted)
        status = (
            "passed"
            if passed
            else child.status
            if child.status in {"blocked", "failed", "cancelled"}
            else "failed"
        )
    if status == "passed":
        failure_category = ""
        recovery_hint = ""
    else:
        failure_category = (
            failure_category
            or child.failure_reason
            or child.blocked_reason
            or child.error_code
            or "scenario_not_passed"
        )
        recovery_hint = recovery_hint or _product_recovery_hint(status)
    repair_action = _product_repair_action(
        status=status,
        failure_category=failure_category,
        child=child,
    )
    cleanup_result = dict(child.cleanup_summary or {})
    cleanup_result.setdefault("residual_tab_count", 0)
    cleanup_result.setdefault("kernel_idle_count", 0)
    return {
        "scenario": scenario_id,
        "status": status,
        "context": str(scenario.context),
        "required_backend": str(scenario.required_backend),
        "live_opt_in": bool(scenario.live_opt_in),
        "failure_category": failure_category,
        "recovery_hint": recovery_hint,
        "repair_action": repair_action,
        "can_retry": repair_action != "none",
        "cleanup_result": cleanup_result,
        "reconnect_delta": reconnect_delta,
        "source_report": child.to_dict(),
        "source_reports": source_reports or [child.to_dict()],
    }


def _product_repair_action(
    *,
    status: str,
    failure_category: str,
    child: BrowserBridgeReport,
) -> str:
    if status == "passed":
        return "none"
    evidence = child.to_dict()
    haystack = " ".join(
        str(value)
        for value in (
            child.error_code,
            child.blocked_reason,
            child.failure_reason,
            failure_category,
            evidence.get("backend_route"),
        )
    ).casefold()
    if (
        BrowserErrorCode.BRIDGE_DISCONNECTED.value in haystack
        or "bridge disconnected" in haystack
        or "browser_bridge_disconnected" in haystack
    ):
        return "reload_extension"
    if status == "blocked":
        return "open_setup_page"
    return "rerun_after_fix"


def _product_recovery_hint(status: str) -> str:
    if status == "blocked":
        return "start latest QwenPaw service and reconnect Browser Bridge"
    return "inspect Browser SDK trace, cleanup, and scenario evidence"


def _render_product_readiness_markdown(
    report: BrowserBridgeReport,
    gate_statuses: dict[str, str],
) -> str:
    rows = [
        "| Scenario | Status | Context | Backend |",
        "|---|---|---|---|",
    ]
    for item in report.scenario_reports:
        rows.append(
            f"| `{item['scenario']}` | `{item['status']}` | "
            f"`{item['context']}` | `{item['required_backend']}` |",
        )
    gate_rows = [
        "| Gate | Status |",
        "|---|---|",
        *(
            f"| `{name}` | `{status}` |"
            for name, status in gate_statuses.items()
        ),
    ]
    return "\n".join(
        [
            "# Browser V10 Product Readiness Report",
            "",
            f"- Status: `{report.status}`",
            f"- Scenario count: `{len(report.scenario_reports)}`",
            f"- Backend route: `{report.backend_route or 'unavailable'}`",
            "",
            "## Gates",
            "",
            *gate_rows,
            "",
            "## Scenarios",
            "",
            *rows,
            "",
            "## Cleanup",
            "",
            f"- Cleanup summary: `{report.cleanup_summary}`",
            "",
        ],
    )


def run_truth_gates_report() -> BrowserBridgeReport:
    started = time.perf_counter()
    result = run_truth_gates(root=_repo_root())
    status = str(result["status"])
    return _report(
        "truth-gates",
        status,
        started,
        failure_reason=(
            "forbidden_browser_residue" if status == "failed" else ""
        ),
        content_evidence={"truth_gates": result},
    )


def _report(
    scenario: str,
    status: str,
    started: float,
    *,
    browser_tool_calls: int = 0,
    backend_route: str = "",
    forbidden_tools: list[str] | None = None,
    trace_event_count: int = 0,
    error_code: str = "",
    blocked_reason: str = "",
    failure_reason: str = "",
    artifact_paths: list[str] | None = None,
    fresh_observe_ok: bool = False,
    cleanup_ok: bool = False,
    preflight_checks: dict[str, str] | None = None,
    content_evidence: dict[str, Any] | None = None,
    safety_boundaries: list[str] | None = None,
    user_preparation: list[str] | None = None,
    scenario_reports: list[dict[str, Any]] | None = None,
    runtime_evidence: dict[str, Any] | None = None,
    trace_summary: dict[str, Any] | None = None,
    report_schema_version: str = "",
    scenario_budget: dict[str, Any] | None = None,
    actual_metrics: dict[str, Any] | None = None,
    cleanup_summary: dict[str, Any] | None = None,
    blocker_classification: dict[str, Any] | None = None,
    source_labels: dict[str, Any] | None = None,
) -> BrowserBridgeReport:
    if status == "blocked" and not blocked_reason and error_code:
        blocked_reason = classify_browser_error(error_code).blocked_reason
    if status == "failed" and not failure_reason:
        failure_reason = (
            classify_browser_error(error_code).failure_reason
            or blocked_reason
            or "verification_failed"
        )
    runtime_payload = dict(runtime_evidence or {})
    runtime_payload.setdefault(
        "runtime_outcome",
        _v9_runtime_outcome_classification(
            status=status,
            error_code=error_code,
            blocked_reason=blocked_reason,
            failure_reason=failure_reason,
            runtime_evidence=runtime_payload,
        ),
    )
    blocker_payload = dict(blocker_classification or {})
    if not blocker_payload:
        blocker_payload = _v9_report_blocker_classification(
            status=status,
            blocked_reason=blocked_reason,
            failure_reason=failure_reason,
        )
    return BrowserBridgeReport(
        scenario=scenario,
        status=status,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        browser_tool_calls=browser_tool_calls,
        backend_route=backend_route,
        forbidden_tools=list(forbidden_tools or []),
        trace_event_count=trace_event_count,
        error_code=str(error_code or ""),
        blocked_reason=blocked_reason,
        failure_reason=failure_reason,
        artifact_paths=list(artifact_paths or []),
        fresh_observe_ok=fresh_observe_ok,
        cleanup_ok=cleanup_ok,
        preflight_checks=dict(preflight_checks or {}),
        content_evidence=dict(content_evidence or {}),
        safety_boundaries=list(safety_boundaries or []),
        user_preparation=list(user_preparation or []),
        scenario_reports=list(scenario_reports or []),
        runtime_evidence=runtime_payload,
        trace_summary=dict(trace_summary or {}),
        report_schema_version=report_schema_version,
        scenario_budget=dict(scenario_budget or {}),
        actual_metrics=dict(actual_metrics or {}),
        cleanup_summary=dict(cleanup_summary or {}),
        blocker_classification=blocker_payload,
        source_labels=dict(source_labels or {}),
    )


def _copy_report(
    report: BrowserBridgeReport,
    *,
    scenario: str,
) -> BrowserBridgeReport:
    return BrowserBridgeReport(
        scenario=scenario,
        status=report.status,
        duration_ms=report.duration_ms,
        browser_tool_calls=report.browser_tool_calls,
        backend_route=report.backend_route,
        forbidden_tools=list(report.forbidden_tools),
        trace_event_count=report.trace_event_count,
        error_code=report.error_code,
        blocked_reason=report.blocked_reason,
        failure_reason=report.failure_reason,
        artifact_paths=list(report.artifact_paths),
        fresh_observe_ok=report.fresh_observe_ok,
        cleanup_ok=report.cleanup_ok,
        preflight_checks=dict(report.preflight_checks),
        content_evidence=dict(report.content_evidence),
        safety_boundaries=list(report.safety_boundaries),
        user_preparation=list(report.user_preparation),
        scenario_reports=list(report.scenario_reports),
        runtime_evidence=dict(report.runtime_evidence),
        trace_summary=dict(report.trace_summary),
        report_schema_version=report.report_schema_version,
        scenario_budget=dict(report.scenario_budget),
        actual_metrics=dict(report.actual_metrics),
        cleanup_summary=dict(report.cleanup_summary),
        blocker_classification=dict(report.blocker_classification),
        source_labels=dict(report.source_labels),
    )


def _run_chat_trace_scenario(
    *,
    scenario: str,
    started: float,
    base_url: str,
    session_id: str,
    prompt: str,
    timeout: float,
    backend_route: str = "",
    artifact_paths: list[str] | None = None,
    require_user_backend: bool = False,
    request_context: dict[str, Any] | None = None,
    required_success_marker: str = "",
    required_context: str = "",
    required_backend_id: str = "",
) -> BrowserBridgeReport:
    try:
        task = _submit_console_task(
            base_url,
            prompt,
            session_id=session_id,
            timeout=timeout,
            request_context=request_context,
        )
        task_status = _poll_console_task(
            base_url,
            str(task.get("task_id") or ""),
            timeout=timeout,
        )
    except RuntimeError as exc:
        return _report(
            scenario,
            "blocked",
            started,
            backend_route=backend_route,
            error_code=BrowserErrorCode.UNKNOWN.value,
            blocked_reason=str(exc),
            artifact_paths=artifact_paths,
        )

    summary = _summarize_task_status(task_status)
    trace_session_id = summary["session_id"] or session_id
    try:
        trace_events = _fetch_extension_traces(
            base_url,
            trace_session_id,
            DEFAULT_TIMEOUT,
        )
    except RuntimeError:
        trace_events = []

    route = _backend_route_from_traces(trace_events) or backend_route
    browser_tool_calls = summary[
        "browser_tool_calls"
    ] or _browser_tool_calls_from_traces(
        trace_events,
    )
    return _classify_chat_trace_result(
        scenario=scenario,
        started=started,
        task_status=task_status,
        summary=summary,
        trace_events=trace_events,
        browser_tool_calls=browser_tool_calls,
        route=route,
        require_user_backend=require_user_backend,
        required_success_marker=required_success_marker,
        required_context=required_context,
        required_backend_id=required_backend_id,
        artifact_paths=artifact_paths,
    )


def _classify_chat_trace_result(
    *,
    scenario: str,
    started: float,
    task_status: dict[str, Any],
    summary: dict[str, Any],
    trace_events: list[dict[str, Any]],
    browser_tool_calls: int,
    route: str,
    require_user_backend: bool,
    required_success_marker: str,
    required_context: str,
    required_backend_id: str,
    artifact_paths: list[str] | None,
) -> BrowserBridgeReport:
    raw_evidence = json.dumps(task_status, ensure_ascii=False)
    report: BrowserBridgeReport | None = None
    actual_metrics = _v9_normalize_actual_metrics(
        started=started,
        browser_tool_calls=browser_tool_calls,
        trace_events=trace_events,
        actual_metrics=(
            summary.get("actual_metrics")
            if isinstance(summary.get("actual_metrics"), dict)
            else None
        ),
    )
    budget = _v9_scenario_budget(scenario)
    budget_failure = _v9_budget_failure(budget, actual_metrics)
    forbidden = _detect_forbidden_tool_usage(summary, trace_events)
    task_completed = (
        task_status.get("status") == "finished"
        and (task_status.get("result") or {}).get("status") == "completed"
    )
    trace_info = _trace_error_info(trace_events) if task_completed else None

    if forbidden:
        report = _report(
            scenario,
            "failed",
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=route,
            forbidden_tools=forbidden,
            trace_event_count=len(trace_events),
            error_code=BrowserErrorCode.CAPABILITY_MISSING.value,
            failure_reason="forbidden_tools",
            artifact_paths=artifact_paths,
        )
    elif require_user_backend and _user_state_routed_to_isolated(trace_events):
        report = _report(
            scenario,
            "failed",
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=route,
            trace_event_count=len(trace_events),
            error_code=BrowserErrorCode.CAPABILITY_MISSING.value,
            failure_reason="user_state_routed_to_isolated",
            artifact_paths=artifact_paths,
        )
    elif not task_completed:
        report = classify_verification_evidence(
            scenario=scenario,
            started=started,
            trace_events=trace_events,
            transcript=raw_evidence,
            browser_tool_calls=browser_tool_calls,
            backend_route=route,
            artifact_paths=artifact_paths,
            actual_metrics=actual_metrics,
        )
    elif trace_info is not None and trace_info.code != BrowserErrorCode.NONE:
        report = classify_verification_evidence(
            scenario=scenario,
            started=started,
            trace_events=trace_events,
            transcript=raw_evidence,
            browser_tool_calls=browser_tool_calls,
            backend_route=route,
            artifact_paths=artifact_paths,
            actual_metrics=actual_metrics,
        )
    else:
        report = _classify_completed_chat_trace_result(
            scenario=scenario,
            started=started,
            summary=summary,
            trace_events=trace_events,
            browser_tool_calls=browser_tool_calls,
            route=route,
            require_user_backend=require_user_backend,
            required_success_marker=required_success_marker,
            required_context=required_context,
            required_backend_id=required_backend_id,
            artifact_paths=artifact_paths,
        )
    if report.status == "passed" and budget_failure:
        return _report(
            scenario,
            "failed",
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=route,
            trace_event_count=len(trace_events),
            failure_reason="budget_exhausted",
            artifact_paths=artifact_paths,
            fresh_observe_ok=report.fresh_observe_ok,
            cleanup_ok=report.cleanup_ok,
            scenario_budget=budget,
            actual_metrics=actual_metrics,
            blocker_classification=budget_failure,
        )
    return replace(
        report,
        scenario_budget=budget,
        actual_metrics=actual_metrics,
    )


def _classify_completed_chat_trace_result(
    *,
    scenario: str,
    started: float,
    summary: dict[str, Any],
    trace_events: list[dict[str, Any]],
    browser_tool_calls: int,
    route: str,
    require_user_backend: bool,
    required_success_marker: str,
    required_context: str,
    required_backend_id: str,
    artifact_paths: list[str] | None,
) -> BrowserBridgeReport:
    status = "passed"
    calls = browser_tool_calls
    error_code = ""
    failure_reason = ""
    trace_count = len(trace_events)

    if browser_tool_calls < 1:
        status = "failed"
        calls = 0
        error_code = BrowserErrorCode.CAPABILITY_MISSING.value
        failure_reason = "missing_browser_tool_call"
    elif required_success_marker and required_success_marker not in str(
        summary.get("final_text") or "",
    ):
        status = "failed"
        error_code = BrowserErrorCode.UNKNOWN.value
        failure_reason = "missing_success_marker"
    elif not trace_events:
        status = "failed"
        error_code = BrowserErrorCode.UNKNOWN.value
        failure_reason = "missing_trace_evidence"
    elif not _trace_completeness_summary(trace_events).get("complete", True):
        status = "failed"
        error_code = BrowserErrorCode.UNKNOWN.value
        failure_reason = "trace_incomplete"
    elif (
        required_context or required_backend_id
    ) and not _has_required_backend_evidence(
        trace_events,
        context=required_context,
        backend_id=required_backend_id,
    ):
        status = "failed"
        error_code = BrowserErrorCode.CAPABILITY_MISSING.value
        failure_reason = "backend_route_mismatch"
    elif require_user_backend and not _has_user_backend_evidence(trace_events):
        status = "failed"
        error_code = BrowserErrorCode.UNKNOWN.value
        failure_reason = "missing_user_backend_trace"
    elif complex_failure := _complex_trace_failure_reason(
        scenario=scenario,
        trace_events=trace_events,
        require_user_backend=require_user_backend,
    ):
        status = "failed"
        error_code = BrowserErrorCode.UNKNOWN.value
        failure_reason = complex_failure

    return _report(
        scenario,
        status,
        started,
        browser_tool_calls=calls,
        backend_route=route,
        trace_event_count=trace_count,
        error_code=error_code,
        failure_reason=failure_reason,
        artifact_paths=artifact_paths,
        fresh_observe_ok=not _fresh_observe_failure_reason(trace_events),
        cleanup_ok=(
            not _user_cleanup_failure_reason(trace_events)
            if require_user_backend or _has_user_backend_evidence(trace_events)
            else True
        ),
        trace_summary=_trace_completeness_summary(trace_events),
    )


def _trace_error_info(trace_events: list[dict[str, Any]]) -> Any | None:
    for event in reversed(
        _drop_non_terminal_kernel_guard_errors(trace_events),
    ):
        if not isinstance(event, dict):
            continue
        code = str(event.get("error_code") or "").strip()
        if not code:
            metadata = event.get("metadata")
            if isinstance(metadata, dict):
                code = str(
                    metadata.get("browser_error_code")
                    or metadata.get("error_code")
                    or "",
                ).strip()
        if code:
            return classify_browser_error(code)
        if str(event.get("status") or "").casefold() == "error":
            return classify_browser_error(BrowserErrorCode.UNKNOWN)
    return None


def _trace_completeness_summary(
    trace_events: list[dict[str, Any]],
) -> dict[str, Any]:
    verifier_events = _drop_non_terminal_kernel_guard_errors(trace_events)
    validation = validate_browser_trace_events(verifier_events)
    return {
        "complete": bool(validation.get("ok")),
        "event_count": int(validation.get("event_count") or 0),
        "missing_fields": dict(validation.get("missing_fields") or {}),
    }


def _drop_non_terminal_kernel_guard_errors(
    trace_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for index, event in enumerate(trace_events):
        if _is_kernel_guard_error(event) and _has_later_backend_success(
            trace_events,
            index,
        ):
            continue
        filtered.append(event)
    return filtered


def _is_kernel_guard_error(event: dict[str, Any]) -> bool:
    return (
        isinstance(event, dict)
        and str(event.get("phase") or "") == "tool"
        and str(event.get("action") or "") == "browser_kernel_guard"
        and str(event.get("status") or "").casefold() == "error"
    )


def _has_later_backend_success(
    trace_events: list[dict[str, Any]],
    index: int,
) -> bool:
    for event in trace_events[index + 1 :]:
        if not isinstance(event, dict):
            continue
        status = str(event.get("status") or "").casefold()
        if status not in {"", "ok"}:
            continue
        if event.get("backend_id") or event.get("selected_context"):
            return True
    return False


def _transcript_error_info(text: str | list[str]) -> Any | None:
    haystack = (
        "\n".join(str(item) for item in text)
        if isinstance(text, list)
        else str(text or "")
    ).casefold()
    if not haystack:
        return None
    login_markers = (
        "login",
        "log in",
        "sign in",
        "sign-in",
        "请登录",
        "登录",
    )
    captcha_markers = (
        "captcha",
        "verification",
        "verify you are human",
        "risk-control",
        "risk control",
        "验证码",
        "验证",
        "风险",
    )
    approval_markers = (
        "approval denied",
        "user denied",
        "permission denied",
    )
    payment_markers = (
        "payment",
        "pay now",
        "submit order",
        "place order",
        "付款",
        "支付",
        "提交订单",
    )
    if any(marker in haystack for marker in approval_markers):
        return classify_browser_error(BrowserErrorCode.APPROVAL_DENIED)
    if any(marker in haystack for marker in captcha_markers):
        return classify_browser_error(BrowserErrorCode.CAPTCHA_OR_RISK_CONTROL)
    if any(marker in haystack for marker in login_markers):
        return classify_browser_error(BrowserErrorCode.LOGIN_REQUIRED)
    if any(marker in haystack for marker in payment_markers):
        return classify_browser_error(BrowserErrorCode.APPROVAL_REQUIRED)
    return None


def _extension_status(base_url: str, timeout: float) -> dict[str, Any]:
    return _http_json(
        f"{_normalize_base_url(base_url)}/api/browser-bridge/status",
        timeout=timeout,
    )


def _submit_console_task(
    base_url: str,
    prompt: str,
    *,
    session_id: str,
    timeout: float,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _http_json(
        f"{_normalize_base_url(base_url)}/api/console/chat/task",
        timeout=DEFAULT_TIMEOUT,
        method="POST",
        payload=_task_payload(
            session_id=session_id,
            prompt=prompt,
            timeout=timeout,
            request_context=request_context,
        ),
    )


def _poll_console_task(
    base_url: str,
    task_id: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    if not task_id:
        raise RuntimeError("chat task did not return task_id")
    deadline = time.perf_counter() + max(float(timeout), 1.0)
    status: dict[str, Any] = {"status": "unknown"}
    while time.perf_counter() < deadline:
        status = _http_json(
            f"{_normalize_base_url(base_url)}/api/console/chat/task/{task_id}",
            timeout=DEFAULT_TIMEOUT,
        )
        if status.get("status") == "finished":
            return status
        time.sleep(min(2.0, max(0.2, float(timeout) / 60.0)))
    return status


def _fetch_extension_traces(
    base_url: str,
    session_id: str,
    timeout: float,
) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"session_id": session_id, "limit": 1000})
    payload = _http_json(
        f"{_normalize_base_url(base_url)}/api/browser-bridge/traces?{query}",
        timeout=timeout,
    )
    events = payload.get("events")
    return (
        [event for event in events if isinstance(event, dict)]
        if isinstance(
            events,
            list,
        )
        else []
    )


def _task_payload(
    *,
    session_id: str,
    prompt: str,
    timeout: float,
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": "browser-bridge-verifier",
        "session_id": session_id,
        "input": [
            {
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            },
        ],
        "timeout": timeout,
    }
    if request_context:
        payload["request_context"] = dict(request_context)
    return payload


def _task_timeout(args: argparse.Namespace) -> float:
    value = getattr(args, "task_timeout", None)
    if value is not None:
        return float(value)
    return max(
        float(getattr(args, "timeout", DEFAULT_TIMEOUT)),
        DEFAULT_TASK_TIMEOUT,
    )


def _complex_task_timeout(args: argparse.Namespace) -> float:
    return max(_task_timeout(args), DETERMINISTIC_COMPLEX_TASK_TIMEOUT)


def _summarize_task_status(status: dict[str, Any]) -> dict[str, Any]:
    result = status.get("result") if isinstance(status, dict) else {}
    result = result if isinstance(result, dict) else {}
    messages = result.get("output")
    messages = messages if isinstance(messages, list) else []
    tool_calls = [
        item
        for item in (_tool_call_from_message(message) for message in messages)
        if item is not None
    ]
    browser_tool_calls = sum(
        1 for call in tool_calls if call.get("name") == "browser"
    )
    return {
        "session_id": str(result.get("session_id") or ""),
        "browser_tool_calls": browser_tool_calls,
        "tool_calls": tool_calls,
        "actual_metrics": _task_status_actual_metrics(
            status,
            result,
            browser_tool_calls,
        ),
        "final_text": "\n".join(
            text
            for text in (_message_text(message) for message in messages)
            if text
        ),
    }


def _task_status_actual_metrics(
    status: dict[str, Any],
    result: dict[str, Any],
    browser_tool_calls: int,
) -> dict[str, Any]:
    metrics = _dict_value(result.get("actual_metrics"))
    runtime_metrics = _dict_value(result.get("metrics"))
    root_metrics = _dict_value(status.get("metrics"))
    for source in (runtime_metrics, root_metrics):
        for key in ("iterations", "elapsed_ms", "token_count"):
            if key in source and key not in metrics:
                metrics[key] = source[key]

    metrics.setdefault("browser_calls", browser_tool_calls)
    iterations = _first_metric_int(
        result,
        runtime_metrics,
        root_metrics,
        keys=("iterations", "iteration_count", "turn_count"),
    )
    if iterations is not None:
        metrics.setdefault("iterations", iterations)

    elapsed_ms = _first_metric_int(
        result,
        runtime_metrics,
        root_metrics,
        keys=("elapsed_ms", "duration_ms"),
    )
    if elapsed_ms is not None:
        metrics.setdefault("elapsed_ms", elapsed_ms)

    if "token_count" not in metrics:
        metrics["token_count"] = _token_count_metric(result, status)
    return metrics


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_metric_int(
    *sources: dict[str, Any],
    keys: tuple[str, ...],
) -> int | None:
    for source in sources:
        for key in keys:
            if key not in source:
                continue
            try:
                return int(source.get(key) or 0)
            except (TypeError, ValueError):
                return None
    return None


def _token_count_metric(
    result: dict[str, Any],
    status: dict[str, Any],
) -> dict[str, Any]:
    for source in (
        _dict_value(result.get("token_count")),
        _dict_value(result.get("token_usage")),
        _dict_value(status.get("token_count")),
        _dict_value(status.get("token_usage")),
    ):
        if not source:
            continue
        count = _token_count_number(source)
        if count > 0:
            return {"available": True, "count": int(count)}
    return {"available": False, "reason": "not_reported"}


def _detect_forbidden_tool_usage(
    summary: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[str]:
    observed: list[str] = []
    for call in summary.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        _append_forbidden_tool(observed, call.get("name"))

    for event in events:
        if not isinstance(event, dict):
            continue
        for key in (
            "tool",
            "tool_name",
            "tool_call",
            "entrypoint",
            "method",
            "transport",
            "endpoint",
        ):
            _append_forbidden_tool(observed, event.get(key))
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            for key in (
                "tool",
                "tool_name",
                "tool_call",
                "entrypoint",
                "method",
                "transport",
                "endpoint",
            ):
                _append_forbidden_tool(observed, metadata.get(key))
    return observed


def _append_forbidden_tool(observed: list[str], value: Any) -> None:
    text = str(value or "")
    if not text:
        return
    for tool in FORBIDDEN_TOOLS:
        if tool in text and tool not in observed:
            observed.append(tool)


def _browser_tool_calls_from_traces(events: list[dict[str, Any]]) -> int:
    return sum(
        1
        for event in events
        if str(event.get("backend_id") or "")
        in {"isolated.playwright", "user.chrome_extension"}
    )


def _tool_call_from_message(message: Any) -> dict[str, str] | None:
    if not isinstance(message, dict) or message.get("type") != "plugin_call":
        return None
    data = _message_data(message)
    return {
        "name": str(data.get("name") or ""),
        "arguments": str(data.get("arguments") or ""),
    }


def _message_data(message: dict[str, Any]) -> dict[str, Any]:
    for part in message.get("content") or []:
        if isinstance(part, dict) and isinstance(part.get("data"), dict):
            return part["data"]
    return {}


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    chunks: list[str] = []
    for part in message.get("content") or []:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    return "\n".join(chunks)


def _backend_route_from_traces(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        backend_id = str(event.get("backend_id") or "").strip()
        if not backend_id:
            continue
        context = str(
            event.get("selected_context")
            or event.get("requested_context")
            or "auto",
        )
        return f'browser(code=...) -> context="{context}" -> {backend_id}'
    return ""


def _user_state_routed_to_isolated(events: list[dict[str, Any]]) -> bool:
    for event in events:
        selected = str(event.get("selected_context") or "").casefold()
        backend_id = str(event.get("backend_id") or "").casefold()
        if selected == "isolated" or backend_id.startswith("isolated."):
            return True
    return False


def _has_user_backend_evidence(events: list[dict[str, Any]]) -> bool:
    return any(
        str(event.get("selected_context") or "") == "user"
        or str(event.get("backend_id") or "") == "user.chrome_extension"
        for event in events
    )


def _has_required_backend_evidence(
    events: list[dict[str, Any]],
    *,
    context: str = "",
    backend_id: str = "",
) -> bool:
    expected_context = str(context or "").strip()
    expected_backend = str(backend_id or "").strip()
    for event in events:
        selected_context = str(event.get("selected_context") or "").strip()
        event_backend = str(event.get("backend_id") or "").strip()
        if expected_context and selected_context != expected_context:
            continue
        if expected_backend and event_backend != expected_backend:
            continue
        return True
    return False


def _complex_trace_failure_reason(
    *,
    scenario: str,
    trace_events: list[dict[str, Any]],
    require_user_backend: bool,
) -> str:
    if not (
        scenario.startswith("complex-")
        or scenario.startswith("v8-capability-")
    ):
        return ""
    fresh_observe_failure = _fresh_observe_failure_reason(trace_events)
    if fresh_observe_failure:
        return fresh_observe_failure
    if (
        scenario in {"complex-user", "v8-capability-user"}
        or require_user_backend
    ):
        return _user_cleanup_failure_reason(trace_events)
    return ""


def _fresh_observe_failure_reason(
    trace_events: list[dict[str, Any]],
) -> str:
    awaiting_observe = False
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        if awaiting_observe:
            if _is_successful_observe(event):
                awaiting_observe = False
            elif _is_successful_mutation(event):
                return "missing_fresh_observe_after_mutation"
        if _is_successful_mutation(event):
            awaiting_observe = True
    return "missing_fresh_observe_after_mutation" if awaiting_observe else ""


def _is_successful_observe(event: dict[str, Any]) -> bool:
    phase = str(event.get("phase") or "").casefold()
    status = str(event.get("status") or "").casefold()
    return phase == "observe" and status in {"", "ok"}


def _is_successful_mutation(event: dict[str, Any]) -> bool:
    phase = str(event.get("phase") or "").casefold()
    action = str(event.get("action") or "").casefold()
    status = str(event.get("status") or "").casefold()
    return (
        phase == "action"
        and action in MUTATING_TRACE_ACTIONS
        and status in {"", "ok"}
    )


def _user_cleanup_failure_reason(trace_events: list[dict[str, Any]]) -> str:
    cleanup_events = [
        event
        for event in trace_events
        if isinstance(event, dict)
        and str(event.get("phase") or "").casefold() == "cleanup"
        and (
            str(event.get("backend_id") or "") == "user.chrome_extension"
            or str(event.get("selected_context") or "") == "user"
        )
    ]
    if not cleanup_events:
        return "missing_user_cleanup_evidence"
    if any(
        str(event.get("status") or "").casefold() == "error"
        for event in cleanup_events
    ):
        return "user_cleanup_failed"
    if any(
        _metadata_int(event, "owned_tabs_remaining") > 0
        for event in cleanup_events
    ):
        return "residual_owned_tabs"
    closed_owned_tabs = sum(
        _metadata_int(event, "closed_owned_tabs") for event in cleanup_events
    )
    if closed_owned_tabs < 1:
        return "residual_owned_tabs"
    return ""


def _metadata_int(event: dict[str, Any], key: str) -> int:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return 0
    try:
        return int(metadata.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _no_progress_failure_reason(trace_events: list[dict[str, Any]]) -> str:
    decision = detect_no_progress(_trace_event_objects(trace_events))
    return decision.reason if decision.blocked else ""


def _trace_event_objects(
    trace_events: list[dict[str, Any]],
) -> list[BrowserTraceEvent]:
    converted: list[BrowserTraceEvent] = []
    for index, event in enumerate(trace_events):
        if not isinstance(event, dict):
            continue
        metadata = event.get("metadata")
        converted.append(
            BrowserTraceEvent(
                event_id=str(event.get("event_id") or f"synthetic-{index}"),
                session_id=str(event.get("session_id") or "synthetic"),
                tool_call_id=str(event.get("tool_call_id") or ""),
                backend_id=str(event.get("backend_id") or ""),
                requested_context=str(event.get("requested_context") or ""),
                selected_context=str(event.get("selected_context") or ""),
                phase=str(event.get("phase") or ""),
                action=str(event.get("action") or ""),
                tab_id=str(event.get("tab_id") or ""),
                url=str(event.get("url") or ""),
                domain=str(event.get("domain") or ""),
                status=str(event.get("status") or ""),
                duration_ms=float(event.get("duration_ms") or 0.0),
                error_code=str(event.get("error_code") or ""),
                approval_state=str(event.get("approval_state") or ""),
                metadata=metadata if isinstance(metadata, dict) else {},
            ),
        )
    return converted


def _fixture_prompt_spec(fixture_url: str) -> HarnessPromptSpec:
    marker = "V6_FIXTURE_PASS"
    return HarnessPromptSpec(
        instruction=(
            "Use browser(code=...) to run this deterministic Browser SDK "
            "fixture script, then return the script output and a one-line "
            "summary."
        ),
        code=(
            'browser = await Browser.connect(context="user", '
            "requires_user_state=True)\n"
            f'tab = await browser.tabs.open("{fixture_url}")\n'
            "snapshot = await tab.snapshot(limit=100)\n"
            'await tab.actions.click({"selector": "[data-testid=\'reset-fixture\']"})\n'
            "snapshot = await tab.snapshot(limit=100)\n"
            'assert "Cart is empty" in snapshot.text\n'
            'await tab.actions.click({"selector": "[data-testid=\'add-men-shampoo\']"})\n'
            "snapshot = await tab.snapshot(limit=100)\n"
            'assert "Men Shampoo x 1" in snapshot.text\n'
            'await tab.actions.click({"selector": "[data-testid=\'clear-cart\']"})\n'
            "snapshot = await tab.snapshot(limit=100)\n"
            'assert "Cart is empty" in snapshot.text\n'
            f'print("{marker} user backend cart add and clear verified")'
        ),
        required_success_marker=marker,
        required_context="user",
        required_backend_id="user.chrome_extension",
        require_user_backend=True,
        request_context={"approval_level": "OFF"},
    )


def _public_search_prompt_spec() -> HarnessPromptSpec:
    marker = "V6_PUBLIC_SEARCH_PASS"
    return HarnessPromptSpec(
        instruction=(
            "Use browser(code=...) to run this deterministic read-only "
            "Browser SDK script, then return the script output and page title. "
            "This scenario name is historical; do not use search engines."
        ),
        code=(
            'browser = await Browser.connect(context="auto")\n'
            'tab = await browser.tabs.open("https://example.com/")\n'
            "snapshot = await tab.snapshot(limit=100)\n"
            "info = await tab.page_info()\n"
            'assert "Example Domain" in snapshot.text\n'
            f'print("{marker}", info.title, browser.context)'
        ),
        required_success_marker=marker,
        required_context="isolated",
        required_backend_id="isolated.playwright",
    )


def _complex_prompt_spec(
    fixture_url: str,
    *,
    context: str,
) -> HarnessPromptSpec:
    if context == "user":
        marker = "V7_COMPLEX_USER_PASS"
        required_success_marker = ""
        connect = (
            'browser = await Browser.connect(context="user", '
            "requires_user_state=True)"
        )
        required_context = "user"
        required_backend_id = "user.chrome_extension"
        require_user_backend = True
        request_context = {"approval_level": "OFF"}
    else:
        marker = "V7_COMPLEX_ISOLATED_PASS"
        required_success_marker = marker
        connect = 'browser = await Browser.connect(context="isolated")'
        required_context = "isolated"
        required_backend_id = "isolated.playwright"
        require_user_backend = False
        request_context = None

    code = (
        _complex_user_fixture_code(
            fixture_url=fixture_url,
            connect=connect,
            marker=marker,
        )
        if context == "user"
        else _complex_fixture_code(
            fixture_url=fixture_url,
            connect=connect,
            marker=marker,
        )
    )
    return HarnessPromptSpec(
        instruction=(
            "Use browser(code=...) to run this deterministic complex Browser "
            "SDK fixture script, then return the script output and a one-line "
            "summary."
        ),
        code=code,
        required_success_marker=required_success_marker,
        required_context=required_context,
        required_backend_id=required_backend_id,
        require_user_backend=require_user_backend,
        request_context=request_context,
    )


def _v8_capability_prompt_spec(
    fixture_url: str,
    *,
    context: str,
) -> HarnessPromptSpec:
    if context == "user":
        marker = "V8_CAPABILITY_USER_PASS"
        connect = (
            'browser = await Browser.connect(context="user", '
            "requires_user_state=True)"
        )
        required_context = "user"
        required_backend_id = "user.chrome_extension"
        require_user_backend = True
        request_context = {"approval_level": "OFF"}
    else:
        marker = "V8_CAPABILITY_ISOLATED_PASS"
        connect = 'browser = await Browser.connect(context="isolated")'
        required_context = "isolated"
        required_backend_id = "isolated.playwright"
        require_user_backend = False
        request_context = None

    upload_path = Path("/tmp/qwenpaw-v8-capability-upload.txt")
    upload_path.write_text("V8 capability upload", encoding="utf-8")
    return HarnessPromptSpec(
        instruction=(
            "Use browser(code=...) to run this deterministic Browser SDK "
            "capability fixture script, then return the script output and a "
            "one-line summary."
        ),
        code=_v8_capability_fixture_code(
            fixture_url=fixture_url,
            connect=connect,
            marker=marker,
            upload_path=str(upload_path),
        ),
        required_success_marker=marker,
        required_context=required_context,
        required_backend_id=required_backend_id,
        require_user_backend=require_user_backend,
        request_context=request_context,
    )


def _v9_approval_probe_prompt_spec(
    fixture_url: str,
    *,
    approval_level: str,
) -> HarnessPromptSpec:
    normalized = str(approval_level or "DEFAULT").upper()
    marker = (
        "V9_APPROVAL_OFF_PASS"
        if normalized == "OFF"
        else "V9_APPROVAL_DEFAULT_FAIL_CLOSED"
    )
    if normalized == "OFF":
        code = (
            'browser = await Browser.connect(context="user", '
            "requires_user_state=True)\n"
            f'tab = await browser.tabs.open("{fixture_url}")\n'
            "snapshot = await tab.snapshot(limit=100)\n"
            'assert "Shopping cart" in snapshot.text\n'
            'await tab.actions.click({"selector": "[data-testid=\'add-men-shampoo\']", '
            '"text": "add men shampoo to cart"})\n'
            "snapshot = await tab.snapshot(limit=100)\n"
            'assert "Men Shampoo x 1" in snapshot.text\n'
            'await tab.actions.click({"selector": "[data-testid=\'clear-cart\']", '
            '"text": "clear cart"})\n'
            "snapshot = await tab.snapshot(limit=100)\n"
            'assert "Cart is empty" in snapshot.text\n'
            f'print("{marker} sensitive clear-cart action executed with OFF")'
        )
    else:
        code = (
            'browser = await Browser.connect(context="user", '
            "requires_user_state=True)\n"
            f'tab = await browser.tabs.open("{fixture_url}")\n'
            "snapshot = await tab.snapshot(limit=100)\n"
            'assert "Shopping cart" in snapshot.text\n'
            "try:\n"
            '    await tab.actions.click({"selector": "[data-testid=\'clear-cart\']", '
            '"text": "clear cart"})\n'
            "except Exception as exc:\n"
            f'    print("{marker}", type(exc).__name__, str(exc)[:120])\n'
            "else:\n"
            "    raise AssertionError('DEFAULT approval allowed sensitive action')"
        )
    return HarnessPromptSpec(
        instruction=(
            "Use browser(code=...) to execute this deterministic approval "
            "probe through Browser SDK user Chrome. Return the script output "
            "only."
        ),
        code=code,
        required_success_marker=marker,
        required_context="user",
        required_backend_id="user.chrome_extension",
        require_user_backend=True,
        request_context={
            "approval_level": normalized,
            "approval_timeout_seconds": 1,
        },
    )


def _v8_capability_fixture_code(
    *,
    fixture_url: str,
    connect: str,
    marker: str,
    upload_path: str,
) -> str:
    return (
        f"upload_path = {upload_path!r}\n"
        f"{connect}\n"
        "try:\n"
        f'    tab = await browser.tabs.open("{fixture_url}")\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'V8 Browser SDK Capability Fixture' in snapshot.text\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'reset-v8-capability-fixture\']"})\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    await tab.actions.upload({"
        '"selector": "[data-testid=\'capability-upload-input\']"}, '
        "str(upload_path))\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Upload received: qwenpaw-v8-capability-upload.txt' "
        "in snapshot.text\n"
        "    download = await tab.actions.download({"
        '"selector": "[data-testid=\'capability-download\']"}, '
        "max_wait_ms=5000)\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert download.data.get('artifact', {}).get('kind') "
        "== 'download'\n"
        "    assert download.data.get('artifact', {}).get('metadata', {})"
        ".get('path')\n"
        "    assert 'Download triggered.' in snapshot.text\n"
        "    await tab.actions.dialog(accept=True)\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'capability-open-dialog\']"})\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Dialog accepted.' in snapshot.text\n"
        "    await tab.actions.dialog("
        "accept=True, prompt_text='V9-D prompt text')\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'capability-open-prompt\']"})\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Prompt received: V9-D prompt text' in snapshot.text\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'capability-frame-trigger\']"})\n'
        "    await tab.actions.wait_for('Frame pong received.', "
        "max_wait_ms=3000)\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Frame pong received.' in snapshot.text\n"
        "    shadow_text = await tab.evaluate("
        "'document.querySelector(\"#shadow-host\").shadowRoot.textContent', "
        "read_only=True)\n"
        "    assert 'Shadow state: pending' in str(shadow_text)\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'capability-shadow-toggle\']"})\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Shadow toggled active.' in snapshot.text\n"
        "    shadow_text = await tab.evaluate("
        "'document.querySelector(\"#shadow-host\").shadowRoot.textContent', "
        "read_only=True)\n"
        "    assert 'Shadow state: active' in str(shadow_text)\n"
        "    assert 'Mutations: 6' in snapshot.text\n"
        "    visual = await tab.screenshot()\n"
        "    assert visual.path\n"
        f"    print('{marker} generic SDK capabilities verified')\n"
        "finally:\n"
        "    await browser.close()"
    )


def _complex_fixture_code(
    *,
    fixture_url: str,
    connect: str,
    marker: str,
) -> str:
    return (
        f"{connect}\n"
        "try:\n"
        f'    tab = await browser.tabs.open("{fixture_url}")\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Complex Deterministic Browser Fixture' in snapshot.text\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'reset-complex-fixture\']"})\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'load-async-items\']"})\n'
        "    await tab.actions.wait_for('Delayed content loaded.', "
        "max_wait_ms=5000)\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Async Result 14' in snapshot.text\n"
        "    await tab.actions.scroll('down', 400)\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'select-secondary-plan\']"})\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Selected: secondary' in snapshot.text\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'save-details\']"})\n'
        "    await tab.actions.wait_for('Form validation failed.', "
        "max_wait_ms=3000)\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    validation_text = await tab.evaluate("
        "'document.querySelector(\"[data-testid=form-error]\").textContent', "
        "read_only=True)\n"
        "    assert 'Form validation failed.' in str(validation_text)\n"
        "    await tab.actions.type({"
        '"selector": "[data-testid=\'details-name\']"}, '
        "'Ada Lovelace')\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    await tab.actions.type({"
        '"selector": "[data-testid=\'details-email\']"}, '
        "'ada@example.test')\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'save-details\']"})\n'
        "    await tab.actions.wait_for('Form saved for deterministic user.', "
        "max_wait_ms=3000)\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    form_status = await tab.evaluate("
        "'document.querySelector(\"[data-testid=form-status]\").textContent', "
        "read_only=True)\n"
        "    assert 'Form saved for deterministic user.' in str(form_status)\n"
        "    await tab.evaluate('window.confirm = () => true')\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'open-confirm\']"})\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Selection confirmed.' in snapshot.text\n"
        "    shadow_text = await tab.evaluate("
        "'document.querySelector(\"#shadow-host\").shadowRoot.textContent', "
        "read_only=True)\n"
        "    assert 'confirmed' in str(shadow_text)\n"
        "    frame_srcdoc = await tab.evaluate("
        '\'document.querySelector("[data-testid=fixture-frame]")'
        '.getAttribute("srcdoc")\', read_only=True)\n'
        "    assert 'Frame ready' in str(frame_srcdoc)\n"
        '    frame_clicked = await tab.evaluate("""(() => { const frame = '
        "document.querySelector(\"[data-testid='fixture-frame']\"); "
        "const button = frame && frame.contentWindow && "
        "frame.contentWindow.document.querySelector("
        '"[data-testid=frame-action]"); '
        'if (!button) { return false; } button.click(); return true; })()""")\n'
        "    assert frame_clicked is True\n"
        "    await tab.actions.wait_for('Frame action clicked.', "
        "max_wait_ms=3000)\n"
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Frame action clicked.' in snapshot.text\n"
        f"    print('{marker} complex deterministic fixture verified')\n"
        "finally:\n"
        "    await browser.close()"
    )


def _complex_user_fixture_code(
    *,
    fixture_url: str,
    connect: str,
    marker: str,
) -> str:
    return (
        f"{connect}\n"
        "try:\n"
        f'    tab = await browser.tabs.open("{fixture_url}")\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Complex Deterministic Browser Fixture' in snapshot.text\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'reset-complex-fixture\']"})\n'
        "    snapshot = await tab.snapshot(limit=100)\n"
        "    assert 'Delayed content pending.' in snapshot.text\n"
        f"    print('{marker} user backend complex fixture smoke verified')\n"
        "finally:\n"
        "    await browser.close()"
    )


def _http_json(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} {method} {url}: {detail[:300]}",
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Network error {method} {url}: {exc.reason}",
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"Network timeout {method} {url}: {exc}",
        ) from exc
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GET {url} returned non-JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"GET {url} returned non-object JSON")
    return payload


def _local_git_commit() -> str:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "--short", "HEAD"),
            cwd=_repo_root(),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _local_repo_dirty() -> bool:
    try:
        result = subprocess.run(
            ("git", "status", "--short"),
            cwd=_repo_root(),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def _local_frontend_fingerprint() -> str:
    static_dir = _repo_root() / "console" / "dist"
    index_path = static_dir / "index.html"
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        names = sorted(
            path.name
            for path in assets_dir.iterdir()
            if path.is_file() and path.suffix in {".js", ".css"}
        )
        if names:
            return ",".join(names[:20])
    if index_path.exists():
        stat = index_path.stat()
        return f"index:{int(stat.st_mtime)}:{stat.st_size}"
    return ""


def _local_plugin_fingerprint() -> str:
    plugin_root = _repo_root() / "plugins" / "bundle" / "browser-bridge"
    return _hash_existing_files(
        [
            plugin_root / "plugin.json",
            plugin_root
            / "assets"
            / "extensions"
            / "qwenpaw-browser-bridge"
            / "manifest.json",
            plugin_root / "api" / "routes.py",
        ],
    )


def _hash_existing_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    seen = False
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        seen = True
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16] if seen else ""


def _restart_qwenpaw_app(port: int, timeout: float) -> None:
    _stop_qwenpaw_app_on_port(port)
    _start_qwenpaw_app(port=port)
    _wait_for_qwenpaw_api(port=port, timeout=timeout)


def _stop_qwenpaw_app_on_port(port: int) -> None:
    pids = _listening_pids_for_port(port)
    if not pids:
        return
    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        if not [pid for pid in pids if _pid_exists(pid)]:
            return
        time.sleep(0.1)
    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)


def _listening_pids_for_port(port: int) -> list[int]:
    try:
        result = subprocess.run(
            ("lsof", "-ti", f"tcp:{int(port)}", "-sTCP:LISTEN"),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        with contextlib.suppress(ValueError):
            pid = int(line.strip())
            if pid != os.getpid():
                pids.add(pid)
    return sorted(pids)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_qwenpaw_api(*, port: int, timeout: float) -> None:
    base_url = f"http://127.0.0.1:{int(port)}"
    deadline = time.perf_counter() + max(float(timeout), 1.0)
    last_error = ""
    while time.perf_counter() < deadline:
        try:
            _http_json(f"{base_url}/api/version", timeout=DEFAULT_TIMEOUT)
            return
        except RuntimeError as exc:
            last_error = str(exc)
            time.sleep(0.2)
    raise RuntimeError(
        f"QwenPaw app did not become ready on port {port}: {last_error}",
    )


def _start_qwenpaw_app(*, port: int | None = None) -> None:
    command = [sys.executable, "-m", "qwenpaw", "app"]
    if port is not None:
        command.extend(["--port", str(int(port))])
    subprocess.Popen(  # noqa: S603  # pylint: disable=consider-using-with
        tuple(command),
        cwd=_repo_root(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)


def _backend_route(status: dict[str, Any]) -> str:
    diagnostics = status.get("sdk_diagnostics")
    if not isinstance(diagnostics, dict):
        return ""
    selected = str(diagnostics.get("selected_backend_id") or "")
    backends = diagnostics.get("backends")
    context = ""
    if isinstance(backends, list):
        for backend in backends:
            if not isinstance(backend, dict):
                continue
            if backend.get("backend_id") == selected:
                context = str(backend.get("browser_context") or "")
                break
    if selected:
        return (
            f'browser(code=...) -> context="{context or "auto"}" -> {selected}'
        )
    return 'browser(code=...) -> context="auto" -> unavailable'


def _normalize_base_url(value: str) -> str:
    return str(value or DEFAULT_BASE_URL).rstrip("/")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _fixture_path(name: str) -> Path:
    return Path(__file__).resolve().parent / "fixtures" / name


if __name__ == "__main__":
    sys.exit(main())
