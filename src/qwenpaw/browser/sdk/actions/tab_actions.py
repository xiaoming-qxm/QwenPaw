# -*- coding: utf-8 -*-
"""Structured browser actions for the unified Browser SDK."""
# pylint: disable=protected-access

from __future__ import annotations

from typing import Any

from ..governance.errors import BrowserSDKGap
from ..primitives.types import BrowserActionResult


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
        return await self.navigate(url)

    async def navigate(self, url: str) -> BrowserActionResult:
        return await self._mutate("navigate", url=url)

    async def back(self) -> BrowserActionResult:
        return await self._mutate("back")

    async def forward(self) -> BrowserActionResult:
        return await self._mutate("forward")

    async def reload(self) -> BrowserActionResult:
        return await self._mutate("reload")

    async def click(
        self,
        target: Any,
        *,
        allow_new_context: bool = False,
    ) -> BrowserActionResult:
        kwargs = _target_kwargs(target)
        if allow_new_context:
            kwargs["allow_new_context"] = True
        _ensure_target("click", kwargs)
        return await self._mutate("click", **kwargs)

    async def type(self, target: Any, text: str) -> BrowserActionResult:
        kwargs = _target_kwargs(target)
        _ensure_target("type", kwargs)
        return await self._mutate("type", **kwargs, text=text)

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
        kwargs = _target_kwargs(target)
        _ensure_target("select", kwargs)
        return await self._mutate("select", **kwargs, value=value)

    async def upload(
        self,
        target: Any,
        file_path: str | list[str],
    ) -> BrowserActionResult:
        kwargs = _target_kwargs(target)
        _ensure_target("upload", kwargs)
        return await self._mutate("upload", **kwargs, file_path=file_path)

    async def download(
        self,
        target: Any | None = None,
        max_wait_ms: int = 30000,
    ) -> BrowserActionResult:
        kwargs: dict[str, Any] = {"max_wait_ms": max_wait_ms}
        if target is not None:
            kwargs.update(_target_kwargs(target))
        return await self._run(
            "download",
            mutating=target is not None,
            transition=True,
            **kwargs,
        )

    async def dialog(
        self,
        accept: bool = True,
        prompt_text: str | None = None,
    ) -> BrowserActionResult:
        return await self._run(
            "dialog",
            mutating=accept,
            transition=accept,
            accept=accept,
            prompt_text=prompt_text,
        )

    async def hover(self, target: Any) -> BrowserActionResult:
        kwargs = _target_kwargs(target)
        _ensure_target("hover", kwargs)
        return await self._mutate("hover", **kwargs)

    async def wait_for(
        self,
        instruction: str,
        max_wait_ms: int = 10000,
    ) -> BrowserActionResult:
        return await self._run(
            "wait_for",
            mutating=False,
            transition=True,
            instruction=instruction,
            max_wait_ms=max_wait_ms,
        )

    async def _mutate(self, name: str, **kwargs: Any) -> BrowserActionResult:
        return await self._run(name, mutating=True, **kwargs)

    async def _run(
        self,
        name: str,
        *,
        mutating: bool,
        transition: bool = False,
        **kwargs: Any,
    ) -> BrowserActionResult:
        if mutating:
            self._tab._ensure_can_mutate(name)
        result = _coerce_action_result(
            await self._tab._call_action(name, **kwargs),
        )
        if mutating or (transition and result.ok):
            self._tab._mark_mutated()
        return result


def _target_kwargs(target: Any) -> dict[str, Any]:
    if isinstance(target, dict):
        return dict(target)
    return {"target": target}


def _ensure_target(action: str, kwargs: dict[str, Any]) -> None:
    if _has_target(kwargs):
        return
    raise BrowserSDKGap(
        f"{action} target is required. Provide a selector, ref, text, "
        "target string, or x/y viewport coordinates.",
        action=action,
        metadata={
            "expected_target_keys": ("target", "selector", "ref", "text"),
            "expected_coordinate_keys": ("x", "y"),
        },
    )


def _has_target(kwargs: dict[str, Any]) -> bool:
    for key in ("target", "selector", "ref", "text"):
        if str(kwargs.get(key) or "").strip():
            return True
    return kwargs.get("x") is not None and kwargs.get("y") is not None


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
