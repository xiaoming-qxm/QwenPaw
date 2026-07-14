# -*- coding: utf-8 -*-
"""Shared, auditable matching rules for canonical Browser conditions."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
import unicodedata
from typing import Literal
from urllib.parse import quote, urlsplit

_VISIBLE_WHITESPACE = re.compile(r"\s+", re.UNICODE)
_PERCENT_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~",
)


@dataclass(frozen=True, slots=True)
class CanonicalURL:
    """A credential-free canonical HTTP(S) URL."""

    scheme: Literal["http", "https"]
    host: str
    port: int | None
    path: str
    query: str
    fragment: str
    value: str

    @property
    def origin(self) -> tuple[str, str, int | None]:
        """Return the exact normalized origin tuple."""
        return (self.scheme, self.host, self.port)


def normalize_visible_text(value: str) -> str:
    """Normalize visible text without changing case or semantic content."""
    if not isinstance(value, str):
        raise TypeError("visible text must be a string")
    normalized = unicodedata.normalize("NFC", value)
    return _VISIBLE_WHITESPACE.sub(" ", normalized).strip()


def canonicalize_http_url(value: str) -> CanonicalURL:
    """Parse and normalize one safe, absolute HTTP(S) URL."""
    if not isinstance(value, str):
        raise TypeError("URL must be a string")
    if not value or any(ord(char) < 0x20 for char in value) or "\\" in value:
        raise ValueError("URL contains invalid characters")
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("URL scheme must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URL credentials are not allowed")
    if not parsed.hostname:
        raise ValueError("URL host is required")
    host = _canonical_host(parsed.hostname)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL port is invalid") from exc
    if port == (80 if scheme == "http" else 443):
        port = None
    path = _normalize_path(parsed.path)
    display_host = f"[{host}]" if ":" in host else host
    authority = display_host if port is None else f"{display_host}:{port}"
    result = f"{scheme}://{authority}{path}"
    if parsed.query:
        result += f"?{parsed.query}"
    if parsed.fragment:
        result += f"#{parsed.fragment}"
    return CanonicalURL(
        scheme=scheme,  # type: ignore[arg-type]
        host=host,
        port=port,
        path=path,
        query=parsed.query,
        fragment=parsed.fragment,
        value=result,
    )


def match_page_url(
    actual: str,
    expected: str,
    *,
    mode: Literal["exact", "prefix"],
) -> bool:
    """Compare canonical URLs using exact or origin/path-bound prefix rules."""
    if mode not in {"exact", "prefix"}:
        raise ValueError(f"invalid URL match mode: {mode}")
    actual_url = canonicalize_http_url(actual)
    expected_url = canonicalize_http_url(expected)
    if mode == "exact":
        return actual_url.value == expected_url.value
    if expected_url.query or expected_url.fragment:
        raise ValueError("URL prefix cannot contain query or fragment")
    if actual_url.origin != expected_url.origin:
        return False
    expected_path = expected_url.path
    actual_path = actual_url.path
    if actual_path == expected_path:
        return True
    if expected_path.endswith("/"):
        return actual_path.startswith(expected_path)
    return actual_path.startswith(f"{expected_path}/")


def _canonical_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as address_error:
        try:
            canonical = host.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("URL host is invalid") from exc
        if not canonical or any(not label for label in canonical.split(".")):
            raise ValueError("URL host is invalid") from address_error
        return canonical
    return address.compressed.lower()


def _normalize_path(path: str) -> str:
    raw_segments = (path or "/").split("/")
    normalized: list[str] = []
    trailing_slash = path.endswith(("/", "/.", "/.."))
    for raw_segment in raw_segments:
        segment = _normalize_segment(raw_segment)
        if segment in {"", "."}:
            if not normalized and segment == "":
                continue
            continue
        if segment == "..":
            if normalized:
                normalized.pop()
            continue
        normalized.append(segment)
    result = "/" + "/".join(normalized)
    if trailing_slash and result != "/":
        result += "/"
    return result


def _normalize_segment(segment: str) -> str:
    def replace_escape(match: re.Match[str]) -> str:
        value = chr(int(match.group(1), 16))
        return value if value in _UNRESERVED else f"%{match.group(1).upper()}"

    normalized = _PERCENT_ESCAPE.sub(replace_escape, segment)
    if "%" in normalized:
        parts: list[str] = []
        cursor = 0
        for match in _PERCENT_ESCAPE.finditer(normalized):
            chunk = normalized[slice(cursor, match.start())]
            parts.append(quote(chunk, safe="!$&'()*+,;=:@-._~"))
            parts.append(match.group(0).upper())
            cursor = match.end()
        parts.append(quote(normalized[cursor:], safe="!$&'()*+,;=:@-._~"))
        return "".join(parts)
    return quote(normalized, safe="!$&'()*+,;=:@-._~")


__all__ = [
    "CanonicalURL",
    "canonicalize_http_url",
    "match_page_url",
    "normalize_visible_text",
]
