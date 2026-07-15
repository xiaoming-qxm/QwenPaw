# -*- coding: utf-8 -*-
"""Task-owned output resources with atomic publication and cleanup."""

from __future__ import annotations

import builtins
import hashlib
import mimetypes
import os
import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from qwenpaw.constant import WORKING_DIR

from ..api.contracts import (
    CleanupInfo,
    ContextVersion,
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
class ScreenshotInvariant:
    """Controller-owned pre/post facts around one native image capture."""

    generation: str
    scroll_offset: tuple[float, float]
    focused_backend_node: int | None
    viewport: tuple[int, int]
    layout: tuple[int, int]
    event_watermark: int
    zoom: float = 1.0
    device_pixel_ratio: float = 1.0


@dataclass(frozen=True, slots=True)
class ScreenshotCapture:
    """Complete private image bytes plus non-mutation evidence."""

    scope: Literal["viewport", "full_page"]
    data: bytes
    media_type: str
    name: str
    width: int
    height: int
    complete: bool
    before: ScreenshotInvariant
    after: ScreenshotInvariant

    @property
    def invariant_unchanged(self) -> bool:
        return self.before == self.after


@dataclass(frozen=True, slots=True)
class DownloadCapture:
    """Private complete bytes correlated to one armed download command."""

    data: bytes
    media_type: str
    name: str
    complete: bool
    native_guid: str
    operation_id: str
    operation_fingerprint: str
    command_id: str
    owner_key: tuple[str, str]
    tab_id: str
    pre_arm_watermark: int

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("download capture bytes are required")
        if not self.complete:
            raise ValueError("download capture must be complete")
        if not all(
            (
                self.media_type,
                self.name,
                self.native_guid,
                self.operation_id,
                self.operation_fingerprint,
                self.command_id,
                self.tab_id,
            ),
        ):
            raise ValueError("download capture correlation is incomplete")
        if (
            not isinstance(self.owner_key, tuple)
            or len(self.owner_key) != 2
            or not all(self.owner_key)
        ):
            raise ValueError("download capture owner is invalid")
        if self.pre_arm_watermark < 0:
            raise ValueError("download capture watermark is invalid")


@dataclass(frozen=True, slots=True)
class PagePdfCapture:
    """Private complete PDF bytes bound to one receiver context."""

    data: bytes
    context_before: ContextVersion
    context_after: ContextVersion
    complete: bool
    operation_id: str
    operation_fingerprint: str
    command_id: str
    owner_key: tuple[str, str]
    tab_id: str
    pre_arm_watermark: int

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("page PDF bytes are required")
        if not self.complete:
            raise ValueError("page PDF capture must be complete")
        if not isinstance(
            self.context_before,
            ContextVersion,
        ) or not isinstance(
            self.context_after,
            ContextVersion,
        ):
            raise TypeError("page PDF contexts must be runtime-issued")
        if not all(
            (
                self.operation_id,
                self.operation_fingerprint,
                self.command_id,
                self.tab_id,
            ),
        ):
            raise ValueError("page PDF correlation is incomplete")
        if (
            not isinstance(self.owner_key, tuple)
            or len(self.owner_key) != 2
            or not all(self.owner_key)
            or self.pre_arm_watermark < 0
        ):
            raise ValueError("page PDF operation binding is invalid")


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
    creation_key: tuple[object, ...] | None = None
    native_guid: str = ""


_RESOURCE_INDEX: dict[str, _StoredResource] = {}
_RESOURCE_STORES: dict[tuple[str, str], "ResourceStore"] = {}


def _operation_creation_key(operation: object) -> tuple[object, ...]:
    values = (
        getattr(operation, "operation_id", ""),
        getattr(operation, "operation_fingerprint", ""),
        getattr(operation, "command_id", ""),
        getattr(operation, "owner_key", None),
        getattr(operation, "tab_id", ""),
        getattr(operation, "pre_arm_watermark", None),
    )
    if (
        not all(values[:5])
        or not isinstance(values[3], tuple)
        or not isinstance(values[5], int)
        or values[5] < 0
    ):
        raise ResourceStoreError(
            "resource operation binding is incomplete",
            code="resource_operation_binding_invalid",
        )
    return values


class ResourceStore:
    """Own output resources for exactly one root-task Browser owner."""

    def __init__(
        self,
        *,
        owner_key: tuple[str, str],
        limits: ResourceLimits,
        storage_root: Path,
        workspace_root: Path | None = None,
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
        self.workspace_root = Path(
            workspace_root if workspace_root is not None else storage_root,
        ).resolve()
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
        return self._publish_source(
            source,
            media_type=media_type,
            name=name,
            required_delivery=required_delivery,
        )

    async def ingest_correlated_download(
        self,
        capture: DownloadCapture,
        operation: object,
    ) -> ResourceHandle:
        """Atomically publish only one exact operation-correlated capture."""
        if not isinstance(capture, DownloadCapture):
            raise ResourceStoreError(
                "download capture is invalid",
                code="download_capture_invalid",
            )
        expected = _operation_creation_key(operation)
        actual = (
            capture.operation_id,
            capture.operation_fingerprint,
            capture.command_id,
            capture.owner_key,
            capture.tab_id,
            capture.pre_arm_watermark,
        )
        if expected != actual or capture.owner_key != self.owner_key:
            raise ResourceStoreError(
                "download correlation mismatch",
                code="download_correlation_mismatch",
            )
        handle = await self.ingest_output(
            TrustedOutputSource.from_bytes(capture.data),
            media_type=capture.media_type,
            name=capture.name,
            required_delivery=True,
        )
        stored = _RESOURCE_INDEX[str(handle.id)]
        _RESOURCE_INDEX[str(handle.id)] = replace(
            stored,
            creation_key=expected,
            native_guid=capture.native_guid,
        )
        return handle

    async def ingest_correlated_page_pdf(
        self,
        capture: PagePdfCapture,
        operation: object,
    ) -> ResourceHandle:
        """Atomically publish one exact context-bound PDF capture."""
        if not isinstance(capture, PagePdfCapture):
            raise ResourceStoreError(
                "page PDF capture is invalid",
                code="page_pdf_capture_invalid",
            )
        expected = _operation_creation_key(operation)
        actual = (
            capture.operation_id,
            capture.operation_fingerprint,
            capture.command_id,
            capture.owner_key,
            capture.tab_id,
            capture.pre_arm_watermark,
        )
        if expected != actual or capture.owner_key != self.owner_key:
            raise ResourceStoreError(
                "page PDF correlation mismatch",
                code="page_pdf_correlation_mismatch",
            )
        handle = await self.ingest_output(
            TrustedOutputSource.from_bytes(capture.data),
            media_type="application/pdf",
            name="page.pdf",
            required_delivery=True,
        )
        stored = _RESOURCE_INDEX[str(handle.id)]
        _RESOURCE_INDEX[str(handle.id)] = replace(
            stored,
            creation_key=expected,
            native_guid="page_pdf",
        )
        return handle

    def created_for(self, operation: object) -> tuple[ResourceHandle, ...]:
        """Return fresh complete resources for one exact private binding."""
        expected = _operation_creation_key(operation)
        handles: list[ResourceHandle] = []
        for stored in self._owned_resources():
            if stored.creation_key != expected or not stored.native_guid:
                continue
            handles.append(self.require(str(stored.handle.id)))
        return tuple(handles)

    def ingest_workspace_file(self, path: str) -> ResourceHandle:
        """Synchronously ingest one authorized file below the workspace."""
        if not isinstance(path, str) or not path.strip():
            raise ResourceStoreError(
                "workspace resource path is invalid",
                code="resource_workspace_path_invalid",
            )
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.workspace_root)
        except (OSError, ValueError) as exc:
            raise ResourceStoreError(
                "workspace resource is outside the authorized root",
                code="resource_workspace_escape",
            ) from exc
        if not _authorize_workspace_file(resolved):
            raise ResourceStoreError(
                "workspace resource access was denied",
                code="resource_workspace_denied",
            )
        return self._ingest_authorized_file(
            resolved,
            name=resolved.name,
            media_type=None,
        )

    def ingest_trusted_attachment(
        self,
        location: Path,
        *,
        name: str,
        media_type: str | None,
    ) -> ResourceHandle:
        """Ingest a host-issued inbound attachment descriptor."""
        try:
            resolved = Path(location).resolve(strict=True)
        except OSError as exc:
            raise ResourceStoreError(
                "trusted attachment is unavailable",
                code="resource_unavailable",
            ) from exc
        if not _authorize_workspace_file(resolved):
            raise ResourceStoreError(
                "trusted attachment access was denied",
                code="resource_workspace_denied",
            )
        return self._ingest_authorized_file(
            resolved,
            name=name,
            media_type=media_type,
        )

    def _ingest_authorized_file(
        self,
        location: Path,
        *,
        name: str,
        media_type: str | None,
    ) -> ResourceHandle:
        try:
            if not location.is_file():
                raise ResourceStoreError(
                    "resource source is not a regular file",
                    code="resource_source_invalid",
                )
            source = TrustedOutputSource.from_file(location)
        except OSError as exc:
            raise ResourceStoreError(
                "resource source could not be read",
                code="resource_unavailable",
            ) from exc
        safe_name = _safe_resource_name(name)
        safe_media_type = _safe_media_type(media_type, safe_name)
        return self._publish_source(
            source,
            media_type=safe_media_type,
            name=safe_name,
            required_delivery=False,
        )

    def _publish_source(
        self,
        source: TrustedOutputSource,
        *,
        media_type: str,
        name: str,
        required_delivery: bool,
    ) -> ResourceHandle:
        """Publish one already trusted complete source atomically."""
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
        if not isinstance(resource_id, str) or not resource_id:
            raise ResourceStoreError(
                "resource id is invalid",
                code="resource_id_invalid",
            )
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
        try:
            digest = hashlib.sha256()
            size = 0
            with stored.location.open("rb") as stream:
                for chunk in iter(lambda: stream.read(64 * 1024), b""):
                    size += len(chunk)
                    digest.update(chunk)
        except OSError as exc:
            raise ResourceStoreError(
                "resource bytes are unavailable",
                code="resource_unavailable",
            ) from exc
        if (
            size != stored.handle.size
            or digest.hexdigest() != stored.handle.sha256
        ):
            self._default_unlink(stored.location)
            _RESOURCE_INDEX.pop(resource_id, None)
            raise ResourceStoreError(
                "resource integrity validation failed",
                code="resource_integrity_mismatch",
            )
        return stored.handle

    def _resolve_for_dispatch(self, handle: ResourceHandle) -> Path:
        """Resolve a private locator only after fresh exact validation."""
        if not isinstance(handle, ResourceHandle):
            raise ResourceStoreError(
                "upload resource is invalid",
                code="resource_type_invalid",
            )
        current = self.require(str(handle.id))
        if current is not handle:
            raise ResourceStoreError(
                "upload resource binding is invalid",
                code="resource_binding_invalid",
            )
        return _RESOURCE_INDEX[str(current.id)].location

    def resolve_upload_paths(
        self,
        handles: tuple[ResourceHandle, ...],
    ) -> tuple[str, ...]:
        """Resolve an exact validated upload group for the trusted adapter."""
        return tuple(
            str(self._resolve_for_dispatch(handle)) for handle in handles
        )

    async def promote_required(
        self,
        handles: tuple[ResourceHandle, ...],
    ) -> None:
        """Atomically move required complete resources to durable storage."""
        if not handles:
            raise ResourceStoreError(
                "required resource group is empty",
                code="resource_promotion_empty",
            )
        prepared: list[tuple[_StoredResource, Path, Path]] = []
        seen: set[str] = set()
        for handle in handles:
            current = self.require(str(handle.id))
            if current is not handle or str(current.id) in seen:
                raise ResourceStoreError(
                    "required resource group is invalid",
                    code="resource_promotion_binding_invalid",
                )
            seen.add(str(current.id))
            stored = _RESOURCE_INDEX[str(current.id)]
            if not stored.required_delivery:
                raise ResourceStoreError(
                    "resource was not declared required",
                    code="resource_not_required",
                )
            if stored.promoted:
                continue
            prepared.append(
                (
                    stored,
                    stored.location,
                    self._promoted_dir / str(current.id),
                ),
            )
        self._promoted_dir.mkdir(parents=True, exist_ok=True)
        moved: list[tuple[_StoredResource, Path, Path]] = []
        try:
            for stored, source, destination in prepared:
                os.replace(source, destination)
                moved.append((stored, source, destination))
        except OSError as exc:
            rollback_failed = False
            for _, source, destination in reversed(moved):
                try:
                    os.replace(destination, source)
                except OSError:
                    rollback_failed = True
            raise ResourceStoreError(
                (
                    "required resource promotion failed"
                    if not rollback_failed
                    else "required resource promotion rollback failed"
                ),
                code=(
                    "resource_promotion_failed"
                    if not rollback_failed
                    else "resource_promotion_rollback_failed"
                ),
            ) from exc
        for stored, _, destination in prepared:
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
            workspace_root=WORKING_DIR,
        )
        _RESOURCE_STORES[owner_key] = store
    return store


async def cleanup_resource_store(owner_key: tuple[str, str]) -> CleanupInfo:
    """Cleanup transient resources and forget the terminal owner store."""
    store = _RESOURCE_STORES.pop(owner_key, None)
    if store is None:
        return CleanupInfo()
    return await store.cleanup_transient()


async def cleanup_expired_promoted_resources(
    *,
    now: datetime | None = None,
    unlink: Callable[[Path], None] | None = None,
) -> CleanupInfo:
    """Delete expired promoted artifacts and report physical failures."""
    current = now or datetime.now(UTC)
    remove = unlink or (lambda location: location.unlink(missing_ok=True))
    warnings: list[Notice] = []
    for resource_id, stored in list(_RESOURCE_INDEX.items()):
        if not stored.promoted or stored.handle.expires_at > current:
            continue
        try:
            remove(stored.location)
        except OSError:
            warnings.append(
                Notice(
                    code="resource_cleanup_failed",
                    safe_message=(
                        "An expired Browser artifact could not be removed."
                    ),
                ),
            )
            continue
        _RESOURCE_INDEX.pop(resource_id, None)
    return CleanupInfo(complete=not warnings, warnings=tuple(warnings))


def resolve_promoted_bytes(
    resource_id: str,
    *,
    owner_key: tuple[str, str],
    now: datetime | None = None,
) -> bytes:
    """Resolve a promoted artifact by controlled identity until expiry."""
    stored = _RESOURCE_INDEX.get(str(resource_id))
    if stored is None or not stored.promoted or stored.owner_key != owner_key:
        raise ResourceStoreError(
            "promoted resource is unavailable",
            code="resource_unavailable",
        )
    current = now or datetime.now(UTC)
    if stored.handle.expires_at <= current:
        try:
            stored.location.unlink(missing_ok=True)
        except OSError as exc:
            raise ResourceStoreError(
                "promoted resource expiry cleanup failed",
                code="resource_cleanup_failed",
            ) from exc
        _RESOURCE_INDEX.pop(str(resource_id), None)
        raise ResourceStoreError(
            "promoted resource has expired",
            code="resource_expired",
        )
    try:
        data = stored.location.read_bytes()
    except OSError as exc:
        raise ResourceStoreError(
            "promoted resource is unavailable",
            code="resource_unavailable",
        ) from exc
    if (
        len(data) != stored.handle.size
        or hashlib.sha256(data).hexdigest() != stored.handle.sha256
    ):
        raise ResourceStoreError(
            "promoted resource integrity validation failed",
            code="resource_integrity_mismatch",
        )
    return data


def resolve_promoted_handle_bytes(handle: ResourceHandle) -> bytes:
    """Resolve one exact promoted runtime handle without exposing a path."""
    if not isinstance(handle, ResourceHandle):
        raise ResourceStoreError(
            "promoted resource handle is invalid",
            code="resource_type_invalid",
        )
    stored = _RESOURCE_INDEX.get(str(handle.id))
    if stored is None or stored.handle is not handle:
        raise ResourceStoreError(
            "promoted resource binding is invalid",
            code="resource_binding_invalid",
        )
    return resolve_promoted_bytes(
        str(handle.id),
        owner_key=stored.owner_key,
    )


def _authorize_workspace_file(location: Path) -> bool:
    """Run always-on ToolGuard path checks before opening file bytes."""
    from qwenpaw.security.tool_guard.engine import get_guard_engine

    engine = get_guard_engine()
    result = engine.guard(
        "browser.resources.from_workspace",
        {"path": str(location)},
        only_always_run=True,
    )
    return result is None or (result.is_safe and not result.guardians_failed)


def _safe_resource_name(name: str) -> str:
    normalized = unicodedata.normalize("NFC", str(name or ""))
    safe = " ".join(Path(normalized).name.split())[:255]
    return safe or "resource.bin"


def _safe_media_type(media_type: str | None, name: str) -> str:
    candidate = str(media_type or "").strip().lower()
    if "/" in candidate and all(char.isprintable() for char in candidate):
        return candidate[:127]
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


__all__ = [
    "ResourceLimits",
    "ResourceStore",
    "ResourceStoreError",
    "ScreenshotCapture",
    "ScreenshotInvariant",
    "TrustedOutputSource",
    "cleanup_resource_store",
    "get_or_create_resource_store",
]
