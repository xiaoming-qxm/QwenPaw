# -*- coding: utf-8 -*-
"""In-memory tab lease arbitration for chrome."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

LEASE_TTL_SECONDS = 15.0


@dataclass(frozen=True)
class Lease:
    """A tab lease owned by one QwenPaw instance."""

    tab_id: int
    instance_id: str
    expires_at: float
    version: int


class TabOccupied(RuntimeError):
    """Raised when another instance owns a live tab lease."""


class LeaseExpired(RuntimeError):
    """Raised when no valid lease exists for an operation."""


class LeaseRegistry:
    """Track tab leases across QwenPaw instances."""

    def __init__(
        self,
        ttl: float = LEASE_TTL_SECONDS,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._leases: dict[int, Lease] = {}
        self._versions: dict[int, int] = {}
        self._ttl = ttl
        self._time_fn = time_fn or time.monotonic

    def _is_expired(self, lease: Lease) -> bool:
        return lease.expires_at <= self._time_fn()

    def claim(self, tab_id: int, instance_id: str) -> Lease:
        """Claim a tab for an instance or return its existing live lease."""
        tab_id = int(tab_id)
        current = self._leases.get(tab_id)
        if current is not None and not self._is_expired(current):
            if current.instance_id != instance_id:
                raise TabOccupied(
                    f"Tab {tab_id} held by {current.instance_id}",
                )
            return current

        version = self._versions.get(tab_id, 0) + 1
        self._versions[tab_id] = version
        lease = Lease(
            tab_id=tab_id,
            instance_id=instance_id,
            expires_at=self._time_fn() + self._ttl,
            version=version,
        )
        self._leases[tab_id] = lease
        return lease

    def validate_and_renew(self, tab_id: int, instance_id: str) -> Lease:
        """Validate ownership and renew the current lease TTL."""
        tab_id = int(tab_id)
        current = self._leases.get(tab_id)
        if current is None or self._is_expired(current):
            self._leases.pop(tab_id, None)
            raise LeaseExpired(f"No valid lease for tab {tab_id}")
        if current.instance_id != instance_id:
            raise TabOccupied(f"Tab {tab_id} held by {current.instance_id}")

        renewed = Lease(
            tab_id=current.tab_id,
            instance_id=current.instance_id,
            expires_at=self._time_fn() + self._ttl,
            version=current.version,
        )
        self._leases[tab_id] = renewed
        return renewed

    def release(self, tab_id: int, instance_id: str) -> None:
        """Release a tab lease if owned by the instance."""
        tab_id = int(tab_id)
        current = self._leases.get(tab_id)
        if current is not None and current.instance_id == instance_id:
            self._leases.pop(tab_id, None)

    def release_all(self, instance_id: str) -> None:
        """Release all leases owned by an instance."""
        for tab_id, lease in list(self._leases.items()):
            if lease.instance_id == instance_id:
                self._leases.pop(tab_id, None)

    def owner(self, tab_id: int) -> str | None:
        """Return the owner of a live tab lease, if any."""
        tab_id = int(tab_id)
        current = self._leases.get(tab_id)
        if current is None:
            return None
        if self._is_expired(current):
            self._leases.pop(tab_id, None)
            return None
        return current.instance_id


__all__ = [
    "LEASE_TTL_SECONDS",
    "Lease",
    "LeaseExpired",
    "LeaseRegistry",
    "TabOccupied",
]
