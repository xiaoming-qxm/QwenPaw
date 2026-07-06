# -*- coding: utf-8 -*-
"""Runtime Product Acceptance run registry for Browser Bridge."""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from argparse import Namespace
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from pydantic import BaseModel, Field


TERMINAL_STATUSES = {"passed", "failed", "blocked", "cancelled"}
SENSITIVE_KEY_MARKERS = (
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)


class AcceptanceRunRequest(BaseModel):
    """Request body used by the Browser Bridge acceptance runner."""

    base_url: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    timeout: float = Field(default=30.0, gt=0)
    live_taobao: bool = False


class AcceptanceRunNotFound(KeyError):
    """Raised when a requested run id does not exist."""


class AcceptanceReportMissing(FileNotFoundError):
    """Raised when a run exists but report artifacts are not ready."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class AcceptanceRunState:
    """Mutable state for one Product Acceptance run."""

    run_id: str
    request: AcceptanceRunRequest
    report_json_path: Path
    report_markdown_path: Path
    status: str = "queued"
    started_at: str = field(default_factory=_utc_now)
    completed_at: str | None = None
    scenario_progress: list[dict[str, Any]] = field(default_factory=list)
    cancel_requested: bool = False
    error: str = ""
    report_json: dict[str, Any] | None = None
    report_markdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _sanitize_json_value(
            {
                "run_id": self.run_id,
                "status": self.status,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "scenario_progress": list(self.scenario_progress),
                "live_taobao": bool(self.request.live_taobao),
                "cancel_requested": self.cancel_requested,
                "report_json_path": str(self.report_json_path),
                "report_markdown_path": str(self.report_markdown_path),
                "error": self.error,
            },
        )


class AcceptanceRunContext:
    """Progress and cancellation boundary passed to run implementations."""

    def __init__(
        self,
        *,
        state: AcceptanceRunState,
        lock: threading.RLock,
    ) -> None:
        self.state = state
        self.request = state.request
        self.run_id = state.run_id
        self.report_json_path = state.report_json_path
        self.report_markdown_path = state.report_markdown_path
        self._lock = lock

    def cancel_requested(self) -> bool:
        with self._lock:
            return self.state.cancel_requested

    def record_scenario(
        self,
        scenario: str,
        status: str,
        **metadata: Any,
    ) -> None:
        payload = _sanitize_json_value(
            {
                "scenario": scenario,
                "status": status,
                **metadata,
            },
        )
        with self._lock:
            progress = [
                item
                for item in self.state.scenario_progress
                if item.get("scenario") != scenario
            ]
            progress.append(payload)
            self.state.scenario_progress = progress


Runner = Callable[[AcceptanceRunContext], Any]


class AcceptanceRunRegistry:
    """In-memory run registry used by the Browser Bridge API."""

    def __init__(
        self,
        *,
        report_dir: Path | None = None,
        runner: Runner | None = None,
        synchronous: bool = False,
    ) -> None:
        self.report_dir = report_dir or default_report_dir()
        self.runner = runner or _product_verifier_runner
        self.synchronous = synchronous
        self._runs: dict[str, AcceptanceRunState] = {}
        self._lock = threading.RLock()

    def start_run(
        self,
        request: AcceptanceRunRequest | None = None,
    ) -> dict[str, Any]:
        run_request = request or AcceptanceRunRequest()
        run_id = uuid.uuid4().hex
        report_stem = f"{_path_timestamp()}-{run_id}"
        state = AcceptanceRunState(
            run_id=run_id,
            request=run_request,
            report_json_path=self.report_dir / f"{report_stem}.json",
            report_markdown_path=self.report_dir / f"{report_stem}.md",
        )
        with self._lock:
            self._runs[run_id] = state
            state.status = "running"

        if self.synchronous:
            self._execute(state)
        else:
            thread = threading.Thread(
                target=self._execute,
                args=(state,),
                name=f"browser-bridge-acceptance-{run_id[:8]}",
                daemon=True,
            )
            thread.start()
        return state.to_dict()

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._state(run_id).to_dict()

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        state = self._state(run_id)
        with self._lock:
            state.cancel_requested = True
            if state.status not in TERMINAL_STATUSES:
                state.status = "cancelled"
                state.completed_at = _utc_now()
        return state.to_dict()

    def get_report(self, run_id: str) -> dict[str, Any]:
        state = self._state(run_id)
        if state.report_json is None and state.report_json_path.exists():
            state.report_json = _read_json(state.report_json_path)
        if not state.report_markdown and state.report_markdown_path.exists():
            state.report_markdown = state.report_markdown_path.read_text(
                encoding="utf-8",
            )
        if state.report_json is None and not state.report_markdown:
            raise AcceptanceReportMissing(run_id)
        return _sanitize_json_value(
            {
                "run_id": run_id,
                "json": state.report_json or {},
                "markdown": state.report_markdown,
                "report_json_path": str(state.report_json_path),
                "report_markdown_path": str(state.report_markdown_path),
            },
        )

    def _state(self, run_id: str) -> AcceptanceRunState:
        with self._lock:
            state = self._runs.get(run_id)
        if state is None:
            raise AcceptanceRunNotFound(run_id)
        return state

    def _execute(self, state: AcceptanceRunState) -> None:
        context = AcceptanceRunContext(state=state, lock=self._lock)
        started = time.perf_counter()
        try:
            result = self.runner(context)
            report_json, markdown = _coerce_runner_result(
                result,
                state=state,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            report_json = _failure_report(exc, state, started)
            markdown = _render_markdown(report_json)

        with self._lock:
            if state.cancel_requested and report_json.get("status") not in {
                "passed",
                "failed",
                "blocked",
            }:
                report_json["status"] = "cancelled"
            state.status = str(report_json.get("status") or "failed")
            state.completed_at = _utc_now()
            reports = report_json.get("scenario_reports")
            if isinstance(reports, list):
                state.scenario_progress = _progress_from_reports(reports)
            state.report_json = _sanitize_json_value(report_json)
            state.report_markdown = markdown

        _write_reports(state)


def default_report_dir() -> Path:
    return Path.home() / ".qwenpaw" / "browser-bridge" / "reports"


def _product_verifier_runner(
    context: AcceptanceRunContext,
) -> tuple[Any, str]:
    from scripts.verify.browser import cli as verify

    args = _product_verifier_args(context)
    report = verify.run_product_verifier(args)
    markdown = ""
    if context.report_markdown_path.exists():
        markdown = context.report_markdown_path.read_text(encoding="utf-8")
    return report, markdown


def _product_verifier_args(context: AcceptanceRunContext) -> Namespace:
    request = context.request
    port = request.port or _port_from_base_url(request.base_url) or 8088
    base_url = request.base_url or f"http://127.0.0.1:{port}"
    return Namespace(
        base_url=base_url,
        port=port,
        timeout=request.timeout,
        live_taobao=bool(request.live_taobao),
        report=str(context.report_markdown_path),
    )


def _port_from_base_url(base_url: str | None) -> int | None:
    if not base_url:
        return None
    try:
        parsed = urlparse(base_url)
    except ValueError:
        return None
    return parsed.port


def _coerce_runner_result(
    result: Any,
    *,
    state: AcceptanceRunState,
    duration_ms: float,
) -> tuple[dict[str, Any], str]:
    markdown = ""
    if isinstance(result, tuple) and len(result) == 2:
        result, markdown = result
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    if not isinstance(result, dict):
        result = {
            "scenario": "browser-v11-product-acceptance",
            "status": "failed",
            "failure_reason": "acceptance runner returned an invalid report",
        }
    report = _sanitize_json_value(dict(result))
    report.setdefault("scenario", "browser-v11-product-acceptance")
    report.setdefault("status", "passed")
    report.setdefault("duration_ms", duration_ms)
    report.setdefault("scenario_reports", list(state.scenario_progress))
    report.update(
        {
            "run_id": state.run_id,
            "live_taobao": bool(state.request.live_taobao),
            "report_json_path": str(state.report_json_path),
            "report_markdown_path": str(state.report_markdown_path),
        },
    )
    if not markdown:
        markdown = _render_markdown(report)
    return report, str(markdown)


def _failure_report(
    exc: Exception,
    state: AcceptanceRunState,
    started: float,
) -> dict[str, Any]:
    return _sanitize_json_value(
        {
            "scenario": "browser-v11-product-acceptance",
            "status": "failed",
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "failure_reason": str(exc),
            "runtime_evidence": {
                "exception_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
            },
            "scenario_reports": list(state.scenario_progress),
            "run_id": state.run_id,
            "live_taobao": bool(state.request.live_taobao),
            "report_json_path": str(state.report_json_path),
            "report_markdown_path": str(state.report_markdown_path),
        },
    )


def _progress_from_reports(reports: list[Any]) -> list[dict[str, Any]]:
    progress: list[dict[str, Any]] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        progress.append(
            _sanitize_json_value(
                {
                    "scenario": str(report.get("scenario") or ""),
                    "status": str(report.get("status") or ""),
                    **{
                        key: value
                        for key, value in report.items()
                        if key
                        in {
                            "failure_category",
                            "recovery_hint",
                            "repair_action",
                        }
                    },
                },
            ),
        )
    return progress


def _write_reports(state: AcceptanceRunState) -> None:
    state.report_json_path.parent.mkdir(parents=True, exist_ok=True)
    state.report_markdown_path.parent.mkdir(parents=True, exist_ok=True)
    state.report_json_path.write_text(
        json.dumps(state.report_json or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state.report_markdown_path.write_text(
        state.report_markdown,
        encoding="utf-8",
    )


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Product Acceptance",
        "",
        f"- Status: `{report.get('status', '')}`",
        f"- Scenario: `{report.get('scenario', '')}`",
    ]
    scenario_reports = report.get("scenario_reports")
    if isinstance(scenario_reports, list) and scenario_reports:
        lines.extend(["", "## Scenarios", ""])
        for item in scenario_reports:
            if not isinstance(item, dict):
                continue
            lines.append(
                "- "
                f"{item.get('scenario', '')}: "
                f"`{item.get('status', '')}`",
            )
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _sanitize_json_value(item)
            for key, item in value.items()
            if not _is_sensitive_key(str(key))
        }
    return value


def _sanitize_text(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
        return "Diagnostic detail redacted."
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def _path_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
