# -*- coding: utf-8 -*-
"""Structured browser actions for the unified Browser SDK."""
# pylint: disable=protected-access

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from ..contract_runtime import BrowserContractRuntime
from ..contracts import BrowserTargetContract, browser_api
from ..primitives.types import BrowserActionResult

_TARGET_METHODS = ("ref", "role_name", "text_exact", "coords")
_REQUIRED_TARGET = BrowserTargetContract(
    required=True,
    methods=_TARGET_METHODS,
    snapshot_bound=True,
)
_OPTIONAL_TARGET = BrowserTargetContract(
    required=False,
    methods=_TARGET_METHODS,
    snapshot_bound=True,
)


class BrowserActions:
    """Browser-level generic actions."""

    def __init__(self, browser: Any) -> None:
        self._browser = browser

    @browser_api(
        public_name="browser.actions.search_web",
        kind="action",
        mutates=True,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=True,
    )
    async def search_web(
        self,
        query: str,
        *,
        engine: str = "google",
    ) -> BrowserActionResult:
        """Search the public web using the selected backend."""
        contract = getattr(self.search_web, "__browser_api_contract__")

        async def dispatch(query: str, engine: str = "google") -> Any:
            search_url = _search_url(query, engine)
            tab = await self._browser.tabs.open(search_url)
            tab_id = getattr(tab, "id", getattr(tab, "tab_id", ""))
            return BrowserActionResult(
                ok=True,
                message=f"Opened {engine} search for {query}",
                data={"url": search_url, "tab_id": str(tab_id or "")},
            )

        return _coerce_action_result(
            await BrowserContractRuntime().execute(
                contract,
                dispatch,
                owner=self._browser,
                query=query,
                engine=engine,
            ),
        )


class TabActions:
    """Tab-level generic actions."""

    def __init__(self, tab: Any) -> None:
        self._tab = tab

    @browser_api(
        public_name="tab.actions.navigate",
        kind="action",
        mutates=True,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=True,
        backend_op="navigate",
    )
    async def navigate(self, url: str) -> BrowserActionResult:
        return await self._run(self.navigate, url=url)

    @browser_api(
        public_name="tab.actions.back",
        kind="action",
        mutates=True,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=True,
        backend_op="back",
    )
    async def back(self) -> BrowserActionResult:
        return await self._run(self.back)

    @browser_api(
        public_name="tab.actions.forward",
        kind="action",
        mutates=True,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=True,
        backend_op="forward",
    )
    async def forward(self) -> BrowserActionResult:
        return await self._run(self.forward)

    @browser_api(
        public_name="tab.actions.reload",
        kind="action",
        mutates=True,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=True,
        backend_op="reload",
    )
    async def reload(self) -> BrowserActionResult:
        return await self._run(self.reload)

    @browser_api(
        public_name="tab.actions.click",
        kind="action",
        mutates=True,
        requires_observation=True,
        satisfies_observation=False,
        invalidates_observation=True,
        target=_REQUIRED_TARGET,
        backend_op="click",
    )
    async def click(
        self,
        target: dict[str, Any],
        *,
        allow_new_context: bool = False,
    ) -> BrowserActionResult:
        kwargs: dict[str, Any] = {"target": target}
        if allow_new_context:
            kwargs["allow_new_context"] = True
        return await self._run(self.click, **kwargs)

    @browser_api(
        public_name="tab.actions.fill",
        kind="action",
        mutates=True,
        requires_observation=True,
        satisfies_observation=False,
        invalidates_observation=True,
        target=_REQUIRED_TARGET,
        backend_op="type",
    )
    async def fill(
        self,
        target: dict[str, Any],
        text: str,
    ) -> BrowserActionResult:
        return await self._run(self.fill, target=target, text=text)

    @browser_api(
        public_name="tab.actions.press_key",
        kind="action",
        mutates=True,
        requires_observation=True,
        satisfies_observation=False,
        invalidates_observation=True,
        backend_op="press",
    )
    async def press_key(self, key: str) -> BrowserActionResult:
        return await self._run(self.press_key, key=key)

    @browser_api(
        public_name="tab.actions.scroll",
        kind="action",
        mutates=True,
        requires_observation=True,
        satisfies_observation=False,
        invalidates_observation=True,
        backend_op="scroll",
    )
    async def scroll(
        self,
        direction: str = "down",
        amount: Any = None,
    ) -> BrowserActionResult:
        kwargs: dict[str, Any] = {"direction": direction}
        if amount is not None:
            kwargs["amount"] = amount
        return await self._run(self.scroll, **kwargs)

    @browser_api(
        public_name="tab.actions.select_option",
        kind="action",
        mutates=True,
        requires_observation=True,
        satisfies_observation=False,
        invalidates_observation=True,
        target=_REQUIRED_TARGET,
        backend_op="select",
    )
    async def select_option(
        self,
        target: dict[str, Any],
        value: Any,
    ) -> BrowserActionResult:
        return await self._run(
            self.select_option,
            target=target,
            value=value,
        )

    @browser_api(
        public_name="tab.actions.upload_file",
        kind="action",
        mutates=True,
        requires_observation=True,
        satisfies_observation=False,
        invalidates_observation=True,
        target=_REQUIRED_TARGET,
        backend_op="upload",
    )
    async def upload_file(
        self,
        target: dict[str, Any],
        file_path: str | list[str],
    ) -> BrowserActionResult:
        return await self._run(
            self.upload_file,
            target=target,
            file_path=file_path,
        )

    @browser_api(
        public_name="tab.actions.download_file",
        kind="action",
        mutates=False,
        requires_observation=True,
        satisfies_observation=False,
        invalidates_observation=False,
        target=_OPTIONAL_TARGET,
        backend_op="download",
    )
    async def download_file(
        self,
        target: dict[str, Any] | None = None,
        timeout_ms: int = 30000,
    ) -> BrowserActionResult:
        return await self._run(
            self.download_file,
            mutating_override=target is not None,
            transition=True,
            target=target,
            timeout_ms=timeout_ms,
        )

    @browser_api(
        public_name="tab.actions.handle_dialog",
        kind="action",
        mutates=False,
        requires_observation=False,
        satisfies_observation=False,
        invalidates_observation=False,
        backend_op="dialog",
    )
    async def handle_dialog(
        self,
        accept: bool = True,
        prompt_text: str | None = None,
    ) -> BrowserActionResult:
        return await self._run(
            self.handle_dialog,
            mutating_override=accept,
            transition=accept,
            accept=accept,
            prompt_text=prompt_text,
        )

    @browser_api(
        public_name="tab.actions.hover",
        kind="action",
        mutates=True,
        requires_observation=True,
        satisfies_observation=False,
        invalidates_observation=True,
        target=_REQUIRED_TARGET,
        backend_op="hover",
    )
    async def hover(self, target: dict[str, Any]) -> BrowserActionResult:
        return await self._run(self.hover, target=target)

    async def wait_for(
        self,
        instruction: str,
        max_wait_ms: int = 10000,
    ) -> BrowserActionResult:
        return await self._run_backend(
            "wait_for",
            mutating=False,
            transition=True,
            instruction=instruction,
            max_wait_ms=max_wait_ms,
        )

    async def _run(
        self,
        method: Any,
        *,
        mutating_override: bool | None = None,
        transition: bool = False,
        **kwargs: Any,
    ) -> BrowserActionResult:
        contract = method.__browser_api_contract__
        backend_name = (
            contract.backend_op or contract.api_id.rsplit(".", 1)[-1]
        )
        mutating = (
            contract.mutates
            if mutating_override is None
            else mutating_override
        )

        async def dispatch(**call_kwargs: Any) -> Any:
            if mutating:
                self._tab._ensure_can_mutate(backend_name)
            return await self._tab._call_action(
                backend_name,
                **_backend_action_kwargs(call_kwargs),
            )

        result = _coerce_action_result(
            await BrowserContractRuntime().execute(
                contract,
                dispatch,
                owner=self._tab,
                **kwargs,
            ),
        )
        if (
            mutating or (transition and result.ok)
        ) and not contract.invalidates_observation:
            self._tab._mark_mutated()
        return result

    async def _run_backend(
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


def _backend_action_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    backend_kwargs = dict(kwargs)
    target = backend_kwargs.pop("target", None)
    timeout_ms = backend_kwargs.pop("timeout_ms", None)
    if isinstance(target, dict):
        backend_kwargs = {**target, **backend_kwargs}
    if timeout_ms is not None:
        backend_kwargs["max_wait_ms"] = timeout_ms
    return backend_kwargs


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


def _search_url(query: str, engine: str) -> str:
    encoded = quote_plus(query)
    normalized_engine = str(engine or "google").strip().casefold()
    if normalized_engine in {"bing", "microsoft"}:
        return f"https://www.bing.com/search?q={encoded}"
    if normalized_engine in {"duckduckgo", "ddg"}:
        return f"https://duckduckgo.com/?q={encoded}"
    return f"https://www.google.com/search?q={encoded}"


__all__ = ["BrowserActions", "TabActions"]
