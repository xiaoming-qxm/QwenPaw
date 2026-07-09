# -*- coding: utf-8 -*-
"""Safe Browser SDK proxies for browser(code=...) runtimes."""

from __future__ import annotations

from typing import Any, NoReturn
from weakref import WeakKeyDictionary

from ..governance.errors import BrowserPolicyDenied

_RAW_TARGETS: WeakKeyDictionary[object, Any] = WeakKeyDictionary()
_MAGIC_ALLOWED = frozenset(
    {
        "__bool__",
        "__class__",
        "__hash__",
        "__repr__",
        "__str__",
        "__weakref__",
    },
)
_RECOVERY_HINT = (
    "Use canonical Browser SDK methods: Browser.connect, "
    "browser.tabs.open, tab.snapshot, and tab.actions.click."
)


class BrowserProxyClass:
    """Runtime-visible Browser factory exposing safe class APIs."""

    @classmethod
    async def connect(cls, *args: Any, **kwargs: Any) -> "BrowserProxy":
        from ..facade.browser import Browser

        return wrap_browser(await Browser.connect(*args, **kwargs))

    @classmethod
    def capabilities(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        from ..facade.browser import Browser

        return Browser.capabilities(*args, **kwargs)

    @classmethod
    def help(cls, *args: Any, **kwargs: Any) -> str:
        from ..facade.browser import Browser

        return Browser.help(*args, **kwargs)

    @classmethod
    async def diagnostics(cls, *args: Any, **kwargs: Any) -> Any:
        from ..facade.browser import Browser

        return await Browser.diagnostics(*args, **kwargs)


async def connect_browser(*args: Any, **kwargs: Any) -> "BrowserProxy":
    """Connect through the raw SDK and return a safe browser proxy."""
    from ..facade.browser import connect_browser as raw_connect_browser

    return wrap_browser(await raw_connect_browser(*args, **kwargs))


class _ProxyBase:
    """Base object that denies every attribute outside an allowlist."""

    __slots__ = ("__weakref__",)
    ALLOWED_NAMES: frozenset[str] = frozenset()

    def __getattribute__(self, name: str) -> Any:
        if name in _MAGIC_ALLOWED:
            return object.__getattribute__(self, name)
        allowed = object.__getattribute__(
            object.__getattribute__(self, "__class__"),
            "ALLOWED_NAMES",
        )
        if name in allowed:
            return object.__getattribute__(self, name)
        _deny(name)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"


class BrowserProxy(_ProxyBase):
    """Safe proxy for a connected browser facade."""

    ALLOWED_NAMES = frozenset(
        {
            "actions",
            "backend_id",
            "close",
            "context",
            "release",
            "preserve",
            "retention",
            "session_id",
            "stop",
            "tabs",
        },
    )

    @property
    def tabs(self) -> "BrowserTabsProxy":
        return wrap_tabs(_raw(self).tabs)

    @property
    def actions(self) -> "BrowserActionsProxy":
        return wrap_browser_actions(_raw(self).actions)

    @property
    def backend_id(self) -> str:
        return str(getattr(_raw(self), "backend_id", ""))

    @property
    def session_id(self) -> str:
        return str(getattr(_raw(self), "session_id", ""))

    @property
    def context(self) -> Any:
        return getattr(_raw(self), "context", None)

    @property
    def retention(self) -> str:
        return str(getattr(_raw(self), "retention", ""))

    async def close(self) -> Any:
        return await _raw(self).close()

    async def release(self) -> Any:
        return await _raw(self).release()

    async def preserve(self) -> Any:
        return await _raw(self).preserve()

    async def stop(self) -> Any:
        return await _raw(self).stop()


class BrowserTabsProxy(_ProxyBase):
    """Safe proxy for browser tab primitives."""

    ALLOWED_NAMES = frozenset({"active", "list", "new", "open", "select"})

    async def open(self, url: str | None = None) -> "TabProxy":
        return wrap_tab(await _raw(self).open(url))

    async def new(self, url: str | None = None) -> "TabProxy":
        return wrap_tab(await _raw(self).new(url))

    async def active(self) -> "TabProxy":
        return wrap_tab(await _raw(self).active())

    async def list(self) -> list["TabProxy"]:  # type: ignore[valid-type]
        return [wrap_tab(tab) for tab in await _raw(self).list()]

    async def select(self, tab_id: str) -> "TabProxy":
        return wrap_tab(await _raw(self).select(tab_id))


class TabProxy(_ProxyBase):
    """Safe proxy for one browser tab."""

    ALLOWED_NAMES = frozenset(
        {
            "actions",
            "close",
            "extract",
            "id",
            "page_info",
            "screenshot",
            "snapshot",
            "tab_id",
            "title",
            "url",
            "wait_for",
        },
    )

    @property
    def id(self) -> str:
        return str(getattr(_raw(self), "id", ""))

    @property
    def tab_id(self) -> str:
        return str(getattr(_raw(self), "tab_id", self.id))

    @property
    def url(self) -> str:
        return str(getattr(_raw(self), "url", ""))

    @property
    def title(self) -> str:
        return str(getattr(_raw(self), "title", ""))

    @property
    def actions(self) -> "TabActionsProxy":
        return wrap_tab_actions(_raw(self).actions)

    async def snapshot(self) -> Any:
        return await _raw(self).snapshot()

    async def screenshot(self) -> Any:
        return await _raw(self).screenshot()

    async def page_info(self) -> Any:
        return await _raw(self).page_info()

    async def extract(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).extract(*args, **kwargs)

    async def wait_for(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).wait_for(*args, **kwargs)

    async def close(self) -> Any:
        return await _raw(self).close()


class BrowserActionsProxy(_ProxyBase):
    """Safe proxy for browser-level canonical actions."""

    ALLOWED_NAMES = frozenset({"search_web"})

    async def search_web(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).search_web(*args, **kwargs)


class TabActionsProxy(_ProxyBase):
    """Safe proxy for tab-level canonical actions."""

    ALLOWED_NAMES = frozenset(
        {
            "back",
            "click",
            "download_file",
            "fill",
            "forward",
            "handle_dialog",
            "hover",
            "navigate",
            "press_key",
            "reload",
            "scroll",
            "select_option",
            "upload_file",
        },
    )

    async def navigate(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).navigate(*args, **kwargs)

    async def back(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).back(*args, **kwargs)

    async def forward(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).forward(*args, **kwargs)

    async def reload(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).reload(*args, **kwargs)

    async def click(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).click(*args, **kwargs)

    async def fill(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).fill(*args, **kwargs)

    async def press_key(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).press_key(*args, **kwargs)

    async def scroll(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).scroll(*args, **kwargs)

    async def select_option(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).select_option(*args, **kwargs)

    async def hover(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).hover(*args, **kwargs)

    async def upload_file(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).upload_file(*args, **kwargs)

    async def download_file(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).download_file(*args, **kwargs)

    async def handle_dialog(self, *args: Any, **kwargs: Any) -> Any:
        return await _raw(self).handle_dialog(*args, **kwargs)


def wrap_browser(raw: Any) -> BrowserProxy:
    if isinstance(raw, BrowserProxy):
        return raw
    return _bind(BrowserProxy(), raw)


def wrap_tabs(raw: Any) -> BrowserTabsProxy:
    if isinstance(raw, BrowserTabsProxy):
        return raw
    return _bind(BrowserTabsProxy(), raw)


def wrap_tab(raw: Any) -> TabProxy:
    if isinstance(raw, TabProxy):
        return raw
    return _bind(TabProxy(), raw)


def wrap_browser_actions(raw: Any) -> BrowserActionsProxy:
    if isinstance(raw, BrowserActionsProxy):
        return raw
    return _bind(BrowserActionsProxy(), raw)


def wrap_tab_actions(raw: Any) -> TabActionsProxy:
    if isinstance(raw, TabActionsProxy):
        return raw
    return _bind(TabActionsProxy(), raw)


def _bind(proxy: Any, raw: Any) -> Any:
    _RAW_TARGETS[proxy] = raw
    return proxy


def _raw(proxy: object) -> Any:
    return _RAW_TARGETS[proxy]


def _deny(attribute: str) -> NoReturn:
    raise BrowserPolicyDenied(
        f"Browser runtime proxy does not expose attribute: {attribute}",
        code="invalid_sdk_usage",
        action="browser_runtime_proxy",
        metadata={
            "attribute": attribute,
            "pattern": "runtime_safe_proxy",
            "recovery_hint": _RECOVERY_HINT,
        },
    )


__all__ = [
    "BrowserActionsProxy",
    "BrowserProxy",
    "BrowserProxyClass",
    "BrowserTabsProxy",
    "TabActionsProxy",
    "TabProxy",
    "connect_browser",
    "wrap_browser",
]
