# -*- coding: utf-8 -*-
"""Verify packaged Chrome Native Messaging on a Windows desktop runner."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

EXTENSION_ID = "nflcgkfjgoiipklkpenmbiificbakoch"
FORBIDDEN_ERRORS = (
    "Error when communicating with the native messaging host",
    "Native host has exited",
)


def _http_json(
    method: str,
    url: str,
    body: dict[str, object] | None = None,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {detail}") from exc
    result = json.loads(payload)
    if not isinstance(result, dict):
        raise RuntimeError(f"Expected a JSON object from {url}")
    return result


def _run_batch(launcher: Path, mode: str, stdin: bytes = b"") -> bytes:
    command = f'cmd.exe /d /s /c ""{launcher}" {mode}"'
    completed = subprocess.run(
        command,
        input=stdin,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(
            f"{launcher.name} {mode} failed with "
            f"exit {completed.returncode}: {stderr}",
        )
    return completed.stdout


def _assert_batch_contract(launcher: Path) -> None:
    content = launcher.read_text(encoding="utf-8")
    if "\\\\?\\" in content:
        raise RuntimeError("Generated launcher contains a \\\\?\\ path prefix")
    invocation = content.splitlines()[-1].removesuffix("%*")
    index = 0
    while index < len(invocation):
        if invocation[index] != "%":
            index += 1
            continue
        if index + 1 >= len(invocation) or invocation[index + 1] != "%":
            raise RuntimeError("Generated launcher contains an unescaped %")
        index += 2


def _assert_cmd_probe(launcher: Path) -> None:
    _run_batch(launcher, "--check-runtime")
    raw = json.dumps(
        {"probe": "qwenpaw"},
        separators=(",", ":"),
    ).encode("utf-8")
    frame = struct.pack("<I", len(raw)) + raw
    if _run_batch(launcher, "--probe", frame) != frame:
        raise RuntimeError("Native Messaging probe frame did not round-trip")


def _wait_for_connection(
    base_url: str,
    worker: Any,
    *,
    timeout: float = 60,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    latest_core: dict[str, Any] = {}
    latest_extension: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest_core = _http_json(
            "GET",
            f"{base_url}/api/browser/chrome/status",
        )
        latest_extension = worker.evaluate("extensionStatusPayload()")
        if latest_core.get("connected") and latest_extension.get("connected"):
            return latest_core, latest_extension
        time.sleep(1)
    raise RuntimeError(
        "Chrome connector did not become ready: "
        f"core={latest_core!r}, extension={latest_extension!r}",
    )


def _write_stale_probe_failure(state_path: Path) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["native_host_probe"] = {
        "ok": False,
        "stage": "launch",
        "detail": "temporary stale-cache validation",
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")


def _wait_for_chrome_plugin(base_url: str, timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    last_error = "Chrome plugin status endpoint was not queried"
    while time.monotonic() < deadline:
        try:
            _http_json(
                "GET",
                f"{base_url}/api/chrome/install-status",
            )
            return
        except RuntimeError as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(
        f"Chrome plugin HTTP routes did not become ready: {last_error}",
    )


def _verify_stale_cache_and_repair(
    base_url: str,
    worker: Any,
    config_path: Path,
    state_path: Path,
    original_token: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _write_stale_probe_failure(state_path)
    stale_status = _http_json(
        "GET",
        f"{base_url}/api/chrome/install-status",
    )
    if not stale_status.get("installed"):
        raise RuntimeError(
            "A stale failed probe incorrectly cleared installed",
        )
    if not stale_status.get("native_host_repair_required"):
        raise RuntimeError("Stale failed probe diagnostic was lost")
    if not _http_json(
        "GET",
        f"{base_url}/api/browser/chrome/status",
    ).get("connected"):
        raise RuntimeError("Stale probe cache overrode live connection")

    repair = _http_json(
        "POST",
        f"{base_url}/api/chrome/setup",
        {"install_mode": "unpacked", "reset": False},
    )
    repaired_token = json.loads(config_path.read_text(encoding="utf-8"))[
        "token"
    ]
    if repaired_token != original_token:
        raise RuntimeError("Non-reset Repair rotated the bridge token")
    if repair.get("native_host_repair_required"):
        raise RuntimeError(f"Repair probe failed: {repair!r}")
    return _wait_for_connection(base_url, worker)


def _verify_browser_runtime(
    base_url: str,
    extension_dir: Path,
    config_path: Path,
    state_path: Path,
    original_token: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    console_messages: list[str] = []
    from playwright.sync_api import sync_playwright

    profile_dir = Path(tempfile.mkdtemp(prefix="qwenpaw-chrome-profile-"))
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                args=[
                    f"--disable-extensions-except={extension_dir}",
                    f"--load-extension={extension_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            try:
                workers = context.service_workers
                worker = (
                    workers[0]
                    if workers
                    else context.wait_for_event(
                        "serviceworker",
                        timeout=30_000,
                    )
                )
                worker.on(
                    "console",
                    lambda message: console_messages.append(message.text),
                )
                expected_origin = f"chrome-extension://{EXTENSION_ID}/"
                if not worker.url.startswith(expected_origin):
                    raise RuntimeError(
                        f"Unexpected extension service worker: {worker.url}",
                    )

                _wait_for_connection(base_url, worker)
                core_status, extension_status = _verify_stale_cache_and_repair(
                    base_url,
                    worker,
                    config_path,
                    state_path,
                    original_token,
                )
                time.sleep(5)
                extension_status = worker.evaluate("extensionStatusPayload()")
                last_disconnect = str(
                    extension_status.get("lastDisconnectReason") or "",
                )
                observed = "\n".join(console_messages + [last_disconnect])
                failures = [
                    message
                    for message in FORBIDDEN_ERRORS
                    if message in observed
                ]
                if failures:
                    raise RuntimeError(
                        f"Native Messaging errors observed: {failures!r}",
                    )
                if not extension_status.get("connected"):
                    raise RuntimeError(
                        f"Extension disconnected after Repair: {extension_status!r}",
                    )
                return core_status, extension_status, console_messages
            finally:
                context.close()
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)


def verify(base_url: str) -> dict[str, Any]:
    setup_url = f"{base_url}/api/chrome/setup"
    _wait_for_chrome_plugin(base_url)
    setup = _http_json(
        "POST",
        setup_url,
        {"install_mode": "unpacked", "reset": False},
    )
    if not setup.get("installed") or setup.get("native_host_repair_required"):
        raise RuntimeError(f"Packaged Chrome setup failed: {setup!r}")

    launcher = Path(str(setup["native_host_path"]))
    extension_dir = Path(str(setup["extension_dir"]))
    config_path = Path(str(setup["config_path"]))
    state_path = Path.home() / ".qwenpaw" / "chrome-extension-install.json"
    for required in (launcher, extension_dir, config_path, state_path):
        if not required.exists():
            raise RuntimeError(
                f"Expected packaged setup path is missing: {required}",
            )

    _assert_batch_contract(launcher)
    _assert_cmd_probe(launcher)
    original_token = json.loads(config_path.read_text(encoding="utf-8"))[
        "token"
    ]

    core_status, extension_status, console_messages = _verify_browser_runtime(
        base_url,
        extension_dir,
        config_path,
        state_path,
        original_token,
    )

    return {
        "ok": True,
        "launcher": str(launcher),
        "extension_dir": str(extension_dir),
        "core_status": core_status,
        "extension_status": extension_status,
        "console_messages": console_messages,
        "token_preserved": True,
        "stale_probe_cache_is_diagnostic": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", ""),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist/verify-chrome-native-messaging"),
    )
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This verifier must run on Windows")
    if not args.base_url:
        parser.error("--base-url or BASE_URL is required")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "report.json"
    try:
        report = verify(args.base_url.rstrip("/"))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        report = {"ok": False, "error": str(exc)}
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"::error::{exc}")
        return 1
    finally:
        log_path = Path.home() / ".qwenpaw" / "logs" / "nm-host.log"
        if log_path.exists():
            shutil.copy2(log_path, args.output_dir / "nm-host.log")

    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
