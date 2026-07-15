# -*- coding: utf-8 -*-
"""Trusted outer seam for issuing Browser root-task bindings."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ..browser.runtime.session_owner import (
    BrowserRequestBinding,
    BrowserSessionOwnerRegistry,
    ResumeToken,
    RootTaskOutcome,
)


@dataclass(slots=True)
class RootRequestControl:
    """Narrow control object containing only registry-issued identity."""

    binding: BrowserRequestBinding
    _disposition: TrustedRootDisposition | None = None
    _released: bool = False
    resume_token: ResumeToken | None = None

    def retain(self, disposition: TrustedRootDisposition) -> None:
        """Accept a trusted Python-only retained disposition once."""
        if self._disposition is not None:
            raise RuntimeError("root_disposition_already_set")
        self._disposition = disposition

    @property
    def disposition(self) -> TrustedRootDisposition | None:
        """Return the trusted outer disposition, if one was selected."""
        return self._disposition

    async def release_request(self) -> None:
        """Release the current request lease exactly once."""
        if self._released:
            return
        await _OWNER_REGISTRY.release_request_lease(self.binding)
        self._released = True


@dataclass(frozen=True, slots=True)
class TrustedRootDisposition:
    """Python-only retained result selected by a trusted callsite."""

    outcome: RootTaskOutcome
    reason: str
    ttl_seconds: float

    def __post_init__(self) -> None:
        if self.outcome not in {
            RootTaskOutcome.HANDOFF,
            RootTaskOutcome.RETAINED_PROMPT,
            RootTaskOutcome.RETAINED_UNCERTAIN,
        }:
            raise ValueError("trusted disposition must be retained")
        if self.ttl_seconds <= 0:
            raise ValueError("trusted disposition TTL must be positive")


_EVENT_ISSUER = object()


@dataclass(frozen=True, slots=True, init=False)
class RootTaskLifecycleEvent:
    """Module-issued lifecycle fact applied after Runtime FINALLY."""

    binding: BrowserRequestBinding
    outcome: RootTaskOutcome
    reason: str

    def __init__(
        self,
        binding: BrowserRequestBinding,
        outcome: RootTaskOutcome,
        reason: str,
        *,
        _issuer: object,
    ) -> None:
        if _issuer is not _EVENT_ISSUER:
            raise TypeError("RootTaskLifecycleEvent is module-issued")
        object.__setattr__(self, "binding", binding)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "reason", reason)


_OWNER_REGISTRY = BrowserSessionOwnerRegistry()
_RETAINED_BINDINGS: dict[tuple[str, str], BrowserRequestBinding] = {}


async def run_root_request(
    runtime: Any,
    request: object,
    *,
    trusted_root_session_id: str,
    inherited_binding: BrowserRequestBinding | None = None,
    resume_token: str | None = None,
) -> AsyncIterator[object]:
    """Issue trusted identity outside Runtime and stream one request."""
    binding = await _OWNER_REGISTRY.begin_request(
        root_session_id=trusted_root_session_id,
        source=(
            "resume"
            if resume_token is not None
            else "continuation"
            if inherited_binding is not None
            else "user"
        ),
        resume_token=resume_token,
        inherited_binding=inherited_binding,
    )
    control = RootRequestControl(binding=binding)
    outcome = RootTaskOutcome.COMPLETE
    reason = "complete"
    try:
        async for item in runtime.run(request, trusted_root=control):
            yield item
    except asyncio.CancelledError:
        outcome = RootTaskOutcome.CANCELLED
        reason = "cancelled"
        raise
    except BaseException:
        outcome = RootTaskOutcome.FAILED
        reason = "failed"
        raise
    finally:
        await control.release_request()
        if control.disposition is not None:
            outcome = control.disposition.outcome
            reason = control.disposition.reason
        event = _issue_lifecycle_event(control.binding, outcome, reason)
        await _apply_lifecycle_event(event, control=control)


def _issue_lifecycle_event(
    binding: BrowserRequestBinding,
    outcome: RootTaskOutcome,
    reason: str,
) -> RootTaskLifecycleEvent:
    return RootTaskLifecycleEvent(
        binding,
        outcome,
        reason,
        _issuer=_EVENT_ISSUER,
    )


async def _apply_lifecycle_event(
    event: RootTaskLifecycleEvent,
    *,
    control: RootRequestControl,
) -> None:
    disposition = control.disposition
    if disposition is not None:
        reacquired = await _OWNER_REGISTRY.begin_request(
            root_session_id=event.binding.root_session_id,
            source="retained",
            inherited_binding=event.binding,
        )
        control.binding = reacquired
        control.resume_token = await _OWNER_REGISTRY.retain(
            reacquired,
            reason=disposition.reason,
            ttl_seconds=disposition.ttl_seconds,
        )
        _RETAINED_BINDINGS[control.binding.owner_key] = control.binding
        return
    _RETAINED_BINDINGS.pop(event.binding.owner_key, None)
    await _cleanup_root_owner(event.binding, reason=event.reason)
    await _OWNER_REGISTRY.finish_root_task(event.binding, event.outcome)


async def _cleanup_root_owner(
    binding: BrowserRequestBinding,
    *,
    reason: str,
) -> None:
    from ..browser.backends.registry import (
        cleanup_browser_backend_request_resources,
    )
    from ..browser.runtime.kernel import (
        cleanup_browser_kernels_for_lifecycle,
    )

    await cleanup_browser_backend_request_resources(
        root_session_id=binding.root_session_id,
        holder_id=binding.browser_owner_id,
        owner_id=binding.browser_owner_id,
        root_task_id=binding.root_task_id,
        owner_key=binding.owner_key,
        cleanup_reason=reason,
    )
    await cleanup_browser_kernels_for_lifecycle(
        session_id=binding.root_task_id,
        root_session_id=binding.root_session_id,
        cleanup_reason=reason,
    )


async def sweep_expired_root_tasks() -> tuple[tuple[str, str], ...]:
    """Clean backend state for registry-confirmed retained TTL expiry."""
    expired = await _OWNER_REGISTRY.sweep_expired()
    for owner_key in expired:
        binding = _RETAINED_BINDINGS.pop(owner_key, None)
        if binding is not None:
            await _cleanup_root_owner(binding, reason="retained_expired")
    return expired


__all__ = [
    "RootRequestControl",
    "RootTaskLifecycleEvent",
    "TrustedRootDisposition",
    "run_root_request",
    "sweep_expired_root_tasks",
]
