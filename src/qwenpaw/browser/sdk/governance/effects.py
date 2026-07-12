# -*- coding: utf-8 -*-
"""Authoritative closed effect classification for Canonical Browser."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .errors import BrowserSDKError


class EffectCategory(StrEnum):
    """Frozen Browser effect categories."""

    PRESENTATION = "PRESENTATION"
    SESSION_STATE = "SESSION_STATE"
    REMOTE_WRITE = "REMOTE_WRITE"
    DELETE = "DELETE"
    DATA_DISCLOSURE = "DATA_DISCLOSURE"
    LOCAL_FILE_WRITE = "LOCAL_FILE_WRITE"
    COMMUNICATION = "COMMUNICATION"
    FINANCIAL = "FINANCIAL"
    PERMISSION_OR_SECURITY = "PERMISSION_OR_SECURITY"
    UNKNOWN = "UNKNOWN"


PRESENTATION = EffectCategory.PRESENTATION
SESSION_STATE = EffectCategory.SESSION_STATE
REMOTE_WRITE = EffectCategory.REMOTE_WRITE
DELETE = EffectCategory.DELETE
DATA_DISCLOSURE = EffectCategory.DATA_DISCLOSURE
LOCAL_FILE_WRITE = EffectCategory.LOCAL_FILE_WRITE
COMMUNICATION = EffectCategory.COMMUNICATION
FINANCIAL = EffectCategory.FINANCIAL
PERMISSION_OR_SECURITY = EffectCategory.PERMISSION_OR_SECURITY
UNKNOWN = EffectCategory.UNKNOWN


@dataclass(frozen=True, slots=True)
class EffectRule:
    """One frozen row in the minimum-effect contract."""

    key: str
    minimum: tuple[EffectCategory, ...]


EFFECT_RULES = (
    EffectRule("navigation", (PRESENTATION, SESSION_STATE)),
    EffectRule("blank_tab_new", (PRESENTATION, SESSION_STATE)),
    EffectRule("hover_scroll", (PRESENTATION,)),
    EffectRule("link_click", (PRESENTATION, SESSION_STATE, UNKNOWN)),
    EffectRule(
        "generic_pointer_or_activation_key",
        (PRESENTATION, UNKNOWN),
    ),
    EffectRule("presentation_key", (PRESENTATION,)),
    EffectRule("printable_key", (SESSION_STATE, DATA_DISCLOSURE)),
    EffectRule("destructive_edit_key", (SESSION_STATE,)),
    EffectRule("text_input", (SESSION_STATE, DATA_DISCLOSURE)),
    EffectRule("checked_or_selected", (SESSION_STATE,)),
    EffectRule("upload", (SESSION_STATE, DATA_DISCLOSURE)),
    EffectRule("download_or_pdf", (LOCAL_FILE_WRITE,)),
    EffectRule("prompt_response", (UNKNOWN,)),
    EffectRule("tab_close", (PRESENTATION, SESSION_STATE)),
)

_RULES = {rule.key: rule for rule in EFFECT_RULES}
_NAVIGATION = frozenset(
    {
        "tab.actions.navigate",
        "tab.actions.back",
        "tab.actions.forward",
        "tab.actions.reload",
        "browser.tabs.open",
    },
)
_HOVER_SCROLL = frozenset(
    {"tab.actions.hover", "tab.actions.scroll"},
)
_TEXT_INPUT = frozenset(
    {
        "tab.actions.fill",
        "tab.actions.type_text",
        "tab.actions.paste",
    },
)
_CHECKED_SELECTED = frozenset(
    {"tab.actions.set_checked", "tab.actions.select_option"},
)
_DOWNLOAD_PDF = frozenset(
    {"tab.actions.download_file", "tab.actions.print_to_pdf"},
)
_PRESENTATION_KEYS = frozenset(
    {
        "Tab",
        "Escape",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
    },
)
_ACTIVATION_KEYS = frozenset({"Enter", "Space"})
_DESTRUCTIVE_KEYS = frozenset({"Backspace", "Delete"})
_PROMPT_KINDS = frozenset(
    {"", "alert", "confirm", "prompt", "beforeunload", "permission"},
)


@dataclass(frozen=True, slots=True)
class TargetFact:
    """Finite trusted target-policy input for conservative escalation."""

    kind: str
    trusted_effects: tuple[EffectCategory, ...] = ()
    proof_ref: str | None = None


@dataclass(frozen=True, slots=True)
class EffectProof:
    """Independent auditable proof supplied inside trusted Runtime."""

    categories: tuple[EffectCategory, ...]
    evidence_ref: str
    replaces_unknown: bool = False


@dataclass(frozen=True, slots=True)
class EffectClassification:
    """Ordered conservative effect categories and optional proof reference."""

    categories: tuple[EffectCategory, ...]
    proof_ref: str | None


def minimum_effects(
    api_id: str,
    arguments: Mapping[str, object],
) -> tuple[EffectCategory, ...]:
    """Return the exact minimum floor or reject an unlisted variant."""
    operation = _operation(api_id)
    args = dict(arguments)
    if operation in _NAVIGATION:
        return _RULES["navigation"].minimum
    if operation == "browser.tabs.new":
        if args.get("url") is not None or args.get("page_handler"):
            raise _invalid_operation(operation)
        return _RULES["blank_tab_new"].minimum
    if operation in _HOVER_SCROLL:
        return _RULES["hover_scroll"].minimum
    if operation in {"tab.actions.click", "tab.actions.drag"}:
        return _RULES["generic_pointer_or_activation_key"].minimum
    if operation == "tab.actions.press_key":
        return _key_effects(args)
    if operation in _TEXT_INPUT:
        return _RULES["text_input"].minimum
    if operation in _CHECKED_SELECTED:
        return _RULES["checked_or_selected"].minimum
    if operation == "tab.actions.upload_file":
        return _RULES["upload"].minimum
    if operation in _DOWNLOAD_PDF:
        return _RULES["download_or_pdf"].minimum
    if operation == "tab.actions.respond_prompt":
        return _prompt_effects(args)
    if operation in {"browser.tabs.close", "tab.close"}:
        return _tab_close_effects(args)
    raise _invalid_operation(operation)


def classify_effects(
    api_id: str,
    *,
    target_facts: tuple[TargetFact, ...],
    arguments: Mapping[str, object],
    trusted_proof: EffectProof | None = None,
) -> EffectClassification:
    """Conservatively append risk and allow only proved UNKNOWN closure."""
    operation = _operation(api_id)
    categories = list(minimum_effects(operation, arguments))
    targets = tuple(target_facts)
    if operation == "tab.actions.click" and any(
        fact.kind == "semantic_link" for fact in targets
    ):
        categories = list(_RULES["link_click"].minimum)

    for fact in targets:
        if fact.trusted_effects:
            if not str(fact.proof_ref or "").strip():
                raise BrowserSDKError(
                    "trusted target effects require an auditable proof",
                    code="effect_proof_invalid",
                )
            categories.extend(_concrete_categories(fact.trusted_effects))
        if fact.kind == "unconstrained_handler":
            categories.append(UNKNOWN)
        if fact.kind == "destructive_target":
            categories.append(DELETE)

    args = dict(arguments)
    if args.get("cross_origin_task_data"):
        categories.append(DATA_DISCLOSURE)
    if args.get("causes_download"):
        categories.append(LOCAL_FILE_WRITE)
    if args.get("causes_prompt") or args.get("origin_mismatch"):
        categories.append(UNKNOWN)
    if args.get("accepted_remote") or args.get("auto_submit"):
        categories.append(REMOTE_WRITE)
    if args.get("declared_variant") is False:
        categories.append(UNKNOWN)

    proof_ref: str | None = None
    if trusted_proof is not None:
        proof_ref = str(trusted_proof.evidence_ref or "").strip()
        concrete = _concrete_categories(trusted_proof.categories)
        if not proof_ref or not concrete:
            raise BrowserSDKError(
                "trusted effect proof is incomplete",
                code="effect_proof_invalid",
            )
        if trusted_proof.replaces_unknown:
            categories = [item for item in categories if item is not UNKNOWN]
        categories.extend(concrete)
    return EffectClassification(
        categories=_ordered_unique(categories),
        proof_ref=proof_ref,
    )


def _operation(api_id: str) -> str:
    operation = str(api_id or "").strip()
    if not operation:
        raise _invalid_operation(operation)
    return operation


def _key_effects(
    arguments: Mapping[str, object],
) -> tuple[EffectCategory, ...]:
    key = str(arguments.get("key") or "")
    if key in _ACTIVATION_KEYS:
        return _RULES["generic_pointer_or_activation_key"].minimum
    if key in _PRESENTATION_KEYS:
        return _RULES["presentation_key"].minimum
    if key in _DESTRUCTIVE_KEYS:
        return _RULES["destructive_edit_key"].minimum
    if len(key) == 1 and key.isprintable() and not key.isspace():
        return _RULES["printable_key"].minimum
    raise _invalid_operation("tab.actions.press_key")


def _prompt_effects(
    arguments: Mapping[str, object],
) -> tuple[EffectCategory, ...]:
    prompt_kind = str(arguments.get("prompt_kind") or "")
    if prompt_kind not in _PROMPT_KINDS:
        raise _invalid_operation("tab.actions.respond_prompt")
    parent = _effect_tuple(arguments.get("parent_effects", ()))
    effects: list[EffectCategory] = [*parent, UNKNOWN]
    if prompt_kind == "permission":
        effects.append(PERMISSION_OR_SECURITY)
    if prompt_kind == "beforeunload":
        effects.append(SESSION_STATE)
    if str(arguments.get("prompt_text") or ""):
        effects.append(DATA_DISCLOSURE)
    return _ordered_unique(effects)


def _tab_close_effects(
    arguments: Mapping[str, object],
) -> tuple[EffectCategory, ...]:
    if arguments.get("protected"):
        raise _invalid_operation("browser.tabs.close")
    provenance = str(arguments.get("provenance") or "UNKNOWN")
    if provenance not in {"TASK_CREATED", "BORROWED", "UNKNOWN"}:
        raise _invalid_operation("browser.tabs.close")
    effects = list(_RULES["tab_close"].minimum)
    if provenance != "TASK_CREATED":
        effects.extend((DELETE, UNKNOWN))
    if arguments.get("beforeunload"):
        effects.extend((UNKNOWN, SESSION_STATE))
    return _ordered_unique(effects)


def _effect_tuple(value: object) -> tuple[EffectCategory, ...]:
    if not isinstance(value, (tuple, list)):
        raise _invalid_operation("effect categories")
    try:
        return tuple(EffectCategory(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise _invalid_operation("effect categories") from exc


def _concrete_categories(
    categories: tuple[EffectCategory, ...],
) -> tuple[EffectCategory, ...]:
    try:
        concrete = tuple(EffectCategory(item) for item in categories)
    except (TypeError, ValueError) as exc:
        raise BrowserSDKError(
            "trusted effect proof has an invalid category",
            code="effect_proof_invalid",
        ) from exc
    return tuple(item for item in concrete if item is not UNKNOWN)


def _ordered_unique(
    categories: list[EffectCategory] | tuple[EffectCategory, ...],
) -> tuple[EffectCategory, ...]:
    return tuple(dict.fromkeys(categories))


def _invalid_operation(operation: str) -> BrowserSDKError:
    return BrowserSDKError(
        f"Canonical effect operation is invalid: {operation}",
        code="effect_operation_invalid",
    )


__all__ = [
    "COMMUNICATION",
    "DATA_DISCLOSURE",
    "DELETE",
    "EFFECT_RULES",
    "FINANCIAL",
    "LOCAL_FILE_WRITE",
    "PERMISSION_OR_SECURITY",
    "PRESENTATION",
    "REMOTE_WRITE",
    "SESSION_STATE",
    "UNKNOWN",
    "EffectCategory",
    "EffectClassification",
    "EffectProof",
    "EffectRule",
    "TargetFact",
    "classify_effects",
    "minimum_effects",
]
