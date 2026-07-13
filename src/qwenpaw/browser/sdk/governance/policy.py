# -*- coding: utf-8 -*-
"""Browser SDK policy hook contracts."""

from __future__ import annotations

import inspect
from hashlib import sha256
import json
from math import isfinite
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit

from .effects import EffectCategory, PRESENTATION, SESSION_STATE
from .errors import BrowserSDKError
from ..primitives.types import (
    BrowserActionRequest,
    BrowserContextRequest,
    BrowserPolicyDecision,
)


class BrowserPolicy(Protocol):
    """Policy hook layer for browser context acquisition and actions."""

    def allow_context_acquisition(
        self,
        request: BrowserContextRequest,
    ) -> BrowserPolicyDecision:
        """Return whether a browser context may be acquired."""

    def allow_action(
        self,
        request: BrowserActionRequest,
    ) -> BrowserPolicyDecision | Awaitable[BrowserPolicyDecision]:
        """Return whether a browser action may execute."""


class DefaultBrowserPolicy:
    """Default allow-all policy used when governance is not wired."""

    def allow_context_acquisition(
        self,
        request: BrowserContextRequest,
    ) -> BrowserPolicyDecision:
        _ = request
        return BrowserPolicyDecision(allowed=True, reason="allowed")

    def allow_action(
        self,
        request: BrowserActionRequest,
    ) -> BrowserPolicyDecision | Awaitable[BrowserPolicyDecision]:
        _ = request
        return BrowserPolicyDecision(allowed=True, reason="allowed")


_TRUSTED_SURFACE_ACTIONS = frozenset({"click", "hover", "drag"})
_TRUSTED_SURFACE_EFFECTS = frozenset({PRESENTATION, SESSION_STATE})


@dataclass(frozen=True, slots=True)
class TrustedSurfaceRule:
    """One independently reviewed exact origin/surface capability rule."""

    origin: str
    surface_identity: str
    allowed_actions: tuple[str, ...]
    effect_ceiling: tuple[EffectCategory, ...]
    revision: str
    evidence_ref: str
    expires_at: float

    def __post_init__(self) -> None:
        normalized_origin = _exact_http_origin(self.origin)
        if normalized_origin != self.origin:
            raise BrowserSDKError(
                "trusted surface origin is not canonical",
                code="surface_policy_invalid",
            )
        if not str(self.surface_identity or "").strip():
            raise BrowserSDKError(
                "trusted surface identity is missing",
                code="surface_policy_invalid",
            )
        actions = tuple(str(item) for item in self.allowed_actions)
        if (
            not actions
            or len(set(actions)) != len(actions)
            or any(item not in _TRUSTED_SURFACE_ACTIONS for item in actions)
        ):
            raise BrowserSDKError(
                "trusted surface actions are invalid",
                code="surface_policy_invalid",
            )
        try:
            ceiling = tuple(EffectCategory(item) for item in self.effect_ceiling)
        except (TypeError, ValueError) as exc:
            raise BrowserSDKError(
                "trusted surface effect ceiling is invalid",
                code="surface_policy_invalid",
            ) from exc
        if not ceiling or any(
            item not in _TRUSTED_SURFACE_EFFECTS for item in ceiling
        ):
            raise BrowserSDKError(
                "trusted surface effect ceiling is not low risk",
                code="surface_policy_invalid",
            )
        if not str(self.revision or "").strip() or not str(
            self.evidence_ref or "",
        ).strip():
            raise BrowserSDKError(
                "trusted surface review evidence is missing",
                code="surface_policy_invalid",
            )
        try:
            expiry = float(self.expires_at)
        except (TypeError, ValueError) as exc:
            raise BrowserSDKError(
                "trusted surface policy expiry is invalid",
                code="surface_policy_invalid",
            ) from exc
        if not isfinite(expiry) or expiry <= 0:
            raise BrowserSDKError(
                "trusted surface policy expiry is invalid",
                code="surface_policy_invalid",
            )
        object.__setattr__(self, "allowed_actions", actions)
        object.__setattr__(self, "effect_ceiling", ceiling)
        object.__setattr__(self, "expires_at", expiry)


class TrustedSurfacePolicy:
    """Constructor-injected immutable mapping of reviewed surface rules."""

    def __init__(self, rules: tuple[TrustedSurfaceRule, ...]) -> None:
        if not isinstance(rules, tuple) or not rules:
            raise BrowserSDKError(
                "trusted surface policy requires reviewed rules",
                code="surface_policy_invalid",
            )
        index: dict[tuple[str, str], TrustedSurfaceRule] = {}
        for rule in rules:
            if not isinstance(rule, TrustedSurfaceRule):
                raise BrowserSDKError(
                    "trusted surface policy rule is invalid",
                    code="surface_policy_invalid",
                )
            key = (rule.origin, rule.surface_identity)
            if key in index:
                raise BrowserSDKError(
                    "trusted surface policy rule is duplicated",
                    code="surface_policy_invalid",
                )
            index[key] = rule
        self._rules = index

    def authorize(
        self,
        *,
        origin: str,
        surface_identity: str,
        action: str,
        now: float,
    ) -> TrustedSurfaceRule | None:
        """Return only one exact fresh reviewed rule, never a fallback."""
        try:
            normalized_origin = _exact_http_origin(origin)
        except BrowserSDKError:
            return None
        rule = self._rules.get((normalized_origin, str(surface_identity)))
        if (
            rule is None
            or str(action) not in rule.allowed_actions
            or float(now) >= rule.expires_at
        ):
            return None
        return rule

    def match(
        self,
        *,
        origin: str,
        surface_identity: str,
        now: float,
    ) -> TrustedSurfaceRule | None:
        """Return one exact fresh reviewed surface before action sealing."""
        try:
            normalized_origin = _exact_http_origin(origin)
        except BrowserSDKError:
            return None
        rule = self._rules.get((normalized_origin, str(surface_identity)))
        if rule is None or float(now) >= rule.expires_at:
            return None
        return rule


def trusted_surface_rule_fingerprint(
    *,
    origin: str,
    surface_identity: str,
    action: str,
    revision: str,
    evidence_ref: str,
    effect_ceiling: tuple[EffectCategory | str, ...],
    expires_at: float,
) -> str:
    """Seal every independently reviewed surface-policy fact."""
    normalized_origin = _exact_http_origin(origin)
    if normalized_origin != origin:
        raise BrowserSDKError(
            "trusted surface origin is not canonical",
            code="surface_policy_invalid",
        )
    normalized_action = str(action or "")
    identity = str(surface_identity or "")
    policy_revision = str(revision or "")
    evidence = str(evidence_ref or "")
    if (
        normalized_action not in _TRUSTED_SURFACE_ACTIONS
        or not identity
        or not policy_revision
        or not evidence
    ):
        raise BrowserSDKError(
            "trusted surface proof facts are invalid",
            code="surface_policy_invalid",
        )
    try:
        ceiling = tuple(EffectCategory(item) for item in effect_ceiling)
    except (TypeError, ValueError) as exc:
        raise BrowserSDKError(
            "trusted surface proof ceiling is invalid",
            code="surface_policy_invalid",
        ) from exc
    if not ceiling or any(
        item not in _TRUSTED_SURFACE_EFFECTS for item in ceiling
    ):
        raise BrowserSDKError(
            "trusted surface proof ceiling is not low risk",
            code="surface_policy_invalid",
        )
    try:
        expiry = float(expires_at)
    except (TypeError, ValueError) as exc:
        raise BrowserSDKError(
            "trusted surface proof expiry is invalid",
            code="surface_policy_invalid",
        ) from exc
    if not isfinite(expiry) or expiry <= 0:
        raise BrowserSDKError(
            "trusted surface proof expiry is invalid",
            code="surface_policy_invalid",
        )
    payload = {
        "action": normalized_action,
        "effect_ceiling": [str(item) for item in ceiling],
        "evidence_ref": evidence,
        "expires_at": expiry,
        "origin": normalized_origin,
        "revision": policy_revision,
        "surface_identity": identity,
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _exact_http_origin(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise BrowserSDKError(
            "trusted surface origin is invalid",
            code="surface_policy_invalid",
        )
    host = parsed.hostname.lower()
    port = parsed.port
    default = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    authority = host if port is None or default else f"{host}:{port}"
    return f"{parsed.scheme}://{authority}"

async def maybe_await_policy_decision(
    value: BrowserPolicyDecision | Awaitable[BrowserPolicyDecision],
) -> BrowserPolicyDecision:
    """Return a browser policy decision from sync or async policies."""
    if inspect.isawaitable(value):
        return await value
    return cast(BrowserPolicyDecision, value)


__all__ = [
    "BrowserPolicy",
    "DefaultBrowserPolicy",
    "TrustedSurfacePolicy",
    "TrustedSurfaceRule",
    "maybe_await_policy_decision",
    "trusted_surface_rule_fingerprint",
]
