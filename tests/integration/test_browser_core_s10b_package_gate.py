# -*- coding: utf-8 -*-
"""S10B package evidence loaded only from the explicit release wheel."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


_RETIRED_HOST_PATHS = {
    "qwenpaw/browser/sdk/facade/__init__.py",
    "qwenpaw/browser/sdk/facade/browser.py",
    "qwenpaw/browser/sdk/contracts.py",
    "qwenpaw/browser/sdk/actions/__init__.py",
    "qwenpaw/browser/sdk/actions/tab_actions.py",
    "qwenpaw/browser/sdk/primitives/tab.py",
    "qwenpaw/browser/sdk/primitives/tabs.py",
    "qwenpaw/browser/sdk/runtime/proxy.py",
    "qwenpaw/browser/sdk/runtime/guard.py",
    "qwenpaw/browser/sdk/generated/api_catalog.json",
    "qwenpaw/browser/sdk/generated/capabilities.json",
    "qwenpaw/browser/sdk/generated/help/index.md",
}
_RETIRED_ROOT_TOKENS = (
    "_LEGACY_FALLBACK_ACTIONS",
    "build_control_snapshot",
    "_control_snapshot_payload_refs",
    "_control_current_snapshot_ref",
    "ContractMode.LEGACY",
)
_BRIDGE_ROOT = "qwenpaw/_plugins/bundle/browser-bridge/"
_REQUIRED_BRIDGE_PATHS = {
    _BRIDGE_ROOT + "plugin.json",
    _BRIDGE_ROOT + "main.py",
    _BRIDGE_ROOT + "api/routes.py",
    _BRIDGE_ROOT + "backend/user.py",
    _BRIDGE_ROOT + "engine_impl.py",
    _BRIDGE_ROOT + "action_runtime/handlers/dispatcher.py",
    _BRIDGE_ROOT + "action_runtime/snapshot_builder.py",
    _BRIDGE_ROOT + "action_runtime/targets.py",
    _BRIDGE_ROOT
    + "assets/extensions/qwenpaw-browser-bridge/service_worker.js",
}


def _release_wheel() -> Path:
    raw = os.environ.get("BROWSER_RELEASE_DIR", "")
    assert raw, "BROWSER_RELEASE_DIR is required"
    release_dir = Path(raw).expanduser()
    assert release_dir.is_absolute(), "BROWSER_RELEASE_DIR must be absolute"
    assert release_dir.is_dir(), "release directory does not exist"
    wheels = tuple(sorted(release_dir.glob("*.whl")))
    assert len(wheels) == 1, "release directory must contain exactly one wheel"
    return wheels[0].resolve()


def test_release_wheel_is_post_retirement_and_excludes_offline_verifier() -> None:
    wheel = _release_wheel()
    required = {
        "qwenpaw/app/_app.py",
        "qwenpaw/app/migration.py",
        "qwenpaw/browser/sdk/__init__.py",
        "qwenpaw/browser/sdk/canonical/action_contract.py",
        "qwenpaw/browser/sdk/canonical/facade.py",
        "qwenpaw/browser/sdk/generated/browser-support.json",
        "qwenpaw/browser/sdk/runtime/session_owner.py",
        "qwenpaw/config/config.py",
        "qwenpaw/runtime/root_request_coordinator.py",
    }
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert required <= names
        assert _REQUIRED_BRIDGE_PATHS <= names
        assert not any("/__pycache__/" in name for name in names)
        assert not any(name.endswith(".pyc") for name in names)
        assert not any(name.startswith(_BRIDGE_ROOT + "frontend/") for name in names)
        assert not (_RETIRED_HOST_PATHS & names)
        assert "qwenpaw/app/routers/browser_core.py" not in names
        assert not any(
            name.startswith("scripts/verify/browser/core_lab/")
            for name in names
        )
        python_text = "\n".join(
            archive.read(name).decode("utf-8")
            for name in names
            if name.endswith(".py")
        )
        support = json.loads(
            archive.read("qwenpaw/browser/sdk/generated/browser-support.json")
        )
    assert not any(token in python_text for token in _RETIRED_ROOT_TOKENS)
    assert support["legacy_state"] == "RETIRED"
    assert support["code_kernel_status"] == "FUTURE"
    assert support["execution_isolation_status"] == "BLOCKED"
    assert support["isolated_canonical_execution_status"] == "BLOCKED"


def test_release_wheel_imports_canonical_without_runtime_endpoint(
    tmp_path: Path,
) -> None:
    wheel = _release_wheel()
    installed_dir = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed_dir)
    working_dir = tmp_path / "package-working"
    working_dir.mkdir()
    script = r"""
import asyncio
import json
from pathlib import Path
import sys

installed_dir = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(installed_dir))
import qwenpaw
from qwenpaw.browser.sdk import Browser
from qwenpaw.browser.sdk.canonical.facade import Browser as CanonicalBrowser
from qwenpaw.config.config import Config
from qwenpaw.app._app import _bundled_plugins_dir
from qwenpaw.plugins.loader import PluginLoader

module_path = Path(qwenpaw.__file__).resolve()
assert module_path.is_relative_to(installed_dir)
assert Browser is CanonicalBrowser
config = Config()
assert config.browser_contract_rollout.revision == 1
assert config.browser_contract_rollout.default == "CANONICAL"
assert not hasattr(config, "browser_legacy_admission")
plugin_dir = _bundled_plugins_dir().resolve()
assert plugin_dir.is_relative_to(installed_dir)
assert (plugin_dir / "browser-bridge" / "plugin.json").is_file()
assert (plugin_dir / "browser-bridge" / "api" / "routes.py").is_file()

async def load_bridge():
    loader = PluginLoader([plugin_dir])
    discovered = loader.discover_plugins()
    assert len(discovered) == 1
    manifest, source = discovered[0]
    assert manifest.id == "chrome"
    record = await loader.load_plugin(manifest, source)
    assert record.manifest.id == "chrome"
    from plugin_chrome.api import routes
    diagnostics = await routes._sdk_diagnostics_snapshot("user")
    assert diagnostics.requested_context == "user"

asyncio.run(load_bridge())
try:
    __import__("qwenpaw.app.routers.browser_core")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("temporary browser_core endpoint module is packaged")
try:
    __import__("qwenpaw.browser.sdk.contracts")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("retired Browser SDK contracts module is packaged")
print(json.dumps({
    "module_path": str(module_path),
    "mode": "CANONICAL",
    "plugin_dir": str(plugin_dir),
}))
"""
    environment = {
        **os.environ,
        "QWENPAW_WORKING_DIR": str(working_dir),
        "QWENPAW_SECRET_DIR": str(tmp_path / "package-secret"),
        "PYTHONNOUSERSITE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(installed_dir)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert Path(evidence["module_path"]).is_relative_to(installed_dir)
    assert Path(evidence["plugin_dir"]).is_relative_to(installed_dir)
    assert evidence["mode"] == "CANONICAL"
