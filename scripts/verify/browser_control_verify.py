# -*- coding: utf-8 -*-
"""Browser Control operational verifier.

The default verifier is local and deterministic: it checks a running QwenPaw
service for code freshness, Browser Control status, and trace evidence. Live
Taobao validation is intentionally opt-in and blocked by default.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qwenpaw.browser_sdk.error_codes import (
    BrowserErrorCode,
    BrowserOutcome,
    classify_browser_error,
)

DEFAULT_BASE_URL = "http://127.0.0.1:8088"
DEFAULT_TIMEOUT = 10.0
DEFAULT_TASK_TIMEOUT = 180.0
FORBIDDEN_TOOLS = (
    "browser_use",
    "DesktopScreenshot",
    "DesktopScreenShot",
    "ViewVideo",
    "RemoteBridge",
    "/ws/browser-sdk",
)


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
        }


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
    subparsers.add_parser("bridge-disconnected")
    taobao = subparsers.add_parser("taobao-live")
    taobao.add_argument("--live-taobao", action="store_true")
    return parser


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
        )

    return _report(
        scenario,
        "passed",
        started,
        browser_tool_calls=browser_tool_calls,
        backend_route=backend_route,
        trace_event_count=len(trace_events or []),
        artifact_paths=artifact_paths,
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
    return _run_chat_trace_scenario(
        scenario="fixture",
        started=started,
        base_url=base_url,
        session_id=session_id,
        prompt=_fixture_prompt(fixture.resolve().as_uri()),
        timeout=_task_timeout(args),
        backend_route=backend_route,
        artifact_paths=[str(fixture)],
        require_user_backend=True,
        request_context={"approval_level": "OFF"},
        required_success_marker="V6_FIXTURE_PASS",
    )


def run_public_search(args: argparse.Namespace) -> BrowserControlReport:
    started = time.perf_counter()
    base_url = _normalize_base_url(args.base_url)
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return _copy_report(preflight, scenario="public-search")
    session_id = f"browser-control-public-search-{int(time.time() * 1000)}"
    return _run_chat_trace_scenario(
        scenario="public-search",
        started=started,
        base_url=base_url,
        session_id=session_id,
        prompt=_public_search_prompt(),
        timeout=_task_timeout(args),
        backend_route=preflight.backend_route,
        required_success_marker="V6_PUBLIC_SEARCH_PASS",
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    runners = {
        "preflight": run_preflight,
        "fixture": run_fixture,
        "public-search": run_public_search,
        "bridge-disconnected": run_bridge_disconnected,
        "taobao-live": run_taobao_live,
    }
    report = runners[args.command](args)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
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
    elif require_user_backend and not _has_user_backend_evidence(trace_events):
        status = "failed"
        error_code = BrowserErrorCode.UNKNOWN.value
        failure_reason = "missing_user_backend_trace"

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
                    or metadata.get("legacy_code")
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


def _fixture_prompt(fixture_url: str) -> str:
    return (
        "Your next action must be exactly one browser(code=...) tool call. "
        "Do not call Skill, read_file, memory_search, glob_search, shell, "
        "desktop tools, browser_use, or direct control engine APIs. "
        "Do not fall back to isolated context for this user-state fixture. "
        "In browser(code=...), Browser is already preloaded; do not import "
        "Browser from any module and do not inspect module names. "
        "Run this exact Browser SDK code, then answer exactly "
        "V6_FIXTURE_PASS plus a one-line summary:\n"
        "```python\n"
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
        'print("V6_FIXTURE_PASS user backend cart add and clear verified")\n'
        "```"
    )


def _public_search_prompt() -> str:
    return (
        "Your next action must be exactly one browser(code=...) tool call. "
        "Do not call Skill, read_file, memory_search, glob_search, shell, "
        "desktop tools, browser_use, or direct network libraries. "
        "This scenario name is historical; do not use search engines. "
        "In browser(code=...), Browser is already preloaded; do not import "
        "Browser from any module and do not inspect module names. "
        "Run this exact read-only Browser SDK code, then answer exactly "
        "V6_PUBLIC_SEARCH_PASS plus the page title and backend route evidence:"
        "\n```python\n"
        'browser = await Browser.connect(context="auto")\n'
        'tab = await browser.tabs.open("https://example.com/")\n'
        "snapshot = await tab.snapshot()\n"
        "info = await tab.page_info()\n"
        'assert "Example Domain" in snapshot.text\n'
        'print("V6_PUBLIC_SEARCH_PASS", info.title, browser.context)\n'
        "```"
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
        ("qwenpaw", "app"),
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
