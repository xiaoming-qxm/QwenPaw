# -*- coding: utf-8 -*-
"""CDP permission classification for Chrome browser control mode."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

POLICY_SEVERITY = {
    "allow": 0,
    "ask_new_domain": 1,
    "ask": 2,
    "deny": 3,
}

CDP_CAPABILITY_MAP: dict[str, str] = {
    # perceive
    "Accessibility.getFullAXTree": "perceive",
    "DOM.enable": "perceive",
    "DOM.getDocument": "perceive",
    "DOM.getContentQuads": "perceive",
    "DOM.getNodeForLocation": "perceive",
    "DOM.describeNode": "perceive",
    "DOM.querySelector": "perceive",
    "DOM.performSearch": "perceive",
    "DOM.getSearchResults": "perceive",
    "DOM.discardSearchResults": "perceive",
    "DOM.focus": "input",
    "DOM.resolveNode": "perceive",
    "DOM.scrollIntoViewIfNeeded": "perceive",
    "DOMSnapshot.captureSnapshot": "perceive",
    "Page.enable": "perceive",
    "Page.getNavigationHistory": "perceive",
    "Page.getLayoutMetrics": "perceive",
    # screenshot
    "Page.captureScreenshot": "screenshot",
    # input
    "Page.handleJavaScriptDialog": "input",
    "Input.dispatchMouseEvent": "input",
    "Input.dispatchKeyEvent": "input",
    "Input.insertText": "input",
    # navigate
    "Page.navigate": "navigate",
    "Page.reload": "navigate",
    "Page.goBack": "navigate",
    "Page.goForward": "navigate",
    "Page.navigateToHistoryEntry": "navigate",
    # evaluate
    "Runtime.evaluate": "evaluate",
    "Runtime.callFunctionOn": "input",
    # storage
    "Storage.clearDataForOrigin": "storage",
    "Network.getCookies": "storage",
    "Network.setCookie": "storage",
    # network
    "Network.enable": "perceive",
    "Network.setExtraHTTPHeaders": "network",
    # download/upload
    "Browser.setDownloadBehavior": "download_upload",
    "DOM.setFileInputFiles": "download_upload",
    # browser control
    "Target.createTarget": "browser_control",
    "Target.closeTarget": "browser_control",
    # debugger
    "Debugger.enable": "debugger",
    "Debugger.setBreakpoint": "debugger",
}

DEFAULT_POLICIES: dict[str, str] = {
    "perceive": "allow",
    "screenshot": "allow",
    "input": "allow",
    "navigate": "ask_new_domain",
    "evaluate": "deny",
    "storage": "deny",
    "network": "ask",
    "download_upload": "ask",
    "browser_control": "deny",
    "debugger": "deny",
    "unknown": "deny",
}


@dataclass(frozen=True)
class PolicyResult:
    decision: str
    category: str
    method: str
    domain: str | None = None
    matched_rules: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PermissionsConfig:
    capability_rules: dict[str, str] = field(default_factory=dict)
    domain_rules: list[dict[str, Any]] = field(default_factory=list)
    approved_domains: set[str] = field(default_factory=set)


DEFAULT_PERMISSIONS_PATH = (
    Path.home() / ".qwenpaw" / "browser-permissions.yaml"
)


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    return (urlparse(url).hostname or "").lower() or None


def _domain_is_approved(
    domain: str | None,
    approved_domains: set[str],
) -> bool:
    if not domain:
        return False
    for approved in approved_domains:
        approved = str(approved).lower().strip()
        if not approved:
            continue
        if domain == approved or domain.endswith(f".{approved}"):
            return True
    return False


def _max_policy(*policies: str) -> str:
    return max(policies, key=lambda policy: POLICY_SEVERITY.get(policy, 3))


def _domain_policy(
    domain: str | None,
    config: PermissionsConfig,
) -> tuple[str, list[dict[str, Any]]]:
    if not domain:
        return "allow", []
    matched: list[dict[str, Any]] = []
    decision = "allow"
    for rule in config.domain_rules:
        pattern = str(rule.get("pattern") or "")
        policy = str(rule.get("policy") or "allow")
        if not pattern:
            continue
        if fnmatch.fnmatch(domain, pattern):
            matched.append(rule)
            decision = _max_policy(decision, policy)
    return decision, matched


def check_permission(
    method: str,
    target_url: str | None = None,
    config: PermissionsConfig | None = None,
) -> PolicyResult:
    config = config or PermissionsConfig()
    category = CDP_CAPABILITY_MAP.get(method, "unknown")
    domain = _domain_from_url(target_url)

    capability_policy = config.capability_rules.get(
        category,
        DEFAULT_POLICIES.get(category, "deny"),
    )
    if category == "navigate" and capability_policy == "ask_new_domain":
        if domain is None or _domain_is_approved(
            domain,
            config.approved_domains,
        ):
            capability_policy = "allow"

    domain_policy, matched_rules = _domain_policy(domain, config)
    decision = _max_policy(capability_policy, domain_policy)
    return PolicyResult(
        decision=decision,
        category=category,
        method=method,
        domain=domain,
        matched_rules=matched_rules,
    )


def load_permissions(
    path: str | Path = DEFAULT_PERMISSIONS_PATH,
) -> PermissionsConfig:
    path = Path(path)
    if not path.exists():
        return PermissionsConfig()

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    control = raw.get("control") or raw
    capabilities = control.get("capabilities") or {}
    domains = control.get("domain_rules") or control.get("domains") or []
    approved_domains = control.get("approved_domains") or []

    return PermissionsConfig(
        capability_rules={
            str(key): str(value)
            for key, value in capabilities.items()
            if str(value) in POLICY_SEVERITY
        },
        domain_rules=[
            {
                "pattern": str(rule.get("pattern")),
                "policy": str(rule.get("policy")),
            }
            for rule in domains
            if isinstance(rule, dict)
            and rule.get("pattern")
            and str(rule.get("policy")) in POLICY_SEVERITY
        ],
        approved_domains={str(domain).lower() for domain in approved_domains},
    )
