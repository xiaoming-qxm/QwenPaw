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


__all__ = ["BrowserContractRuntime"]
