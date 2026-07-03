# -*- coding: utf-8 -*-
"""Agent-visible browser(code=...) tool."""

from __future__ import annotations

from typing import Any

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from qwenpaw.runtime.tool_registry import tool_descriptor

from .kernel import BrowserKernelResult, get_default_kernel_manager
from .isolated_backend import register_isolated_backend_once

register_isolated_backend_once()


@tool_descriptor(
    name="browser",
    enabled_by_default=True,
    async_execution=True,
    description=(
        "Execute Python code in the unified Browser SDK. Use "
        "`browser = await Browser.connect(context=\"auto\")` inside code."
    ),
)
async def browser(
    code: str,
    context: str = "auto",
    timeout_ms: int = 30000,
) -> ToolChunk:
    """Execute Browser SDK Python code in a session-scoped kernel."""
    session_id = _current_session_id()
    result = await get_default_kernel_manager().execute(
        session_id=session_id,
        code=code,
        timeout_ms=timeout_ms,
        context=context,  # type: ignore[arg-type]
    )
    ok = result.error is None
    metadata = _metadata(result, ok=ok, session_id=session_id, context=context)
    return ToolChunk(
        content=[TextBlock(type="text", text=_summary_text(result))],
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
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "ok": ok,
        "session_id": session_id,
        "context": context,
        "output": result.output,
        "return_value": result.return_value,
    }
    if result.error:
        metadata["error_type"] = result.error.get("type", "")
        metadata["error_code"] = (
            result.error.get("code") or result.error.get("type", "")
        )
        metadata["error_message"] = result.error.get("message", "")
        for key in ("backend_id", "action", "metadata"):
            if key in result.error:
                metadata[key] = result.error[key]
    return metadata


def _summary_text(result: BrowserKernelResult) -> str:
    if result.error:
        error = result.error
        code = error.get("code") or error.get("type") or "Error"
        lines = [f"Error ({code}): {error.get('message', '')}"]
        traceback_text = str(error.get("traceback") or "").strip()
        if traceback_text:
            lines.append(traceback_text)
        return "\n".join(lines)

    parts = []
    if result.output:
        parts.append(result.output.rstrip("\n"))
    if result.return_value is not None:
        parts.append(result.return_value)
    return "\n".join(parts) or "(no output)"


__all__ = ["browser"]
