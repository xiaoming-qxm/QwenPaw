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
from .trace import get_browser_trace_store

register_isolated_backend_once()

_ERROR_HINTS = {
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
    metadata = _metadata(
        result,
        ok=ok,
        session_id=session_id,
        context=context,
        browser_trace=[event.to_dict() for event in trace_events],
    )
    content: list[TextBlock | DataBlock] = [
        TextBlock(type="text", text=_summary_text(result)),
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
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "ok": ok,
        "session_id": session_id,
        "context": context,
        "output": result.output,
        "return_value": result.return_value,
        "browser_trace": browser_trace,
    }
    if result.error:
        metadata["error_type"] = result.error.get("type", "")
        metadata["error_code"] = result.error.get("code") or result.error.get(
            "type",
            "",
        )
        metadata["error_message"] = result.error.get("message", "")
        metadata["traceback"] = result.error.get("traceback", "")
        for key in ("backend_id", "action", "metadata"):
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


def _summary_text(result: BrowserKernelResult) -> str:
    if result.error:
        return _error_summary_text(result.error)

    parts = []
    if result.output:
        parts.append(result.output.rstrip("\n"))
    if result.return_value is not None:
        parts.append(result.return_value)
    return "\n".join(parts) or "(no output)"


def _error_summary_text(error: dict[str, Any]) -> str:
    code = str(error.get("code") or error.get("type") or "Error")
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
