# -*- coding: utf-8 -*-
"""Local Browser Bridge product truth audit."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.verify.browser.product_matrix import (
    BROWSER_PRODUCT_CAPABILITIES,
    BrowserProductCapability,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

MODEL_VISIBLE_PATHS = (
    "src/qwenpaw/agents/skills/browser-sdk-zh/SKILL.md",
    "plugins/bundle/browser-bridge/skills/browser-bridge/SKILL.md",
    "plugins/bundle/browser-bridge/skills/browser-bridge/ops.md",
    "plugins/bundle/browser-bridge/skills/browser-bridge/blocker-report.md",
    "plugins/bundle/browser-bridge/skills/browser-bridge/control-mode.md",
)
VERIFIER_PATH = "scripts/verify/browser/cli.py"
FRONTEND_EVIDENCE_PATHS = (
    "console/src/pages/Settings/browserBridgeReadiness.tsx",
    "console/src/pages/Settings/PluginDetail/index.tsx",
    "console/src/components/ApprovalCard/ApprovalCard.tsx",
    "plugins/bundle/browser-bridge/api/routes.py",
)
SDK_API_PATHS = (
    "src/qwenpaw/browser/sdk/facade/browser.py",
    "src/qwenpaw/browser/sdk/primitives/tab.py",
    "src/qwenpaw/browser/sdk/primitives/tabs.py",
    "src/qwenpaw/browser/sdk/actions/tab_actions.py",
)
BACKEND_PATHS = (
    "src/qwenpaw/browser/sdk/backends/isolated.py",
    "src/qwenpaw/browser/sdk/backends/user.py",
    "plugins/bundle/browser-bridge/action_runtime/handlers/__init__.py",
)
LEGACY_EVIDENCE_FIXTURES = (
    "tests/local/fixtures/browser_bridge_historical_actions.json",
)
LEGACY_BROWSER_TOOL = "".join(("browser", "_use"))

MODEL_FORBIDDEN_PATTERNS = (
    (
        "browser_use_call",
        re.compile(r"\b" + re.escape(LEGACY_BROWSER_TOOL) + r"\s*\("),
    ),
    (
        "use_browser_use",
        re.compile(r"\bUse\s+" + re.escape(LEGACY_BROWSER_TOOL) + r"\b"),
    ),
    (
        "zh_use_browser_use",
        re.compile(r"使用\s*" + re.escape(LEGACY_BROWSER_TOOL)),
    ),
    ("python_repl", re.compile(r"\bpython_repl\b")),
    ("named_live_site_recipe", re.compile(r"\btaobao\b", re.IGNORECASE)),
    ("old_fixture_marker", re.compile(r"\bV[0-9]+_[A-Z_]+_PASS\b")),
)

LEGACY_ACTION_CAPABILITY_MAP = {
    "back": "navigation.history",
    "claim_tab": "tabs.multi_tab",
    "click": "forms.submit_guard",
    "discover_tabs": "tabs.multi_tab",
    "download": "files.download_read",
    "eval": "extraction.structured",
    "evaluate": "extraction.structured",
    "forward": "navigation.history",
    "navigate": "navigation.open",
    "navigate_back": "navigation.history",
    "navigate_forward": "navigation.history",
    "open": "navigation.open",
    "press_key": "forms.type",
    "release_tab": "lifecycle.cleanup",
    "reload": "navigation.history",
    "screenshot": "observation.screenshot",
    "select_option": "forms.select",
    "snapshot": "observation.snapshot",
    "start": "lifecycle.cleanup",
    "stop": "lifecycle.cleanup",
    "tabs": "tabs.multi_tab",
    "type": "forms.type",
    "upload": "files.upload_select",
    "wait_for": "trace.evidence",
}
DEFAULT_LEGACY_CAPABILITIES = ("trace.evidence", "routing.context_resolution")
ARCHIVED_LEGACY_CAPABILITY_MAP = {
    "claim_tab": ("tabs.multi_tab",),
    "context_pruning": ("routing.context_resolution",),
    "open_url": ("navigation.open",),
    "prompt_guidance": ("trace.evidence",),
    "snapshot": ("observation.snapshot",),
    "wait_for_network": ("forms.submit_guard", "trace.evidence"),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Browser Bridge product truth from local files.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-report", type=Path)
    return parser.parse_args(argv)


def build_audit(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Build a deterministic local-only audit payload."""
    capabilities = [_capability_payload(item) for item in _capabilities()]
    gaps = [
        _gap_payload(item)
        for item in _capabilities()
        if item.gap_status != "supported"
    ]
    entropy = scan_entropy_findings(repo_root)
    legacy = classify_legacy_evidence(repo_root)
    return {
        "schema_version": "browser-bridge-v8-a.truth-audit.v1",
        "repo_root": str(repo_root),
        "capabilities": capabilities,
        "gaps": gaps,
        "entropy_findings": entropy,
        "legacy_evidence": legacy,
        "next_specs": {
            "V8-B": "SDK capability gaps",
            "V8-C": "lifecycle and hard cleanup",
            "V8-D": "product UX readiness",
            "V8-E": "deterministic and live verification",
        },
        "evidence_surfaces": evidence_surfaces(repo_root),
    }


def scan_entropy_findings(repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """Scan prompt, skill, verifier, and UX evidence surfaces."""
    findings: list[dict[str, Any]] = []
    for relative_path in MODEL_VISIBLE_PATHS:
        findings.extend(
            _scan_patterns(
                repo_root / relative_path,
                surface="model_visible_skill",
                patterns=MODEL_FORBIDDEN_PATTERNS,
            ),
        )
    verifier = repo_root / VERIFIER_PATH
    findings.extend(
        _scan_patterns(
            verifier,
            surface="verifier_prompt_policy",
            patterns=(
                MODEL_FORBIDDEN_PATTERNS[0],
                MODEL_FORBIDDEN_PATTERNS[1],
                MODEL_FORBIDDEN_PATTERNS[2],
            ),
        ),
    )
    if not findings:
        findings.append(
            {
                "kind": "entropy_scan",
                "status": "clean",
                "surface": "model_visible_and_verifier",
                "path": "",
                "line": 0,
                "matched": "",
                "message": (
                    "No Browser Bridge hot-path legacy instructions found."
                ),
            },
        )
    return findings


def classify_legacy_evidence(
    repo_root: Path = REPO_ROOT,
) -> list[dict[str, Any]]:
    """Classify archived old legacy-tool samples as historical evidence only."""
    entries: list[dict[str, Any]] = []
    for fixture_path in LEGACY_EVIDENCE_FIXTURES:
        archive = repo_root / fixture_path
        if not archive.exists():
            continue
        for record in _legacy_fixture_records(archive):
            old_action = str(record.get("old_action") or "")
            archived_capability = str(record.get("capability_id") or "")
            actions = _legacy_actions(old_action)
            mapped_ids: set[str] = {
                LEGACY_ACTION_CAPABILITY_MAP[action]
                for action in actions
                if action in LEGACY_ACTION_CAPABILITY_MAP
            }
            mapped_ids.update(
                ARCHIVED_LEGACY_CAPABILITY_MAP.get(
                    archived_capability,
                    (),
                ),
            )
            capability_ids = tuple(sorted(mapped_ids))
            if not capability_ids:
                capability_ids = DEFAULT_LEGACY_CAPABILITIES
            entries.append(
                {
                    "classification": "historical_evidence",
                    "old_tool": LEGACY_BROWSER_TOOL,
                    "source_path": _relative(archive, repo_root),
                    "matched_symbols": tuple(sorted(actions))
                    or (archived_capability,)
                    or (LEGACY_BROWSER_TOOL,),
                    "capability_ids": capability_ids,
                    "public_api": (),
                    "policy": (
                        "Use archived old samples only to preserve product "
                        "capability evidence; Browser SDK API names come "
                        "from the product matrix."
                    ),
                },
            )
    return entries


def evidence_surfaces(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Return deterministic evidence surface existence and symbol matches."""
    return {
        "sdk_public_api": _symbol_scan(repo_root, SDK_API_PATHS),
        "backend_dispatch": _symbol_scan(repo_root, BACKEND_PATHS),
        "frontend_evidence": _symbol_scan(repo_root, FRONTEND_EVIDENCE_PATHS),
        "verifier": _symbol_scan(repo_root, (VERIFIER_PATH,)),
    }


def render_markdown_report(payload: dict[str, Any]) -> str:
    """Render the human report from the JSON audit model."""
    capabilities = _as_list(payload.get("capabilities"))
    gaps = _as_list(payload.get("gaps"))
    entropy = _as_list(payload.get("entropy_findings"))
    legacy = _as_list(payload.get("legacy_evidence"))
    next_specs = payload.get("next_specs")
    if not isinstance(next_specs, dict):
        next_specs = {}

    lines = [
        "# Browser Bridge V8-A Product Truth Audit",
        "",
        "Generated from `scripts/verify/browser/truth_audit.py`.",
        "This report is a local repository audit; it does not start QwenPaw, "
        "open Chrome, call network, or inspect a user profile.",
        "",
        "## Capability Matrix",
        "",
        "| Capability | Gap Status | Isolated | User | Follow-Up |",
        "|---|---|---|---|---|",
    ]
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {_cell(item.get('capability_id'))} "
            f"| {_cell(item.get('gap_status'))} "
            f"| {_cell(_support_status(item, 'isolated_support'))} "
            f"| {_cell(_support_status(item, 'user_support'))} "
            f"| {_cell(item.get('follow_up'))} |",
        )

    lines.extend(
        [
            "",
            "## Confirmed Support",
            "",
            "| Capability | Product Task | Public API |",
            "|---|---|---|",
        ],
    )
    for item in capabilities:
        if not isinstance(item, dict) or item.get("gap_status") != "supported":
            continue
        lines.append(
            f"| {_cell(item.get('capability_id'))} "
            f"| {_cell(item.get('product_task'))} "
            f"| {_cell(', '.join(_string_list(item.get('public_api'))))} |",
        )

    lines.extend(
        [
            "",
            "## Capability Gaps",
            "",
            "Gap categories covered here: `missing`, `partial`, "
            "`internal_only`.",
            "",
            "| Capability | Gap Status | Route | Current Evidence |",
            "|---|---|---|---|",
        ],
    )
    for item in gaps:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {_cell(item.get('capability_id'))} "
            f"| {_cell(item.get('gap_status'))} "
            f"| {_cell(item.get('follow_up'))} "
            f"| {_cell(', '.join(_string_list(item.get('evidence'))))} |",
        )

    lines.extend(["", "## Entropy Findings", ""])
    for item in entropy:
        if not isinstance(item, dict):
            continue
        status = _cell(item.get("status"))
        surface = _cell(item.get("surface"))
        path = _cell(item.get("path"))
        message = _cell(item.get("message"))
        lines.append(f"- `{status}` `{surface}` {path}: {message}")

    lines.extend(
        [
            "",
            "## Legacy Evidence Policy",
            "",
            f"Archived old `{LEGACY_BROWSER_TOOL}` samples are historical "
            "capability evidence only. They map to product capability IDs "
            "and do not define Browser SDK public API names.",
            "",
            f"- Classified legacy evidence records: `{len(legacy)}`",
            "- Public API names are sourced from `product_matrix.py`.",
            "- Removal candidates and compatibility cleanup belong to V8-C.",
            "",
        ],
    )

    legacy_capabilities = sorted(
        {
            capability
            for item in legacy
            if isinstance(item, dict)
            for capability in _string_list(item.get("capability_ids"))
        },
    )
    if legacy_capabilities:
        lines.append(
            "- Legacy evidence maps to: "
            + ", ".join(f"`{item}`" for item in legacy_capabilities),
        )
        lines.append("")

    lines.extend(
        [
            "## V8 Follow-Up Routing",
            "",
            "| Spec | Scope |",
            "|---|---|",
        ],
    )
    for spec_name in ("V8-B", "V8-C", "V8-D", "V8-E"):
        lines.append(
            f"| `{spec_name}` | {_cell(next_specs.get(spec_name, ''))} |",
        )
    lines.append("")
    return "\n".join(lines)


def write_report(path: Path, payload: dict[str, Any]) -> None:
    text = render_markdown_report(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_audit()
    if args.write_report is not None:
        write_report(args.write_report, payload)
    if args.json or args.write_report is None:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


def _capabilities() -> tuple[BrowserProductCapability, ...]:
    return BROWSER_PRODUCT_CAPABILITIES


def _capability_payload(item: BrowserProductCapability) -> dict[str, Any]:
    return dataclasses.asdict(item)


def _gap_payload(item: BrowserProductCapability) -> dict[str, Any]:
    return {
        "capability_id": item.capability_id,
        "gap_status": item.gap_status,
        "product_task": item.product_task,
        "public_api": item.public_api,
        "isolated_status": item.isolated_support.status,
        "user_status": item.user_support.status,
        "follow_up": item.follow_up,
        "evidence": (
            item.isolated_support.evidence
            + item.user_support.evidence
            + item.verifier_evidence
        ),
    }


def _scan_patterns(
    path: Path,
    *,
    surface: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not path.exists():
        return [
            {
                "kind": "missing_surface",
                "status": "missing",
                "surface": surface,
                "path": str(path),
                "line": 0,
                "matched": "",
                "message": "Expected audit surface is missing.",
            },
        ]
    for line_number, line in enumerate(_read_text(path).splitlines(), 1):
        for name, pattern in patterns:
            match = pattern.search(line)
            if match is None:
                continue
            findings.append(
                {
                    "kind": name,
                    "status": "drift",
                    "surface": surface,
                    "path": _relative(path, REPO_ROOT),
                    "line": line_number,
                    "matched": match.group(0),
                    "message": (
                        "Legacy or site-specific Browser Bridge wording "
                        "appears on a hot-path surface."
                    ),
                },
            )
    return findings


def _symbol_scan(
    repo_root: Path,
    paths: tuple[str, ...],
) -> list[dict[str, Any]]:
    symbols = (
        "Browser.connect",
        "Browser.diagnostics",
        "Tab.snapshot",
        "Tab.screenshot",
        "Tab.extract",
        "actions.navigate",
        "register_handler",
        "browserBridgeReadiness",
        "ApprovalCard",
        "classify_verification_evidence",
    )
    results: list[dict[str, Any]] = []
    for relative_path in paths:
        path = repo_root / relative_path
        text = _read_text(path) if path.exists() else ""
        matches = tuple(symbol for symbol in symbols if symbol in text)
        results.append(
            {
                "path": relative_path,
                "exists": path.exists(),
                "matched_symbols": matches,
            },
        )
    return results


def _legacy_actions(text: str) -> tuple[str, ...]:
    tool_pattern = re.escape(LEGACY_BROWSER_TOOL)
    actions = set(
        re.findall(tool_pattern + r"\s*\(\s*action=[\"']([^\"']+)", text),
    )
    actions.update(re.findall(tool_pattern + r":([a-zA-Z_]+)", text))
    actions.update(
        re.findall(r"name=[\"']" + tool_pattern + r"[\"']", text),
    )
    normalized = {
        action.strip().lower()
        for action in actions
        if action.strip().lower() != LEGACY_BROWSER_TOOL
    }
    return tuple(sorted(normalized))


def _legacy_fixture_records(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(_read_text(path))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def _support_status(item: dict[str, Any], key: str) -> str:
    support = item.get(key)
    if isinstance(support, dict):
        return str(support.get("status") or "")
    return ""


def _cell(value: object) -> str:
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
