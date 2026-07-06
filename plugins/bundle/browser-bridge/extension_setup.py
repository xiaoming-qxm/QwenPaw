# -*- coding: utf-8 -*-
"""Chrome extension setup command."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import webbrowser
from pathlib import Path
from uuid import uuid4

import click

NATIVE_HOST_NAME = "com.qwenpaw.browser"
EXTENSION_ID = "nflcgkfjgoiipklkpenmbiificbakoch"
CWS_EXTENSION_ID = EXTENSION_ID
CWS_URL = (
    "https://chromewebstore.google.com/detail/"
    f"qwenpaw-browser-bridge/{CWS_EXTENSION_ID}"
)
DEFAULT_WS_URL = "ws://127.0.0.1:8088/ws/browser-bridge"
CHROME_EXTENSIONS_URL = "chrome://extensions"
LOCAL_BRIDGE_CONFIG_JS = "bridge_config.js"
LOCAL_INITIAL_RECONNECT_BACKOFF_SECONDS = 5
LOCAL_MAX_RECONNECT_BACKOFF_SECONDS = 60
BRIDGE_MANIFEST_FILENAME = "browser-bridge-hosts.json"
BRIDGE_MANIFEST_SCHEMA_VERSION = 1
NATIVE_HOST_REPAIR_INSTRUCTION = (
    "Run qwenpaw setup-extension --yes --reset, then reload the Browser "
    "Bridge Chrome extension."
)


def native_manifest_path(
    *,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    home = home or Path.home()
    platform = platform or sys.platform
    if platform == "darwin":
        return (
            home
            / "Library"
            / "Application Support"
            / "Google"
            / "Chrome"
            / "NativeMessagingHosts"
            / f"{NATIVE_HOST_NAME}.json"
        )
    if platform == "win32":
        base = Path.home() / "AppData" / "Roaming"
        return (
            base
            / "Google"
            / "Chrome"
            / "NativeMessagingHosts"
            / f"{NATIVE_HOST_NAME}.json"
        )
    return (
        home
        / ".config"
        / "google-chrome"
        / "NativeMessagingHosts"
        / f"{NATIVE_HOST_NAME}.json"
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _plugin_root() -> Path:
    return Path(__file__).resolve().parent


def _first_existing_path(candidates: list[Path], label: str) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    joined = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"{label} not found. Checked: {joined}")


def _extension_source_dir() -> Path:
    plugin_root = _plugin_root()
    repo_root = _repo_root()
    return _first_existing_path(
        [
            plugin_root / "assets" / "extensions" / "qwenpaw-browser-bridge",
            repo_root / "extensions" / "qwenpaw-browser-bridge",
        ],
        "Browser bridge extension assets",
    )


def _native_host_source_path() -> Path:
    plugin_root = _plugin_root()
    repo_root = _repo_root()
    return _first_existing_path(
        [
            plugin_root / "assets" / "scripts" / "nm_host.py",
            repo_root / "scripts" / "nm_host.py",
        ],
        "Native Messaging host script",
    )


def _native_host_support_paths() -> list[Path]:
    source_dir = _native_host_source_path().parent
    return [
        source_dir / name
        for name in (
            "handshake.py",
            "lease_registry.py",
            "manifest.py",
            "router.py",
        )
        if (source_dir / name).exists()
    ]


def _qwenpaw_home() -> Path:
    return Path.home() / ".qwenpaw"


def resolve_default_ws_url() -> str:
    """Resolve the bridge WebSocket URL for the currently running API."""
    try:
        from qwenpaw.config.utils import read_last_api

        api_info = read_last_api()
    except Exception:
        api_info = None

    if not api_info:
        return DEFAULT_WS_URL

    host, port = api_info
    host = "127.0.0.1" if host in {"", "0.0.0.0"} else str(host)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"ws://{host}:{port}/ws/browser-bridge"


def _copy_extension(qwenpaw_home: Path) -> Path:
    source = _extension_source_dir()
    target = qwenpaw_home / "chrome-extension" / "qwenpaw-browser-bridge"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _write_local_extension_config(extension_dir: Path) -> Path:
    config_path = extension_dir / LOCAL_BRIDGE_CONFIG_JS
    config = {
        "initialReconnectBackoffSeconds": (
            LOCAL_INITIAL_RECONNECT_BACKOFF_SECONDS
        ),
        "maxReconnectBackoffSeconds": LOCAL_MAX_RECONNECT_BACKOFF_SECONDS,
    }
    config_path.write_text(
        "globalThis.QWENPAW_BRIDGE_CONFIG = "
        f"{json.dumps(config, separators=(',', ':'))};\n",
        encoding="utf-8",
    )
    return config_path


def _write_nm_config(qwenpaw_home: Path, token: str, ws_url: str) -> Path:
    config_path = qwenpaw_home / "nm-bridge.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"ws_url": ws_url, "token": token}, indent=2),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    return config_path


def _bridge_manifest_path(qwenpaw_home: Path) -> Path:
    return qwenpaw_home / BRIDGE_MANIFEST_FILENAME


def _write_bridge_manifest_entry(
    qwenpaw_home: Path,
    token: str,
    ws_url: str,
) -> Path:
    manifest_path = _bridge_manifest_path(qwenpaw_home)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    entry_id = f"qwenpaw-runtime-{uuid4().hex[:8]}"
    manifest = {
        "schemaVersion": BRIDGE_MANIFEST_SCHEMA_VERSION,
        "entries": [
            {
                "entryId": entry_id,
                "channel": "stable",
                "appVersion": "",
                "protocolVersion": BRIDGE_MANIFEST_SCHEMA_VERSION,
                "wsUrl": ws_url,
                "token": token,
                "presence": {
                    "pid": os.getpid(),
                    "startedAt": _utc_now(),
                    "lastSeenAt": _utc_now(),
                },
                "updatedAt": _utc_now(),
            },
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)
    return manifest_path


def _bridge_manifest_entries(manifest_path: Path) -> list[dict]:
    if not manifest_path.exists():
        return []
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = raw.get("entries")
    if not isinstance(entries, list):
        return []
    return [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and str(entry.get("wsUrl") or "").strip()
        and str(entry.get("token") or "").strip()
    ]


def _utc_now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_existing_nm_token(qwenpaw_home: Path) -> str | None:
    config_path = qwenpaw_home / "nm-bridge.json"
    if not config_path.exists():
        return None
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = str(raw.get("token") or "").strip()
    return token or None


def _write_host(qwenpaw_home: Path) -> Path:
    bin_dir = qwenpaw_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    host_impl = bin_dir / "qwenpaw-nm-host.py"
    shutil.copy2(_native_host_source_path(), host_impl)
    host_impl.chmod(0o755)
    for support_path in _native_host_support_paths():
        shutil.copy2(support_path, bin_dir / support_path.name)

    host = bin_dir / "qwenpaw-nm-host"
    host.write_text(
        "#!/usr/bin/env sh\n" f'exec "{sys.executable}" "{host_impl}" "$@"\n',
        encoding="utf-8",
    )
    host.chmod(
        host.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
    )
    return host


def _write_native_manifest(
    host_path: Path,
    extension_id: str = EXTENSION_ID,
) -> Path:
    manifest_path = native_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": NATIVE_HOST_NAME,
        "description": "QwenPaw Chrome browser bridge Native Messaging host",
        "path": str(host_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest_path.chmod(0o600)
    return manifest_path


def _uninstall(qwenpaw_home: Path) -> None:
    manifest_path = native_manifest_path()
    if manifest_path.exists():
        manifest_path.unlink()
    bridge_manifest_path = _bridge_manifest_path(qwenpaw_home)
    if bridge_manifest_path.exists():
        bridge_manifest_path.unlink()
    host = qwenpaw_home / "bin" / "qwenpaw-nm-host"
    host_impl = qwenpaw_home / "bin" / "qwenpaw-nm-host.py"
    for path in (host, host_impl):
        if path.exists():
            path.unlink()


def setup_extension_files(
    *,
    install_mode: str = "unpacked",
    ws_url: str | None = None,
    reset: bool = False,
) -> dict[str, str | bool]:
    """Install extension files and Native Messaging registration."""
    ws_url = ws_url or resolve_default_ws_url()
    qwenpaw_home = _qwenpaw_home()
    if reset:
        _uninstall(qwenpaw_home)

    if install_mode not in {"unpacked", "cws"}:
        raise ValueError("install_mode must be 'unpacked' or 'cws'")

    token = None if reset else _read_existing_nm_token(qwenpaw_home)
    token = token or secrets.token_urlsafe(32)
    extension_dir = None
    if install_mode == "unpacked":
        extension_dir = _copy_extension(qwenpaw_home)
        _write_local_extension_config(extension_dir)
    config_path = _write_nm_config(qwenpaw_home, token, ws_url)
    bridge_manifest_path = _write_bridge_manifest_entry(
        qwenpaw_home,
        token,
        ws_url,
    )
    host_path = _write_host(qwenpaw_home)
    extension_id = CWS_EXTENSION_ID if install_mode == "cws" else EXTENSION_ID
    manifest_path = _write_native_manifest(host_path, extension_id)
    result: dict[str, str | bool] = {
        "installed": True,
        "install_mode": install_mode,
        "extension_id": extension_id,
        "extension_dir": str(extension_dir)
        if extension_dir is not None
        else "",
        "native_manifest_path": str(manifest_path),
        "native_host_path": str(host_path),
        "config_path": str(config_path),
        "bridge_manifest_path": str(bridge_manifest_path),
        "manifest_configured": True,
        "native_host_repair_required": False,
        "native_host_repair_instruction": "",
        "ws_url": ws_url,
        "chrome_extensions_url": CHROME_EXTENSIONS_URL,
    }
    if install_mode == "cws":
        result["cws_url"] = CWS_URL
    return result


def extension_install_status() -> dict[str, str | bool | None]:
    """Return install paths and whether the local registration exists."""
    qwenpaw_home = _qwenpaw_home()
    extension_dir = (
        qwenpaw_home / "chrome-extension" / "qwenpaw-browser-bridge"
    )
    manifest_path = native_manifest_path()
    host_path = qwenpaw_home / "bin" / "qwenpaw-nm-host"
    config_path = qwenpaw_home / "nm-bridge.json"
    bridge_manifest_path = _bridge_manifest_path(qwenpaw_home)
    manifest_configured = bool(_bridge_manifest_entries(bridge_manifest_path))
    legacy_config_exists = config_path.exists()
    repair_required = legacy_config_exists and not manifest_configured
    ws_url = None
    if config_path.exists():
        try:
            ws_url = json.loads(config_path.read_text(encoding="utf-8")).get(
                "ws_url",
            )
        except (OSError, json.JSONDecodeError):
            ws_url = None
    installed = (
        (extension_dir / "manifest.json").exists()
        and manifest_path.exists()
        and host_path.exists()
    )
    return {
        "installed": installed,
        "install_mode": "unpacked" if installed else None,
        "extension_id": EXTENSION_ID,
        "extension_dir": str(extension_dir),
        "native_manifest_path": str(manifest_path),
        "native_host_path": str(host_path),
        "config_path": str(config_path),
        "bridge_manifest_path": str(bridge_manifest_path),
        "manifest_configured": manifest_configured,
        "native_host_repair_required": repair_required,
        "native_host_repair_instruction": (
            NATIVE_HOST_REPAIR_INSTRUCTION if repair_required else ""
        ),
        "legacy_config_path": str(config_path) if legacy_config_exists else "",
        "ws_url": ws_url or resolve_default_ws_url(),
        "chrome_extensions_url": CHROME_EXTENSIONS_URL,
    }


def open_chrome_extensions_page(
    *,
    platform: str | None = None,
) -> dict[str, str | bool]:
    """Open Chrome's extension manager through a fixed local action."""
    platform = platform or sys.platform
    commands: list[list[str]] = []

    if platform == "darwin":
        commands.append(["open", "-a", "Google Chrome", CHROME_EXTENSIONS_URL])
    elif platform == "win32":
        commands.append(
            ["cmd", "/c", "start", "", "chrome", CHROME_EXTENSIONS_URL],
        )
    else:
        commands.extend(
            [
                [browser, CHROME_EXTENSIONS_URL]
                for browser in (
                    "google-chrome",
                    "google-chrome-stable",
                    "chromium",
                    "chromium-browser",
                )
            ],
        )

    for command in commands:
        try:
            subprocess.Popen(  # pylint: disable=consider-using-with
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"opened": True, "url": CHROME_EXTENSIONS_URL}
        except OSError:
            continue

    try:
        opened = webbrowser.open(CHROME_EXTENSIONS_URL)
    except Exception as exc:  # pragma: no cover - defensive OS fallback
        return {
            "opened": False,
            "url": CHROME_EXTENSIONS_URL,
            "error": str(exc),
        }
    return {"opened": bool(opened), "url": CHROME_EXTENSIONS_URL}


@click.command("setup-extension")
@click.option(
    "--mode",
    "install_mode",
    type=click.Choice(["unpacked", "cws"]),
    default=None,
    help="Extension install mode.",
)
@click.option("--ws-url", default=DEFAULT_WS_URL, show_default=True)
@click.option("--reset", is_flag=True, help="Overwrite existing setup files.")
@click.option(
    "--uninstall",
    is_flag=True,
    help="Remove Native Messaging setup.",
)
@click.option("--yes", is_flag=True, help="Use defaults without prompting.")
def setup_extension_cmd(
    install_mode: str | None,
    ws_url: str,
    reset: bool,
    uninstall: bool,
    yes: bool,
) -> None:
    """Register the Chrome extension Native Messaging bridge."""
    qwenpaw_home = _qwenpaw_home()

    if uninstall:
        _uninstall(qwenpaw_home)
        click.echo("Removed QwenPaw Native Messaging host registration.")
        return

    if install_mode is None:
        install_mode = (
            "unpacked"
            if yes
            else click.prompt(
                "Extension install mode",
                type=click.Choice(["unpacked", "cws"]),
                default="unpacked",
            )
        )

    result = setup_extension_files(
        install_mode=install_mode,
        ws_url=ws_url,
        reset=reset,
    )

    click.echo(f"Extension mode: {result['install_mode']}")
    click.echo(f"Extension files: {result['extension_dir']}")
    click.echo(f"Native host manifest: {result['native_manifest_path']}")
    click.echo(f"Native host executable: {result['native_host_path']}")
