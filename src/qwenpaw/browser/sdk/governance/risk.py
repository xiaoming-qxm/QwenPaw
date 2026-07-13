# -*- coding: utf-8 -*-
"""Browser SDK action risk classification."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from ..primitives.types import BrowserActionRisk, BrowserBoundaryEvidence
from ..primitives.types import BrowserEvidenceSource
from ..primitives.types import BrowserRiskKind

_READ_ACTIONS = {
    "active_tab",
    "extract",
    "evaluate",
    "list_tabs",
    "page_info",
    "screenshot",
    "snapshot",
}
_NAVIGATION_ACTIONS = {
    "back",
    "click",
    "forward",
    "hover",
    "navigate",
    "open",
    "press",
    "reload",
    "scroll",
    "select",
    "type",
    "wait_for",
}
RISK_ACTIONS_BY_KIND: dict[BrowserRiskKind, frozenset[str]] = {
    "destructive": frozenset({"clear", "delete", "remove"}),
    "purchase": frozenset({"buy", "checkout", "purchase"}),
    "payment": frozenset({"pay", "payment"}),
    "submission": frozenset({"submit"}),
    "upload": frozenset({"upload"}),
    "download": frozenset({"download"}),
}

RISK_KEYWORDS_BY_KIND: dict[BrowserRiskKind, frozenset[str]] = {
    "credential": frozenset(
        {"credential", "login", "otp", "password", "secret", "token"},
    ),
    "destructive": frozenset({"clear", "delete", "remove"}),
    "purchase": frozenset({"buy", "cart", "checkout", "purchase"}),
    "payment": frozenset({"pay", "payment"}),
    "submission": frozenset({"submit"}),
    "upload": frozenset({"upload"}),
    "download": frozenset({"download"}),
    "unknown_sensitive": frozenset({"reveal"}),
}

_STRUCTURED_SENSITIVE_ACTIONS: dict[str, BrowserRiskKind] = {
    action: kind
    for kind, actions in RISK_ACTIONS_BY_KIND.items()
    for action in actions
}
_CREDENTIAL_KEYWORDS = set(RISK_KEYWORDS_BY_KIND["credential"])
_SENSITIVE_KEYWORDS = set().union(
    *(
        set(keywords)
        for kind, keywords in RISK_KEYWORDS_BY_KIND.items()
        if kind != "credential"
    ),
)


# pylint: disable-next=too-many-return-statements,too-many-branches
def classify_browser_action(
    action: str,
    kwargs: Mapping[str, Any],
) -> BrowserActionRisk:
    """Classify browser action risk using action structure first."""
    normalized = _normalize(action)
    evidence = _target_evidence(kwargs)

    if normalized == "evaluate" and not _bool_arg(
        kwargs.get("read_only", True),
    ):
        if evidence:
            return _risk(
                sensitive=True,
                level="high",
                kind="unknown_sensitive",
                capability_class="script",
                boundary_severity="sensitive",
                confidence=evidence[0].confidence,
                evidence=evidence,
                decision_reason="script write has effect evidence",
                consequence_summary=_consequence_summary(
                    "execute script",
                    evidence,
                ),
            )
        return _unknown_write(
            capability_class="script",
            decision_reason="script write without effect evidence",
        )

    if normalized in _READ_ACTIONS:
        return _risk(
            sensitive=False,
            level="none",
            kind="read",
            capability_class="observation",
            boundary_severity="operational",
            confidence=1.0,
            evidence=evidence,
            decision_reason="read-only browser action",
        )

    if normalized == "dialog":
        if _bool_arg(kwargs.get("accept", True)):
            dialog_evidence = evidence or (
                BrowserBoundaryEvidence(
                    source="kwargs",
                    label="dialog.accept=True",
                    confidence=1.0,
                ),
            )
            return _risk(
                sensitive=True,
                level="high",
                kind="submission",
                capability_class="dialog",
                boundary_severity="critical_known",
                confidence=1.0,
                evidence=dialog_evidence,
                decision_reason="accepting a browser dialog may submit state",
                consequence_summary=_consequence_summary(
                    "accept browser dialog",
                    dialog_evidence,
                ),
                matched=("dialog.accept",),
            )
        return _risk(
            sensitive=False,
            level="low",
            kind="navigation",
            capability_class="dialog",
            boundary_severity="operational",
            confidence=1.0,
            evidence=evidence,
            decision_reason="dismissing a browser dialog is non-sensitive",
            matched=("dialog.dismiss",),
        )

    if normalized in _STRUCTURED_SENSITIVE_ACTIONS:
        kind = _STRUCTURED_SENSITIVE_ACTIONS[normalized]
        structured_evidence = evidence or (
            BrowserBoundaryEvidence(
                source="kwargs",
                label=normalized,
                confidence=1.0,
            ),
        )
        return _risk(
            sensitive=True,
            level="high",
            kind=kind,
            capability_class=_capability_for_kind(kind),
            boundary_severity="critical_known",
            confidence=1.0,
            evidence=structured_evidence,
            decision_reason=(
                f"structured sensitive browser action: {normalized}"
            ),
            consequence_summary=_consequence_summary(
                normalized,
                structured_evidence,
            ),
            matched=(normalized,),
        )

    credential_matches = _matches(_CREDENTIAL_KEYWORDS, action, kwargs)
    if credential_matches:
        credential_evidence = evidence or tuple(
            BrowserBoundaryEvidence(
                source="kwargs",
                label=match,
                confidence=0.8,
            )
            for match in credential_matches
        )
        return _risk(
            sensitive=True,
            level="high",
            kind="credential",
            capability_class="credential",
            boundary_severity="critical_known",
            confidence=0.9,
            evidence=credential_evidence,
            decision_reason="credential-like browser action arguments",
            consequence_summary=_consequence_summary(
                "enter or expose credentials",
                credential_evidence,
            ),
            matched=credential_matches,
        )

    if normalized in _NAVIGATION_ACTIONS:
        if normalized in {"click", "navigate", "open"} and _is_link_navigation(
            kwargs,
        ):
            return _risk(
                sensitive=False,
                level="low",
                kind="navigation",
                capability_class="navigation",
                boundary_severity="operational",
                confidence=_best_confidence(evidence, 0.9),
                evidence=evidence,
                decision_reason=(
                    "target evidence identifies ordinary navigation"
                ),
                consequence_summary=_consequence_summary(
                    "navigate",
                    evidence,
                ),
            )
        if _is_reversible_account_state(kwargs):
            return _risk(
                sensitive=True,
                level="low",
                kind="submission",
                capability_class="input",
                boundary_severity="sensitive",
                confidence=_best_confidence(evidence, 0.9),
                evidence=evidence,
                decision_reason=(
                    "task-scoped reversible account state change"
                ),
                consequence_summary=_consequence_summary(
                    "change reversible account state",
                    evidence,
                ),
                matched=("account_state_reversible",),
            )
        sensitive_matches = _matches(_SENSITIVE_KEYWORDS, action, kwargs)
        if sensitive_matches:
            keyword_evidence = evidence or tuple(
                BrowserBoundaryEvidence(
                    source="kwargs",
                    label=match,
                    confidence=0.5,
                )
                for match in sensitive_matches
            )
            return _risk(
                sensitive=True,
                level="high",
                kind="unknown_sensitive",
                capability_class="input",
                boundary_severity="sensitive",
                confidence=0.5,
                evidence=keyword_evidence,
                decision_reason="sensitive keyword fallback",
                consequence_summary=_consequence_summary(
                    "perform sensitive action",
                    keyword_evidence,
                ),
                matched=sensitive_matches,
            )
        if _can_write(kwargs):
            if evidence:
                return _risk(
                    sensitive=True,
                    level="medium",
                    kind="navigation",
                    capability_class="input",
                    boundary_severity="sensitive",
                    confidence=evidence[0].confidence,
                    evidence=evidence,
                    decision_reason=(
                        f"{evidence[0].source} target evidence supports "
                        "state-changing input"
                    ),
                    consequence_summary=_consequence_summary(
                        f"{normalized} target",
                        evidence,
                    ),
                )
            return _unknown_write(
                capability_class="unknown_write",
                decision_reason="state-changing browser action lacks target "
                "or effect evidence",
            )
        return _risk(
            sensitive=False,
            level="low",
            kind="navigation",
            capability_class="navigation",
            boundary_severity="operational",
            confidence=0.8,
            evidence=evidence,
            decision_reason="non-sensitive browser interaction",
        )

    sensitive_matches = _matches(_SENSITIVE_KEYWORDS, action, kwargs)
    if sensitive_matches:
        keyword_evidence = evidence or tuple(
            BrowserBoundaryEvidence(
                source="kwargs",
                label=match,
                confidence=0.5,
            )
            for match in sensitive_matches
        )
        return _risk(
            sensitive=True,
            level="high",
            kind="unknown_sensitive",
            capability_class="input",
            boundary_severity="sensitive",
            confidence=0.5,
            evidence=keyword_evidence,
            decision_reason="sensitive keyword fallback",
            consequence_summary=_consequence_summary(
                "perform sensitive action",
                keyword_evidence,
            ),
            matched=sensitive_matches,
        )

    if _can_write(kwargs):
        return _unknown_write(
            capability_class="unknown_write",
            decision_reason=(
                "unknown state-changing browser action lacks target or "
                "effect evidence"
            ),
        )

    return _risk(
        sensitive=False,
        level="low",
        kind="navigation",
        capability_class="navigation",
        boundary_severity="operational",
        confidence=0.5,
        evidence=evidence,
        decision_reason="no sensitive browser risk matched",
    )


def _normalize(value: Any) -> str:
    return str(value or "").strip().casefold().replace("-", "_")


def _matches(
    keywords: Collection[str],
    action: str,
    kwargs: Mapping[str, Any],
) -> tuple[str, ...]:
    haystack = " ".join([str(action), *_flatten_values(kwargs)]).casefold()
    return tuple(
        sorted(keyword for keyword in keywords if keyword in haystack),
    )


def _flatten_values(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        out: list[str] = []
        for key, item in value.items():
            out.append(str(key))
            out.extend(_flatten_values(item))
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        out = []
        for item in value:
            out.extend(_flatten_values(item))
        return out
    return [str(value)]


def _bool_arg(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _risk(
    *,
    sensitive: bool,
    level: str,
    kind: BrowserRiskKind,
    capability_class: str,
    boundary_severity: str,
    confidence: float,
    evidence: tuple[BrowserBoundaryEvidence, ...] = (),
    decision_reason: str,
    consequence_summary: str = "",
    matched: tuple[str, ...] = (),
    error_code: str = "",
) -> BrowserActionRisk:
    return BrowserActionRisk(
        sensitive=sensitive,
        level=level,  # type: ignore[arg-type]
        kind=kind,
        reason=decision_reason,
        matched=matched,
        capability_class=capability_class,  # type: ignore[arg-type]
        boundary_severity=boundary_severity,  # type: ignore[arg-type]
        confidence=confidence,
        evidence=evidence,
        decision_reason=decision_reason,
        consequence_summary=consequence_summary,
        error_code=error_code,
    )


def _unknown_write(
    *,
    capability_class: str,
    decision_reason: str,
) -> BrowserActionRisk:
    return _risk(
        sensitive=True,
        level="high",
        kind="unknown_write",
        capability_class=capability_class,
        boundary_severity="critical_unknown",
        confidence=0.0,
        decision_reason=decision_reason,
        matched=("unknown_write",),
        error_code="boundary_user_intervention_required",
    )


def _target_evidence(
    kwargs: Mapping[str, Any],
) -> tuple[BrowserBoundaryEvidence, ...]:
    raw_target = kwargs.get("target")
    if isinstance(raw_target, Mapping):
        source = _evidence_source(raw_target.get("source"))
        label = _first_text(
            raw_target.get("label"),
            raw_target.get("text"),
            raw_target.get("aria"),
            raw_target.get("name"),
        )
        if not label and source == "visual" and raw_target.get("bbox"):
            label = "visual target"
        if label or source != "unknown":
            metadata = _target_metadata(raw_target)
            return (
                BrowserBoundaryEvidence(
                    source=source,
                    label=label,
                    confidence=_source_confidence(source),
                    metadata=metadata,
                ),
            )
    if isinstance(raw_target, str) and raw_target.strip():
        return (
            BrowserBoundaryEvidence(
                source="kwargs",
                label=raw_target.strip(),
                confidence=0.5,
            ),
        )
    raw_evidence = kwargs.get("evidence")
    if isinstance(raw_evidence, Mapping):
        source = _evidence_source(raw_evidence.get("source"))
        label = _first_text(
            raw_evidence.get("label"),
            raw_evidence.get("text"),
        )
        return (
            BrowserBoundaryEvidence(
                source=source,
                label=label,
                confidence=_source_confidence(source),
                metadata=_target_metadata(raw_evidence),
            ),
        )
    return ()


def _target_metadata(target: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
        "role",
        "href",
        "url",
        "button_type",
        "form_type",
        "accessible_name",
        "name",
        "consequence",
    ):
        value = target.get(key)
        if value:
            metadata[key] = str(value)
    return metadata


def _is_link_navigation(kwargs: Mapping[str, Any]) -> bool:
    target = kwargs.get("target")
    if isinstance(target, Mapping):
        role = _normalize(target.get("role"))
        if role == "link":
            return True
        if str(target.get("href") or target.get("url") or "").strip():
            return True
    href = str(kwargs.get("href") or kwargs.get("url") or "").strip()
    return bool(href and not _is_reversible_account_state(kwargs))


def _is_reversible_account_state(kwargs: Mapping[str, Any]) -> bool:
    target = kwargs.get("target")
    values = [kwargs.get("consequence")]
    if isinstance(target, Mapping):
        values.append(target.get("consequence"))
    return any(
        _normalize(value) == "account_state_reversible" for value in values
    )


def _best_confidence(
    evidence: tuple[BrowserBoundaryEvidence, ...],
    fallback: float,
) -> float:
    return evidence[0].confidence if evidence else fallback


def _evidence_source(value: Any) -> BrowserEvidenceSource:
    normalized = _normalize(value)
    if normalized in {
        "dom",
        "aria",
        "snapshot",
        "screenshot",
        "visual",
        "kwargs",
        "backend",
    }:
        return normalized  # type: ignore[return-value]
    return "unknown"


def _source_confidence(source: BrowserEvidenceSource) -> float:
    if source == "visual":
        return 0.8
    if source in {"dom", "aria", "snapshot", "screenshot", "backend"}:
        return 0.9
    if source == "kwargs":
        return 0.5
    return 0.0


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _can_write(kwargs: Mapping[str, Any]) -> bool:
    for key in ("can_write", "writes_state", "mutates", "state_change"):
        if key in kwargs:
            return _bool_arg(kwargs.get(key))
    return False


def _capability_for_kind(kind: BrowserRiskKind) -> str:
    if kind in {"purchase", "payment"}:
        return "commerce"
    if kind in {"upload", "download"}:
        return "file_transfer"
    return "input"


def _consequence_summary(
    action: str,
    evidence: tuple[BrowserBoundaryEvidence, ...],
) -> str:
    label = evidence[0].label if evidence else ""
    if label:
        return f"May {action} on {label}."
    return f"May {action}."


__all__ = [
    "RISK_ACTIONS_BY_KIND",
    "RISK_KEYWORDS_BY_KIND",
    "classify_browser_action",
]
