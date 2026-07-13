# -*- coding: utf-8 -*-
"""Clean-profile Canonical User Chrome flow from the S10A wheel."""

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


def test_clean_profile_upgrade_connect_reconnect_handoff_cleanup(
    tmp_path: Path,
) -> None:
    wheel = _release_wheel()
    installed = tmp_path / "installed"
    installed.mkdir()
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)
    working_dir = tmp_path / "clean-profile"
    working_dir.mkdir()
    old_config = {"show_tool_details": False}
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

import qwenpaw
from qwenpaw.app.migration import migrate_browser_contract_rollout_config
from qwenpaw.browser.sdk import Browser
from qwenpaw.browser.sdk.backends.protocols import BackendProfile
from qwenpaw.browser.sdk.backends.registry import get_default_backend_registry
from qwenpaw.browser.sdk.canonical.facade import Browser as CanonicalBrowser
from qwenpaw.browser.sdk.docs.capabilities import browser_support_manifest
from qwenpaw.browser.sdk.governance.errors import BrowserContextUnavailable
from qwenpaw.browser.sdk.primitives.types import BrowserBackendCapabilities
from qwenpaw.browser.sdk.runtime.kernel import (
    BrowserExecutionContext,
    reset_current_execution_context,
    set_current_execution_context,
)
from qwenpaw.browser.sdk.runtime.session_owner import RootTaskOutcome
from qwenpaw.config.utils import load_config_strict
from qwenpaw.runtime import root_request_coordinator as coordinator


class ReleaseChromeSession:
    backend_id = "user.chrome_extension"

    async def close(self):
        return None


class ReleaseUserChromeBackend:
    backend_id = "user.chrome_extension"

    def __init__(self, manifest):
        self.manifest = manifest
        self.connect_calls = 0

    def capabilities(self):
        return BrowserBackendCapabilities(
            backend_id=self.backend_id,
            browser_context="user",
            features=frozenset({"release_candidate_extension"}),
        )

    def profile(self):
        return BackendProfile(
            variants={
                row["capability_id"]: row["status"]
                for row in self.manifest["capabilities"]
            },
            hard_limits={
                "max_retained_state_ttl_seconds": self.manifest[
                    "max_retained_state_ttl_seconds"
                ],
                "max_legacy_token_ttl_seconds": self.manifest[
                    "max_legacy_token_ttl_seconds"
                ],
            },
            contract_fingerprint=self.manifest["contract_fingerprint"],
            profile_fingerprint=self.manifest["profile_fingerprint"],
            build_fingerprint=self.manifest["build_fingerprint"],
            extension_fingerprint=self.manifest["extension_fingerprint"],
        )

    def is_available(self):
        return True

    def unavailable_error(self):
        return BrowserContextUnavailable(
            "release candidate extension unavailable",
            backend_id=self.backend_id,
        )

    async def connect(self, session_id, context, **kwargs):
        assert session_id
        assert context.selected == "user"
        assert kwargs["retention"] == "clean"
        assert kwargs["ownership_context"].root_session_id
        self.connect_calls += 1
        return ReleaseChromeSession()


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
    assert raw["browser_legacy_admission"] == "OPEN"
    load_config_strict(config_path)
    rollout = coordinator._load_browser_contract_rollout(config_path)
    await coordinator.initialize_browser_contract_rollout()
    binding = await coordinator._OWNER_REGISTRY.begin_request(
        root_session_id="release-root-session",
        source="s10a-release-e2e",
        rollout_revision=rollout.revision,
        rollout_default=rollout.default,
    )
    assert binding.contract_mode.value == "CANONICAL"

    manifest = browser_support_manifest()
    backend = ReleaseUserChromeBackend(manifest)
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
        assert first.session_capabilities["fingerprints"][
            "provider_fingerprint"
        ] == manifest["provider_fingerprint"]
        await first.close()
        second = await Browser.connect(context="user")
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
        source="s10a-release-resume",
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
        "extension_fingerprint": manifest["extension_fingerprint"],
        "provider_fingerprint": manifest["provider_fingerprint"],
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
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(installed),
            str(working_dir),
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
    assert evidence == {
        **evidence,
        "connect_calls": 3,
        "mode": "CANONICAL",
        "old_value_preserved": True,
    }
    assert evidence["extension_fingerprint"]
    assert evidence["provider_fingerprint"]
