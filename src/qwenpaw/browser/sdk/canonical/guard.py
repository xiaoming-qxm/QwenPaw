# -*- coding: utf-8 -*-
"""Canonical browser(code=...) capability guard."""

from __future__ import annotations

from ..runtime.guard import CapabilityGuard


class CanonicalCapabilityGuard(CapabilityGuard):
    """Mode-specific guard type for canonical namespaces."""


__all__ = ["CanonicalCapabilityGuard"]
