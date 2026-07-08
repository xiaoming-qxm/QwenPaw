# -*- coding: utf-8 -*-
"""Browser SDK public API metadata contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, TypeVar


F = TypeVar("F", bound=Callable[..., Any])

_BROWSER_API_CONTRACT_ATTR = "__browser_api_contract__"
_BROWSER_API_REGISTRY: dict[str, BrowserAPIContract] = {}
_API_KINDS = frozenset({"primitive", "action", "diagnostic", "lifecycle"})
_VISIBILITIES = frozenset({"default", "internal"})


@dataclass(frozen=True)
class BrowserTargetContract:
    """Target requirements that cannot be derived from Python signatures."""

    required: bool
    methods: tuple[str, ...]
    snapshot_bound: bool

    def as_dict(self) -> dict[str, Any]:
        """Return a stable JSON-ready representation."""
        return {
            "required": self.required,
            "methods": list(self.methods),
            "snapshot_bound": self.snapshot_bound,
        }


@dataclass(frozen=True)
class BrowserAPIContract:
    """Metadata attached to one public Browser SDK callable."""

    api_id: str
    kind: str
    visibility: str
    mutates: bool
    requires_observation: bool
    satisfies_observation: bool
    invalidates_observation: bool
    public_name: str | None = None
    target: BrowserTargetContract | None = None
    backend_op: str | None = None
    callable_path: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return a stable JSON-ready representation."""
        payload: dict[str, Any] = {
            "api_id": self.api_id,
            "kind": self.kind,
            "visibility": self.visibility,
            "mutates": self.mutates,
            "requires_observation": self.requires_observation,
            "satisfies_observation": self.satisfies_observation,
            "invalidates_observation": self.invalidates_observation,
            "callable_path": self.callable_path,
        }
        if self.public_name is not None:
            payload["public_name"] = self.public_name
        if self.target is not None:
            payload["target"] = self.target.as_dict()
        if self.backend_op is not None:
            payload["backend_op"] = self.backend_op
        return payload


def browser_api(
    *,
    kind: str,
    visibility: str = "default",
    mutates: bool,
    requires_observation: bool,
    satisfies_observation: bool,
    invalidates_observation: bool,
    public_name: str | None = None,
    target: BrowserTargetContract | dict[str, Any] | None = None,
    backend_op: str | None = None,
) -> Callable[[F], F]:
    """Attach Browser SDK public API metadata to a callable."""
    _validate_literal("kind", kind, _API_KINDS)
    _validate_literal("visibility", visibility, _VISIBILITIES)
    target_contract = _coerce_target_contract(target)

    def decorate(func: F) -> F:
        api_id = str(public_name or _derive_api_id(func))
        contract = BrowserAPIContract(
            api_id=api_id,
            kind=str(kind),
            visibility=str(visibility),
            mutates=bool(mutates),
            requires_observation=bool(requires_observation),
            satisfies_observation=bool(satisfies_observation),
            invalidates_observation=bool(invalidates_observation),
            public_name=public_name,
            target=target_contract,
            backend_op=backend_op,
            callable_path=_callable_path(func),
        )
        setattr(func, _BROWSER_API_CONTRACT_ATTR, contract)
        _BROWSER_API_REGISTRY[contract.api_id] = contract
        return func

    return decorate


def iter_browser_api_contracts() -> tuple[BrowserAPIContract, ...]:
    """Iterate registered Browser SDK API contracts in stable order."""
    return tuple(
        _BROWSER_API_REGISTRY[api_id]
        for api_id in sorted(_BROWSER_API_REGISTRY)
    )


def _coerce_target_contract(
    target: BrowserTargetContract | dict[str, Any] | None,
) -> BrowserTargetContract | None:
    if target is None or isinstance(target, BrowserTargetContract):
        return target
    return BrowserTargetContract(
        required=bool(target["required"]),
        methods=tuple(str(method) for method in target["methods"]),
        snapshot_bound=bool(target["snapshot_bound"]),
    )


def _validate_literal(
    field_name: str,
    value: str,
    allowed: Iterable[str],
) -> None:
    if value in allowed:
        return
    allowed_text = ", ".join(sorted(allowed))
    raise ValueError(f"{field_name} must be one of: {allowed_text}")


def _derive_api_id(func: Callable[..., Any]) -> str:
    module_parts = [
        part
        for part in str(func.__module__).split(".")
        if part not in {"qwenpaw", "browser", "sdk"}
    ]
    qualname_parts = [
        part
        for part in str(func.__qualname__).split(".")
        if part != "<locals>"
    ]
    return ".".join([*module_parts, *qualname_parts])


def _callable_path(func: Callable[..., Any]) -> str:
    return f"{func.__module__}:{func.__qualname__}"


__all__ = [
    "BrowserAPIContract",
    "BrowserTargetContract",
    "browser_api",
    "iter_browser_api_contracts",
]
