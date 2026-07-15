# -*- coding: utf-8 -*-
"""Owner-bound immutable observation evidence and read collections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Literal
from uuid import uuid4

from ..api.contracts import (
    ContextVersion,
    Coverage,
    CoverageGap,
    EvidenceKind,
    EvidenceMeta,
    EvidenceRef,
    ObservationScope,
    ReadCursor,
    RegionRef,
    RegionScope,
    _issue_opaque_value,
    _RUNTIME_VALUE_ISSUER,
)
from .session_owner import OwnerKey


class ObservationStoreError(RuntimeError):
    """Typed fail-closed observation registry error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True, kw_only=True)
class ImmutableReadCollection:
    """Captured read facts detached from every live browser object."""

    owner_key: OwnerKey
    root_session_id: str
    tab_id: str
    context: ContextVersion
    generation: int
    evidence: EvidenceMeta
    segments: tuple[object, ...]
    expires_at: datetime
    kind: Literal["READ"] = "READ"

    def __post_init__(self) -> None:
        _require_owner_key(self.owner_key)
        if not self.root_session_id.strip() or not self.tab_id.strip():
            raise ValueError("collection session and tab are required")
        if not isinstance(self.context, ContextVersion):
            raise TypeError("collection context must be a ContextVersion")
        if self.generation < 1:
            raise ValueError("collection generation must be positive")
        if not isinstance(self.evidence, EvidenceMeta):
            raise TypeError("collection evidence must be EvidenceMeta")
        if not isinstance(self.segments, tuple):
            raise TypeError("collection segments must be an immutable tuple")
        if self.kind != "READ":
            raise ValueError("unsupported collection kind")


@dataclass(frozen=True, slots=True)
class ReadPage:
    """One immutable page from a previously captured collection."""

    segments: tuple[object, ...]
    next_cursor: ReadCursor | None
    end_of_collection: bool
    evidence: EvidenceMeta


@dataclass(frozen=True, slots=True)
class _CollectionEntry:
    collection_id: str
    collection: ImmutableReadCollection


@dataclass(frozen=True, slots=True)
class _CursorEntry:
    cursor_id: str
    collection_id: str
    offset: int
    owner_key: OwnerKey
    root_session_id: str
    tab_id: str
    context: ContextVersion
    generation: int
    kind: Literal["READ"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _EvidenceEntry:
    evidence_id: str
    owner_key: OwnerKey
    root_session_id: str
    tab_id: str
    context: ContextVersion
    generation: int
    expires_at: datetime
    meta: EvidenceMeta


@dataclass(frozen=True, slots=True)
class _ContextEntry:
    context: ContextVersion
    owner_key: OwnerKey
    root_session_id: str
    tab_id: str
    generation: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RegionBinding:
    """Private exact surface identity behind an opaque RegionRef."""

    ref: RegionRef
    kind: Literal["FRAME", "CONTENT", "OWNER"]
    owner_chain: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RegionEntry:
    region_id: str
    owner_key: OwnerKey
    root_session_id: str
    tab_id: str
    context: ContextVersion
    generation: int
    expires_at: datetime
    binding: RegionBinding
    native_identity: str


_COLLECTIONS: dict[str, _CollectionEntry] = {}
_CURSORS: dict[str, _CursorEntry] = {}
_EVIDENCE: dict[str, _EvidenceEntry] = {}
_REGIONS: dict[str, _RegionEntry] = {}
_CONTEXTS: dict[int, _ContextEntry] = {}


class ObservationStore:
    """Issue and validate observation values for one exact owner surface."""

    def __init__(
        self,
        *,
        owner_key: OwnerKey,
        root_session_id: str,
        tab_id: str,
        context: ContextVersion,
        generation: int,
        ttl_seconds: float = 900.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        _require_owner_key(owner_key)
        if not root_session_id.strip() or not tab_id.strip():
            raise ValueError("observation session and tab are required")
        if not isinstance(context, ContextVersion):
            raise TypeError("context must be a ContextVersion")
        if generation < 1:
            raise ValueError("generation must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.owner_key = owner_key
        self.root_session_id = root_session_id
        self.tab_id = tab_id
        self.context = context
        self.generation = generation
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        _CONTEXTS[id(context)] = _ContextEntry(
            context=context,
            owner_key=owner_key,
            root_session_id=root_session_id,
            tab_id=tab_id,
            generation=generation,
            expires_at=self._clock(),
        )

    def collection_expiry(self) -> datetime:
        """Retain a legacy timestamp; collection validity is state-driven."""
        return self._clock()

    def issue_evidence(
        self,
        *,
        kind: EvidenceKind,
        scope: ObservationScope,
        coverage: Coverage,
        gaps: tuple[CoverageGap, ...],
    ) -> EvidenceMeta:
        """Issue evidence and bind its private registry facts to this store."""
        evidence_id = f"evidence-{uuid4().hex}"
        ref = _issue_opaque_value(
            EvidenceRef,
            _RUNTIME_VALUE_ISSUER,
            id=evidence_id,
        )
        assert isinstance(ref, EvidenceRef)
        captured_at = self._clock()
        meta = EvidenceMeta(
            ref=ref,
            kind=kind,
            context=self.context,
            scope=scope,
            captured_at=captured_at,
            coverage=coverage,
            gaps=gaps,
        )
        _EVIDENCE[evidence_id] = _EvidenceEntry(
            evidence_id=evidence_id,
            owner_key=self.owner_key,
            root_session_id=self.root_session_id,
            tab_id=self.tab_id,
            context=self.context,
            generation=self.generation,
            expires_at=captured_at,
            meta=meta,
        )
        return meta

    def save_collection(
        self,
        collection: ImmutableReadCollection,
    ) -> ReadCursor:
        """Save one immutable collection and issue its first opaque cursor."""
        self._validate_collection_binding(collection)
        collection_id = f"read-collection-{uuid4().hex}"
        _COLLECTIONS[collection_id] = _CollectionEntry(
            collection_id=collection_id,
            collection=collection,
        )
        return self._issue_cursor(collection_id, collection, offset=0)

    def page(self, cursor: ReadCursor, *, limit: int) -> ReadPage:
        """Page a stored tuple without consulting any live browser backend."""
        if limit < 1:
            raise ObservationStoreError("cursor_limit_invalid")
        entry = self._require_cursor(cursor)
        stored = _COLLECTIONS.get(entry.collection_id)
        if stored is None:
            raise ObservationStoreError("cursor_collection_unavailable")
        collection = stored.collection
        end = min(entry.offset + limit, len(collection.segments))
        segments = collection.segments[slice(entry.offset, end)]
        exhausted = end >= len(collection.segments)
        next_cursor = None
        if not exhausted:
            next_cursor = self._issue_cursor(
                entry.collection_id,
                collection,
                offset=end,
            )
        return ReadPage(
            segments=segments,
            next_cursor=next_cursor,
            end_of_collection=exhausted,
            evidence=collection.evidence,
        )

    def require_evidence(self, ref: EvidenceRef) -> EvidenceMeta:
        """Resolve a current evidence value only inside this exact binding."""
        evidence_id = _opaque_id(ref, EvidenceRef, "evidence_unavailable")
        entry = _EVIDENCE.get(evidence_id)
        if entry is None:
            raise ObservationStoreError("evidence_unavailable")
        self._validate_binding(
            owner_key=entry.owner_key,
            root_session_id=entry.root_session_id,
            tab_id=entry.tab_id,
            context=entry.context,
            generation=entry.generation,
            prefix="evidence",
        )
        return entry.meta

    def require_context_baseline(
        self,
        context: ContextVersion,
    ) -> ContextVersion:
        """Validate a prior page context against this exact receiver."""
        if not isinstance(context, ContextVersion):
            raise ObservationStoreError("context_invalid")
        entry = _CONTEXTS.get(id(context))
        if entry is None or entry.context is not context:
            raise ObservationStoreError("context_unavailable")
        if entry.owner_key != self.owner_key:
            raise ObservationStoreError("context_owner_mismatch")
        if entry.root_session_id != self.root_session_id:
            raise ObservationStoreError("context_session_mismatch")
        if entry.tab_id != self.tab_id:
            raise ObservationStoreError("context_tab_mismatch")
        if entry.generation > self.generation:
            raise ObservationStoreError("context_generation_mismatch")
        return entry.context

    def require_region_evidence_baseline(
        self,
        region: RegionRef,
        evidence: EvidenceRef,
    ) -> tuple[RegionBinding, EvidenceMeta]:
        """Validate an exact region/evidence baseline in this document."""
        region_id = _opaque_id(region, RegionRef, "region_unavailable")
        evidence_id = _opaque_id(
            evidence,
            EvidenceRef,
            "evidence_unavailable",
        )
        region_entry = _REGIONS.get(region_id)
        evidence_entry = _EVIDENCE.get(evidence_id)
        if region_entry is None:
            raise ObservationStoreError("region_unavailable")
        if evidence_entry is None:
            raise ObservationStoreError("evidence_unavailable")
        self._validate_binding(
            owner_key=region_entry.owner_key,
            root_session_id=region_entry.root_session_id,
            tab_id=region_entry.tab_id,
            context=region_entry.context,
            generation=region_entry.generation,
            prefix="region",
        )
        self._validate_binding(
            owner_key=evidence_entry.owner_key,
            root_session_id=evidence_entry.root_session_id,
            tab_id=evidence_entry.tab_id,
            context=evidence_entry.context,
            generation=evidence_entry.generation,
            prefix="evidence",
        )
        if (
            region_entry.context is not evidence_entry.context
            or region_entry.generation != evidence_entry.generation
        ):
            raise ObservationStoreError("region_evidence_context_mismatch")
        scope = evidence_entry.meta.scope
        if not isinstance(scope, RegionScope) or scope.region is not region:
            raise ObservationStoreError("region_evidence_scope_mismatch")
        return region_entry.binding, evidence_entry.meta

    def issue_region(
        self,
        *,
        kind: Literal["FRAME", "CONTENT", "OWNER"],
        native_identity: str,
        owner_chain: tuple[str, ...],
    ) -> RegionRef:
        """Issue an opaque region bound to owner/tab/context generation."""
        if kind not in {"FRAME", "CONTENT", "OWNER"}:
            raise ValueError("unsupported region kind")
        if not native_identity.strip() or not owner_chain:
            raise ValueError("region identity and owner chain are required")
        region_id = f"region-{uuid4().hex}"
        ref = _issue_opaque_value(
            RegionRef,
            _RUNTIME_VALUE_ISSUER,
            id=region_id,
        )
        assert isinstance(ref, RegionRef)
        binding = RegionBinding(
            ref=ref,
            kind=kind,
            owner_chain=tuple(owner_chain),
        )
        _REGIONS[region_id] = _RegionEntry(
            region_id=region_id,
            owner_key=self.owner_key,
            root_session_id=self.root_session_id,
            tab_id=self.tab_id,
            context=self.context,
            generation=self.generation,
            expires_at=self._clock(),
            binding=binding,
            native_identity=native_identity,
        )
        return ref

    def require_region(
        self,
        ref: RegionRef,
        *,
        kind: Literal["FRAME", "CONTENT", "OWNER"],
    ) -> RegionBinding:
        """Resolve only the exact original region; replacements are stale."""
        region_id = _opaque_id(ref, RegionRef, "region_unavailable")
        entry = _REGIONS.get(region_id)
        if entry is None:
            raise ObservationStoreError("region_unavailable")
        self._validate_binding(
            owner_key=entry.owner_key,
            root_session_id=entry.root_session_id,
            tab_id=entry.tab_id,
            context=entry.context,
            generation=entry.generation,
            prefix="region",
        )
        if entry.binding.kind != kind:
            raise ObservationStoreError("region_type_mismatch")
        return entry.binding

    def release_owner(self, owner_key: OwnerKey) -> None:
        """Release all observation state for one exact S0 owner key."""
        cleanup_observation_store(owner_key)

    def _validate_collection_binding(
        self,
        collection: ImmutableReadCollection,
    ) -> None:
        self._validate_binding(
            owner_key=collection.owner_key,
            root_session_id=collection.root_session_id,
            tab_id=collection.tab_id,
            context=collection.context,
            generation=collection.generation,
            prefix="collection",
        )
        if (
            collection.evidence.ref
            is not self.require_evidence(
                collection.evidence.ref,
            ).ref
        ):
            raise ObservationStoreError("collection_evidence_mismatch")

    def _require_cursor(self, cursor: ReadCursor) -> _CursorEntry:
        cursor_id = _opaque_id(cursor, ReadCursor, "cursor_invalid")
        entry = _CURSORS.get(cursor_id)
        if entry is None:
            raise ObservationStoreError("cursor_invalid")
        self._validate_binding(
            owner_key=entry.owner_key,
            root_session_id=entry.root_session_id,
            tab_id=entry.tab_id,
            context=entry.context,
            generation=entry.generation,
            prefix="cursor",
        )
        if entry.kind != "READ":
            raise ObservationStoreError("cursor_type_mismatch")
        return entry

    def _validate_binding(
        self,
        *,
        owner_key: OwnerKey,
        root_session_id: str,
        tab_id: str,
        context: ContextVersion,
        generation: int,
        prefix: str,
    ) -> None:
        if owner_key != self.owner_key:
            raise ObservationStoreError(f"{prefix}_owner_mismatch")
        if root_session_id != self.root_session_id:
            raise ObservationStoreError(f"{prefix}_session_mismatch")
        if tab_id != self.tab_id:
            raise ObservationStoreError(f"{prefix}_tab_mismatch")
        if generation != self.generation:
            raise ObservationStoreError(f"{prefix}_generation_mismatch")
        if context is not self.context:
            raise ObservationStoreError(f"{prefix}_context_mismatch")

    def _issue_cursor(
        self,
        collection_id: str,
        collection: ImmutableReadCollection,
        *,
        offset: int,
    ) -> ReadCursor:
        cursor_id = f"read-cursor-{uuid4().hex}"
        cursor = _issue_opaque_value(
            ReadCursor,
            _RUNTIME_VALUE_ISSUER,
            id=cursor_id,
        )
        assert isinstance(cursor, ReadCursor)
        _CURSORS[cursor_id] = _CursorEntry(
            cursor_id=cursor_id,
            collection_id=collection_id,
            offset=offset,
            owner_key=collection.owner_key,
            root_session_id=collection.root_session_id,
            tab_id=collection.tab_id,
            context=collection.context,
            generation=collection.generation,
            kind=collection.kind,
            expires_at=collection.expires_at,
        )
        return cursor


def cleanup_observation_tab(owner_key: OwnerKey, tab_id: str) -> None:
    """Remove every observation value for one exact owner and tab."""
    _require_owner_key(owner_key)
    if not isinstance(tab_id, str) or not tab_id.strip():
        raise ValueError("tab_id is required")
    _cleanup_observation_values(owner_key, tab_id=tab_id)


def cleanup_observation_store(owner_key: OwnerKey) -> None:
    """Remove every evidence, cursor, and collection owned by owner_key."""
    _require_owner_key(owner_key)
    _cleanup_observation_values(owner_key)


def _cleanup_observation_values(
    owner_key: OwnerKey,
    *,
    tab_id: str | None = None,
) -> None:
    """Delete state selected by one owner and optional native tab id."""
    collection_ids = {
        key
        for key, entry in _COLLECTIONS.items()
        if entry.collection.owner_key == owner_key
        and (tab_id is None or entry.collection.tab_id == tab_id)
    }
    for key in collection_ids:
        _COLLECTIONS.pop(key, None)
    for key, cursor_entry in tuple(_CURSORS.items()):
        if (
            cursor_entry.owner_key == owner_key
            and (tab_id is None or cursor_entry.tab_id == tab_id)
        ) or cursor_entry.collection_id in collection_ids:
            _CURSORS.pop(key, None)
    for key, evidence_entry in tuple(_EVIDENCE.items()):
        if evidence_entry.owner_key == owner_key and (
            tab_id is None or evidence_entry.tab_id == tab_id
        ):
            _EVIDENCE.pop(key, None)
    for key, region_entry in tuple(_REGIONS.items()):
        if region_entry.owner_key == owner_key and (
            tab_id is None or region_entry.tab_id == tab_id
        ):
            _REGIONS.pop(key, None)
    for context_key, context_entry in tuple(_CONTEXTS.items()):
        if context_entry.owner_key == owner_key and (
            tab_id is None or context_entry.tab_id == tab_id
        ):
            _CONTEXTS.pop(context_key, None)


def _opaque_id(value: object, expected: type[object], code: str) -> str:
    if not isinstance(value, expected):
        raise ObservationStoreError(code)
    value_id = str(value.to_dict().get("id", ""))  # type: ignore[attr-defined]
    if not value_id:
        raise ObservationStoreError(code)
    return value_id


def _require_owner_key(owner_key: OwnerKey) -> None:
    if (
        not isinstance(owner_key, tuple)
        or len(owner_key) != 2
        or not all(
            isinstance(item, str) and item.strip() for item in owner_key
        )
    ):
        raise ValueError("owner_key must be the S0 root-task/owner tuple")


__all__ = [
    "ImmutableReadCollection",
    "ObservationStore",
    "ObservationStoreError",
    "ReadPage",
    "RegionBinding",
    "cleanup_observation_tab",
    "cleanup_observation_store",
]
