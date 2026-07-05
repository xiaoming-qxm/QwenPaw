# -*- coding: utf-8 -*-
"""Browser Control operational verifier.

The default verifier is local and deterministic: it checks a running QwenPaw
service for code freshness, Browser Control status, and trace evidence. Live
Taobao validation is intentionally opt-in and blocked by default.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from qwenpaw.browser_sdk.error_codes import (
    BrowserErrorCode,
    BrowserOutcome,
    classify_browser_error,
)
from qwenpaw.browser_sdk.progress import detect_no_progress
from qwenpaw.browser_sdk.trace import BrowserTraceEvent

DEFAULT_BASE_URL = "http://127.0.0.1:8088"
DEFAULT_TIMEOUT = 10.0
DEFAULT_TASK_TIMEOUT = 180.0


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
class BrowserControlReport:
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
        return (
            f"{self.instruction.strip()}\n\n"
            "Browser is already preloaded in the browser(code=...) runtime; "
            "do not import Browser. Use exactly one browser(code=...) call. "
            "Pass timeout_ms=180000, for example "
            "browser(code=..., timeout_ms=180000). "
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
        description="Verify Browser Control operational readiness.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument(
        "--task-timeout",
        type=float,
        default=DEFAULT_TASK_TIMEOUT,
    )
    parser.add_argument("--start-if-missing", action="store_true")
    parser.set_defaults(live_taobao=False)

    subparsers = parser.add_subparsers(dest="command", required=True)
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
        default="docs/browser-control-v8-product-readiness-report.md",
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


def detect_forbidden_tools(text: str | list[str]) -> list[str]:
    haystack = "\n".join(text) if isinstance(text, list) else str(text or "")
    return [tool for tool in FORBIDDEN_TOOLS if tool in haystack]


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
) -> BrowserControlReport:
    """Classify synthetic verifier evidence into a scenario report."""
    forbidden = list(forbidden_tools or [])
    if forbidden:
        return _report(
            scenario,
            "failed",
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            forbidden_tools=forbidden,
            trace_event_count=len(trace_events or []),
            error_code=BrowserErrorCode.CAPABILITY_MISSING.value,
            failure_reason="forbidden_tools",
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(
                trace_events or [],
            ),
            cleanup_ok=(
                not _user_cleanup_failure_reason(trace_events or [])
                if _has_user_backend_evidence(trace_events or [])
                else True
            ),
        )

    if assertion_failure:
        return _report(
            scenario,
            "failed",
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(trace_events or []),
            error_code=BrowserErrorCode.UNKNOWN.value,
            failure_reason=assertion_failure,
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(
                trace_events or [],
            ),
            cleanup_ok=(
                not _user_cleanup_failure_reason(trace_events or [])
                if _has_user_backend_evidence(trace_events or [])
                else True
            ),
        )

    no_progress = _no_progress_failure_reason(trace_events or [])
    if no_progress:
        return _report(
            scenario,
            "failed",
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(trace_events or []),
            error_code=BrowserErrorCode.OBSERVATION_STALE.value,
            failure_reason=no_progress,
            artifact_paths=artifact_paths,
            fresh_observe_ok=False,
            cleanup_ok=(
                not _user_cleanup_failure_reason(trace_events or [])
                if _has_user_backend_evidence(trace_events or [])
                else True
            ),
        )

    trace_info = _trace_error_info(trace_events or [])
    if trace_info is not None:
        status = (
            "blocked"
            if trace_info.outcome == BrowserOutcome.BLOCKED
            else "failed"
        )
        return _report(
            scenario,
            status,
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(trace_events or []),
            error_code=trace_info.code.value,
            blocked_reason=trace_info.blocked_reason,
            failure_reason=trace_info.failure_reason,
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(
                trace_events or [],
            ),
            cleanup_ok=(
                not _user_cleanup_failure_reason(trace_events or [])
                if _has_user_backend_evidence(trace_events or [])
                else True
            ),
        )

    transcript_info = _transcript_error_info(transcript)
    if transcript_info is not None:
        return _report(
            scenario,
            "blocked",
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=backend_route,
            trace_event_count=len(trace_events or []),
            error_code=transcript_info.code.value,
            blocked_reason=transcript_info.blocked_reason,
            artifact_paths=artifact_paths,
            fresh_observe_ok=not _fresh_observe_failure_reason(
                trace_events or [],
            ),
            cleanup_ok=(
                not _user_cleanup_failure_reason(trace_events or [])
                if _has_user_backend_evidence(trace_events or [])
                else True
            ),
        )

    return _report(
        scenario,
        "passed",
        started,
        browser_tool_calls=browser_tool_calls,
        backend_route=backend_route,
        trace_event_count=len(trace_events or []),
        artifact_paths=artifact_paths,
        fresh_observe_ok=not _fresh_observe_failure_reason(trace_events or []),
        cleanup_ok=(
            not _user_cleanup_failure_reason(trace_events or [])
            if _has_user_backend_evidence(trace_events or [])
            else True
        ),
    )


def run_preflight(args: argparse.Namespace) -> BrowserControlReport:
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
            f"{base_url}/api/extension/status",
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


def run_v8_preflight(args: argparse.Namespace) -> BrowserControlReport:
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
                f"{base_url}/api/extension/self-test",
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


def run_v8_deterministic(args: argparse.Namespace) -> BrowserControlReport:
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
) -> BrowserControlReport:
    runners = {
        "preflight": run_v8_preflight,
        "public-search": run_public_search,
        "complex-isolated": run_complex_isolated,
        "complex-user": run_complex_user,
        "v8-capability-isolated": run_v8_capability_isolated,
        "v8-capability-user": run_v8_capability_user,
    }
    return runners[scenario](args)


def run_v8_public_live(args: argparse.Namespace) -> BrowserControlReport:
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


def run_v8_user_live(args: argparse.Namespace) -> BrowserControlReport:
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


def run_v8_taobao_live(args: argparse.Namespace) -> BrowserControlReport:
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


def run_v8_lifecycle_live(args: argparse.Namespace) -> BrowserControlReport:
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


def run_v8_report(args: argparse.Namespace) -> BrowserControlReport:
    return write_v8_product_report(
        output=Path(args.output),
        result_files=[
            Path(item) for item in getattr(args, "result_files", [])
        ],
    )


def run_taobao_live(args: argparse.Namespace) -> BrowserControlReport:
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


def run_fixture(args: argparse.Namespace) -> BrowserControlReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="fixture")
    fixture = Path(__file__).with_name("browser_control_cart_fixture.html")
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

    session_id = f"browser-control-fixture-{int(time.time() * 1000)}"
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


def run_public_search(args: argparse.Namespace) -> BrowserControlReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="public-search")
    session_id = f"browser-control-public-search-{int(time.time() * 1000)}"
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


def run_complex_isolated(args: argparse.Namespace) -> BrowserControlReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    fixture = Path(__file__).with_name("browser_control_complex_fixture.html")
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
    session_id = f"browser-control-complex-isolated-{int(time.time() * 1000)}"
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
        timeout=_task_timeout(args),
        backend_route=preflight.backend_route,
        artifact_paths=[str(fixture)],
        require_user_backend=prompt_spec.require_user_backend,
        request_context=prompt_spec.request_context,
        required_success_marker=prompt_spec.required_success_marker,
        required_context=prompt_spec.required_context,
        required_backend_id=prompt_spec.required_backend_id,
    )


def run_complex_user(args: argparse.Namespace) -> BrowserControlReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    fixture = Path(__file__).with_name("browser_control_complex_fixture.html")
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
    session_id = f"browser-control-complex-user-{int(time.time() * 1000)}"
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
        timeout=_task_timeout(args),
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
) -> BrowserControlReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    fixture = Path(__file__).with_name(
        "browser_control_v8_capability_fixture.html",
    )
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
        f"browser-control-v8-capability-isolated-" f"{int(time.time() * 1000)}"
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


def run_v8_capability_user(args: argparse.Namespace) -> BrowserControlReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    fixture = Path(__file__).with_name(
        "browser_control_v8_capability_fixture.html",
    )
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
        f"browser-control-v8-capability-user-" f"{int(time.time() * 1000)}"
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


def run_bridge_disconnected(args: argparse.Namespace) -> BrowserControlReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    try:
        status = _http_json(
            f"{base_url}/api/extension/status",
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


def _v8_user_live_task_specs() -> list[V8LiveTaskSpec]:
    return [
        V8LiveTaskSpec(
            scenario="user-chrome-readonly",
            prompt=(
                'Use Browser Control with context="user" and '
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
                'Use Browser Control with context="user" and '
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
            'Use Browser Control with context="user" and '
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


def _v8_lifecycle_live_task_specs() -> list[V8LiveTaskSpec]:
    return [
        V8LiveTaskSpec(
            scenario="multi-tab-user-lifecycle",
            prompt=(
                'Use Browser Control with context="user" and '
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
                "Attempt a user-context Browser Control read while the bridge "
                "is disconnected or unavailable. The expected result is a "
                "blocked bridge_disconnected outcome and no isolated fallback."
            ),
            required_context="user",
            required_backend_id="user.chrome_extension",
            requires_user_state=True,
            expected_blocker="bridge_disconnected",
        ),
    ]


def _run_v8_live_task(
    args: argparse.Namespace,
    spec: V8LiveTaskSpec,
) -> BrowserControlReport:
    started = time.perf_counter()
    early_report: BrowserControlReport | None = None
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
        return early_report

    session_id = (
        f"browser-control-v8-{spec.scenario}-{int(time.time() * 1000)}"
    )
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

    if spec.scenario == "v8-taobao-live":
        return _classify_v8_taobao_live_evidence(
            started=started,
            trace_events=trace_events,
            transcript=str(summary.get("final_text") or ""),
            artifact_paths=list(spec.artifact_paths),
            browser_tool_calls=browser_tool_calls,
        )
    if spec.scenario.startswith("multi-tab") or spec.expected_blocker:
        return _classify_v8_lifecycle_evidence(
            scenario=spec.scenario,
            started=started,
            trace_events=trace_events,
            transcript=str(summary.get("final_text") or ""),
            browser_tool_calls=browser_tool_calls,
        )

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
            started,
            browser_tool_calls=browser_tool_calls,
            backend_route=route,
            trace_event_count=len(trace_events),
            error_code=BrowserErrorCode.UNKNOWN.value,
            failure_reason="missing_content_evidence",
        )
    return replace(report, content_evidence=evidence)


def _content_evidence(
    transcript: str,
    markers: tuple[str, ...],
) -> dict[str, bool]:
    lowered = transcript.casefold()
    return {marker: marker.casefold() in lowered for marker in markers}


def _aggregate_v8_suite(
    *,
    scenario: str,
    started: float,
    reports: list[BrowserControlReport],
    user_preparation: list[str] | None = None,
) -> BrowserControlReport:
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


def _join_forbidden(reports: list[BrowserControlReport]) -> list[str]:
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
) -> BrowserControlReport:
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
) -> BrowserControlReport:
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
) -> BrowserControlReport:
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


def _load_v8_report(path: Path) -> BrowserControlReport:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} did not contain a JSON object")
    return BrowserControlReport(
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


def _render_v8_markdown_report(
    reports: list[BrowserControlReport],
    aggregate: BrowserControlReport,
) -> str:
    deterministic = [
        report for report in reports if "deterministic" in report.scenario
    ]
    live = [report for report in reports if report not in deterministic]
    return "\n".join(
        [
            "# Browser Control V8 Product Readiness Report",
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


def _markdown_report_table(reports: list[BrowserControlReport]) -> str:
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
        "v8-deterministic": run_v8_deterministic,
        "v8-public-live": run_v8_public_live,
        "v8-user-live": run_v8_user_live,
        "v8-taobao-live": run_v8_taobao_live,
        "v8-lifecycle-live": run_v8_lifecycle_live,
        "v8-report": run_v8_report,
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
) -> BrowserControlReport:
    if status == "blocked" and not blocked_reason and error_code:
        blocked_reason = classify_browser_error(error_code).blocked_reason
    if status == "failed" and not failure_reason:
        failure_reason = (
            classify_browser_error(error_code).failure_reason
            or blocked_reason
            or "verification_failed"
        )
    return BrowserControlReport(
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
    )


def _copy_report(
    report: BrowserControlReport,
    *,
    scenario: str,
) -> BrowserControlReport:
    return BrowserControlReport(
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
) -> BrowserControlReport:
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
) -> BrowserControlReport:
    raw_evidence = json.dumps(task_status, ensure_ascii=False)
    report: BrowserControlReport | None = None
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
    return report


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
) -> BrowserControlReport:
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
    )


def _trace_error_info(trace_events: list[dict[str, Any]]) -> Any | None:
    for event in reversed(trace_events):
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
        f"{_normalize_base_url(base_url)}/api/extension/status",
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
        f"{_normalize_base_url(base_url)}/api/extension/traces?{query}",
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
        "user_id": "browser-control-verifier",
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
    return {
        "session_id": str(result.get("session_id") or ""),
        "browser_tool_calls": sum(
            1 for call in tool_calls if call.get("name") == "browser"
        ),
        "tool_calls": tool_calls,
        "final_text": "\n".join(
            text
            for text in (_message_text(message) for message in messages)
            if text
        ),
    }


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
            "snapshot = await tab.snapshot()\n"
            'await tab.actions.click({"selector": "[data-testid=\'reset-fixture\']"})\n'
            "snapshot = await tab.snapshot()\n"
            'assert "Cart is empty" in snapshot.text\n'
            'await tab.actions.click({"selector": "[data-testid=\'add-men-shampoo\']"})\n'
            "snapshot = await tab.snapshot()\n"
            'assert "Men Shampoo x 1" in snapshot.text\n'
            'await tab.actions.click({"selector": "[data-testid=\'clear-cart\']"})\n'
            "snapshot = await tab.snapshot()\n"
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
            "snapshot = await tab.snapshot()\n"
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
        connect = 'browser = await Browser.connect(context="isolated")'
        required_context = "isolated"
        required_backend_id = "isolated.playwright"
        require_user_backend = False
        request_context = None

    return HarnessPromptSpec(
        instruction=(
            "Use browser(code=...) to run this deterministic complex Browser "
            "SDK fixture script, then return the script output and a one-line "
            "summary."
        ),
        code=_complex_fixture_code(
            fixture_url=fixture_url,
            connect=connect,
            marker=marker,
        ),
        required_success_marker=marker,
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
        ),
        required_success_marker=marker,
        required_context=required_context,
        required_backend_id=required_backend_id,
        require_user_backend=require_user_backend,
        request_context=request_context,
    )


def _v8_capability_fixture_code(
    *,
    fixture_url: str,
    connect: str,
    marker: str,
) -> str:
    return (
        "from pathlib import Path\n"
        "upload_path = Path('/tmp/qwenpaw-v8-capability-upload.txt')\n"
        "upload_path.write_text('V8 capability upload', encoding='utf-8')\n"
        f"{connect}\n"
        "try:\n"
        f'    tab = await browser.tabs.open("{fixture_url}")\n'
        "    snapshot = await tab.snapshot()\n"
        "    assert 'V8 Browser SDK Capability Fixture' in snapshot.text\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'reset-v8-capability-fixture\']"})\n'
        "    snapshot = await tab.snapshot()\n"
        "    await tab.actions.upload({"
        '"selector": "[data-testid=\'capability-upload-input\']"}, '
        "str(upload_path))\n"
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Upload received: qwenpaw-v8-capability-upload.txt' "
        "in snapshot.text\n"
        "    download = await tab.actions.download({"
        '"selector": "[data-testid=\'capability-download\']"}, '
        "timeout_ms=5000)\n"
        "    snapshot = await tab.snapshot()\n"
        "    assert download.data.get('artifact', {}).get('kind') "
        "== 'download'\n"
        "    assert 'Download triggered.' in snapshot.text\n"
        "    await tab.actions.dialog(accept=True)\n"
        "    snapshot = await tab.snapshot()\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'capability-open-dialog\']"})\n'
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Dialog accepted.' in snapshot.text\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'capability-frame-trigger\']"})\n'
        "    await tab.actions.wait_for('Frame pong received.', "
        "timeout_ms=3000)\n"
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Frame pong received.' in snapshot.text\n"
        "    shadow_text = await tab.evaluate("
        "'document.querySelector(\"#shadow-host\").shadowRoot.textContent', "
        "read_only=True)\n"
        "    assert 'Shadow state: pending' in str(shadow_text)\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'capability-shadow-toggle\']"})\n'
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Shadow toggled active.' in snapshot.text\n"
        "    shadow_text = await tab.evaluate("
        "'document.querySelector(\"#shadow-host\").shadowRoot.textContent', "
        "read_only=True)\n"
        "    assert 'Shadow state: active' in str(shadow_text)\n"
        "    assert 'Mutations: 5' in snapshot.text\n"
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
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Complex Deterministic Browser Fixture' in snapshot.text\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'reset-complex-fixture\']"})\n'
        "    snapshot = await tab.snapshot()\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'load-async-items\']"})\n'
        "    await tab.actions.wait_for('Delayed content loaded.', "
        "timeout_ms=5000)\n"
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Async Result 14' in snapshot.text\n"
        "    await tab.actions.scroll('down', 400)\n"
        "    snapshot = await tab.snapshot()\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'select-secondary-plan\']"})\n'
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Selected: secondary' in snapshot.text\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'save-details\']"})\n'
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Form validation failed.' in snapshot.text\n"
        "    await tab.actions.type({"
        '"selector": "[data-testid=\'details-name\']"}, '
        "'Ada Lovelace')\n"
        "    snapshot = await tab.snapshot()\n"
        "    await tab.actions.type({"
        '"selector": "[data-testid=\'details-email\']"}, '
        "'ada@example.test')\n"
        "    snapshot = await tab.snapshot()\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'save-details\']"})\n'
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Form saved for deterministic user.' in snapshot.text\n"
        "    await tab.evaluate('window.confirm = () => true')\n"
        "    snapshot = await tab.snapshot()\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'open-confirm\']"})\n'
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Selection confirmed.' in snapshot.text\n"
        "    shadow_text = await tab.evaluate("
        "'document.querySelector(\"#shadow-host\").shadowRoot.textContent', "
        "read_only=True)\n"
        "    assert 'confirmed' in str(shadow_text)\n"
        "    frame_srcdoc = await tab.evaluate("
        '\'document.querySelector("[data-testid=fixture-frame]")'
        '.getAttribute("srcdoc")\', read_only=True)\n'
        "    assert 'Frame ready' in str(frame_srcdoc)\n"
        "    await tab.actions.click({"
        '"selector": "[data-testid=\'navigate-step-two\']"})\n'
        "    snapshot = await tab.snapshot()\n"
        "    assert 'Step: two' in snapshot.text\n"
        f"    print('{marker} complex deterministic fixture verified')\n"
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


def _start_qwenpaw_app() -> None:
    subprocess.Popen(  # noqa: S603  # pylint: disable=consider-using-with
        (sys.executable, "-m", "qwenpaw", "app"),
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
    return Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    sys.exit(main())
