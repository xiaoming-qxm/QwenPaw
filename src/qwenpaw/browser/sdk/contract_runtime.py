# -*- coding: utf-8 -*-
"""Thin Browser SDK Contract Runtime skeleton."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .contracts import BrowserAPIContract
from .contracts import iter_browser_api_contracts
from .governance.errors import BrowserObservationRequired
from .governance.errors import BrowserSDKError
from .governance.errors import BrowserTargetResolutionError


class BrowserContractRuntime:
    """Apply public API contract preflight and postflight checks."""

    async def execute(
        self,
        contract: BrowserAPIContract | str,
        func: Callable[..., Any],
        *args: Any,
        owner: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute a callable through a thin contract wrapper."""
        resolved = self._resolve_contract(contract)
        self._validate_arguments(resolved, func, owner, *args, **kwargs)
        self._enforce_preconditions(resolved, owner)
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        self._apply_postconditions(resolved, owner)
        return result

    def _resolve_contract(
        self,
        contract: BrowserAPIContract | str,
    ) -> BrowserAPIContract:
        if isinstance(contract, BrowserAPIContract):
            return contract
        api_id = str(contract)
        for candidate in iter_browser_api_contracts():
            if candidate.api_id == api_id:
                return candidate
        raise BrowserSDKError(
            f"Unknown Browser SDK API contract: {api_id}",
            code="browser_contract_missing",
            action=api_id,
        )

    def _validate_arguments(
        self,
        contract: BrowserAPIContract,
        func: Callable[..., Any],
        owner: Any | None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if contract.target is None:
            return
        signature = inspect.signature(func)
        bound = signature.bind_partial(*args, **kwargs)
        target = bound.arguments.get("target")
        if target is None:
            if contract.target.required:
                _raise_target_invalid(contract, target)
            return
        _validate_target_shape(contract, target)
        _validate_target_resolution(contract, target, owner)

    def _enforce_preconditions(
        self,
        contract: BrowserAPIContract,
        owner: Any | None,
    ) -> None:
        if not contract.requires_observation:
            return
        if not bool(getattr(owner, "_observation_required", False)):
            return
        raise BrowserObservationRequired(
            "A fresh Browser observation is required before this call.",
            action=contract.api_id,
            metadata={"api_id": contract.api_id},
        )

    def _apply_postconditions(
        self,
        contract: BrowserAPIContract,
        owner: Any | None,
    ) -> None:
        if owner is None:
            return
        if contract.satisfies_observation:
            mark_observed = getattr(owner, "_mark_observed", None)
            if callable(mark_observed):
                mark_observed()
        if contract.invalidates_observation:
            mark_mutated = getattr(owner, "_mark_mutated", None)
            if callable(mark_mutated):
                mark_mutated()


def _validate_target_shape(
    contract: BrowserAPIContract,
    target: Any,
) -> None:
    if not isinstance(target, dict):
        _raise_target_invalid(contract, target)
    keys = set(target)
    if not keys:
        _raise_target_invalid(contract, target)
    if not keys <= {"ref", "role", "name", "text", "x", "y"}:
        _raise_target_invalid(contract, target)
    methods = _target_methods(target)
    allowed = set(contract.target.methods if contract.target else ())
    if len(methods) != 1 or not methods <= allowed:
        _raise_target_invalid(contract, target)
    method = next(iter(methods))
    allowed_keys = {
        "ref": {"ref"},
        "role_name": {"role", "name"},
        "text_exact": {"text"},
        "coords": {"x", "y"},
    }[method]
    if keys != allowed_keys:
        _raise_target_invalid(contract, target)


def _validate_target_resolution(
    contract: BrowserAPIContract,
    target: dict[str, Any],
    owner: Any | None,
) -> None:
    observation = _latest_observation(owner)
    if observation is None:
        return
    targets = tuple(getattr(observation, "targets", ()) or ())
    if not targets:
        return
    methods = _target_methods(target)
    method = next(iter(methods))
    if method == "ref":
        _validate_ref_target(contract, target, observation, targets)
    elif method == "text_exact":
        _validate_exact_matches(
            contract,
            method,
            target,
            targets,
            lambda candidate: getattr(candidate, "text", "") == target["text"],
        )
    elif method == "role_name":
        _validate_exact_matches(
            contract,
            method,
            target,
            targets,
            lambda candidate: (
                getattr(candidate, "role", "") == target["role"]
                and getattr(candidate, "name", "") == target["name"]
            ),
        )


def _latest_observation(owner: Any | None) -> Any | None:
    if owner is None:
        return None
    for name in ("_last_observation", "last_observation"):
        observation = getattr(owner, name, None)
        if observation is not None:
            return observation
    return None


def _validate_ref_target(
    contract: BrowserAPIContract,
    target: dict[str, Any],
    observation: Any,
    candidates: tuple[Any, ...],
) -> None:
    ref = str(target["ref"])
    refs = getattr(observation, "refs", {}) or {}
    if ref in refs:
        return
    raise BrowserTargetResolutionError(
        "Target ref is not present in the latest Browser observation.",
        code="stale_observation",
        action=contract.api_id,
        metadata={
            "api_id": contract.api_id,
            "target_method": "ref",
            "requested_ref": ref,
            "fallback": "none",
            "candidates": _candidate_payloads(candidates),
        },
    )


def _validate_exact_matches(
    contract: BrowserAPIContract,
    method: str,
    target: dict[str, Any],
    candidates: tuple[Any, ...],
    predicate: Callable[[Any], bool],
) -> None:
    matches = tuple(
        candidate for candidate in candidates if predicate(candidate)
    )
    if len(matches) == 1:
        return
    if not matches:
        raise BrowserTargetResolutionError(
            "Target did not match any candidate in the latest observation.",
            code="target_not_found",
            action=contract.api_id,
            metadata={
                "api_id": contract.api_id,
                "target_method": method,
                "target": target,
                "fallback": "none",
                "candidates": _candidate_payloads(candidates),
            },
        )
    raise BrowserTargetResolutionError(
        "Target matched multiple candidates in the latest observation.",
        code="target_ambiguous",
        action=contract.api_id,
        metadata={
            "api_id": contract.api_id,
            "target_method": method,
            "target": target,
            "fallback": "none",
            "matches": _candidate_payloads(matches),
        },
    )


def _candidate_payloads(candidates: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [_candidate_payload(candidate) for candidate in candidates]


def _candidate_payload(candidate: Any) -> dict[str, Any]:
    bounds = getattr(candidate, "bounds", None)
    return {
        "ref": str(getattr(candidate, "ref", "") or ""),
        "role": str(getattr(candidate, "role", "") or ""),
        "name": str(getattr(candidate, "name", "") or ""),
        "text": str(getattr(candidate, "text", "") or ""),
        "bounds": dict(bounds) if isinstance(bounds, dict) else None,
        "source": str(getattr(candidate, "source", "") or "snapshot"),
    }


def _target_methods(target: dict[str, Any]) -> set[str]:
    methods: set[str] = set()
    if _has_text(target.get("ref")):
        methods.add("ref")
    if _has_text(target.get("role")) and _has_text(target.get("name")):
        methods.add("role_name")
    elif "role" in target or "name" in target:
        methods.add("incomplete_role_name")
    if _has_text(target.get("text")):
        methods.add("text_exact")
    if target.get("x") is not None and target.get("y") is not None:
        methods.add("coords")
    elif "x" in target or "y" in target:
        methods.add("incomplete_coords")
    return methods


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def _raise_target_invalid(
    contract: BrowserAPIContract,
    target: Any,
) -> None:
    raise BrowserSDKError(
        "Browser action target must use exactly one supported dict shape.",
        code="target_invalid",
        action=contract.api_id,
        metadata={
            "api_id": contract.api_id,
            "target": target,
            "allowed_methods": (
                list(contract.target.methods) if contract.target else []
            ),
            "allowed_shapes": (
                {"ref": "e42"},
                {"role": "button", "name": "Submit"},
                {"text": "Submit"},
                {"x": 120, "y": 300},
            ),
        },
    )


__all__ = ["BrowserContractRuntime"]
