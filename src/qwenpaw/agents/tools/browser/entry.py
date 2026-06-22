# -*- coding: utf-8 -*-
# mypy: ignore-errors
"""Unified browser tool entry point."""

from .namespace import *  # noqa: F401,F403

__all__ = [name for name in globals() if not name.startswith("__")]
