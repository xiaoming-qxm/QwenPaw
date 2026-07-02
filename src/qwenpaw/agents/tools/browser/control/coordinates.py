# -*- coding: utf-8 -*-
"""Coordinate helpers for Browser Control viewport actions."""

from __future__ import annotations

import struct
from typing import Any

from .errors import TargetResolutionFailed

_POINT_TRACKING_BUCKET_CSS_PX = 32


def _control_coordinate_space_payload(
    *,
    viewport_width: float,
    viewport_height: float,
    screenshot_width: int = 0,
    screenshot_height: int = 0,
) -> dict[str, Any]:
    """Return LLM-readable metadata for visual-to-click coordinates."""
    payload: dict[str, Any] = {
        "click_coordinates": "viewport_css_pixels",
        "viewport_width": _clean_number(viewport_width),
        "viewport_height": _clean_number(viewport_height),
        "screenshot_width": int(screenshot_width or 0),
        "screenshot_height": int(screenshot_height or 0),
        "instruction": (
            "Convert screenshot image pixels to tab.click coordinates by "
            "multiplying image_x/image_y by image_to_viewport_scale_x/y. "
            "Coordinates outside the viewport are invalid."
        ),
    }
    if screenshot_width > 0 and screenshot_height > 0:
        payload["image_to_viewport_scale_x"] = _safe_ratio(
            viewport_width,
            screenshot_width,
        )
        payload["image_to_viewport_scale_y"] = _safe_ratio(
            viewport_height,
            screenshot_height,
        )
    return payload


def _control_image_size(
    image_bytes: bytes,
    *,
    media_type: str,
) -> tuple[int, int]:
    """Return image dimensions for PNG/JPEG screenshots."""
    if media_type == "image/png":
        return _png_size(image_bytes)
    if media_type == "image/jpeg":
        return _jpeg_size(image_bytes)
    return (0, 0)


def _control_point_tracking_ref(x: float, y: float) -> str:
    """Return a stable key for nearby coordinate clicks."""
    return "point:{x:g}:{y:g}".format(
        x=_bucket_point(float(x)),
        y=_bucket_point(float(y)),
    )


def _control_validate_viewport_coordinates(
    *,
    x: float,
    y: float,
    viewport_width: float,
    viewport_height: float,
) -> None:
    """Reject coordinates that cannot be clicked in the current viewport."""
    if viewport_width <= 0 or viewport_height <= 0:
        return
    if 0 <= x <= viewport_width and 0 <= y <= viewport_height:
        return
    raise TargetResolutionFailed(
        "Coordinate ({x:g}, {y:g}) is outside the current viewport CSS "
        "coordinates 0..{width:g} x 0..{height:g}. Browser Control "
        "tab.click(x=..., y=...) uses viewport CSS coordinates, not raw "
        "screenshot image pixels. If you chose the point from a screenshot, "
        "convert it with the screenshot coordinate_space scale first.".format(
            x=float(x),
            y=float(y),
            width=float(viewport_width),
            height=float(viewport_height),
        ),
    )


def _bucket_point(value: float) -> float:
    return (
        round(float(value) / _POINT_TRACKING_BUCKET_CSS_PX)
        * _POINT_TRACKING_BUCKET_CSS_PX
    )


def _clean_number(value: float) -> int | float:
    numeric = float(value or 0)
    if numeric.is_integer():
        return int(numeric)
    return round(numeric, 3)


def _safe_ratio(numerator: float, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator or 0) / float(denominator), 6)


def _png_size(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 24:
        return (0, 0)
    if image_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    return struct.unpack(">II", image_bytes[16:24])


def _jpeg_size(image_bytes: bytes) -> tuple[int, int]:
    if len(image_bytes) < 4 or image_bytes[:2] != b"\xff\xd8":
        return (0, 0)
    index = 2
    while index + 9 < len(image_bytes):
        if image_bytes[index] != 0xFF:
            index += 1
            continue
        marker = image_bytes[index + 1]
        index += 2
        while marker == 0xFF and index < len(image_bytes):
            marker = image_bytes[index]
            index += 1
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(image_bytes):
            return (0, 0)
        segment_length = struct.unpack(">H", image_bytes[index : index + 2])[0]
        if segment_length < 2:
            return (0, 0)
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            start = index + 2
            if start + 5 > len(image_bytes):
                return (0, 0)
            height = struct.unpack(">H", image_bytes[start + 1 : start + 3])[0]
            width = struct.unpack(">H", image_bytes[start + 3 : start + 5])[0]
            return (int(width), int(height))
        index += segment_length
    return (0, 0)


__all__ = [
    "_control_coordinate_space_payload",
    "_control_image_size",
    "_control_point_tracking_ref",
    "_control_validate_viewport_coordinates",
]
