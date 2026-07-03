# -*- coding: utf-8 -*-
"""Structured browser actions for the unified Browser SDK."""
# pylint: disable=protected-access

from __future__ import annotations

from typing import Any

from .types import BrowserActionResult


class BrowserActions:
    """Browser-level generic actions."""

    def __init__(self, browser: Any) -> None:
        self._browser = browser

    async def search(
        self,
        query: str,
        *,
        engine: str = "google",
    ) -> BrowserActionResult:
        """Search the public web using the selected backend."""
        result = await self._browser._call_browser_action(
            "search",
            query=query,
            engine=engine,
        )
        return _coerce_action_result(result)


class TabActions:
    """Tab-level generic actions."""

    def __init__(self, tab: Any) -> None:
        self._tab = tab

    async def open(self, url: str) -> BrowserActionResult:
        return await self._mutate("open", url=url)

    async def click(self, target: Any) -> BrowserActionResult:
        return await self._mutate("click", **_target_kwargs(target))

    async def type(self, target: Any, text: str) -> BrowserActionResult:
        return await self._mutate(
            "type",
            **_target_kwargs(target),
            text=text,
        )

    async def press(self, key: str) -> BrowserActionResult:
        return await self._mutate("press", key=key)

    async def scroll(
        self,
        direction: str = "down",
        amount: Any = None,
    ) -> BrowserActionResult:
        kwargs = {"direction": direction}
        if amount is not None:
            kwargs["amount"] = amount
        return await self._mutate("scroll", **kwargs)

    async def select(self, target: Any, value: Any) -> BrowserActionResult:
        return await self._mutate(
            "select",
            **_target_kwargs(target),
            value=value,
        )

    async def wait_for(
        self,
        instruction: str,
        timeout_ms: int = 10000,
    ) -> BrowserActionResult:
        return await self._run(
            "wait_for",
            mutating=False,
            instruction=instruction,
            timeout_ms=timeout_ms,
        )

    async def _mutate(self, name: str, **kwargs: Any) -> BrowserActionResult:
        return await self._run(name, mutating=True, **kwargs)

    async def _run(
        self,
        name: str,
        *,
        mutating: bool,
        **kwargs: Any,
    ) -> BrowserActionResult:
        if mutating:
            self._tab._ensure_can_mutate(name)
        result = _coerce_action_result(
            await self._tab._call_action(name, **kwargs),
        )
        if mutating:
            self._tab._mark_mutated()
        return result


def _target_kwargs(target: Any) -> dict[str, Any]:
    if isinstance(target, dict):
        return dict(target)
    return {"target": target}


def _coerce_action_result(value: Any) -> BrowserActionResult:
    if isinstance(value, BrowserActionResult):
        return value
    if isinstance(value, dict):
        return BrowserActionResult(
            ok=bool(value.get("ok", True)),
            message=str(
                value.get("message")
                or value.get("next_instruction")
                or value.get("error")
                or "",
            ),
            needs_observation=bool(value.get("needs_observation", True)),
            data=dict(value.get("data") or {}),
        )
    return BrowserActionResult(ok=True, message=str(value or ""))


__all__ = ["BrowserActions", "TabActions"]
