# -*- coding: utf-8 -*-
"""Sync/async Playwright compatibility helpers."""

from __future__ import annotations

import asyncio
from concurrent import futures
import sys
from typing import Any, Optional

from ....constant import EnvVarLoader

_USE_SYNC_PLAYWRIGHT = sys.platform == "win32" and EnvVarLoader.get_bool(
    "QWENPAW_RELOAD_MODE",
)

if _USE_SYNC_PLAYWRIGHT:
    _executor: Optional[futures.ThreadPoolExecutor] = None

    def _get_executor() -> futures.ThreadPoolExecutor:
        global _executor
        if _executor is None:
            _executor = futures.ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="playwright",
            )
        return _executor

    async def _run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a sync function in the Playwright compatibility executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _get_executor(),
            lambda: func(*args, **kwargs),
        )

else:

    async def _run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
        """Call an async function in normal async Playwright mode."""
        return await func(*args, **kwargs)
