# -*- coding: utf-8 -*-
# mypy: ignore-errors
# flake8: noqa: F401,F403,E501
"""Playwright backend advanced page actions."""

from ..runtime import *
from .playwright_basic import *

async def _action_evaluate(
    state: dict,
    page_id: str,
    code: str,
    ref: str = "",
    element: str = "",  # pylint: disable=unused-argument
    frame_selector: str = "",
) -> ToolChunk:
    code = (code or "").strip()
    if not code:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "code required for evaluate"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if ref and ref.strip():
            locator = _get_locator_by_ref(
                state,
                page,
                page_id,
                ref.strip(),
                frame_selector,
            )
            if locator is None:
                return _tool_response(
                    json.dumps(
                        {"ok": False, "error": f"Unknown ref: {ref}"},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            if _USE_SYNC_PLAYWRIGHT:
                result = await _run_sync(locator.evaluate, code)
            else:
                result = await locator.evaluate(code)
        else:
            if code.strip().startswith("(") or code.strip().startswith(
                "function",
            ):
                if _USE_SYNC_PLAYWRIGHT:
                    result = await _run_sync(page.evaluate, code)
                else:
                    result = await page.evaluate(code)
            else:
                if _USE_SYNC_PLAYWRIGHT:
                    result = await _run_sync(
                        page.evaluate,
                        f"() => {{ return ({code}); }}",
                    )
                else:
                    result = await page.evaluate(
                        f"() => {{ return ({code}); }}",
                    )
        try:
            out = json.dumps(
                {"ok": True, "result": result},
                ensure_ascii=False,
                indent=2,
            )
        except TypeError:
            out = json.dumps(
                {"ok": True, "result": str(result)},
                ensure_ascii=False,
                indent=2,
            )
        return _tool_response(out)
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Evaluate failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_resize(
    state: dict,
    page_id: str,
    width: int,
    height: int,
) -> ToolChunk:
    if width <= 0 or height <= 0:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "width and height must be positive"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(
                page.set_viewport_size,
                {"width": width, "height": height},
            )
        else:
            await page.set_viewport_size({"width": width, "height": height})
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Resized to {width}x{height}"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Resize failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_console_messages(
    state: dict,
    page_id: str,
    level: str,
    filename: str,
) -> ToolChunk:
    level = (level or "info").strip().lower()
    order = ("error", "warning", "info", "debug")
    idx = order.index(level) if level in order else 2
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    logs = state["console_logs"].get(page_id, [])
    filtered = (
        [m for m in logs if order.index(m["level"]) <= idx] if level in order else logs
    )
    lines = [f"[{m['level']}] {m['text']}" for m in filtered]
    text = "\n".join(lines)
    if filename and filename.strip():
        resolved = _resolve_output_path(filename.strip())
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(text)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Console messages saved to {resolved}",
                    "filename": resolved,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return _tool_response(
        json.dumps(
            {"ok": True, "messages": filtered, "text": text},
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_handle_dialog(
    state: dict,
    page_id: str,
    accept: bool,
    prompt_text: str,
) -> ToolChunk:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    dialogs = state["pending_dialogs"].get(page_id, [])
    if not dialogs:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "No pending dialog"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        dialog = dialogs.pop(0)
        if accept:
            if prompt_text and hasattr(dialog, "accept"):
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(dialog.accept, prompt_text)
                else:
                    await dialog.accept(prompt_text)
            else:
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(dialog.accept)
                else:
                    await dialog.accept()
        else:
            if _USE_SYNC_PLAYWRIGHT:
                await _run_sync(dialog.dismiss)
            else:
                await dialog.dismiss()
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Dialog handled"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Handle dialog failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _action_file_upload(
    state: dict,
    page_id: str,
    paths_json: str,
) -> ToolChunk:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    paths = _parse_json_param(paths_json, [])
    if not isinstance(paths, list):
        paths = []
    try:
        choosers = state["pending_file_choosers"].get(page_id, [])
        if not choosers:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": "No chooser. Click upload then file_upload.",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        chooser = choosers.pop(0)
        if paths:
            if _USE_SYNC_PLAYWRIGHT:
                await _run_sync(chooser.set_files, paths)
            else:
                await chooser.set_files(paths)
            return _tool_response(
                json.dumps(
                    {"ok": True, "message": f"Uploaded {len(paths)} file(s)"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(chooser.set_files, [])
        else:
            await chooser.set_files([])
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "File chooser cancelled"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"File upload failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


async def _download_context_url(
    page,
    source_url: str,
    destination: str,
) -> tuple[int, str]:
    if _USE_SYNC_PLAYWRIGHT:
        head_response = await _run_sync(
            page.context.request.head,
            source_url,
        )
    else:
        head_response = await page.context.request.head(source_url)
    head_status = head_response.status
    if not head_response.ok:
        raise DirectUrlDownloadRejectedError(
            "Direct URL file_download requires a successful HEAD response "
            "before downloading. Use file_download with ref instead.",
            status=head_status,
        )
    head_headers = head_response.headers
    raw_content_length = (
        head_headers.get("content-length") or head_headers.get("Content-Length") or ""
    )
    if not raw_content_length:
        raise DirectUrlDownloadRejectedError(
            "Direct URL file_download requires Content-Length before "
            "downloading. Use file_download with ref instead.",
            status=head_status,
        )
    try:
        content_length = int(raw_content_length)
    except (TypeError, ValueError) as exc:
        raise DirectUrlDownloadRejectedError(
            "Direct URL file_download received an invalid Content-Length. "
            "Use file_download with ref instead.",
            status=head_status,
        ) from exc
    if content_length > _MAX_DIRECT_URL_DOWNLOAD_BYTES:
        raise DirectUrlDownloadRejectedError(
            "Direct URL file_download is disabled for files larger than "
            "10 MB. Use file_download with ref instead.",
            content_length=content_length,
            status=head_status,
        )

    if _USE_SYNC_PLAYWRIGHT:
        response = await _run_sync(page.context.request.get, source_url)
    else:
        response = await page.context.request.get(source_url)
    status = response.status
    if not response.ok:
        return status, ""
    headers = response.headers
    content_type = headers.get("content-type") or headers.get("Content-Type") or ""
    if _USE_SYNC_PLAYWRIGHT:
        body = await _run_sync(response.body)
    else:
        body = await response.body()
    Path(destination).write_bytes(body)
    return status, content_type


def _direct_url_download_rejected_response(
    page_id: str,
    source_url: str,
    file_path: str,
    error: DirectUrlDownloadRejectedError,
) -> ToolChunk:
    payload = {
        "ok": False,
        "error": error.message or str(error),
        "hint": (
            "Take a snapshot, pass the download control's ref, and let the "
            "browser download event save the file directly."
        ),
        "page_id": page_id,
        "url": source_url,
        "file_path": file_path,
        "max_direct_url_download_bytes": _MAX_DIRECT_URL_DOWNLOAD_BYTES,
    }
    if error.content_length is not None:
        payload["content_length"] = error.content_length
    if error.status is not None:
        payload["status"] = error.status
    return _tool_response(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_file_download(  # pylint: disable=too-many-branches,too-many-return-statements,too-many-statements
    state: dict,
    page_id: str,
    file_path: str,
    ref: str = "",
    url: str = "",
    wait_time: float = 0.0,
) -> ToolChunk:
    """Save a browser download event or a page resource to a local file."""
    file_path = (file_path or "").strip()
    if not file_path:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "path or filename required for file_download",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    resolved = _resolve_output_path(file_path)
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)

    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )

    ref = (ref or "").strip()
    url = (url or "").strip()
    timeout_ms = max(float(wait_time or 30.0), 0.1) * 1000

    try:
        # file_download with url saves the target resource directly through
        # the browser context, so cookies/session state are preserved.
        if url:
            source_url = urljoin(getattr(page, "url", ""), url)
            try:
                status, content_type = await _download_context_url(
                    page,
                    source_url,
                    resolved,
                )
            except DirectUrlDownloadRejectedError as exc:
                return _direct_url_download_rejected_response(
                    page_id,
                    source_url,
                    resolved,
                    exc,
                )
            if not content_type:
                return _tool_response(
                    json.dumps(
                        {
                            "ok": False,
                            "error": (
                                "File download failed: browser-context request "
                                f"returned HTTP {status}"
                            ),
                            "page_id": page_id,
                            "url": source_url,
                            "status": status,
                            "file_path": resolved,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            _touch_activity(state)
            return _tool_response(
                json.dumps(
                    {
                        "ok": True,
                        "message": "Download saved",
                        "page_id": page_id,
                        "file_path": resolved,
                        "url": source_url,
                        "status": status,
                        "content_type": content_type,
                        "download_method": "browser_context_request",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        before_url = getattr(page, "url", "")

        if not ref:
            return _tool_response(
                json.dumps(
                    {
                        "ok": False,
                        "error": "ref or url required for file_download",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        # file_download with ref clicks a snapshot element and waits for the
        # browser download event from that click.
        locator = _get_locator_by_ref(
            state,
            page,
            page_id,
            ref,
        )
        if locator is None:
            return _tool_response(
                json.dumps(
                    {"ok": False, "error": f"Unknown ref: {ref}"},
                    ensure_ascii=False,
                    indent=2,
                ),
            )

        before_page_ids = set(state["pages"].keys())
        if _USE_SYNC_PLAYWRIGHT:
            try:
                download = await _run_sync(
                    lambda: _sync_click_and_expect_download(
                        page,
                        locator,
                        timeout_ms,
                    ),
                )
            except Exception as exc:
                return await _file_download_click_fallback(
                    state,
                    page,
                    page_id,
                    ref,
                    resolved,
                    before_url,
                    before_page_ids,
                    exc,
                )
        else:
            try:
                async with page.expect_download(
                    timeout=timeout_ms,
                ) as download_info:
                    await locator.click()
                    download = await download_info.value
            except Exception as exc:
                return await _file_download_click_fallback(
                    state,
                    page,
                    page_id,
                    ref,
                    resolved,
                    before_url,
                    before_page_ids,
                    exc,
                )
        suggested_filename = _safe_download_filename(
            getattr(download, "suggested_filename", ""),
        )
        if _USE_SYNC_PLAYWRIGHT:
            await _run_sync(download.save_as, resolved)
        else:
            await download.save_as(resolved)
        try:
            source_url = download.url
        except Exception:
            source_url = ""
        _touch_activity(state)
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": "Download saved",
                    "page_id": page_id,
                    "file_path": resolved,
                    "suggested_filename": suggested_filename,
                    "url": source_url,
                    "download_method": "click_ref_download_event",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": f"File download failed: {e!s}",
                    "hint": (
                        "Pass ref to click a download control, or pass an "
                        "explicit url to save a resource directly."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )


def _sync_click_and_expect_download(page, locator, timeout_ms: float):
    with page.expect_download(timeout=timeout_ms) as download_info:
        locator.click()
    return download_info.value


async def _file_download_click_fallback(
    state: dict,
    page,
    page_id: str,
    ref: str,
    resolved: str,
    before_url: str,
    before_page_ids: set[str],
    original_error: Exception,
) -> ToolChunk:
    new_page_id = None
    current_page = page
    current_page_id = page_id
    for candidate_id, candidate in state["pages"].items():
        if candidate_id not in before_page_ids:
            new_page_id = candidate_id
            current_page = candidate
            current_page_id = candidate_id
            break
    current_url = getattr(current_page, "url", "")
    if current_url and (current_url != before_url or new_page_id is not None):
        try:
            status, content_type = await _download_context_url(
                current_page,
                current_url,
                resolved,
            )
        except DirectUrlDownloadRejectedError as exc:
            return _direct_url_download_rejected_response(
                page_id,
                current_url,
                resolved,
                exc,
            )
        if content_type:
            _touch_activity(state)
            payload = {
                "ok": True,
                "message": "Download saved from current page URL after click",
                "page_id": page_id,
                "current_page_id": current_page_id,
                "file_path": resolved,
                "url": current_url,
                "status": status,
                "content_type": content_type,
                "download_method": ("browser_context_request_after_inline_navigation"),
                "note": (
                    "The click navigated to an inline resource instead of "
                    "firing a browser download event."
                ),
            }
            if new_page_id is not None:
                payload["tabs"] = list(state["pages"].keys())
            return _tool_response(
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
    return _tool_response(
        json.dumps(
            {
                "ok": False,
                "error": (
                    "File download failed after click: no browser download "
                    "event occurred."
                ),
                "page_id": page_id,
                "ref": ref,
                "current_page_id": current_page_id,
                "current_url": current_url,
                "original_error": str(original_error),
                "hint": (
                    "If the browser opened an inline PDF/file page, retry "
                    "with the explicit file URL."
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


async def _action_fill_form(
    state: dict,
    page_id: str,
    fields_json: str,
) -> ToolChunk:
    page = _get_page(state, page_id)
    if not page:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Page '{page_id}' not found"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    fields = _parse_json_param(fields_json, [])
    if not isinstance(fields, list) or not fields:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": "fields required (JSON array)"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    refs = _get_refs(state, page_id)
    # Use last snapshot's frame so fill_form works after iframe snapshot
    frame = state["refs_frame"].get(page_id, "")
    try:
        for f in fields:
            ref = (f.get("ref") or "").strip()
            if not ref or ref not in refs:
                continue
            locator = _get_locator_by_ref(state, page, page_id, ref, frame)
            if locator is None:
                continue
            field_type = (f.get("type") or "textbox").lower()
            value = f.get("value")
            if field_type == "checkbox":
                if isinstance(value, str):
                    value = value.strip().lower() in ("true", "1", "yes")
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(locator.set_checked, bool(value))
                else:
                    await locator.set_checked(bool(value))
            elif field_type == "radio":
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(locator.set_checked, True)
                else:
                    await locator.set_checked(True)
            elif field_type == "combobox":
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(
                        locator.select_option,
                        label=value if isinstance(value, str) else None,
                        value=value,
                    )
                else:
                    await locator.select_option(
                        label=value if isinstance(value, str) else None,
                        value=value,
                    )
            elif field_type == "slider":
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(locator.fill, str(value))
                else:
                    await locator.fill(str(value))
            else:
                if _USE_SYNC_PLAYWRIGHT:
                    await _run_sync(
                        locator.fill,
                        str(value) if value is not None else "",
                    )
                else:
                    await locator.fill(str(value) if value is not None else "")
        return _tool_response(
            json.dumps(
                {"ok": True, "message": f"Filled {len(fields)} field(s)"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {"ok": False, "error": f"Fill form failed: {e!s}"},
                ensure_ascii=False,
                indent=2,
            ),
        )


def _run_playwright_install() -> None:
    """Run playwright install in a blocking way (for use in thread)."""
    subprocess.run(
        [sys.executable, "-m", "playwright", "install"],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutes max
    )


async def _action_install() -> ToolChunk:
    """Install Playwright browsers. If a system Chrome/Chromium/Edge is found,
    use it and skip download. On macOS with no Chromium, use Safari (WebKit)
    so no download is needed. Only run playwright install when necessary.
    """
    exe = _chromium_executable_path()
    if exe:
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": f"Using system browser (no download): {exe}",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    if _use_webkit_fallback():
        return _tool_response(
            json.dumps(
                {
                    "ok": True,
                    "message": "On macOS using Safari (WebKit); no browser download needed.",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    try:
        await asyncio.to_thread(_run_playwright_install)
        return _tool_response(
            json.dumps(
                {"ok": True, "message": "Browser installed"},
                ensure_ascii=False,
                indent=2,
            ),
        )
    except subprocess.TimeoutExpired:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": "Browser install timed out (10 min). Run manually in terminal: "
                    f"{sys.executable!s} -m playwright install",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    except Exception as e:
        return _tool_response(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Install failed: {e!s}. Install manually: "
                    f"{sys.executable!s} -m pip install playwright && "
                    f"{sys.executable!s} -m playwright install",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )




__all__ = [name for name in globals() if not name.startswith("__")]
