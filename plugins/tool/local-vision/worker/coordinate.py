# -*- coding: utf-8 -*-
"""Coordinate conversion helpers for Local Vision worker output."""

from __future__ import annotations


def compute_resize_dimensions(
    original_size: tuple[int, int],
    max_long_side: int = 1280,
    multiple_of: int = 28,
) -> tuple[int, int]:
    """Compute Qwen2.5-VL input resize dimensions."""
    width, height = original_size
    if width <= 0 or height <= 0:
        raise ValueError("original_size must contain positive dimensions")
    scale = max_long_side / max(width, height)
    if scale >= 1.0:
        new_width, new_height = width, height
    else:
        new_width = int(width * scale)
        new_height = int(height * scale)
    new_width = ((new_width + multiple_of - 1) // multiple_of) * multiple_of
    new_height = ((new_height + multiple_of - 1) // multiple_of) * multiple_of
    return new_width, new_height


def restore_coordinates(
    model_bbox: list[int | float],
    original_size: tuple[int, int],
    resized_size: tuple[int, int],
) -> list[int]:
    """Restore model-space bbox coordinates to original image pixels."""
    if len(model_bbox) != 4:
        raise ValueError("model_bbox must have four coordinates")
    scale_x = original_size[0] / resized_size[0]
    scale_y = original_size[1] / resized_size[1]
    x1, y1, x2, y2 = model_bbox
    return [
        round(float(x1) * scale_x),
        round(float(y1) * scale_y),
        round(float(x2) * scale_x),
        round(float(y2) * scale_y),
    ]
