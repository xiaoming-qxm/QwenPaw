# -*- coding: utf-8 -*-
"""Public data types for the Browser Control SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RefInfo:
    """Information about one interactive snapshot reference."""

    role: str
    name: str
    x: float
    y: float
    bounds: tuple[float, float, float, float] | None = None
    href: str = ""
    target: str = ""


@dataclass(frozen=True)
class Snapshot(dict):
    """Text snapshot plus ref metadata for one browser tab."""

    text: str
    refs: dict[str, RefInfo]
    degraded: bool

    def __post_init__(self) -> None:
        dict.__init__(self, self.to_jsonable())

    def __str__(self) -> str:
        return self.text

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str) and key in {
            "text",
            "refs",
            "items",
            "degraded",
        }:
            return self._mapping_value(key)
        return self.text[key]

    def __contains__(self, value: object) -> bool:
        if isinstance(value, str) and value in {
            "text",
            "refs",
            "items",
            "degraded",
        }:
            return True
        if not isinstance(value, str):
            return False
        return value in self.text

    def get(self, key: str, default: Any = None) -> Any:
        if key in {"text", "refs", "items", "degraded"}:
            return self._mapping_value(key)
        return default

    def split(self, *args: Any, **kwargs: Any) -> list[str]:
        return self.text.split(*args, **kwargs)

    def splitlines(self, *args: Any, **kwargs: Any) -> list[str]:
        return self.text.splitlines(*args, **kwargs)

    def find(self, *args: Any, **kwargs: Any) -> int:
        return self.text.find(*args, **kwargs)

    def lower(self) -> str:
        return self.text.lower()

    def strip(self, *args: Any, **kwargs: Any) -> str:
        return self.text.strip(*args, **kwargs)

    def startswith(self, *args: Any, **kwargs: Any) -> bool:
        return self.text.startswith(*args, **kwargs)

    def endswith(self, *args: Any, **kwargs: Any) -> bool:
        return self.text.endswith(*args, **kwargs)

    def replace(self, *args: Any, **kwargs: Any) -> str:
        return self.text.replace(*args, **kwargs)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "refs": {
                ref: self._ref_payload(ref, info)
                for ref, info in self.refs.items()
            },
            "items": self._items_payload(),
            "degraded": self.degraded,
        }

    def _mapping_value(self, key: str) -> Any:
        if key == "items":
            return self._items_payload()
        if key == "refs":
            return {
                ref: self._ref_payload(ref, info)
                for ref, info in self.refs.items()
            }
        return getattr(self, key)

    def _items_payload(self) -> list[dict[str, Any]]:
        return [
            self._ref_payload(ref, info) for ref, info in self.refs.items()
        ]

    @staticmethod
    def _ref_payload(ref: str, info: RefInfo) -> dict[str, Any]:
        payload = {
            "ref": ref,
            "role": info.role,
            "tag": info.role,
            "name": info.name,
            "text": info.name,
            "x": info.x,
            "y": info.y,
            "bounds": info.bounds,
        }
        if info.href:
            payload["href"] = info.href
        if info.target:
            payload["target"] = info.target
        return payload


@dataclass(frozen=True)
class ClickResult:
    """Result of a click action."""

    ok: bool
    navigation_occurred: bool
    url: str
    needs_observation: bool
    message: str
    clicked_point: dict[str, Any] = field(default_factory=dict)
    coordinate_space: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TypeResult:
    """Result of a text input action."""

    ok: bool
    needs_observation: bool
    message: str


@dataclass(frozen=True)
class ActionResult:
    """Result of a generic browser action."""

    ok: bool
    needs_observation: bool
    message: str


@dataclass(frozen=True)
class ScreenshotResult:
    """Result of a tab screenshot observation."""

    ok: bool
    needs_observation: bool
    message: str
    path: str
    coordinate_space: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PageInfo:
    """Read-only page metadata useful for navigation and scroll decisions."""

    url: str
    title: str
    viewport_width: int
    viewport_height: int
    content_width: int
    content_height: int
    scroll_x: int
    scroll_y: int
    max_scroll_y: int
    scroll_percent: int
    at_top: bool
    at_bottom: bool
    device_pixel_ratio: float


@dataclass(frozen=True)
class EvaluateResult:
    """Result of a bounded read-only JavaScript evaluation."""

    ok: bool
    type: str
    value: Any = None
    description: str = ""
    exception_text: str = ""


@dataclass(frozen=True)
class TabInfo:
    """Summary of a browser tab."""

    id: int
    url: str
    title: str

    def __getitem__(self, key: str) -> Any:
        if key in {"id", "url", "title"}:
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key in {"id", "url", "title"}:
            return getattr(self, key)
        return default
