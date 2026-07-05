# -*- coding: utf-8 -*-
"""Agent-visible browser(code=...) tool."""

from __future__ import annotations

from typing import Any
from typing import cast

from agentscope.message import DataBlock, TextBlock, ToolResultState, URLSource
from agentscope.tool import ToolChunk
from pydantic import AnyUrl

from qwenpaw.runtime.tool_registry import tool_descriptor

from .kernel import BrowserKernelResult, get_default_kernel_manager
from .backends.isolated import register_isolated_backend_once
from .error_codes import classify_browser_error
from .loop_gate import register_browser_loop_gate_provider_once
from .progress import BrowserProgressDecision, detect_no_progress
from .recovery import (
    BrowserRecoveryDecision,
    BrowserRecoveryPolicy,
    BrowserRequestEvidence,
)
from .trace import get_browser_trace_store, record_browser_trace_event
from .trace import BrowserTraceEvent

register_isolated_backend_once()
register_browser_loop_gate_provider_once()

_ERROR_HINTS = {
    "bridge_disconnected": (
        "Reconnect the Chrome extension bridge, then run diagnostics before "
        "retrying."
    ),
    "approval_required": (
        "Wait for an explicit user approval decision before continuing the "
        "browser action."
    ),
    "approval_denied": (
        "Stop this browser action because the user denied approval."
    ),
    "network_timeout": (
        "Report the timeout and retry later only if the network or page "
        "settles."
    ),
    "observation_stale": (
        "Take a fresh browser observation before attempting another "
        "mutating action."
    ),
    "capability_missing": (
        "Add or use a generic Browser SDK capability instead of a one-off "
        "workaround."
    ),
    "browser_bridge_disconnected": (
        "Reload the extension or reopen the target browser tab."
    ),
    "browser_backend_unavailable": (
        "Refresh the status after the backend is available."
    ),
    "browser_control_engine_missing": (
        "Restart QwenPaw or reload the Browser Control plugin."
    ),
    "isolated_backend_unavailable": (
        "Install or restart the isolated browser runtime."
    ),
    "browser_kernel_timeout": "Reduce the browser task size and retry.",
}


@tool_descriptor(
    name="browser",
    enabled_by_default=True,
    async_execution=True,
    description=(
        "Execute Python code in the unified Browser SDK. Use "
        '`browser = await Browser.connect(context="auto")` inside code.'
    ),
)
async def browser(
    code: str,
    context: str = "auto",
    timeout_ms: int = 30000,
) -> ToolChunk:
    """Execute Browser SDK Python code in a session-scoped kernel."""
    session_id = _current_session_id()
    trace_store = get_browser_trace_store()
    trace_start_index = len(trace_store.list(session_id))
    result = await get_default_kernel_manager().execute(
        session_id=session_id,
        code=code,
        timeout_ms=timeout_ms,
        context=context,  # type: ignore[arg-type]
    )
    ok = result.error is None
    trace_events = trace_store.list(session_id)[trace_start_index:]
    if result.error and not trace_events:
        record_browser_trace_event(
            session_id=session_id,
            phase="tool",
            requested_context=context,
            action=str(result.error.get("action") or "browser"),
            backend_id=str(result.error.get("backend_id") or ""),
            status="error",
            error_code=_result_error_code(result.error),
            metadata={
                "error_type": result.error.get("type", ""),
            },
        )
        trace_events = trace_store.list(session_id)[trace_start_index:]
    progress_decision = detect_no_progress(trace_store.list(session_id))
    metadata = _metadata(
        result,
        ok=ok,
        session_id=session_id,
        context=context,
        browser_trace=[event.to_dict() for event in trace_events],
        progress_decision=progress_decision,
    )
    metadata["recovery_decision"] = _recovery_decision_metadata(
        session_id=session_id,
        trace_events=trace_events,
        metadata=metadata,
    )
    content: list[TextBlock | DataBlock] = [
        TextBlock(type="text", text=_summary_text(result, progress_decision)),
    ]
    content.extend(_artifact_blocks(result))
    return ToolChunk(
        content=content,
        state=ToolResultState.SUCCESS if ok else ToolResultState.ERROR,
        is_last=True,
        metadata=metadata,
    )


def _current_session_id() -> str:
    try:
        from qwenpaw.app.agent_context import (
            get_current_root_session_id,
            get_current_session_id,
        )

        return (
            get_current_root_session_id()
            or get_current_session_id()
            or "default"
        )
    except Exception:  # pragma: no cover - defensive runtime fallback
        return "default"


def _metadata(
    result: BrowserKernelResult,
    *,
    ok: bool,
    session_id: str,
    context: str,
    browser_trace: list[dict[str, Any]],
    progress_decision: BrowserProgressDecision,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "ok": ok,
        "session_id": session_id,
        "context": context,
        "output": result.output,
        "return_value": result.return_value,
        "browser_trace": browser_trace,
        "progress_decision": progress_decision.to_dict(),
    }
    if browser_trace:
        metadata["trace_event_id"] = str(browser_trace[-1].get("event_id"))
    if result.error:
        error_info = classify_browser_error(_result_error_code(result.error))
        metadata["error_type"] = result.error.get("type", "")
        metadata["error_code"] = error_info.code.value
        metadata["browser_error_code"] = error_info.code.value
        metadata["error_outcome"] = error_info.outcome.value
        metadata["recovery_hint"] = str(
            result.error.get("recovery_hint") or error_info.recovery_hint,
        )
        metadata["error_message"] = result.error.get("message", "")
        metadata["traceback"] = result.error.get("traceback", "")
        for key in ("backend_id", "action", "metadata", "outcome"):
            if key in result.error:
                metadata[key] = result.error[key]
    if result.artifacts:
        metadata["artifacts"] = [
            {
                "kind": artifact.kind,
                "url": artifact.url,
                "media_type": artifact.media_type,
                "name": artifact.name,
                "metadata": dict(artifact.metadata),
            }
            for artifact in result.artifacts
        ]
    return metadata


def _recovery_decision_metadata(
    *,
    session_id: str,
    trace_events: tuple[BrowserTraceEvent, ...],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    decision = BrowserRecoveryPolicy().decide(
        BrowserRequestEvidence(
            session_id=session_id,
            request_scope_key=f"{session_id}:tool",
            tool_call_ids=_tool_call_ids(trace_events),
            trace_events=trace_events,
            tool_metadata=(metadata,),
            has_browser_tool_calls=True,
        ),
    )
    return _decision_to_dict(decision)


def _tool_call_ids(
    trace_events: tuple[BrowserTraceEvent, ...],
) -> tuple[str, ...]:
    ids: list[str] = []
    for event in trace_events:
        if event.tool_call_id and event.tool_call_id not in ids:
            ids.append(event.tool_call_id)
    return tuple(ids or ["current_browser_tool"])


def _decision_to_dict(
    decision: BrowserRecoveryDecision,
) -> dict[str, Any]:
    return {
        "action": decision.action.value,
        "reason": decision.reason,
        "requested_context": decision.requested_context,
        "selected_context": decision.selected_context,
        "next_context": decision.next_context,
        "required_next_step": decision.required_next_step,
        "forbidden": list(decision.forbidden),
        "metadata": dict(decision.metadata),
    }


def _artifact_blocks(result: BrowserKernelResult) -> list[DataBlock]:
    blocks: list[DataBlock] = []
    for artifact in result.artifacts:
        if not artifact.url or not artifact.media_type:
            continue
        blocks.append(
            DataBlock(
                source=URLSource(
                    url=cast(AnyUrl, artifact.url),
                    media_type=artifact.media_type,
                ),
                name=artifact.name,
            ),
        )
    return blocks


def _summary_text(
    result: BrowserKernelResult,
    progress_decision: BrowserProgressDecision | None = None,
) -> str:
    if result.error:
        text = _error_summary_text(result.error)
        if progress_decision is not None and progress_decision.blocked:
            return f"{text}\nNo progress: {progress_decision.recovery_hint}"
        return text

    parts = []
    if result.output:
        parts.append(result.output.rstrip("\n"))
    if result.return_value is not None:
        parts.append(result.return_value)
    if progress_decision is not None and progress_decision.blocked:
        parts.append(f"No progress: {progress_decision.recovery_hint}")
    return "\n".join(parts) or "(no output)"


def _error_summary_text(error: dict[str, Any]) -> str:
    code = _result_error_code(error)
    message = str(error.get("message") or "").strip()
    lines = [f"Error: {code}"]
    if message:
        lines.append(f"Message: {message}")

    hint = _error_hint(error, code)
    if hint:
        lines.append(f"Hint: {hint}")

    diagnostics = _error_diagnostics_summary(error, code)
    if diagnostics:
        lines.append(f"Diagnostics: {diagnostics}")

    return "\n".join(lines)


def _error_hint(error: dict[str, Any], code: str) -> str:
    value = error.get("recovery_hint")
    if isinstance(value, str) and value.strip():
        return value.strip()
    metadata = error.get("metadata")
    if isinstance(metadata, dict):
        for key in ("hint", "message_fallback"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        hint_key = metadata.get("hint_key")
        if isinstance(hint_key, str) and hint_key in _ERROR_HINTS:
            return _ERROR_HINTS[hint_key]
    return _ERROR_HINTS.get(code, "")


def _result_error_code(error: dict[str, Any]) -> str:
    raw = error.get("code") or error.get("browser_error_code")
    if not raw:
        raw = error.get("type") or "unknown"
    return classify_browser_error(str(raw)).code.value


def _error_diagnostics_summary(error: dict[str, Any], code: str) -> str:
    metadata = error.get("metadata")
    if isinstance(metadata, dict):
        diagnostics = metadata.get("diagnostics")
        if isinstance(diagnostics, str) and diagnostics.strip():
            return diagnostics.strip()
        if isinstance(diagnostics, dict):
            summary = _diagnostics_dict_summary(diagnostics)
            if summary:
                return summary

    backend_id = str(error.get("backend_id") or "").strip()
    if not backend_id:
        return ""
    status = "unavailable" if _looks_unavailable(code) else "error"
    return f"{backend_id} {status} ({code})"


def _diagnostics_dict_summary(diagnostics: dict[str, Any]) -> str:
    backend_id = str(
        diagnostics.get("backend_id")
        or diagnostics.get("selected_backend_id")
        or "",
    ).strip()
    status = str(diagnostics.get("status") or "unavailable").strip()
    code = str(diagnostics.get("code") or "").strip()
    if not backend_id and not code:
        return ""
    if backend_id and code:
        return f"{backend_id} {status} ({code})"
    return backend_id or code


def _looks_unavailable(code: str) -> bool:
    lowered = code.lower()
    return any(
        marker in lowered
        for marker in (
            "disconnected",
            "unavailable",
            "missing",
            "timeout",
        )
    )


__all__ = ["browser"]
