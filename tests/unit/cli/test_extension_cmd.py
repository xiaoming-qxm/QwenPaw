# -*- coding: utf-8 -*-
"""Tests for qwenpaw setup-extension file generation."""

from __future__ import annotations

import json

from tests.unit.browser_bridge_plugin import load_browser_bridge_submodule

extension_cmd = load_browser_bridge_submodule("extension_setup")


def test_setup_extension_files_registers_native_host(
    monkeypatch,
    tmp_path,
) -> None:
    qwenpaw_home = tmp_path / ".qwenpaw"
    native_manifest = (
        tmp_path / "NativeMessagingHosts" / "com.qwenpaw.browser.json"
    )

    monkeypatch.setattr(extension_cmd, "_qwenpaw_home", lambda: qwenpaw_home)
    monkeypatch.setattr(
        extension_cmd,
        "native_manifest_path",
        lambda: native_manifest,
    )
    monkeypatch.setattr(
        extension_cmd.secrets,
        "token_urlsafe",
        lambda _length: "fixed-token",
    )

    result = extension_cmd.setup_extension_files(
        install_mode="unpacked",
        ws_url="ws://127.0.0.1:8088/ws/nm-bridge",
        reset=True,
    )

    manifest = json.loads(native_manifest.read_text(encoding="utf-8"))
    config = json.loads((qwenpaw_home / "nm-bridge.json").read_text("utf-8"))

    assert result["installed"] is True
    assert manifest["name"] == extension_cmd.NATIVE_HOST_NAME
    assert manifest["allowed_origins"] == [
        f"chrome-extension://{extension_cmd.EXTENSION_ID}/",
    ]
    assert (qwenpaw_home / "bin" / "qwenpaw-nm-host").exists()
    assert (
        qwenpaw_home
        / "chrome-extension"
        / "qwenpaw-browser-bridge"
        / "manifest.json"
    ).exists()
    assert config == {
        "ws_url": "ws://127.0.0.1:8088/ws/nm-bridge",
        "token": "fixed-token",
    }


def test_native_manifest_paths_are_platform_specific(tmp_path) -> None:
    assert (
        "Library/Application Support/Google/Chrome/NativeMessagingHosts"
        in str(
            extension_cmd.native_manifest_path(
                home=tmp_path,
                platform="darwin",
            ),
        )
    )
    assert ".config/google-chrome/NativeMessagingHosts" in str(
        extension_cmd.native_manifest_path(home=tmp_path, platform="linux"),
    )
