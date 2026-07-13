# -*- coding: utf-8 -*-
"""Clean-profile Canonical User Chrome flow from the S10B wheel."""

from __future__ import annotations

import json
import os
from pathlib import Path
from hashlib import sha256
import site
import subprocess
import sys


def _release_wheel() -> Path:
    raw = os.environ.get("BROWSER_RELEASE_DIR", "")
    assert raw, "BROWSER_RELEASE_DIR is required"
    release_dir = Path(raw).expanduser()
    assert release_dir.is_absolute(), "BROWSER_RELEASE_DIR must be absolute"
    assert release_dir.is_dir(), "release directory does not exist"
    wheels = tuple(sorted(release_dir.glob("*.whl")))
    assert len(wheels) == 1, "release directory must contain exactly one wheel"
    return wheels[0].resolve()


def _s10a_release() -> tuple[Path, tuple[Path, ...]]:
    raw = os.environ.get("S10A_RELEASE_HANDOFF", "")
    assert raw, "S10A_RELEASE_HANDOFF is required"
    handoff_path = Path(raw).expanduser().resolve()
    payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert payload["outcome"] == "READY_FOR_DEPLOYMENT"
    assert payload["legacy_state"] == "present"
    artifact = payload["artifact"]
    wheel = Path(artifact["path"]).expanduser().resolve()
    assert wheel.is_file(), "S10A handoff wheel is unavailable"
    assert sha256(wheel.read_bytes()).hexdigest() == artifact["sha256"]
    legacy_paths = tuple(
        Path(row["path"]).relative_to("src")
        for row in payload["legacy_inventory"]
    )
    assert len(legacy_paths) == 12
    return wheel, legacy_paths


def test_clean_profile_upgrade_connect_reconnect_handoff_cleanup(
    tmp_path: Path,
) -> None:
    wheel = _release_wheel()
    s10a_wheel, legacy_paths = _s10a_release()
    virtualenv = tmp_path / "upgrade-environment"
    install_env = {**os.environ, "PYTHONNOUSERSITE": "1"}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            "--system-site-packages",
            str(virtualenv),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=install_env,
    )
    venv_python = virtualenv / "bin" / "python"
    subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            str(s10a_wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=install_env,
    )
    site_result = subprocess.run(
        [
            str(venv_python),
            "-I",
            "-c",
            "import json, site; print(json.dumps(site.getsitepackages()))",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=install_env,
    )
    site_packages = tuple(json.loads(site_result.stdout.strip()))
    installed = next(
        Path(item).resolve()
        for item in site_packages
        if Path(item).is_relative_to(virtualenv)
    )
    assert all((installed / path).is_file() for path in legacy_paths)
    subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=install_env,
    )
    assert all(not (installed / path).exists() for path in legacy_paths)
    working_dir = tmp_path / "clean-profile"
    working_dir.mkdir()
    old_config = {
        "show_tool_details": False,
        "browser_contract_rollout": {
            "revision": 1,
            "default": "CANONICAL",
        },
        "browser_legacy_admission": "CLOSED",
    }
    (working_dir / "config.json").write_text(
        json.dumps(old_config),
        encoding="utf-8",
    )
    script = r"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import sys

installed = Path(sys.argv[1]).resolve()
working_dir = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(installed))
sys.path.extend(json.loads(sys.argv[3]))

from fastapi import FastAPI
import qwenpaw
from qwenpaw.app._app import _bundled_plugins_dir
from qwenpaw.app.migration import migrate_browser_contract_rollout_config
from qwenpaw.browser.sdk import Browser
from qwenpaw.browser.sdk.backends.registry import get_default_backend_registry
from qwenpaw.browser.sdk.canonical.facade import Browser as CanonicalBrowser
from qwenpaw.browser.sdk.docs.capabilities import browser_support_manifest
from qwenpaw.browser.sdk.runtime.kernel import (
    BrowserExecutionContext,
    reset_current_execution_context,
    set_current_execution_context,
)
from qwenpaw.browser.sdk.runtime.session_owner import RootTaskOutcome
from qwenpaw.config.utils import load_config_strict
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.state import PluginStateStore
from qwenpaw.runtime import root_request_coordinator as coordinator


class ReleaseBridge:
    connected = True

    def is_connected(self):
        return True


async def load_packaged_bridge():
    plugin_dir = _bundled_plugins_dir().resolve()
    assert plugin_dir.is_relative_to(installed)
    PluginStateStore().set_enabled("chrome", True)
    loader = PluginLoader([plugin_dir])
    loader.registry.set_plugin_http_app(FastAPI())
    discovered = loader.discover_plugins()
    assert len(discovered) == 1
    plugin_manifest, source = discovered[0]
    assert plugin_manifest.id == "chrome"
    record = await loader.load_plugin(plugin_manifest, source)
    assert record.enabled is True
    from plugin_chrome.backend.user import ChromeExtensionBrowserBackend

    class CountingChromeBackend(ChromeExtensionBrowserBackend):
        def __init__(self):
            super().__init__(
                bridge_manager=ReleaseBridge(),
                control_engine=SimpleNamespace(),
            )
            self.connect_calls = 0

        async def connect(self, session_id, context, **kwargs):
            self.connect_calls += 1
            return await super().connect(session_id, context, **kwargs)

    return CountingChromeBackend()


def execution_context(binding, session_id, provider):
    context = BrowserExecutionContext(
        session_id=session_id,
        context="user",
        root_session_id=binding.root_session_id,
        root_task_id=binding.root_task_id,
        browser_owner_id=binding.browser_owner_id,
        contract_mode=binding.contract_mode,
        lease_generation=binding.lease_generation,
        requires_user_state=True,
        browser_intent="user_state",
    )
    object.__setattr__(context, "provider_block_profile", provider)
    return context


async def main():
    module_path = Path(qwenpaw.__file__).resolve()
    assert module_path.is_relative_to(installed)
    assert Browser is CanonicalBrowser
    config_path = working_dir / "config.json"
    migrated = migrate_browser_contract_rollout_config(config_path)
    assert migrated is True
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["show_tool_details"] is False
    assert raw["browser_contract_rollout"] == {
        "revision": 1,
        "default": "CANONICAL",
    }
    assert "browser_legacy_admission" not in raw
    load_config_strict(config_path)
    rollout = coordinator._load_browser_contract_rollout(config_path)
    await coordinator.initialize_browser_contract_rollout(config_path)
    binding = await coordinator._OWNER_REGISTRY.begin_request(
        root_session_id="release-root-session",
        source="s10b-release-e2e",
        rollout_revision=rollout.revision,
        rollout_default=rollout.default,
    )
    assert binding.contract_mode.value == "CANONICAL"

    manifest = browser_support_manifest()
    assert manifest["legacy_state"] == "RETIRED"
    assert manifest["execution_isolation_status"] == "BLOCKED"
    backend = await load_packaged_bridge()
    registry = get_default_backend_registry()
    registry.clear()
    registry.register(backend)
    provider = SimpleNamespace(
        text=True,
        data=True,
        image=True,
        artifact=True,
        provider_fingerprint=manifest["provider_fingerprint"],
    )

    token = set_current_execution_context(
        execution_context(binding, "release-session-1", provider)
    )
    try:
        first = await Browser.connect(context="user")
        assert first.context.backend_id == backend.backend_id
        assert type(first.session).__name__ == "ChromeExtensionBrowserSession"
        await first.session.close()
        await first.close()
        second = await Browser.connect(context="user")
        await second.session.close()
        await second.close()
    finally:
        reset_current_execution_context(token)

    resume = await coordinator._OWNER_REGISTRY.retain(
        binding,
        reason="release-handoff",
        ttl_seconds=60,
    )
    resumed = await coordinator._OWNER_REGISTRY.begin_request(
        root_session_id=binding.root_session_id,
        source="s10b-release-resume",
        resume_token=resume.value,
    )
    assert resumed.owner_key == binding.owner_key
    assert resumed.lease_generation == binding.lease_generation + 1
    assert resumed.contract_mode.value == "CANONICAL"

    token = set_current_execution_context(
        execution_context(resumed, "release-session-2", provider)
    )
    try:
        handed_off = await Browser.connect(context="user")
        await handed_off.session.close()
        await handed_off.close()
    finally:
        reset_current_execution_context(token)
    await coordinator._OWNER_REGISTRY.finish_root_task(
        resumed,
        RootTaskOutcome.COMPLETE,
    )
    assert not coordinator._OWNER_REGISTRY.has_owner(resumed.owner_key)
    assert backend.connect_calls == 3
    return {
        "module_path": str(module_path),
        "connect_calls": backend.connect_calls,
        "mode": resumed.contract_mode.value,
        "legacy_state": manifest["legacy_state"],
        "old_value_preserved": raw["show_tool_details"] is False,
    }


print(json.dumps(asyncio.run(main()), sort_keys=True))
"""
    environment = {
        **os.environ,
        "QWENPAW_WORKING_DIR": str(working_dir),
        "QWENPAW_SECRET_DIR": str(tmp_path / "clean-secret"),
        "PYTHONNOUSERSITE": "1",
    }
    dependency_paths = json.dumps(
        [
            str(Path(item).resolve())
            for item in site.getsitepackages()
            if Path(item).is_dir()
        ],
    )
    result = subprocess.run(
        [
            str(venv_python),
            "-I",
            "-c",
            script,
            str(installed),
            str(working_dir),
            dependency_paths,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert Path(evidence["module_path"]).is_relative_to(installed)
    assert evidence["connect_calls"] == 3
    assert evidence["mode"] == "CANONICAL"
    assert evidence["legacy_state"] == "RETIRED"
    assert evidence["old_value_preserved"] is True
