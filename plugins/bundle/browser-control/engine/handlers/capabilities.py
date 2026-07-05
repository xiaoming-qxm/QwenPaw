# -*- coding: utf-8 -*-
"""Generic Browser SDK capability handlers for Browser Control."""
# pylint: disable=too-many-arguments,too-many-locals

from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qwenpaw.browser_sdk._runtime import (
    _browser_output_dir,
    _safe_download_filename,
    _tool_response,
)
from qwenpaw.browser_sdk.error_codes import (
    BrowserErrorCode,
    classify_browser_error,
)
from qwenpaw.security.tool_guard.engine import get_guard_engine

from ..errors import BrowserControlRecoverableError, TargetResolutionFailed
from ..navigation import _control_tab_id
from ..ref_scope import _control_current_snapshot_ref
from ..session_manager import _control_get_session
from ..state import ControlState
from ..tab_manager import _control_ensure_tab_available, _control_page_id
from ..targets import _control_node_params, _control_selector_target
from .protocol import ActionMeta

BACKEND_ID = "user.chrome_extension"
_DOWNLOAD_TIMEOUT_SECONDS = 30.0
_FILE_CLICK_FUNCTION = (
    "function() { "
    "this.dispatchEvent(new MouseEvent('click', { bubbles: true })); "
    "if (typeof this.click === 'function') { this.click(); } "
    "return true; "
    "}"
)


@dataclass(frozen=True)
class UploadHandler:
    """Set file input files through the controlled Chrome tab."""

    meta: ActionMeta = ActionMeta(True, True, True)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        try:
            files = _resolve_upload_paths(kwargs.get("file_path"))
            tab_id, session = await _tab_session(
                state,
                holder_id=holder_id,
                bridge=bridge,
                kwargs=kwargs,
            )
            node_params = await _node_params(state, session, tab_id, kwargs)
            await session.send(
                "DOM.setFileInputFiles",
                {**node_params, "files": files},
            )
            return _json_response(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "uploaded": True,
                    "file_count": len(files),
                    "data": {
                        "backend_id": BACKEND_ID,
                        "file_count": len(files),
                    },
                },
            )
        except (BrowserControlRecoverableError, OSError, ValueError) as exc:
            return _capability_error_response("upload", str(exc))


@dataclass(frozen=True)
class DownloadHandler:
    """Trigger and collect a browser download artifact."""

    meta: ActionMeta = ActionMeta(True, False, True)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        try:
            tab_id, session = await _tab_session(
                state,
                holder_id=holder_id,
                bridge=bridge,
                kwargs=kwargs,
            )
            output_dir = _browser_output_dir(dict(state), "downloads")
            await session.send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allow",
                    "downloadPath": str(output_dir),
                    "eventsEnabled": True,
                },
            )
            timeout_seconds = _timeout_seconds(kwargs.get("timeout_ms"))
            waiter = asyncio.create_task(
                _wait_for_download(
                    bridge,
                    tab_id=tab_id,
                    timeout_seconds=timeout_seconds,
                ),
            )
            try:
                if _has_target(kwargs):
                    await _click_target(session, state, tab_id, kwargs)
                event = await waiter
            finally:
                if not waiter.done():
                    waiter.cancel()
            artifact = _download_artifact(output_dir, event)
            return _json_response(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "downloaded": True,
                    "artifact": artifact,
                    "data": {
                        "backend_id": BACKEND_ID,
                        "artifact": artifact,
                    },
                },
            )
        except asyncio.TimeoutError:
            return _taxonomy_error_response(
                "download",
                BrowserErrorCode.NETWORK_TIMEOUT,
                "Download did not complete before timeout.",
            )
        except (BrowserControlRecoverableError, OSError, ValueError) as exc:
            return _capability_error_response("download", str(exc))


@dataclass(frozen=True)
class DialogHandler:
    """Configure the next JavaScript dialog decision."""

    meta: ActionMeta = ActionMeta(True, False, False)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        del holder_id
        try:
            tab_id = _control_tab_id(
                _control_page_id(state, str(kwargs.get("page_id", ""))),
                kwargs.get("index", -1),
            )
            await _control_ensure_tab_available(bridge, tab_id)
            accept = _bool_arg(kwargs.get("accept"), default=True)
            prompt_text = kwargs.get("prompt_text")
            decision = {
                "tab_id": tab_id,
                "accept": accept,
                "prompt_text": "" if prompt_text is None else str(prompt_text),
                "configured_at": time.time(),
            }
            _set_next_dialog_decision(state, decision)
            request = getattr(bridge, "request", None)
            if callable(request):
                await request(
                    "dialog.set",
                    {
                        "tabId": tab_id,
                        "accept": accept,
                        "promptText": decision["prompt_text"],
                    },
                )
            return _json_response(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "dialog_configured": True,
                    "accept": accept,
                    "data": {
                        "backend_id": BACKEND_ID,
                        "dialog_configured": True,
                        "accept": accept,
                    },
                },
            )
        except (BrowserControlRecoverableError, OSError, ValueError) as exc:
            return _capability_error_response("dialog", str(exc))


async def _tab_session(
    state: ControlState,
    *,
    holder_id: str,
    bridge: Any,
    kwargs: dict[str, Any],
) -> tuple[int, Any]:
    tab_id = _control_tab_id(
        _control_page_id(state, str(kwargs.get("page_id", ""))),
        kwargs.get("index", -1),
    )
    await _control_ensure_tab_available(bridge, tab_id)
    session = await _control_get_session(
        state,
        tab_id=tab_id,
        holder_id=holder_id,
        bridge=bridge,
        request_context=kwargs.get("request_context") or {},
    )
    return tab_id, session


def _target_selector(kwargs: dict[str, Any]) -> str:
    selector = str(kwargs.get("selector") or "").strip()
    if selector:
        return selector
    target = kwargs.get("target")
    return str(target or "").strip() if isinstance(target, str) else ""


async def _node_params(
    state: ControlState,
    session: Any,
    tab_id: int,
    kwargs: dict[str, Any],
) -> dict[str, int]:
    ref = str(kwargs.get("ref") or "")
    selector = _target_selector(kwargs)
    resolved_ref = _control_current_snapshot_ref(state, tab_id, ref)
    target = (
        state.refs.get(str(tab_id), {}).get(resolved_ref, {}) if ref else {}
    )
    if not target and selector:
        target = await _control_selector_target(session, selector)
    node_params = _control_node_params(target)
    if node_params is None:
        raise TargetResolutionFailed("ref or selector required")
    return node_params


async def _click_target(
    session: Any,
    state: ControlState,
    tab_id: int,
    kwargs: dict[str, Any],
) -> None:
    node_params = await _node_params(state, session, tab_id, kwargs)
    resolved = await session.send("DOM.resolveNode", node_params)
    remote_object = (
        resolved.get("object") if isinstance(resolved, dict) else {}
    )
    object_id = (
        remote_object.get("objectId")
        if isinstance(remote_object, dict)
        else ""
    )
    if not object_id:
        raise TargetResolutionFailed("Unable to resolve download target")
    await session.send(
        "Runtime.callFunctionOn",
        {
            "objectId": object_id,
            "functionDeclaration": _FILE_CLICK_FUNCTION,
            "returnByValue": True,
            "awaitPromise": False,
        },
    )


def _has_target(kwargs: dict[str, Any]) -> bool:
    return bool(
        kwargs.get("ref")
        or kwargs.get("selector")
        or isinstance(kwargs.get("target"), str),
    )


async def _wait_for_download(
    bridge: Any,
    *,
    tab_id: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    add_listener = getattr(bridge, "add_event_listener", None)
    remove_listener = getattr(bridge, "remove_event_listener", None)
    if not callable(add_listener) or not callable(remove_listener):
        raise ValueError("Download events are not available from bridge")

    loop = asyncio.get_running_loop()
    future: asyncio.Future[dict[str, Any]] = loop.create_future()
    details: dict[str, Any] = {}

    def _finish(payload: dict[str, Any]) -> None:
        if not future.done():
            future.set_result(payload)

    def _fail(message: str) -> None:
        if not future.done():
            future.set_exception(ValueError(message))

    async def on_event(event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return
        event_tab_id = event.get("tabId", event.get("tab_id"))
        if event_tab_id is None or int(event_tab_id) != int(tab_id):
            return
        params = event.get("params")
        if not isinstance(params, dict):
            params = {}
        method = str(event.get("method") or "")
        if method == "Page.downloadWillBegin":
            details.update(params)
            return
        if method != "Page.downloadProgress":
            return
        state = str(params.get("state") or "")
        details.update(params)
        if state == "completed":
            _finish(dict(details))
        elif state in {"canceled", "cancelled"}:
            _fail("Download was canceled by Chrome")

    add_listener("cdp.event", on_event)
    try:
        return await asyncio.wait_for(future, timeout=timeout_seconds)
    finally:
        remove_listener("cdp.event", on_event)


def _download_artifact(
    output_dir: Path,
    event: dict[str, Any],
) -> dict[str, Any]:
    name = _safe_download_filename(
        event.get("suggestedFilename")
        or event.get("suggested_filename")
        or event.get("guid")
        or "download",
    )
    path = output_dir / name
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return {
        "kind": "download",
        "url": path.resolve().as_uri(),
        "media_type": media_type,
        "name": name,
        "metadata": {
            "path": str(path),
            "source_url": str(event.get("url") or ""),
            "guid": str(event.get("guid") or ""),
        },
    }


def _resolve_upload_paths(raw_value: Any) -> list[str]:
    if isinstance(raw_value, (list, tuple)):
        raw_paths = list(raw_value)
    else:
        raw_paths = [raw_value]
    files: list[str] = []
    for raw_path in raw_paths:
        text = str(raw_path or "").strip()
        if not text:
            continue
        path = Path(text).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Upload path is not a file: {path}")
        _enforce_file_guard(str(path))
        files.append(str(path))
    if not files:
        raise ValueError("file_path required for upload")
    return files


def _enforce_file_guard(path: str) -> None:
    result = get_guard_engine().guard(
        "browser.upload",
        {"file_path": path},
        only_always_run=True,
    )
    if result is None or result.is_safe:
        return
    finding = result.findings[0] if result.findings else None
    reason = (
        getattr(finding, "title", "")
        or getattr(finding, "description", "")
        or "file guard rejected upload path"
    )
    raise ValueError(str(reason))


def _set_next_dialog_decision(
    state: ControlState,
    decision: dict[str, Any],
) -> None:
    extra = getattr(state, "extra", None)
    if isinstance(extra, dict):
        extra["next_dialog_decision"] = decision
        return
    state["next_dialog_decision"] = decision


def _timeout_seconds(value: Any) -> float:
    try:
        timeout_ms = float(value)
    except (TypeError, ValueError):
        return _DOWNLOAD_TIMEOUT_SECONDS
    if timeout_ms <= 0:
        return _DOWNLOAD_TIMEOUT_SECONDS
    return max(0.1, timeout_ms / 1000.0)


def _bool_arg(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "y", "on", "accept"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", "dismiss"}:
            return False
    return default


def _capability_error_response(action: str, message: str):
    return _taxonomy_error_response(
        action,
        BrowserErrorCode.CAPABILITY_MISSING,
        message,
    )


def _taxonomy_error_response(
    action: str,
    code: BrowserErrorCode,
    message: str,
):
    info = classify_browser_error(code)
    return _json_response(
        {
            "ok": False,
            "mode": "control",
            "error": message,
            "error_code": info.code.value,
            "recovery_hint": info.recovery_hint,
            "data": {
                "backend_id": BACKEND_ID,
                "action": action,
                "error_code": info.code.value,
                "recovery_hint": info.recovery_hint,
            },
        },
    )


def _json_response(payload: dict[str, Any]):
    return _tool_response(json.dumps(payload, ensure_ascii=False, indent=2))


UPLOAD_HANDLER = UploadHandler()
DOWNLOAD_HANDLER = DownloadHandler()
DIALOG_HANDLER = DialogHandler()

__all__ = [
    "DIALOG_HANDLER",
    "DOWNLOAD_HANDLER",
    "DialogHandler",
    "DownloadHandler",
    "UPLOAD_HANDLER",
    "UploadHandler",
]
