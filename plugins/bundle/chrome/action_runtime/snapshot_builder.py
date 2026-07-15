# -*- coding: utf-8 -*-
"""Structured snapshot builders for Chrome."""
# pylint: disable=implicit-str-concat,too-many-boolean-expressions
# pylint: disable=too-many-branches,too-many-return-statements
# pylint: disable=too-many-statements

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any
from qwenpaw.browser.api.contracts import (
    ContextVersion,
    Coverage,
    CurrentSurface,
    ObservationScope,
    OptionSummary,
    _issue_opaque_value,
    _RUNTIME_VALUE_ISSUER,
)
from qwenpaw.browser.primitives.matching import (
    canonicalize_http_url,
    normalize_visible_text,
)
from qwenpaw.browser.runtime.snapshot import (
    ObservationBudget,
    ProbeBatch,
    ProbeNode,
    SnapshotCapture,
    capture_snapshot,
)
from .errors import DOMSettleTimeout
from .session_manager import _control_document_generation
from .targets import (
    canonical_probe_nodes_from_ax,
    canonical_probe_surface_from_dom,
)

_CONTROL_AX_SNAPSHOT_TIMEOUT_SECONDS = 5.0
_CONTROL_DOM_TREE_TIMEOUT_SECONDS = 5.0


class _CanonicalSessionProbe:
    """Neutral same-session probe for the canonical observation pipeline."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def generation(self) -> str:
        return await _control_document_generation(self._session)

    async def capture_ax(self, *, limit: int) -> tuple[ProbeNode, ...]:
        del limit
        result = await _send_with_timeout(
            self._session,
            "Accessibility.getFullAXTree",
            timeout=_CONTROL_AX_SNAPSHOT_TIMEOUT_SECONDS,
        )
        return canonical_probe_nodes_from_ax(result)

    async def capture_dom(self, *, limit: int) -> ProbeBatch:
        result = await _send_with_timeout(
            self._session,
            "DOM.getDocument",
            {"depth": max(1, min(int(limit), 64)), "pierce": True},
            timeout=_CONTROL_DOM_TREE_TIMEOUT_SECONDS,
        )
        setattr(
            self._session,
            "_canonical_observed_urls",
            _canonical_link_urls_from_dom(result),
        )
        return canonical_probe_surface_from_dom(result)


def _canonical_link_urls_from_dom(payload: dict[str, Any]) -> dict[str, str]:
    """Return only unique credential-free HTTP(S) links by native id."""
    root = payload.get("root")
    if not isinstance(root, dict):
        return {}
    pending = [root]
    candidates: dict[str, set[str]] = {}
    while pending:
        node = pending.pop()
        attributes = node.get("attributes")
        pairs = (
            zip(attributes[::2], attributes[1::2])
            if isinstance(attributes, list)
            else ()
        )
        attrs = {str(key).lower(): str(value) for key, value in pairs}
        backend_id = node.get("backendNodeId") or node.get(
            "backendDOMNodeId",
        )
        if isinstance(backend_id, int) and attrs.get("href"):
            try:
                url = canonicalize_http_url(attrs["href"]).value
            except (TypeError, ValueError):
                pass
            else:
                candidates.setdefault(f"backend:{backend_id}", set()).add(
                    url,
                )
        for key in ("children", "shadowRoots"):
            children = node.get(key)
            if isinstance(children, list):
                pending.extend(
                    item for item in children if isinstance(item, dict)
                )
        content = node.get("contentDocument")
        if isinstance(content, dict):
            pending.append(content)
    return {
        identity: next(iter(urls))
        for identity, urls in candidates.items()
        if len(urls) == 1
    }


async def build_canonical_snapshot(
    session: Any,
    *,
    context: ContextVersion | None = None,
    scope: ObservationScope | None = None,
    budget: ObservationBudget | None = None,
) -> SnapshotCapture:
    """Build neutral AX + bounded DOM capture for trusted CANONICAL mode."""
    probe = _CanonicalSessionProbe(session)
    if context is None:
        generation = await probe.generation()
        issued = _issue_opaque_value(
            ContextVersion,
            _RUNTIME_VALUE_ISSUER,
            value=generation,
        )
        assert isinstance(issued, ContextVersion)
        context = issued
    return await capture_snapshot(
        probe,
        context=context,
        scope=scope or CurrentSurface(),
        budget=budget
        or ObservationBudget(
            capture_nodes=256,
            output_targets=128,
            hard_maximum=512,
        ),
    )


def canonical_option_collection(
    raw_options: tuple[dict[str, object], ...] | list[dict[str, object]],
    *,
    complete: bool,
    limit: int = 128,
) -> tuple[tuple[OptionSummary, ...], Coverage]:
    """Project one bounded visible option collection with explicit coverage."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("option limit must be positive")
    if not isinstance(raw_options, (tuple, list)):
        raise TypeError("raw options must be a bounded sequence")
    coverage: Coverage = "COMPLETE" if complete else "PARTIAL"
    projected: list[OptionSummary] = []
    for raw in raw_options[:limit]:
        if not isinstance(raw, dict) or raw.get("observed", True) is not True:
            coverage = "PARTIAL"
            continue
        label = raw.get("label")
        value = raw.get("value")
        if not isinstance(label, str) or not isinstance(value, str):
            coverage = "PARTIAL"
            continue
        enabled = all(
            raw.get(key, True) is True
            for key in ("enabled", "select_enabled", "optgroup_enabled")
        )
        projected.append(
            OptionSummary(
                label=normalize_visible_text(label),
                value=value,
                enabled=enabled,
            ),
        )
    if len(raw_options) > limit:
        coverage = "PARTIAL"
    return tuple(projected), coverage


async def capture_condition_probe_facts(
    session: Any,
    *,
    region_descriptors: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Capture raw Page/Region facts without evaluating any condition."""
    evaluated = await session.send(
        "Runtime.evaluate",
        {
            "expression": (
                "({url:String(location.href),title:String(document.title),"
                "ready_state:String(document.readyState)})"
            ),
            "returnByValue": True,
        },
    )
    result = evaluated.get("result") if isinstance(evaluated, dict) else None
    page = result.get("value") if isinstance(result, dict) else None
    if not isinstance(page, dict):
        raise RuntimeError("condition_page_facts_unavailable")
    generation = await _control_document_generation(session)
    raw_regions: list[dict[str, Any]] = []
    coverage = "COMPLETE"
    if region_descriptors:
        capture = await build_canonical_snapshot(session)
        coverage = capture.coverage
        for descriptor in region_descriptors:
            owner_chain = tuple(
                str(item) for item in descriptor.get("owner_chain", ())
            )
            kind = str(descriptor.get("kind") or "")
            if not owner_chain or kind not in {"FRAME", "CONTENT", "OWNER"}:
                raise ValueError("condition_region_descriptor_invalid")
            names = tuple(
                target.name
                for target in capture.targets
                if tuple(target.owner_chain) == owner_chain
            )
            text = normalize_visible_text(" ".join(names))
            raw_regions.append(
                {
                    "key": str(descriptor.get("key") or ""),
                    "kind": kind,
                    "owner_chain": list(owner_chain),
                    "text": text,
                    "item_count": len(names),
                    "digest": hashlib.sha256(text.encode()).hexdigest(),
                    "coverage": capture.coverage,
                },
            )
    return {
        "page": {
            "url": str(page.get("url") or ""),
            "title": str(page.get("title") or ""),
            "document_generation": generation,
            "ready_state": str(page.get("ready_state") or "loading"),
        },
        "regions": raw_regions,
        "coverage": coverage,
    }


async def _send_with_timeout(
    session: Any,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float,
) -> dict[str, Any]:
    bounded_timeout = max(float(timeout), 0.1)
    try:
        return await asyncio.wait_for(
            session.send(method, params or {}),
            timeout=bounded_timeout,
        )
    except asyncio.TimeoutError as exc:
        raise DOMSettleTimeout(
            f"{method} did not complete before {bounded_timeout}s",
        ) from exc


def _dom_action_semantic_text(attributes: dict[str, str]) -> str:
    source = " ".join(
        str(attributes.get(name) or "")
        for name in (
            "aria-label",
            "title",
            "alt",
            "data-title",
            "data-action",
            "data-role",
            "data-testid",
            "data-test",
            "id",
            "class",
            "href",
        )
    )
    if not source.strip():
        return ""
    labels = [
        label
        for pattern, label in (
            (
                r"(?:add|plus)[-_\s]*(?:to[-_\s]*)?cart|"
                r"cart[-_\s]*(?:add|plus)|addcart|cartadd",
                "add cart",
            ),
            (
                r"select[-_\s]*all|all[-_\s]*select|check[-_\s]*all|全选",
                "select all",
            ),
            (r"delete|remove|clear|删除|清空", "delete"),
            (
                r"checkbox|check[-_\s]*box|item[-_\s]*(?:check|select)|勾选|选择",
                "checkbox",
            ),
            (r"cart|basket|购物车", "cart"),
            (r"buy[-_\s]*now|buy|purchase|购买|立即|马上", "buy"),
            (r"checkout|settle|结算", "checkout"),
            (r"submit|提交", "submit"),
            (r"confirm|ok|确定|确认", "confirm"),
            (r"search|搜索", "search"),
            (r"sku|spec|variant|option|select", "option"),
        )
        if re.search(pattern, source, re.IGNORECASE)
    ][:3]
    for preferred in (
        "add cart",
        "select all",
        "delete",
        "checkbox",
        "buy",
    ):
        if preferred in labels:
            return preferred
    return " ".join(dict.fromkeys(labels))


__all__ = [
    "build_canonical_snapshot",
    "capture_condition_probe_facts",
]
