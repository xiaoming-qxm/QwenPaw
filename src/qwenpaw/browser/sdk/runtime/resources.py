# -*- coding: utf-8 -*-
"""Task-owned output resources with atomic publication and cleanup."""

from __future__ import annotations

import builtins
import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from uuid import uuid4

from qwenpaw.constant import WORKING_DIR

from ..canonical.contracts import (
    CleanupInfo,
    Notice,
    ResourceHandle,
    _RUNTIME_VALUE_ISSUER,
    _issue_opaque_value,
)
from ..governance.errors import BrowserSDKError


class ResourceStoreError(BrowserSDKError):
    """Closed resource-store failure."""

    code = "resource_store_error"


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_item_bytes: int
    max_task_bytes: int
    max_items: int

    def __post_init__(self) -> None:
        if min(self.max_item_bytes, self.max_task_bytes, self.max_items) <= 0:
            raise ValueError("resource limits must be positive")


@dataclass(frozen=True, slots=True)
class TrustedOutputSource:
    """Private complete-or-partial byte source accepted from producers."""

    _chunks: tuple[bytes, ...]
    complete: bool

    @classmethod
    def from_bytes(cls, data: bytes) -> "TrustedOutputSource":
        return cls((bytes(data),), True)

    @classmethod
    def from_chunks(
        cls,
        chunks: tuple[bytes, ...],
        *,
        complete: bool,
    ) -> "TrustedOutputSource":
        return cls(tuple(bytes(chunk) for chunk in chunks), complete)

    @classmethod
    def from_file(cls, location: Path) -> "TrustedOutputSource":
        return cls((location.read_bytes(),), True)

    def iter_chunks(self) -> tuple[bytes, ...]:
        """Return immutable chunks to the trusted store writer."""
        return self._chunks


@dataclass(slots=True)
class _StoredResource:
    handle: ResourceHandle
    owner_key: tuple[str, str]
    store_root: Path
    location: Path
    required_delivery: bool
    promoted: bool = False


_RESOURCE_INDEX: dict[str, _StoredResource] = {}
_RESOURCE_STORES: dict[tuple[str, str], "ResourceStore"] = {}


class ResourceStore:
    """Own output resources for exactly one root-task Browser owner."""

    def __init__(
        self,
        *,
        owner_key: tuple[str, str],
        limits: ResourceLimits,
        storage_root: Path,
        ttl_seconds: float = 3600.0,
        clock: Callable[[], datetime] | None = None,
        unlink: Callable[[Path], None] | None = None,
    ) -> None:
        if not all(str(value).strip() for value in owner_key):
            raise ValueError("resource owner key is required")
        if ttl_seconds <= 0:
            raise ValueError("resource TTL must be positive")
        self.owner_key = owner_key
        self.limits = limits
        self.storage_root = Path(storage_root).resolve()
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._unlink = unlink or self._default_unlink
        self._transient_dir = self.storage_root / "transient"
        self._promoted_dir = self.storage_root / "promoted"

    async def ingest_output(
        self,
        source: TrustedOutputSource,
        *,
        media_type: str,
        name: str,
        required_delivery: bool,
    ) -> ResourceHandle:
        """Validate a complete source before atomically publishing a handle."""
        if not isinstance(source, TrustedOutputSource):
            raise ResourceStoreError(
                "untrusted resource source",
                code="resource_source_untrusted",
            )
        current = self._owned_resources()
        if len(current) >= self.limits.max_items:
            raise ResourceStoreError(
                "resource count limit exceeded",
                code="resource_count_limit",
            )
        self._transient_dir.mkdir(parents=True, exist_ok=True)
        resource_id = f"resource-{uuid4().hex}"
        partial = self._transient_dir / f"{resource_id}.part"
        final = self._transient_dir / resource_id
        digest = hashlib.sha256()
        size = 0
        try:
            with partial.open("xb") as stream:
                for chunk in source.iter_chunks():
                    size += len(chunk)
                    if size > self.limits.max_item_bytes:
                        raise ResourceStoreError(
                            "resource item limit exceeded",
                            code="resource_item_limit",
                        )
                    stream.write(chunk)
                    digest.update(chunk)
            if not source.complete:
                raise ResourceStoreError(
                    "resource source is incomplete",
                    code="resource_incomplete",
                )
            if self._owned_bytes() + size > self.limits.max_task_bytes:
                raise ResourceStoreError(
                    "resource task limit exceeded",
                    code="resource_task_limit",
                )
            os.replace(partial, final)
        except BaseException:
            self._default_unlink(partial)
            raise
        expires_at = self._clock() + timedelta(seconds=self.ttl_seconds)
        handle = _issue_opaque_value(
            ResourceHandle,
            _RUNTIME_VALUE_ISSUER,
            id=resource_id,
            media_type=media_type,
            name=name,
            size=size,
            sha256=digest.hexdigest(),
            expires_at=expires_at,
        )
        assert isinstance(handle, ResourceHandle)
        _RESOURCE_INDEX[resource_id] = _StoredResource(
            handle=handle,
            owner_key=self.owner_key,
            store_root=self.storage_root,
            location=final,
            required_delivery=required_delivery,
        )
        return handle

    def list(self) -> list[ResourceHandle]:
        """List non-expired resources belonging to this exact owner."""
        handles: list[ResourceHandle] = []
        for stored in self._owned_resources():
            try:
                handles.append(self.require(str(stored.handle.id)))
            except ResourceStoreError as exc:
                if exc.code != "resource_expired":
                    raise
        return handles

    def require(self, resource_id: str) -> ResourceHandle:
        """Return a current owner-scoped handle or a typed error."""
        stored = _RESOURCE_INDEX.get(resource_id)
        if stored is None or stored.store_root != self.storage_root:
            raise ResourceStoreError(
                "resource is unavailable",
                code="resource_unavailable",
            )
        if stored.owner_key != self.owner_key:
            raise ResourceStoreError(
                "resource belongs to another owner",
                code="resource_owner_mismatch",
            )
        if stored.handle.expires_at <= self._clock():
            self._default_unlink(stored.location)
            _RESOURCE_INDEX.pop(resource_id, None)
            raise ResourceStoreError(
                "resource has expired",
                code="resource_expired",
            )
        if not stored.location.is_file():
            _RESOURCE_INDEX.pop(resource_id, None)
            raise ResourceStoreError(
                "resource bytes are unavailable",
                code="resource_unavailable",
            )
        return stored.handle

    async def promote_required(
        self,
        handles: tuple[ResourceHandle, ...],
    ) -> None:
        """Atomically move required complete resources to durable storage."""
        self._promoted_dir.mkdir(parents=True, exist_ok=True)
        for handle in handles:
            current = self.require(str(handle.id))
            stored = _RESOURCE_INDEX[str(current.id)]
            if not stored.required_delivery:
                raise ResourceStoreError(
                    "resource was not declared required",
                    code="resource_not_required",
                )
            destination = self._promoted_dir / str(current.id)
            os.replace(stored.location, destination)
            stored.location = destination
            stored.promoted = True

    async def cleanup_transient(self) -> CleanupInfo:
        """Physically delete optional/transient resources for this owner."""
        warnings: list[Notice] = []
        for stored in self._owned_resources():
            if stored.promoted:
                continue
            try:
                self._unlink(stored.location)
            except OSError:
                warnings.append(
                    Notice(
                        code="resource_cleanup_failed",
                        safe_message=(
                            "A transient Browser resource could not "
                            "be removed."
                        ),
                    ),
                )
                continue
            _RESOURCE_INDEX.pop(str(stored.handle.id), None)
        return CleanupInfo(complete=not warnings, warnings=tuple(warnings))

    def _owned_resources(self) -> builtins.list[_StoredResource]:
        return [
            stored
            for stored in _RESOURCE_INDEX.values()
            if stored.owner_key == self.owner_key
            and stored.store_root == self.storage_root
        ]

    def _owned_bytes(self) -> int:
        return sum(
            int(stored.handle.size) for stored in self._owned_resources()
        )

    @staticmethod
    def _default_unlink(location: Path) -> None:
        location.unlink(missing_ok=True)


def get_or_create_resource_store(
    owner_key: tuple[str, str],
) -> ResourceStore:
    """Return the sole process store for a trusted Browser owner."""
    store = _RESOURCE_STORES.get(owner_key)
    if store is None:
        owner_digest = hashlib.sha256(
            "://".join(owner_key).encode(),
        ).hexdigest()
        store = ResourceStore(
            owner_key=owner_key,
            limits=ResourceLimits(
                max_item_bytes=20 * 1024 * 1024,
                max_task_bytes=100 * 1024 * 1024,
                max_items=32,
            ),
            storage_root=(
                WORKING_DIR / "browser" / "resources" / owner_digest
            ),
        )
        _RESOURCE_STORES[owner_key] = store
    return store


async def cleanup_resource_store(owner_key: tuple[str, str]) -> CleanupInfo:
    """Cleanup transient resources and forget the terminal owner store."""
    store = _RESOURCE_STORES.pop(owner_key, None)
    if store is None:
        return CleanupInfo()
    return await store.cleanup_transient()


__all__ = [
    "ResourceLimits",
    "ResourceStore",
    "ResourceStoreError",
    "TrustedOutputSource",
    "cleanup_resource_store",
    "get_or_create_resource_store",
]
