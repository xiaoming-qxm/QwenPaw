# -*- coding: utf-8 -*-
"""Incremental, document-bound canonical source traversal.

The bridge retains only opaque cursor state and source positions.  It never
caches a complete AX/DOM snapshot or materialized result set between pages.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, replace
from typing import Any, Protocol
from uuid import uuid4

from qwenpaw.browser.api.contracts import (
    CaptureGap,
    Coverage,
    CoverageGap,
    TargetQuery,
    coverage_from_gaps,
)
from qwenpaw.browser.primitives.matching import normalize_visible_text
from qwenpaw.browser.runtime.snapshot import (
    ProbeNode,
    SnapshotTarget,
    SourceOutcome,
    _merge_neutral_targets,
)
from .errors import DOMSettleTimeout
from .targets import (
    _CANONICAL_ACTIONABLE_ROLES,
    _CANONICAL_NON_VISIBLE_DOM_TAGS,
    _CANONICAL_STRUCTURAL_ARIA_ROLES,
    _canonical_dom_attributes,
    _canonical_native_role,
    canonical_probe_nodes_from_ax,
)


_TRAVERSALS_KEY = "canonical_source_traversals"
_TAB_CURSORS_KEY = "canonical_source_traversal_tabs"
_INVALIDATED_CURSORS_KEY = "canonical_source_traversal_invalidated"


class SourceTraversalUnavailable(RuntimeError):
    """A source became unavailable while it was being traversed."""

    def __init__(self, source: str, code: str = "source_unavailable") -> None:
        super().__init__(code)
        self.source = str(source).upper()
        self.code = str(code)


@dataclass(frozen=True, slots=True)
class SourceTraversalStep:
    """One source position and its direct children, never a source snapshot."""

    nodes: tuple[ProbeNode, ...] = ()
    children: tuple[str, ...] = ()
    unavailable_sources: tuple[str, ...] = ()
    gaps: tuple[CoverageGap, ...] = ()


class SourceTraversalSource(Protocol):
    """Private bridge source adapter used to resume one cursor."""

    async def generation(self) -> str:
        """Return the exact current document generation."""

    async def root_position(self) -> str:
        """Return the first opaque source position."""

    async def step(self, position: str) -> SourceTraversalStep:
        """Read one position and its direct source children."""


@dataclass(frozen=True, slots=True)
class SourceTraversalPage:
    """Stable backend-facing page; private source records never escape."""

    generation: str
    coverage: Coverage
    targets: tuple[SnapshotTarget, ...]
    sources: tuple[SourceOutcome, ...]
    cursor: str | None
    end_of_collection: bool
    gaps: tuple[CoverageGap, ...] = ()
    visual_region: dict[str, object] | None = None


class CDPSourceTraversalAdapter:
    """Page a DOM walk and query AX only for the current native node."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def generation(self) -> str:
        try:
            frame_tree = await self._send("Page.getFrameTree")
        except Exception as exc:  # noqa: BLE001 - preserve timeout transport
            self._raise_or_unavailable("DOM", exc)
        frame = frame_tree.get("frameTree", {}).get("frame", {})
        generation = frame.get("loaderId") if isinstance(frame, dict) else None
        if not generation:
            raise SourceTraversalUnavailable(
                "DOM",
                "document_generation_unavailable",
            )
        return str(generation)

    async def root_position(self) -> str:
        try:
            await self._send("DOM.enable")
            document = await self._send("DOM.getDocument", {"depth": 0})
        except Exception as exc:  # noqa: BLE001 - preserve timeout transport
            self._raise_or_unavailable("DOM", exc)
        root = document.get("root") if isinstance(document, dict) else None
        if not isinstance(root, dict):
            raise SourceTraversalUnavailable("DOM", "source_root_unavailable")
        return _position_from_node(root, ("main",), False)

    async def step(self, position: str) -> SourceTraversalStep:
        node_id, owner_chain, hidden_by_ancestor = _position_data(position)
        try:
            payload = await self._send(
                "DOM.describeNode",
                {"nodeId": node_id, "depth": 1, "pierce": True},
            )
        except Exception as exc:  # noqa: BLE001 - preserve timeout transport
            self._raise_or_unavailable("DOM", exc)
        raw = payload.get("node") if isinstance(payload, dict) else None
        if not isinstance(raw, dict):
            raise SourceTraversalUnavailable("DOM", "source_node_unavailable")
        dom_nodes, effective_chain, hidden = _dom_node(
            raw,
            owner_chain=owner_chain,
            hidden_by_ancestor=hidden_by_ancestor,
        )
        frame_accessibility = await self._frame_accessibility(raw)
        children, gaps = _child_positions(
            raw,
            effective_chain,
            hidden,
            frame_accessibility=frame_accessibility,
        )
        ax_nodes: tuple[ProbeNode, ...] = ()
        unavailable: tuple[str, ...] = ()
        backend_id = raw.get("backendNodeId") or raw.get("backendDOMNodeId")
        if isinstance(backend_id, int) and backend_id > 0:
            try:
                ax = await self._send(
                    "Accessibility.queryAXTree",
                    {"nodeId": node_id},
                )
            except Exception as exc:  # noqa: BLE001 - source loss is typed
                if _is_transport_timeout(exc):
                    raise
                unavailable = ("AX",)
            else:
                identity = f"backend:{backend_id}"
                ax_nodes = tuple(
                    replace(
                        node,
                        owner=effective_chain[-1],
                        owner_chain=effective_chain,
                    )
                    for node in canonical_probe_nodes_from_ax(ax)
                    if node.native_identity == identity
                )
        return SourceTraversalStep(
            nodes=(*ax_nodes, *dom_nodes),
            children=children,
            unavailable_sources=unavailable,
            gaps=gaps,
        )

    async def _frame_accessibility(self, raw: dict[str, Any]) -> str | None:
        """Classify a frame owner from protocol-owned frame-tree facts.

        CDP DOM.Node deliberately does not expose a ``crossOrigin`` flag.  A
        frame owner does expose its child ``frameId``; Page.getFrameTree then
        supplies the protocol-owned parent/child security origins needed for
        this coverage decision.
        """
        tag = str(raw.get("nodeName") or "").strip().lower()
        if tag not in {"frame", "iframe"}:
            return None
        content_document = raw.get("contentDocument")
        frame_id = str(
            raw.get("frameId")
            or (
                content_document.get("frameId")
                if isinstance(content_document, dict)
                else ""
            )
            or "",
        ).strip()
        if not frame_id:
            return "UNAVAILABLE"
        try:
            payload = await self._send("Page.getFrameTree")
        except Exception as exc:  # noqa: BLE001 - preserve transport timeout
            if _is_transport_timeout(exc):
                raise
            return "UNAVAILABLE"
        records = _frame_records(payload)
        frame = records.get(frame_id)
        if frame is None:
            return "UNAVAILABLE"
        parent_id, origin = frame
        parent = records.get(parent_id)
        if parent is None:
            return "UNAVAILABLE"
        parent_origin = parent[1]
        if not origin or not parent_origin:
            return "UNAVAILABLE"
        return "SAME_ORIGIN" if origin == parent_origin else "CROSS_ORIGIN"

    async def _send(
        self,
        method: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        try:
            result = await asyncio.wait_for(
                self._session.send(method, params or {}),
                timeout=5.0,
            )
        except asyncio.TimeoutError as exc:
            raise DOMSettleTimeout(f"{method} timed out") from exc
        if not isinstance(result, dict):
            raise SourceTraversalUnavailable("DOM", "source_payload_invalid")
        return result

    @staticmethod
    def _raise_or_unavailable(source: str, exc: Exception) -> None:
        if _is_transport_timeout(exc):
            raise exc
        raise SourceTraversalUnavailable(source) from exc


def _position_from_node(
    raw: dict[str, Any],
    owner_chain: tuple[str, ...],
    hidden_by_ancestor: bool,
) -> str:
    node_id = raw.get("nodeId")
    if not isinstance(node_id, int) or node_id <= 0:
        raise SourceTraversalUnavailable("DOM", "source_node_identity_missing")
    return json.dumps(
        {
            "node_id": node_id,
            "owner_chain": list(owner_chain),
            "hidden": bool(hidden_by_ancestor),
        },
        separators=(",", ":"),
    )


def _position_data(position: str) -> tuple[int, tuple[str, ...], bool]:
    try:
        data = json.loads(position)
    except (TypeError, ValueError) as exc:
        raise ValueError("source traversal position is invalid") from exc
    if not isinstance(data, dict):
        raise ValueError("source traversal position is invalid")
    node_id = data.get("node_id")
    owner_chain = data.get("owner_chain")
    hidden = data.get("hidden")
    if (
        not isinstance(node_id, int)
        or node_id <= 0
        or not isinstance(owner_chain, list)
        or not owner_chain
        or not all(isinstance(owner, str) and owner for owner in owner_chain)
        or not isinstance(hidden, bool)
    ):
        raise ValueError("source traversal position is invalid")
    return node_id, tuple(owner_chain), hidden


def _dom_node(
    raw: dict[str, Any],
    *,
    owner_chain: tuple[str, ...],
    hidden_by_ancestor: bool,
) -> tuple[tuple[ProbeNode, ...], tuple[str, ...], bool]:
    frame_id = str(raw.get("frameId") or "").strip()
    if frame_id and owner_chain[-1] == "main":
        owner_chain = (*owner_chain, f"frame:{frame_id}")
    attributes = _canonical_dom_attributes(raw.get("attributes"))
    tag = str(raw.get("nodeName") or "").strip().lower()
    hidden = hidden_by_ancestor or tag in _CANONICAL_NON_VISIBLE_DOM_TAGS
    role = str(attributes.get("role") or _canonical_native_role(tag))
    is_explicitly_semantic = (
        "role" in attributes and role not in _CANONICAL_STRUCTURAL_ARIA_ROLES
    )
    backend_id = raw.get("backendNodeId") or raw.get("backendDOMNodeId")
    if (
        hidden
        or not isinstance(backend_id, int)
        or backend_id <= 0
        or not role
        or (
            role not in _CANONICAL_ACTIONABLE_ROLES
            and not is_explicitly_semantic
        )
    ):
        return (), owner_chain, hidden
    name = next(
        (
            attributes[key]
            for key in ("aria-label", "title", "alt", "placeholder")
            if attributes.get(key)
        ),
        str(raw.get("nodeValue") or "").strip(),
    )
    return (
        (
            ProbeNode(
                source="DOM",
                native_identity=f"backend:{backend_id}",
                owner=owner_chain[-1],
                owner_chain=owner_chain,
                role=role,
                name=name,
                actionable=(
                    role in _CANONICAL_ACTIONABLE_ROLES
                    and "disabled" not in attributes
                ),
                states=tuple(
                    key
                    for key in ("disabled", "checked", "selected", "expanded")
                    if key in attributes
                ),
            ),
        ),
        owner_chain,
        hidden,
    )


def _child_positions(
    raw: dict[str, Any],
    owner_chain: tuple[str, ...],
    hidden_by_ancestor: bool,
    *,
    frame_accessibility: str | None,
) -> tuple[tuple[str, ...], tuple[CoverageGap, ...]]:
    children: list[str] = []
    gaps: list[CoverageGap] = []
    raw_children = raw.get("children")
    if isinstance(raw_children, list):
        children.extend(
            _position_from_node(child, owner_chain, hidden_by_ancestor)
            for child in raw_children
            if isinstance(child, dict)
        )
    tag = str(raw.get("nodeName") or "").strip().lower()
    content_document = raw.get("contentDocument")
    if tag in {"frame", "iframe"}:
        if frame_accessibility == "CROSS_ORIGIN":
            gaps.append(
                CoverageGap(
                    stage="CAPTURE",
                    detail=CaptureGap(
                        source="FRAME",
                        reason="CROSS_ORIGIN",
                    ),
                ),
            )
        elif frame_accessibility == "SAME_ORIGIN" and isinstance(
            content_document,
            dict,
        ):
            frame_id = str(
                raw.get("frameId") or content_document.get("frameId") or "",
            ).strip()
            backend_id = raw.get("backendNodeId") or raw.get(
                "backendDOMNodeId",
            )
            frame_owner = frame_id or f"backend-{backend_id}"
            child_chain = (*owner_chain, f"frame:{frame_owner}")
            if owner_chain[-1] == f"frame:{frame_owner}":
                child_chain = owner_chain
            children.append(
                _position_from_node(
                    content_document,
                    child_chain,
                    False,
                ),
            )
        else:
            gaps.append(
                CoverageGap(
                    stage="CAPTURE",
                    detail=CaptureGap(
                        source="FRAME",
                        reason="SOURCE_UNAVAILABLE",
                    ),
                ),
            )
    backend_id = raw.get("backendNodeId") or raw.get("backendDOMNodeId")
    if isinstance(backend_id, int) and backend_id > 0:
        shadow_roots = raw.get("shadowRoots")
        if isinstance(shadow_roots, list):
            for shadow in shadow_roots:
                if not isinstance(shadow, dict):
                    continue
                shadow_type = str(
                    shadow.get("shadowRootType") or "closed",
                ).lower()
                if shadow_type != "open":
                    gaps.append(
                        CoverageGap(
                            stage="CAPTURE",
                            detail=CaptureGap(
                                source="SHADOW",
                                reason="CLOSED_SHADOW",
                            ),
                        ),
                    )
                    continue
                children.append(
                    _position_from_node(
                        shadow,
                        (*owner_chain, f"shadow:backend:{backend_id}"),
                        hidden_by_ancestor,
                    ),
                )
    return tuple(children), tuple(gaps)


def _frame_records(
    payload: dict[str, Any],
) -> dict[str, tuple[str, str]]:
    """Flatten CDP Page.FrameTree to child -> (parent, security origin)."""
    tree = payload.get("frameTree")
    records: dict[str, tuple[str, str]] = {}

    def collect(value: object, parent_id: str = "") -> None:
        if not isinstance(value, dict):
            return
        frame = value.get("frame")
        if not isinstance(frame, dict):
            return
        frame_id = str(frame.get("id") or "").strip()
        if not frame_id:
            return
        parent = str(frame.get("parentId") or parent_id or "").strip()
        origin = str(frame.get("securityOrigin") or "").strip()
        records[frame_id] = (parent, origin)
        children = value.get("childFrames")
        if isinstance(children, list):
            for child in children:
                collect(child, frame_id)

    collect(tree)
    return records


def _is_transport_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (DOMSettleTimeout, asyncio.TimeoutError)):
        return True
    return str(getattr(exc, "browser_error_code", "")) in {
        "cdp_command_timeout",
        "dom_settle_timeout",
        "network_timeout",
        "network_settle_timeout",
    }


def _note_generation(
    callback: Callable[[str], None] | None,
    generation: str,
) -> None:
    """Commit a trusted generation before exposing its traversal state."""
    if callback is not None:
        callback(str(generation))


class SourceTraversalManager:
    """Own opaque, per-tab cursor state for incremental source traversal."""

    def __init__(self, state: MutableMapping[str, object]) -> None:
        self._state = state

    async def start(
        self,
        *,
        tab_id: int,
        source: SourceTraversalSource,
        limit: int,
        query: TargetQuery | None = None,
        region_owner_chain: tuple[str, ...] | None = None,
        visual_region: dict[str, object] | None = None,
        on_generation: Callable[[str], None] | None = None,
    ) -> SourceTraversalPage:
        """Replace any tab cursor and return the first source-derived page."""
        _validate_limit(limit)
        _validate_query(query, region_owner_chain)
        self.cancel_tab(tab_id)
        generation = ""
        try:
            generation = await source.generation()
            _note_generation(on_generation, generation)
            root = await source.root_position()
        except SourceTraversalUnavailable as exc:
            return _unavailable_page(generation, exc)
        if not isinstance(root, str) or not root:
            return _unavailable_page(
                generation,
                SourceTraversalUnavailable("DOM", "source_root_unavailable"),
            )
        cursor = f"traversal_{uuid4().hex}"
        self._sessions()[cursor] = {
            "tab_id": int(tab_id),
            "generation": str(generation),
            "pending": [_pending_position(root)],
            "query": _query_state(query),
            "region_owner_chain": list(region_owner_chain or ()),
            "visual_region": (
                dict(visual_region)
                if isinstance(visual_region, dict)
                else None
            ),
            "unavailable_sources": {},
            "examined": {"AX": 0, "DOM": 0},
            "gaps": [],
        }
        self._tab_cursors()[str(int(tab_id))] = cursor
        return await self._page(
            tab_id=tab_id,
            source=source,
            cursor=cursor,
            limit=limit,
            on_generation=on_generation,
        )

    async def continue_(
        self,
        *,
        tab_id: int,
        source: SourceTraversalSource,
        cursor: str,
        limit: int,
        on_generation: Callable[[str], None] | None = None,
    ) -> SourceTraversalPage:
        """Resume exactly one current tab cursor from its source position."""
        _validate_limit(limit)
        session = self._sessions().get(str(cursor))
        if not isinstance(session, dict):
            invalidated = self._invalidated_cursor(cursor)
            if invalidated is not None:
                if int(invalidated["tab_id"]) != int(tab_id):
                    raise ValueError(
                        "source traversal cursor belongs to another tab",
                    )
                return self._invalidated_page(invalidated)
            raise ValueError("source traversal cursor is unknown")
        if int(session["tab_id"]) != int(tab_id):
            raise ValueError("source traversal cursor belongs to another tab")
        if self.active_cursor_for_tab(tab_id) != cursor:
            raise ValueError("source traversal cursor is no longer active")
        return await self._page(
            tab_id=tab_id,
            source=source,
            cursor=cursor,
            limit=limit,
            on_generation=on_generation,
        )

    def cancel(self, *, tab_id: int, cursor: str) -> bool:
        """Release only the currently active cursor for one receiver tab."""
        if self.active_cursor_for_tab(tab_id) != cursor:
            return False
        self._release(cursor)
        return True

    def cancel_tab(self, tab_id: int) -> bool:
        """Release a cursor when a new request replaces its tab traversal."""
        cursor = self.active_cursor_for_tab(tab_id)
        if cursor is None:
            return False
        self._release(cursor)
        return True

    def invalidate_tab(self, tab_id: int) -> bool:
        """Release a cursor when trusted receiver state becomes invalid."""
        cursor = self.active_cursor_for_tab(tab_id)
        if cursor is None:
            return False
        self._invalidate(cursor)
        return True

    def active_cursor_for_tab(self, tab_id: int) -> str | None:
        value = self._tab_cursors().get(str(int(tab_id)))
        return value if isinstance(value, str) and value else None

    def has(self, cursor: str | None) -> bool:
        return bool(cursor and cursor in self._sessions())

    async def _page(
        self,
        *,
        tab_id: int,
        source: SourceTraversalSource,
        cursor: str,
        limit: int,
        on_generation: Callable[[str], None] | None,
    ) -> SourceTraversalPage:
        session = self._session(cursor)
        expected_generation = str(session["generation"])
        try:
            generation_before = await source.generation()
            _note_generation(on_generation, generation_before)
        except SourceTraversalUnavailable as exc:
            if not self._is_active(tab_id, cursor):
                return self._stale(cursor, expected_generation, session)
            return self._unavailable(cursor, expected_generation, exc)
        if generation_before != expected_generation:
            return self._stale(cursor, generation_before, session)
        if not self._is_active(tab_id, cursor):
            return self._stale(cursor, expected_generation, session)

        targets: list[SnapshotTarget] = []
        pending = session["pending"]
        if not isinstance(pending, list):
            raise ValueError("source traversal state is invalid")
        query = _query_from_state(session.get("query"))
        region_owner_chain = tuple(session.get("region_owner_chain") or ())

        while pending and len(targets) < limit:
            position, processed, child_index = _pending_data(pending.pop())
            try:
                step = await source.step(position)
            except SourceTraversalUnavailable as exc:
                if not self._is_active(tab_id, cursor):
                    return self._stale(cursor, expected_generation, session)
                _record_unavailable(session, exc.source, exc.code)
                if exc.source == "DOM":
                    pending.clear()
                continue
            if not self._is_active(tab_id, cursor):
                return self._stale(cursor, expected_generation, session)
            if not isinstance(step, SourceTraversalStep):
                raise TypeError(
                    "source traversal adapter returned invalid step",
                )
            if processed:
                if child_index >= len(step.children):
                    continue
                if child_index + 1 < len(step.children):
                    pending.append(
                        _pending_position(
                            position,
                            child_index + 1,
                            processed=True,
                        ),
                    )
                child = step.children[child_index]
                if isinstance(child, str) and child:
                    pending.append(_pending_position(child))
                continue

            _record_step(session, step)
            if len(step.children) == 1:
                child = step.children[0]
                if isinstance(child, str) and child:
                    pending.append(_pending_position(child))
            elif step.children:
                pending.append(
                    _pending_position(position, 0, processed=True),
                )
            merged = _merge_step(step)
            if len(merged) > 1:
                raise ValueError("source traversal step must address one node")
            if merged and _matches(
                merged[0],
                query=query,
                region_owner_chain=region_owner_chain,
            ):
                targets.append(merged[0])

        try:
            generation_after = await source.generation()
            _note_generation(on_generation, generation_after)
        except SourceTraversalUnavailable as exc:
            if not self._is_active(tab_id, cursor):
                return self._stale(cursor, expected_generation, session)
            return self._unavailable(cursor, expected_generation, exc)
        if generation_after != expected_generation:
            return self._stale(cursor, generation_after, session)
        if not self._is_active(tab_id, cursor):
            return self._stale(cursor, expected_generation, session)

        end_of_collection = not pending
        sources = _sources(session)
        gaps = _gaps(session)
        coverage = _coverage(sources, gaps)
        next_cursor = None if end_of_collection else cursor
        if end_of_collection:
            self._release(cursor)
        return SourceTraversalPage(
            generation=expected_generation,
            coverage=coverage,
            targets=tuple(targets),
            sources=sources,
            cursor=next_cursor,
            end_of_collection=end_of_collection,
            gaps=gaps,
            visual_region=(
                dict(session["visual_region"])
                if isinstance(session.get("visual_region"), dict)
                else None
            ),
        )

    def _stale(
        self,
        cursor: str,
        generation: str,
        session: dict[str, object],
    ) -> SourceTraversalPage:
        sources = _sources(session)
        self._release(cursor)
        return SourceTraversalPage(
            generation=str(generation),
            coverage="STALE",
            targets=(),
            sources=sources,
            cursor=None,
            end_of_collection=True,
            gaps=(
                CoverageGap(
                    stage="CAPTURE",
                    detail=CaptureGap(
                        source="DOCUMENT",
                        reason="GENERATION_MISMATCH",
                    ),
                ),
            ),
        )

    def _sessions(self) -> dict[str, dict[str, object]]:
        sessions = self._state.get(_TRAVERSALS_KEY)
        if not isinstance(sessions, dict):
            sessions = {}
            self._state[_TRAVERSALS_KEY] = sessions
        return sessions

    def _invalidated(self) -> dict[str, dict[str, object]]:
        invalidated = self._state.get(_INVALIDATED_CURSORS_KEY)
        if not isinstance(invalidated, dict):
            invalidated = {}
            self._state[_INVALIDATED_CURSORS_KEY] = invalidated
        return invalidated

    def _tab_cursors(self) -> dict[str, str]:
        cursors = self._state.get(_TAB_CURSORS_KEY)
        if not isinstance(cursors, dict):
            cursors = {}
            self._state[_TAB_CURSORS_KEY] = cursors
        return cursors

    def _session(self, cursor: str) -> dict[str, object]:
        session = self._sessions().get(str(cursor))
        if not isinstance(session, dict):
            raise ValueError("source traversal cursor is unknown")
        return session

    def _release(self, cursor: str) -> None:
        session = self._sessions().pop(str(cursor), None)
        if isinstance(session, dict):
            tab_id = str(session.get("tab_id") or "")
            if self._tab_cursors().get(tab_id) == cursor:
                self._tab_cursors().pop(tab_id, None)

    def _invalidate(self, cursor: str) -> None:
        session = self._sessions().get(str(cursor))
        if not isinstance(session, dict):
            return
        self._invalidated()[str(cursor)] = {
            "tab_id": int(session["tab_id"]),
            "generation": str(session["generation"]),
            "sources": _sources(session),
        }
        self._release(cursor)

    def _invalidated_cursor(self, cursor: str) -> dict[str, object] | None:
        record = self._invalidated().get(str(cursor))
        return record if isinstance(record, dict) else None

    def _invalidated_page(
        self,
        invalidated: dict[str, object],
    ) -> SourceTraversalPage:
        sources = invalidated.get("sources")
        if not isinstance(sources, tuple) or not all(
            isinstance(source, SourceOutcome) for source in sources
        ):
            raise ValueError("source traversal invalidation state is invalid")
        return SourceTraversalPage(
            generation=str(invalidated["generation"]),
            coverage="STALE",
            targets=(),
            sources=sources,
            cursor=None,
            end_of_collection=True,
            gaps=(
                CoverageGap(
                    stage="CAPTURE",
                    detail=CaptureGap(
                        source="DOCUMENT",
                        reason="GENERATION_MISMATCH",
                    ),
                ),
            ),
        )

    def _is_active(self, tab_id: int, cursor: str) -> bool:
        return self.active_cursor_for_tab(tab_id) == cursor and isinstance(
            self._sessions().get(str(cursor)),
            dict,
        )

    def _unavailable(
        self,
        cursor: str,
        generation: str,
        error: SourceTraversalUnavailable,
    ) -> SourceTraversalPage:
        self._release(cursor)
        return _unavailable_page(generation, error)


def invalidate_source_traversals(
    state: MutableMapping[str, object],
    *,
    tab_id: int,
) -> bool:
    """State-lifecycle hook for invalidating a receiver's active cursor."""
    return SourceTraversalManager(state).invalidate_tab(tab_id)


def _unavailable_page(
    generation: str,
    error: SourceTraversalUnavailable,
) -> SourceTraversalPage:
    return SourceTraversalPage(
        generation=str(generation),
        coverage="UNAVAILABLE",
        targets=(),
        sources=tuple(
            SourceOutcome(
                source=source,  # type: ignore[arg-type]
                available=False,
                examined=0,
                error_code=(
                    error.code
                    if source == error.source
                    else "source_unavailable"
                ),
            )
            for source in ("AX", "DOM")
        ),
        cursor=None,
        end_of_collection=True,
        gaps=(
            CoverageGap(
                stage="CAPTURE",
                detail=CaptureGap(
                    source=error.source,  # type: ignore[arg-type]
                    reason="SOURCE_UNAVAILABLE",
                ),
            ),
        ),
    )


def _merge_step(step: SourceTraversalStep) -> tuple[SnapshotTarget, ...]:
    nodes = tuple(node for node in step.nodes if hasattr(node, "source"))
    return _merge_neutral_targets(nodes)  # type: ignore[arg-type]


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("source traversal limit must be positive")


def _validate_query(
    query: TargetQuery | None,
    region_owner_chain: tuple[str, ...] | None,
) -> None:
    if query is not None and not isinstance(query, TargetQuery):
        raise TypeError("query must be a TargetQuery")
    if (
        query is not None
        and query.region is not None
        and not region_owner_chain
    ):
        raise ValueError("region query requires a resolved owner chain")


def _query_state(query: TargetQuery | None) -> dict[str, str] | None:
    if query is None:
        return None
    return {
        key: value
        for key, value in {
            "role": query.role,
            "name": query.name,
            "text": query.text,
            "match": query.match,
        }.items()
        if isinstance(value, str) and value
    }


def _query_from_state(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("source traversal query state is invalid")
    return {
        key: str(item)
        for key, item in value.items()
        if key in {"role", "name", "text", "match"} and isinstance(item, str)
    }


def _pending_position(
    position: str,
    child_index: int = 0,
    *,
    processed: bool = False,
) -> dict[str, object]:
    return {
        "position": position,
        "processed": processed,
        "child_index": child_index,
    }


def _pending_data(value: object) -> tuple[str, bool, int]:
    if not isinstance(value, dict):
        raise ValueError("source traversal pending state is invalid")
    position = value.get("position")
    processed = value.get("processed")
    child_index = value.get("child_index")
    if (
        not isinstance(position, str)
        or not position
        or not isinstance(processed, bool)
        or isinstance(child_index, bool)
        or not isinstance(child_index, int)
        or child_index < 0
    ):
        raise ValueError("source traversal pending state is invalid")
    return position, processed, child_index


def _record_step(
    session: dict[str, object],
    step: SourceTraversalStep,
) -> None:
    examined = session["examined"]
    if not isinstance(examined, dict):
        raise ValueError("source traversal state is invalid")
    for node in step.nodes:
        source = str(getattr(node, "source", "")).upper()
        if source in examined:
            examined[source] = int(examined[source]) + 1
    for source in step.unavailable_sources:
        _record_unavailable(session, source, "source_unavailable")
    gaps = session["gaps"]
    if not isinstance(gaps, list) or not all(
        isinstance(gap, CoverageGap) for gap in step.gaps
    ):
        raise ValueError("source traversal state is invalid")
    gaps.extend(step.gaps)


def _record_unavailable(
    session: dict[str, object],
    source: str,
    code: str,
) -> None:
    unavailable = session["unavailable_sources"]
    if not isinstance(unavailable, dict):
        raise ValueError("source traversal state is invalid")
    normalized = str(source).upper()
    if normalized in {"AX", "DOM"}:
        unavailable[normalized] = str(code or "source_unavailable")


def _sources(session: dict[str, object]) -> tuple[SourceOutcome, ...]:
    examined = session.get("examined")
    unavailable = session.get("unavailable_sources")
    if not isinstance(examined, dict) or not isinstance(unavailable, dict):
        raise ValueError("source traversal state is invalid")
    return tuple(
        SourceOutcome(
            source=source,  # type: ignore[arg-type]
            available=source not in unavailable,
            examined=int(examined.get(source, 0)),
            error_code=str(unavailable.get(source) or ""),
        )
        for source in ("AX", "DOM")
    )


def _gaps(session: dict[str, object]) -> tuple[CoverageGap, ...]:
    gaps = session.get("gaps")
    if not isinstance(gaps, list) or not all(
        isinstance(gap, CoverageGap) for gap in gaps
    ):
        raise ValueError("source traversal state is invalid")
    return tuple(gaps)


def _coverage(
    sources: tuple[SourceOutcome, ...],
    gaps: tuple[CoverageGap, ...],
) -> Coverage:
    if not any(source.available for source in sources):
        return "UNAVAILABLE"
    if any(not source.available for source in sources):
        return "PARTIAL"
    return coverage_from_gaps(gaps)


def _matches(
    target: SnapshotTarget,
    *,
    query: dict[str, str] | None,
    region_owner_chain: tuple[str, ...],
) -> bool:
    target_owner_chain = target.owner_chain[: len(region_owner_chain)]
    if region_owner_chain and target_owner_chain != region_owner_chain:
        return False
    if query is None:
        return True
    checks: list[bool] = []
    role = query.get("role")
    if role:
        checks.append(normalize_visible_text(target.role) == role)
    name = query.get("name")
    if name:
        checks.append(_text_matches(target.name, name, query.get("match")))
    text = query.get("text")
    if text:
        checks.append(_text_matches(target.name, text, query.get("match")))
    return all(checks)


def _text_matches(value: str, expected: str, match: str | None) -> bool:
    normalized = normalize_visible_text(value)
    expected_normalized = normalize_visible_text(expected)
    if match == "contains":
        return expected_normalized in normalized
    return normalized == expected_normalized


__all__ = [
    "SourceTraversalManager",
    "SourceTraversalPage",
    "SourceTraversalSource",
    "SourceTraversalStep",
    "SourceTraversalUnavailable",
    "invalidate_source_traversals",
]
