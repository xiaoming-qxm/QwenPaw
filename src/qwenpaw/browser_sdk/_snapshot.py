# -*- coding: utf-8 -*-
"""Snapshot helpers shared by Browser SDK backends."""

from __future__ import annotations

from typing import Any

INTERACTIVE_ROLES = frozenset(
    {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "combobox",
        "listbox",
        "menuitem",
        "menuitemcheckbox",
        "menuitemradio",
        "option",
        "searchbox",
        "slider",
        "spinbutton",
        "switch",
        "tab",
        "treeitem",
    },
)


def build_role_snapshot_from_aria(*args: Any, **kwargs: Any) -> Any:
    """Build a role snapshot from a Playwright ARIA snapshot."""
    from qwenpaw.agents.tools.browser_snapshot import (
        build_role_snapshot_from_aria as _build,
    )

    return _build(*args, **kwargs)


def from_cdp_ax_tree(*args: Any, **kwargs: Any) -> Any:
    """Build a snapshot from a Chrome DevTools accessibility tree."""
    from qwenpaw.agents.tools.browser_snapshot import (
        from_cdp_ax_tree as _build,
    )

    return _build(*args, **kwargs)


def from_cdp_dom_tree(*args: Any, **kwargs: Any) -> Any:
    """Build a snapshot from a Chrome DevTools DOM tree."""
    from qwenpaw.agents.tools.browser_snapshot import (
        from_cdp_dom_tree as _build,
    )

    return _build(*args, **kwargs)


def from_cdp_dom_snapshot(*args: Any, **kwargs: Any) -> Any:
    """Build a snapshot from a Chrome DevTools DOM snapshot."""
    from qwenpaw.agents.tools.browser_snapshot import (
        from_cdp_dom_snapshot as _build,
    )

    return _build(*args, **kwargs)


def is_trivial_snapshot(snapshot: str, *, min_length: int = 50) -> bool:
    """Return true when structured evidence is too small to act on."""
    text = str(snapshot or "").strip()
    return not text or text == "(empty)" or len(text) < min_length


def refs_from_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return refs from a snapshot-like payload."""
    refs = payload.get("refs")
    return refs if isinstance(refs, dict) else {}


__all__ = [
    "build_role_snapshot_from_aria",
    "from_cdp_ax_tree",
    "from_cdp_dom_snapshot",
    "from_cdp_dom_tree",
    "INTERACTIVE_ROLES",
    "is_trivial_snapshot",
    "refs_from_snapshot_payload",
]
