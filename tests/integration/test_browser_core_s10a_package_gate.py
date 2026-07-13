# -*- coding: utf-8 -*-
"""S10A package evidence loaded only from the explicit release wheel."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


def _release_wheel() -> Path:
    raw = os.environ.get("BROWSER_RELEASE_DIR", "")
    assert raw, "BROWSER_RELEASE_DIR is required"
    release_dir = Path(raw).expanduser()
    assert release_dir.is_absolute(), "BROWSER_RELEASE_DIR must be absolute"
    assert release_dir.is_dir(), "release directory does not exist"
    wheels = tuple(sorted(release_dir.glob("*.whl")))
    assert len(wheels) == 1, "release directory must contain exactly one wheel"
    return wheels[0].resolve()


def test_release_wheel_contains_exact_browser_contract_assets() -> None:
    wheel = _release_wheel()
    required = {
        "qwenpaw/app/_app.py",
        "qwenpaw/app/migration.py",
        "qwenpaw/app/routers/browser_core.py",
        "qwenpaw/browser/sdk/__init__.py",
        "qwenpaw/browser/sdk/canonical/facade.py",
        "qwenpaw/browser/sdk/facade/browser.py",
        "qwenpaw/browser/sdk/generated/browser-support.json",
        "qwenpaw/browser/sdk/runtime/session_owner.py",
        "qwenpaw/config/config.py",
        "qwenpaw/config/utils.py",
        "qwenpaw/runtime/root_request_coordinator.py",
    }
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert required.issubset(names)
        support = json.loads(
            archive.read(
                "qwenpaw/browser/sdk/generated/browser-support.json"
            )
        )
    fingerprints = {
        key: support[key]
        for key in (
            "build_fingerprint",
            "contract_fingerprint",
            "profile_fingerprint",
            "extension_fingerprint",
            "provider_fingerprint",
        )
    }
    assert all(isinstance(value, str) and value for value in fingerprints.values())
    for key in (
        "max_retained_state_ttl_seconds",
        "max_legacy_token_ttl_seconds",
    ):
        assert isinstance(support[key], int) and not isinstance(support[key], bool)
        assert support[key] > 0
    assert support["schema_version"] == "browser-support-v1"
    assert support["capabilities"]
    assert all(
        row["status"] in {"READY", "BLOCKED"}
        and row["requirement"] in {"REQUIRED", "OPTIONAL", "FUTURE"}
        and row["family"]
        and "limits" in row
        and "validation_evidence" in row
        for row in support["capabilities"]
    )


def test_release_wheel_imports_canonical_and_authenticated_endpoint(
    tmp_path: Path,
) -> None:
    wheel = _release_wheel()
    installed_dir = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed_dir)
    working_dir = tmp_path / "package-working"
    working_dir.mkdir()
    script = r"""
import json
from pathlib import Path
import sys

installed_dir = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(installed_dir))
import qwenpaw
from qwenpaw.browser.sdk import Browser
from qwenpaw.browser.sdk.canonical.facade import Browser as CanonicalBrowser
from qwenpaw.config.config import Config
from qwenpaw.app.routers.browser_core import router

module_path = Path(qwenpaw.__file__).as_posix()
assert module_path.startswith(installed_dir.as_posix() + "/")
assert Browser is CanonicalBrowser
config = Config()
assert config.browser_contract_rollout.revision == 1
assert config.browser_contract_rollout.default == "CANONICAL"
assert config.browser_legacy_admission == "OPEN"
routes = [
    route
    for route in router.routes
    if getattr(route, "path", "") == "/browser-core/retirement-evidence"
]
assert len(routes) == 1
route = routes[0]
assert route.methods == {"GET"}
dependencies = route.dependant.dependencies
assert len(dependencies) == 1
assert dependencies[0].call.__name__ == "_require_authenticated_nonce"
print(json.dumps({"module_path": module_path, "route": route.path}))
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
    assert evidence["module_path"].startswith(str(installed_dir) + "/")
    assert evidence["route"] == "/browser-core/retirement-evidence"
