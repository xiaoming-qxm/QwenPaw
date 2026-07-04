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
    preflight = run_preflight(args)
    if preflight.status != "passed":
        return BrowserControlReport(
            scenario="fixture",
            status=preflight.status,
            duration_ms=preflight.duration_ms,
            backend_route=preflight.backend_route,
            error_code=preflight.error_code,
            blocked_reason=preflight.blocked_reason,
            failure_reason=preflight.failure_reason,
        )
    fixture = Path(__file__).with_name("browser_control_cart_fixture.html")
    if not fixture.exists():
        return _report(
            "fixture",
            "failed",
            started,
            blocked_reason=f"missing fixture: {fixture}",
        )
    return _report(
        "fixture",
        "blocked",
        started,
        backend_route=preflight.backend_route,
        blocked_reason=(
            "fixture scenario requires a running configured QwenPaw chat/task "
            "API and Chrome Extension bridge"
        ),
        artifact_paths=[str(fixture)],
    )


def run_public_search(args: argparse.Namespace) -> BrowserControlReport:
    preflight = run_preflight(args)
    return BrowserControlReport(
        scenario="public-search",
        status=preflight.status,
        duration_ms=preflight.duration_ms,
        backend_route=preflight.backend_route,
        error_code=preflight.error_code,
        blocked_reason=preflight.blocked_reason,
        failure_reason=preflight.failure_reason,
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


def _http_json(url: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error GET {url}: {exc.reason}") from exc
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
