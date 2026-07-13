# -*- coding: utf-8 -*-
"""Generic Browser SDK capability handlers for Browser Bridge."""

# pylint: disable=too-many-arguments,too-many-locals

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from qwenpaw.browser.sdk.backends.protocols import BackendProfile
from qwenpaw.browser.sdk.runtime.responses import (
    _browser_output_dir,
    _safe_download_filename,
    _tool_response,
)
from qwenpaw.browser.sdk.governance.error_codes import (
    BrowserErrorCode,
    classify_browser_error,
)
from qwenpaw.security.tool_guard.engine import get_guard_engine

from ..errors import (
    BrowserBridgeRecoverableError,
    DownloadTimeout,
    TargetResolutionFailed,
)
from ..interactions import _canonical_execute_interaction
from ..navigation import _control_tab_id
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
class DownloadCorrelation:
    """Trusted identity required before accepting one native download."""

    operation_id: str
    command_id: str
    owner_key: tuple[str, str]
    tab_id: int
    pre_arm_watermark: int


def _download_event_matches(
    event: dict[str, Any],
    expected: DownloadCorrelation,
) -> bool:
    """Reject ambient, pre-arm, or differently-owned download events."""
    if not isinstance(event, dict):
        return False
    try:
        tab_id = int(str(event.get("tabId", event.get("tab_id"))))
        sequence = int(str(event.get("sequence")))
    except (TypeError, ValueError):
        return False
    params = event.get("params")
    if not isinstance(params, dict):
        return False
    owner_key = params.get("ownerKey", params.get("owner_key"))
    return (
        tab_id == expected.tab_id
        and sequence > expected.pre_arm_watermark
        and str(params.get("operationId") or "") == expected.operation_id
        and str(params.get("commandId") or "") == expected.command_id
        and isinstance(owner_key, (tuple, list))
        and tuple(str(item) for item in owner_key) == expected.owner_key
        and bool(str(params.get("guid") or ""))
    )


def _stable_download_bytes(path: Path) -> bytes:
    """Read one completed file only when identity and bytes stay stable."""
    if path.name.endswith(".crdownload") or path.is_symlink():
        raise ValueError("Download bytes are incomplete")
    try:
        resolved = path.resolve(strict=True)
        before = resolved.stat()
        data = resolved.read_bytes()
        after = resolved.stat()
    except OSError as exc:
        raise ValueError("Download bytes are unavailable") from exc
    if (
        not data
        or before.st_size != len(data)
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        raise ValueError("Download bytes are unstable")
    return data


def _download_correlation(
    kwargs: Mapping[str, Any],
    *,
    tab_id: int,
) -> DownloadCorrelation:
    raw = kwargs.get("resource_operation")
    request_context = kwargs.get("request_context")
    context = (
        request_context.get("canonical_dispatch_context")
        if isinstance(request_context, Mapping)
        else None
    )
    if not isinstance(raw, Mapping) or context is None:
        raise ValueError("Download operation correlation is unavailable")
    owner_key = raw.get("owner_key")
    if not isinstance(owner_key, (tuple, list)) or len(owner_key) != 2:
        raise ValueError("Download operation owner is invalid")
    try:
        correlation = DownloadCorrelation(
            operation_id=str(raw.get("operation_id") or ""),
            command_id=str(raw.get("command_id") or ""),
            owner_key=(str(owner_key[0]), str(owner_key[1])),
            tab_id=int(tab_id),
            pre_arm_watermark=int(str(raw.get("pre_arm_watermark"))),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Download operation correlation is invalid") from exc
    if (
        correlation.operation_id != str(getattr(context, "operation_id", ""))
        or correlation.command_id != str(getattr(context, "command_id", ""))
        or correlation.owner_key
        != (
            str(getattr(context, "root_task_id", "")),
            str(getattr(context, "browser_owner_id", "")),
        )
    ):
        raise ValueError("Download operation correlation mismatch")
    return correlation


def _page_pdf_options(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise ValueError("Page PDF options are invalid")
    paper = str(raw.get("paper") or "")
    sizes = {
        "a4": (8.27, 11.69),
        "letter": (8.5, 11.0),
        "legal": (8.5, 14.0),
    }
    if paper not in sizes:
        raise ValueError("Page PDF paper is invalid")
    margins = str(raw.get("margins") or "")
    if margins not in {"default", "none"}:
        raise ValueError("Page PDF margins are invalid")
    width, height = sizes[paper]
    options: dict[str, object] = {
        "paperWidth": width,
        "paperHeight": height,
        "landscape": bool(raw.get("landscape")),
        "printBackground": bool(raw.get("print_background")),
        "preferCSSPageSize": False,
    }
    if margins == "none":
        options.update(
            {
                "marginTop": 0,
                "marginBottom": 0,
                "marginLeft": 0,
                "marginRight": 0,
            },
        )
    return options


def _frame_tree_identity(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    return json.dumps(value.get("frameTree"), sort_keys=True, default=str)


def backend_profile() -> BackendProfile:
    """Return reviewed exact ResultDelivery variants for this package build."""
    return BackendProfile(
        variants={
            "result.terminal_delivery": "READY",
            "result.model_image_delivery": "READY",
            "result.artifact_delivery": "READY",
        },
        hard_limits={
            "max_image_bytes": 20 * 1024 * 1024,
            "max_artifact_bytes": 20 * 1024 * 1024,
        },
        contract_fingerprint="contract-v1",
        profile_fingerprint="profile-v1",
        build_fingerprint="build-1",
        extension_fingerprint="extension@build-1",
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
            request_context = kwargs.get("request_context")
            if isinstance(request_context, dict) and bool(
                request_context.get("canonical_dispatch_context"),
            ):
                paths, resource_ids = _resolve_canonical_upload_paths(kwargs)
                injector = kwargs.get("_canonical_native_injector")
                if not callable(injector):
                    raise ValueError(
                        "Canonical upload injector is unavailable",
                    )
                canonical_kwargs = dict(kwargs)
                canonical_kwargs["_canonical_resource_paths"] = paths
                canonical_kwargs["_canonical_resource_ids"] = resource_ids
                result = await _canonical_execute_interaction(
                    state,
                    action="upload_file",
                    target_labels=("target",),
                    kwargs=canonical_kwargs,
                    injector=injector,
                )
                result.pop("path", None)
                result.pop("paths", None)
                result["upload"] = _canonical_upload_outcome(resource_ids)
                return _json_response(result)
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
        except asyncio.TimeoutError:
            return _taxonomy_error_response(
                "upload",
                BrowserErrorCode.UPLOAD_TIMEOUT,
                "Upload did not complete before timeout.",
            )
        except (BrowserBridgeRecoverableError, OSError, ValueError) as exc:
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
            request_context = kwargs.get("request_context")
            canonical = isinstance(request_context, dict) and bool(
                request_context.get("canonical_dispatch_context"),
            )
            correlation = (
                _download_correlation(kwargs, tab_id=tab_id)
                if canonical
                else None
            )
            waiter = asyncio.create_task(
                _wait_for_download(
                    bridge,
                    tab_id=tab_id,
                    timeout_seconds=timeout_seconds,
                    correlation=correlation,
                ),
            )
            try:
                if canonical:

                    async def inject(prepared, arguments):
                        del arguments
                        await _click_prepared_target(session, prepared)
                        return {}

                    await _canonical_execute_interaction(
                        state,
                        action="download_file",
                        target_labels=("target",),
                        kwargs=kwargs,
                        injector=inject,
                    )
                elif _has_target(kwargs):
                    await _click_target(session, state, tab_id, kwargs)
                event = await waiter
            finally:
                if not waiter.done():
                    waiter.cancel()
            if correlation is not None:
                name = _safe_download_filename(
                    event.get("suggestedFilename")
                    or event.get("suggested_filename")
                    or event.get("guid")
                    or "download",
                )
                data = _stable_download_bytes(output_dir / name)
                media_type = (
                    mimetypes.guess_type(name)[0] or "application/octet-stream"
                )
                return _json_response(
                    {
                        "ok": True,
                        "mode": "control",
                        "tab_id": tab_id,
                        "capture": {
                            "bytes_base64": base64.b64encode(data).decode(),
                            "media_type": media_type,
                            "name": name,
                            "complete": True,
                            "native_guid": str(event.get("guid") or ""),
                        },
                    },
                )
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
        except (DownloadTimeout, asyncio.TimeoutError):
            return _taxonomy_error_response(
                "download",
                BrowserErrorCode.DOWNLOAD_TIMEOUT,
                "Download did not complete before timeout.",
            )
        except (BrowserBridgeRecoverableError, OSError, ValueError) as exc:
            return _capability_error_response("download", str(exc))


@dataclass(frozen=True)
class PagePdfHandler:
    """Capture one PDF with before/after document identity evidence."""

    meta: ActionMeta = ActionMeta(True, False, False)

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
            request_context = kwargs.get("request_context")
            if not isinstance(request_context, Mapping) or not bool(
                request_context.get("canonical_dispatch_context"),
            ):
                raise ValueError("Page PDF requires Canonical dispatch")
            options = _page_pdf_options(kwargs.get("_canonical_pdf_options"))
            before = await session.send("Page.getFrameTree", {})
            printed = await session.send("Page.printToPDF", options)
            after = await session.send("Page.getFrameTree", {})
            data = printed.get("data") if isinstance(printed, Mapping) else ""
            if not isinstance(data, str) or not data:
                raise ValueError("Page.printToPDF returned no complete bytes")
            base64.b64decode(data, validate=True)
            return _json_response(
                {
                    "ok": True,
                    "mode": "control",
                    "tab_id": tab_id,
                    "capture": {
                        "bytes_base64": data,
                        "complete": True,
                        "context_same": _frame_tree_identity(before)
                        == _frame_tree_identity(after),
                    },
                },
            )
        except (BrowserBridgeRecoverableError, OSError, ValueError) as exc:
            return _capability_error_response("page_pdf", str(exc))


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
        except (BrowserBridgeRecoverableError, OSError, ValueError) as exc:
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
    resolved_ref = ref
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


async def _click_prepared_target(
    session: Any,
    prepared: tuple[dict[str, object], ...],
) -> None:
    """Inject one click from the just-revalidated native identity."""
    if len(prepared) != 1:
        raise TargetResolutionFailed("Download target is unavailable")
    raw_identity = prepared[0].get("native_identity")
    if not isinstance(raw_identity, tuple):
        raise TargetResolutionFailed("Download target identity is invalid")
    identity = {str(key): value for key, value in raw_identity}
    node_params = _control_node_params(identity)
    if node_params is None and len(identity) == 1:
        native_value = next(iter(identity.values()))
        if isinstance(native_value, int):
            node_params = {"backendNodeId": native_value}
    if node_params is None:
        raise TargetResolutionFailed("Download target identity is invalid")
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
    correlation: DownloadCorrelation | None = None,
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
        normalized = _download_event_payload(event, tab_id=tab_id)
        if normalized is None:
            return
        method, params = normalized
        if method == "Page.downloadWillBegin":
            if correlation is not None and not _download_event_matches(
                event,
                correlation,
            ):
                return
            details.update(params)
            details["sequence"] = event.get("sequence")
            return
        if method != "Page.downloadProgress":
            return
        if correlation is not None and not _download_progress_matches(
            event,
            params=params,
            details=details,
            correlation=correlation,
        ):
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
    except asyncio.TimeoutError as exc:
        raise DownloadTimeout(
            "Download did not complete before timeout.",
        ) from exc
    finally:
        remove_listener("cdp.event", on_event)


def _download_event_payload(
    event: object,
    *,
    tab_id: int,
) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(event, dict):
        return None
    event_tab_id = event.get("tabId", event.get("tab_id"))
    if event_tab_id is None or int(event_tab_id) != int(tab_id):
        return None
    params = event.get("params")
    return (
        str(event.get("method") or ""),
        params if isinstance(params, dict) else {},
    )


def _download_progress_matches(
    event: dict[str, Any],
    *,
    params: dict[str, Any],
    details: dict[str, Any],
    correlation: DownloadCorrelation,
) -> bool:
    try:
        sequence = int(str(event.get("sequence")))
    except (TypeError, ValueError):
        return False
    expected_guid = str(details.get("guid") or "")
    return (
        sequence > correlation.pre_arm_watermark
        and bool(expected_guid)
        and str(params.get("guid") or "") == expected_guid
    )


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


def _resolve_canonical_upload_paths(
    kwargs: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    raw_paths = kwargs.get("_canonical_resource_paths")
    raw_ids = kwargs.get("_canonical_resource_ids")
    if not isinstance(raw_paths, (tuple, list)) or not isinstance(
        raw_ids,
        (tuple, list),
    ):
        raise ValueError("Canonical upload resources are unavailable")
    paths = tuple(str(path) for path in raw_paths)
    resource_ids = tuple(str(resource_id) for resource_id in raw_ids)
    if not paths or len(paths) != len(resource_ids):
        raise ValueError("Canonical upload resource binding is invalid")
    if len(set(resource_ids)) != len(resource_ids):
        raise ValueError("Canonical upload resource binding is duplicated")
    for raw_path in paths:
        try:
            path = Path(raw_path).resolve(strict=True)
        except OSError as exc:
            raise ValueError(
                "Canonical upload resource is unavailable",
            ) from exc
        if not path.is_file():
            raise ValueError("Canonical upload resource is unavailable")
    return paths, resource_ids


def _canonical_upload_outcome(
    resource_ids: tuple[str, ...],
) -> dict[str, object]:
    """Selection is known; transfer and page acceptance remain unknown."""
    return {
        "items": [
            {
                "resource_id": resource_id,
                "selection": "SELECTED",
                "transfer": "UNKNOWN",
                "acceptance": "UNKNOWN",
            }
            for resource_id in resource_ids
        ],
        "aggregate": "UNKNOWN",
    }


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
PAGE_PDF_HANDLER = PagePdfHandler()
DIALOG_HANDLER = DialogHandler()

__all__ = [
    "DIALOG_HANDLER",
    "DOWNLOAD_HANDLER",
    "DialogHandler",
    "DownloadHandler",
    "PAGE_PDF_HANDLER",
    "PagePdfHandler",
    "UPLOAD_HANDLER",
    "UploadHandler",
    "backend_profile",
]
