# -*- coding: utf-8 -*-
"""Product truth gates for Browser verifier hot paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class TruthGateViolation:
    """One forbidden token found in a Browser hot path."""

    path: str
    token: str
    line: int
    snippet: str


def _token(*parts: str) -> str:
    return "".join(parts)


FORBIDDEN_HOT_PATH_TOKENS: tuple[str, ...] = (
    _token("qwenpaw.", "browser_sdk"),
    _token("/", "extension"),
    _token("/ws/", "nm-bridge"),
    _token("browser", "-control"),
    _token("browser", "_control"),
    _token("Desktop", "ScreenShot"),
    _token("View", "Video"),
    _token("browser", "_use"),
)

DEFAULT_HOT_PATHS: tuple[str, ...] = (
    "src/qwenpaw/browser",
    "plugins/bundle/chrome",
    "scripts/verify/browser",
    "console/src/chrome",
    "console/src/pages/Settings/chromeReadiness.tsx",
)

DEFAULT_SKIP_PREFIXES: tuple[str, ...] = (
    ".git/",
    ".mypy_cache/",
    ".pytest_cache/",
    "__pycache__/",
    "MyNotebook/",
    "node_modules/",
    "plugins/bundle/chrome/frontend/node_modules/",
    "scripts/verify/browser/fixtures/",
    "scripts/verify/browser/scenario_outputs/",
)

DEFAULT_SKIP_SUFFIXES: tuple[str, ...] = (
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
)

SCENARIO_SPECIFIC_RISK_WORDS: tuple[str, ...] = (
    "taobao",
    "tmall",
    "loop",
    "fixture",
    "amazon",
)


def scan_text_for_forbidden_tokens(
    text: str,
    *,
    path: str = "",
    forbidden_tokens: tuple[str, ...] = FORBIDDEN_HOT_PATH_TOKENS,
) -> list[TruthGateViolation]:
    """Return forbidden token violations for one text blob."""
    violations: list[TruthGateViolation] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for token in forbidden_tokens:
            if _token_present(line, token):
                violations.append(
                    TruthGateViolation(
                        path=path,
                        token=token,
                        line=line_number,
                        snippet=line.strip(),
                    ),
                )
    return violations


def _token_present(line: str, token: str) -> bool:
    if token == _token("/", "extension"):
        return (
            re.search(
                r"(?<![A-Za-z0-9_@.-])\/extension(?:\/|$|[\"'])",
                line,
            )
            is not None
        )
    if token == _token("browser", "_use"):
        pattern = (
            r"(?<![A-Za-z0-9_])"
            + re.escape(_token("browser", "_use"))
            + r"(?![A-Za-z0-9_])"
        )
        return re.search(pattern, line) is not None
    return token in line


def scan_paths_for_forbidden_tokens(
    paths: list[Path],
    *,
    root: Path,
) -> list[TruthGateViolation]:
    """Scan explicit hot paths for forbidden Browser residue."""
    violations: list[TruthGateViolation] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        relative = _relative_path(path, root)
        violations.extend(
            scan_text_for_forbidden_tokens(
                path.read_text(encoding="utf-8", errors="ignore"),
                path=relative,
            ),
        )
    return violations


def run_truth_gates(
    *,
    root: Path,
    paths: list[Path] | None = None,
) -> dict[str, object]:
    """Run V10 product truth gates for Browser hot paths."""
    root = root.resolve()
    selected_paths = paths if paths is not None else _default_scan_paths(root)
    skipped_paths: list[str] = []
    scan_paths: list[Path] = []
    for path in selected_paths:
        relative = _relative_path(path, root)
        if _should_skip(relative):
            skipped_paths.append(relative)
            continue
        scan_paths.append(path)

    violations = scan_paths_for_forbidden_tokens(scan_paths, root=root)
    return {
        "status": "failed" if violations else "passed",
        "violations": [asdict(violation) for violation in violations],
        "scanned_paths": [_relative_path(path, root) for path in scan_paths],
        "skipped_paths": skipped_paths,
        "forbidden_tokens": list(FORBIDDEN_HOT_PATH_TOKENS),
    }


def run_risk_genericity_gates(
    *,
    action_groups: dict[Any, Any],
    keyword_groups: dict[Any, Any],
) -> dict[str, object]:
    """Reject site- or fixture-specific risk classifier allowlist entries."""
    violations: list[dict[str, str]] = []
    for source, groups in (
        ("action", action_groups),
        ("keyword", keyword_groups),
    ):
        for kind, words in groups.items():
            for word in words:
                normalized = str(word).strip().casefold()
                if not normalized:
                    continue
                for forbidden in SCENARIO_SPECIFIC_RISK_WORDS:
                    if forbidden in normalized:
                        violations.append(
                            {
                                "kind": str(kind),
                                "word": str(word),
                                "source": source,
                            },
                        )
                        break
    return {
        "status": "failed" if violations else "passed",
        "violations": violations,
        "forbidden_words": list(SCENARIO_SPECIFIC_RISK_WORDS),
    }


def _default_scan_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for relative in DEFAULT_HOT_PATHS:
        path = root / relative
        if path.is_file():
            paths.append(path)
        elif path.is_dir():
            paths.extend(
                item for item in sorted(path.rglob("*")) if item.is_file()
            )
    return paths


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _should_skip(relative_path: str) -> bool:
    parts = relative_path.split("/")
    if "__pycache__" in parts:
        return True
    return relative_path.endswith(
        DEFAULT_SKIP_SUFFIXES,
    ) or relative_path.startswith(
        DEFAULT_SKIP_PREFIXES,
    )


__all__ = [
    "FORBIDDEN_HOT_PATH_TOKENS",
    "SCENARIO_SPECIFIC_RISK_WORDS",
    "TruthGateViolation",
    "run_risk_genericity_gates",
    "run_truth_gates",
    "scan_paths_for_forbidden_tokens",
    "scan_text_for_forbidden_tokens",
]
