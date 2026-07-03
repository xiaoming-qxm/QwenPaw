# -*- coding: utf-8 -*-
"""Compatibility exports for Browser SDK snapshot helpers."""

from qwenpaw.browser_sdk._snapshot import (
    build_role_snapshot_from_aria,
    from_cdp_ax_tree,
    from_cdp_dom_snapshot,
    from_cdp_dom_tree,
    is_trivial_snapshot,
    refs_from_snapshot_payload,
)

__all__ = [
    "build_role_snapshot_from_aria",
    "from_cdp_ax_tree",
    "from_cdp_dom_snapshot",
    "from_cdp_dom_tree",
    "is_trivial_snapshot",
    "refs_from_snapshot_payload",
]
