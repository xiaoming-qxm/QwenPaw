# -*- coding: utf-8 -*-
"""Safe Browser SDK proxies for browser(code=...) runtimes."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn
from weakref import WeakKeyDictionary

from ..governance.errors import BrowserPolicyDenied

_RAW_TARGETS: WeakKeyDictionary[object, Any] = WeakKeyDictionary()
_CALL_BINDINGS: WeakKeyDictionary[object, "_CallBinding"] = WeakKeyDictionary()
_RECOVERY_HINT = (
    "Use canonical Browser SDK methods: Browser.connect, "
    "browser.tabs.open, tab.snapshot, and tab.actions.click."
)
_SYNC = "sync"
_ASYNC = "async"


@dataclass(frozen=True)
class _CallBinding:
    """Private call target for runtime-visible safe callables."""

    call: Callable[..., Any]
    mode: str = _ASYNC
    wrap_result: Callable[[Any], Any] | None = None


class _SafeCallable:
    """Callable object that does not expose Python function internals."""

    __slots__ = ("__weakref__",)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        binding = _CALL_BINDINGS[self]
        if binding.mode == _SYNC:
            result = binding.call(*args, **kwargs)
            return _wrap_call_result(binding, result)
        return _invoke_async(binding, args, kwargs)

    def __getattribute__(self, name: str) -> Any:
        if name in {"__repr__", "__str__"}:
            return object.__getattribute__(self, name)
        _deny(name)

    def __repr__(self) -> str:
        return "<BrowserRuntimeCallable>"


class _BrowserFactoryProxy:
    """Runtime-visible Browser factory exposing safe class-like APIs."""

    __slots__ = ("__weakref__",)

    def __getattribute__(self, name: str) -> Any:
        if name in {"__repr__", "__str__"}:
            return object.__getattribute__(self, name)
        if name == "connect":
            return _bind_callable(_CallBinding(_connect_browser_raw))
        if name == "capabilities":
            return _bind_callable(_CallBinding(_browser_capabilities, _SYNC))
        if name == "help":
            return _bind_callable(_CallBinding(_browser_help, _SYNC))
        if name == "diagnostics":
            return _bind_callable(_CallBinding(_browser_diagnostics))
        _deny(name)

    def __repr__(self) -> str:
        return "<BrowserProxyClass>"


BrowserProxyClass = _BrowserFactoryProxy()


class _ProxyBase:
    """Base object that denies every attribute outside an allowlist."""

    __slots__ = ("__weakref__",)
    PROPERTY_NAMES: frozenset[str] = frozenset()
    CALL_NAMES: frozenset[str] = frozenset()

    def __getattribute__(self, name: str) -> Any:
        if name in {"__repr__", "__str__"}:
            return object.__getattribute__(self, name)
        cls = type(self)
        if name in cls.PROPERTY_NAMES:
            return cls._property_value(self, name)
        if name in cls.CALL_NAMES:
            return cls._callable_value(self, name)
        _deny(name)

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"

    @classmethod
    def _property_value(cls, _proxy: "_ProxyBase", name: str) -> Any:
        _deny(name)

    @classmethod
    def _callable_value(cls, proxy: "_ProxyBase", name: str) -> _SafeCallable:
        raw = _raw(proxy)
        return _bind_callable(_CallBinding(getattr(raw, name)))


class BrowserProxy(_ProxyBase):
    """Safe proxy for a connected browser facade."""

    PROPERTY_NAMES = frozenset(
        {
            "actions",
            "backend_id",
            "context",
            "retention",
            "session_id",
            "tabs",
        },
    )
    CALL_NAMES = frozenset({"close", "release", "preserve", "stop"})

    @classmethod
    def _property_value(cls, proxy: _ProxyBase, name: str) -> Any:
        raw = _raw(proxy)
        if name == "tabs":
            return wrap_tabs(raw.tabs)
        if name == "actions":
            return wrap_browser_actions(raw.actions)
        if name == "backend_id":
            return str(getattr(raw, "backend_id", ""))
        if name == "session_id":
            return str(getattr(raw, "session_id", ""))
        if name == "context":
            return getattr(raw, "context", None)
        if name == "retention":
            return str(getattr(raw, "retention", ""))
        _deny(name)


class BrowserTabsProxy(_ProxyBase):
    """Safe proxy for browser tab primitives."""

    CALL_NAMES = frozenset({"active", "list", "new", "open", "select"})

    @classmethod
    def _callable_value(cls, proxy: _ProxyBase, name: str) -> _SafeCallable:
        return _bind_callable(
            _CallBinding(
                getattr(_raw(proxy), name),
                wrap_result=_wrap_tabs_call,
            ),
        )


class TabProxy(_ProxyBase):
    """Safe proxy for one browser tab."""

    PROPERTY_NAMES = frozenset({"actions", "id", "tab_id", "title", "url"})
    CALL_NAMES = frozenset(
        {
            "close",
            "extract",
            "page_info",
            "screenshot",
            "snapshot",
            "wait_for",
        },
    )

    @classmethod
    def _property_value(cls, proxy: _ProxyBase, name: str) -> Any:
        raw = _raw(proxy)
        if name == "id":
            return str(getattr(raw, "id", ""))
        if name == "tab_id":
            return str(
                getattr(raw, "tab_id", cls._property_value(proxy, "id")),
            )
        if name == "url":
            return str(getattr(raw, "url", ""))
        if name == "title":
            return str(getattr(raw, "title", ""))
        if name == "actions":
            return wrap_tab_actions(raw.actions)
        _deny(name)


class BrowserActionsProxy(_ProxyBase):
    """Safe proxy for browser-level canonical actions."""

    CALL_NAMES = frozenset({"search_web"})


class TabActionsProxy(_ProxyBase):
    """Safe proxy for tab-level canonical actions."""

    CALL_NAMES = frozenset(
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


async def _connect_browser_raw(*args: Any, **kwargs: Any) -> BrowserProxy:
    from ..facade.browser import Browser

    return wrap_browser(await Browser.connect(*args, **kwargs))


async def _connect_browser_alias(*args: Any, **kwargs: Any) -> BrowserProxy:
    from ..facade.browser import connect_browser as raw_connect_browser

    return wrap_browser(await raw_connect_browser(*args, **kwargs))


def _browser_capabilities(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from ..facade.browser import Browser

    return Browser.capabilities(*args, **kwargs)


def _browser_help(*args: Any, **kwargs: Any) -> str:
    from ..facade.browser import Browser

    return Browser.help(*args, **kwargs)


async def _browser_diagnostics(*args: Any, **kwargs: Any) -> Any:
    from ..facade.browser import Browser

    return await Browser.diagnostics(*args, **kwargs)


async def _invoke_async(
    binding: _CallBinding,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    result = binding.call(*args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return _wrap_call_result(binding, result)


def _wrap_call_result(binding: _CallBinding, result: Any) -> Any:
    if binding.wrap_result is None:
        return result
    return binding.wrap_result(result)


def _wrap_tabs_call(result: Any) -> Any:
    if isinstance(result, list):
        return [wrap_tab(tab) for tab in result]
    return wrap_tab(result)


def _bind(proxy: Any, raw: Any) -> Any:
    _RAW_TARGETS[proxy] = raw
    return proxy


def _bind_callable(binding: _CallBinding) -> _SafeCallable:
    callable_proxy = _SafeCallable()
    _CALL_BINDINGS[callable_proxy] = binding
    return callable_proxy


connect_browser = _bind_callable(_CallBinding(_connect_browser_alias))


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
