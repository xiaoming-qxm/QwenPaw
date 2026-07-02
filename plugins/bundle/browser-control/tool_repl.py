# -*- coding: utf-8 -*-
"""Python REPL tools for Browser Control SDK scripting."""

from __future__ import annotations

from pathlib import Path

from .repl.manager import KernelManager
from .routes import _expected_token, extension_install_status


_manager: KernelManager | None = None


def _get_manager() -> KernelManager:
    global _manager  # pylint: disable=global-statement
    if _manager is None:
        plugin_dir = Path(__file__).parent
        status = extension_install_status()
        _manager = KernelManager(
            plugin_dir / "repl" / "kernel.py",
            plugin_dir / "sdk",
            ws_url=str(status.get("ws_url") or ""),
            token=_expected_token(),
        )
    return _manager


async def python_repl(code: str, timeout_ms: int = 30000) -> str:
    """Execute Python code in the Browser Control REPL kernel."""
    manager = _get_manager()
    result = await manager.execute(code, timeout_ms)
    error = result.get("error")
    if error:
        return (
            f"Error ({error['type']}): {error['message']}\n"
            f"{error.get('traceback', '')}"
        )
    parts = []
    if result.get("output"):
        parts.append(result["output"])
    if result.get("return_value"):
        parts.append(result["return_value"])
    return "\n".join(parts) or "(no output)"


async def python_repl_reset() -> str:
    """Reset the Browser Control REPL kernel namespace."""
    manager = _get_manager()
    await manager.reset()
    return "Python REPL environment reset."


async def shutdown_python_repl() -> None:
    """Shutdown the Browser Control REPL kernel if it exists."""
    global _manager  # pylint: disable=global-statement
    if _manager is not None:
        await _manager.shutdown()
        _manager = None


__all__ = ["python_repl", "python_repl_reset", "shutdown_python_repl"]
