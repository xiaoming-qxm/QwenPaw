# -*- coding: utf-8 -*-
"""Chrome extension setup command."""

from __future__ import annotations

import json
import secrets
import shutil
import stat
import sys
from pathlib import Path

import click

NATIVE_HOST_NAME = "com.qwenpaw.browser"
EXTENSION_ID = "nflcgkfjgoiipklkpenmbiificbakoch"
DEFAULT_WS_URL = "ws://127.0.0.1:8765/ws/nm-bridge"


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


def _qwenpaw_home() -> Path:
    return Path.home() / ".qwenpaw"


def _copy_extension(qwenpaw_home: Path) -> Path:
    source = _repo_root() / "extensions" / "qwenpaw-browser-bridge"
    target = qwenpaw_home / "chrome-extension" / "qwenpaw-browser-bridge"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def _write_nm_config(qwenpaw_home: Path, token: str, ws_url: str) -> Path:
    config_path = qwenpaw_home / "nm-bridge.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"ws_url": ws_url, "token": token}, indent=2),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    return config_path


def _write_host(qwenpaw_home: Path) -> Path:
    bin_dir = qwenpaw_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    host_impl = bin_dir / "qwenpaw-nm-host.py"
    shutil.copy2(_repo_root() / "scripts" / "nm_host.py", host_impl)
    host_impl.chmod(0o755)

    host = bin_dir / "qwenpaw-nm-host"
    host.write_text(
        "#!/usr/bin/env sh\n"
        f'exec "{sys.executable}" "{host_impl}" "$@"\n',
        encoding="utf-8",
    )
    host.chmod(host.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return host


def _write_native_manifest(host_path: Path) -> Path:
    manifest_path = native_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": NATIVE_HOST_NAME,
        "description": "QwenPaw Chrome browser bridge Native Messaging host",
        "path": str(host_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest_path.chmod(0o600)
    return manifest_path


def _uninstall(qwenpaw_home: Path) -> None:
    manifest_path = native_manifest_path()
    if manifest_path.exists():
        manifest_path.unlink()
    host = qwenpaw_home / "bin" / "qwenpaw-nm-host"
    host_impl = qwenpaw_home / "bin" / "qwenpaw-nm-host.py"
    for path in (host, host_impl):
        if path.exists():
            path.unlink()


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
@click.option("--uninstall", is_flag=True, help="Remove Native Messaging setup.")
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

    if reset:
        _uninstall(qwenpaw_home)

    token = secrets.token_urlsafe(32)
    extension_dir = _copy_extension(qwenpaw_home)
    _write_nm_config(qwenpaw_home, token, ws_url)
    host_path = _write_host(qwenpaw_home)
    manifest_path = _write_native_manifest(host_path)

    click.echo(f"Extension mode: {install_mode}")
    click.echo(f"Extension files: {extension_dir}")
    click.echo(f"Native host manifest: {manifest_path}")
    click.echo(f"Native host executable: {host_path}")
