# -*- coding: utf-8 -*-
"""Bridge-owned paged canonical source traversal action."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from qwenpaw.browser.sdk.canonical.contracts import (
    ContextVersion,
    CurrentSurface,
    TargetQuery,
    _issue_opaque_value,
    _RUNTIME_VALUE_ISSUER,
)
from qwenpaw.browser.sdk.runtime.responses import _tool_response
from qwenpaw.browser.sdk.runtime.snapshot import SnapshotCapture
from ..session_manager import _control_get_session
from ..ref_scope import _control_note_canonical_document
from ..source_traversal import (
    CDPSourceTraversalAdapter,
    SourceTraversalManager,
)
from ..state import ControlState
from ..tab_manager import _control_ensure_tab_available, _control_page_id
from ..navigation import _control_tab_id
from .protocol import ActionMeta
from .snapshot import _canonical_snapshot_payload


@dataclass(frozen=True)
class SnapshotPageHandler:
    """Serve one exact source page without accepting capture budgets."""

    meta: ActionMeta = ActionMeta(True, False, False)

    async def execute(
        self,
        state: ControlState,
        *,
        holder_id: str,
        bridge: Any,
        **kwargs: Any,
    ):
        tab_id = _control_tab_id(
            _control_page_id(state, str(kwargs.get("page_id", ""))),
            kwargs.get("index", -1),
        )
        await _control_ensure_tab_available(bridge, tab_id)
        request = _traversal_request(kwargs.get("traversal"))
        manager = SourceTraversalManager(state)
        cursor = request["cursor"]
        if request["cancel"]:
            cancelled = manager.cancel(tab_id=tab_id, cursor=cursor or "")
            return _tool_response(
                json.dumps(
                    {
                        "ok": True,
                        "mode": "canonical",
                        "tab_id": tab_id,
                        "cancelled": cancelled,
                        "continuation": None,
                        "end_of_collection": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        session = await _control_get_session(
            state,
            tab_id=tab_id,
            holder_id=holder_id,
            bridge=bridge,
            request_context=kwargs.get("request_context") or {},
        )
        source = CDPSourceTraversalAdapter(session)
        def note_generation(generation: str) -> None:
            _control_note_canonical_document(
                state,
                tab_id=tab_id,
                document_token=generation,
            )

        if cursor is None:
            page = await manager.start(
                tab_id=tab_id,
                source=source,
                limit=request["limit"],
                query=request["query"],
                region_owner_chain=request["region_owner_chain"],
                on_generation=note_generation,
            )
        else:
            page = await manager.continue_(
                tab_id=tab_id,
                source=source,
                cursor=cursor,
                limit=request["limit"],
                on_generation=note_generation,
            )
        context = _issue_opaque_value(
            ContextVersion,
            _RUNTIME_VALUE_ISSUER,
            value=page.generation,
        )
        assert isinstance(context, ContextVersion)
        capture = SnapshotCapture(
            context=context,
            scope=CurrentSurface(),
            generation=page.generation,
            coverage=page.coverage,
            gaps=page.gaps,
            sources=page.sources,
            targets=page.targets,
        )
        payload = _canonical_snapshot_payload(
            state,
            tab_id=tab_id,
            request_context=kwargs.get("request_context") or {},
            capture=capture,
            include_trusted_bindings=False,
        )
        return _tool_response(
            json.dumps(
                {
                    **payload,
                    "continuation": page.cursor,
                    "end_of_collection": page.end_of_collection,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )


def _traversal_request(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("source traversal request is required")
    if set(value) - {
        "cursor",
        "limit",
        "query",
        "region_owner_chain",
        "cancel",
    }:
        raise ValueError(
            "source traversal request contains unsupported fields",
        )
    limit = value.get("limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("source traversal limit must be positive")
    cursor = value.get("cursor")
    if cursor is not None and (not isinstance(cursor, str) or not cursor):
        raise ValueError("source traversal cursor is invalid")
    cancel = value.get("cancel", False)
    if not isinstance(cancel, bool):
        raise TypeError("source traversal cancel must be a bool")
    raw_chain = value.get("region_owner_chain", ())
    if not isinstance(raw_chain, (tuple, list)) or not all(
        isinstance(owner, str) and owner for owner in raw_chain
    ):
        raise ValueError("region owner chain is invalid")
    raw_query = value.get("query")
    query = None
    if raw_query is not None:
        if not isinstance(raw_query, dict):
            raise TypeError("source traversal query is invalid")
        query = TargetQuery(
            **{
                key: raw_query[key]
                for key in ("role", "name", "text", "match")
                if key in raw_query
            },
        )
    return {
        "cursor": cursor,
        "limit": limit,
        "query": query,
        "region_owner_chain": tuple(raw_chain),
        "cancel": cancel,
    }


SNAPSHOT_PAGE_HANDLER = SnapshotPageHandler()

__all__ = ["SNAPSHOT_PAGE_HANDLER", "SnapshotPageHandler"]
