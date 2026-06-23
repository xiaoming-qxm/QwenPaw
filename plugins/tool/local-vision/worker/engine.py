# -*- coding: utf-8 -*-
"""Local Vision model engine."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import importlib.util
from pathlib import Path
from typing import Any

from PIL import Image

try:
    from .coordinate import compute_resize_dimensions, restore_coordinates
    from .prompts import UI_PARSE_PROMPT
except ImportError:
    _WORKER_DIR = Path(__file__).resolve().parent

    def _load_worker_module(module_name: str, filename: str):
        spec = importlib.util.spec_from_file_location(
            module_name,
            _WORKER_DIR / filename,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load worker module: {filename}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    _coordinate = _load_worker_module(
        "local_vision_worker_coordinate",
        "coordinate.py",
    )
    _prompts = _load_worker_module(
        "local_vision_worker_prompts",
        "prompts.py",
    )
    compute_resize_dimensions = _coordinate.compute_resize_dimensions
    restore_coordinates = _coordinate.restore_coordinates
    UI_PARSE_PROMPT = _prompts.UI_PARSE_PROMPT


class VisionEngine:
    """Load a local VLM and parse UI screenshot elements."""

    def __init__(self) -> None:
        self.model_path = os.environ.get("VISION_MODEL_PATH", "")
        self.model_id = os.environ.get("VISION_MODEL_ID", "local")
        self.model_size = os.environ.get("VISION_MODEL_SIZE", "local")
        self.framework = os.environ.get("VISION_FRAMEWORK", "local")
        self.device = os.environ.get("VISION_DEVICE", "auto")
        self.degraded = os.environ.get("VISION_DEGRADED") == "1"
        self._loaded = False
        self._model: Any = None
        self._processor: Any = None

    async def load(self) -> None:
        """Load model dependencies and weights."""
        if self._loaded:
            return
        if os.environ.get("VISION_FAKE_ENGINE") == "1":
            self._loaded = True
            return
        if self.framework == "mlx":
            self._load_mlx()
        elif self.framework == "transformers":
            self._load_transformers()
        elif self.framework == "local":
            self._load_mlx()
        else:
            raise RuntimeError(
                f"Unsupported Local Vision framework: {self.framework}",
            )
        self._loaded = True

    async def parse(
        self,
        image_path: str,
        max_elements: int = 50,
        viewport_width: int = 0,
        viewport_height: int = 0,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Parse one screenshot and return structured UI elements."""
        start = time.perf_counter()
        await self.load()
        image = Image.open(image_path)
        original_size = image.size
        resized_size = compute_resize_dimensions(original_size)
        raw_elements = self._infer_elements(
            str(Path(image_path)),
            max_elements,
        )
        elements = self._normalize_elements(
            raw_elements,
            original_size=original_size,
            resized_size=resized_size,
            max_elements=max_elements,
        )
        width = int(viewport_width or original_size[0])
        height = int(viewport_height or original_size[1])
        return {
            "viewport": {"width": width, "height": height},
            "model_input_size": {
                "width": resized_size[0],
                "height": resized_size[1],
            },
            "model": self.model_id,
            "elements": elements,
            "processing_time_ms": round((time.perf_counter() - start) * 1000),
            "degraded": self.degraded,
        }

    def health(self) -> dict[str, Any]:
        return {
            "model_loaded": self._loaded,
            "model_name": self.model_id,
            "device": self.device,
        }

    def _load_mlx(self) -> None:
        try:
            from mlx_vlm import load
        except ImportError as exc:
            raise RuntimeError(
                "Local Vision mlx backend requires mlx-vlm. "
                "Install with: pip install mlx-vlm",
            ) from exc
        self._model, self._processor = load(self.model_path)

    def _load_transformers(self) -> None:
        try:
            import torch
            from transformers import AutoModelForImageTextToText, AutoProcessor
        except ImportError as exc:
            raise RuntimeError(
                "Local Vision transformers backend requires torch and "
                "transformers. Install the Linux GPU dependencies first.",
            ) from exc
        self._processor = AutoProcessor.from_pretrained(self.model_path)
        self._model = AutoModelForImageTextToText.from_pretrained(
            self.model_path,
            device_map="auto",
            torch_dtype=torch.float16,
        )

    def _infer_elements(
        self,
        image_path: str,
        max_elements: int,
    ) -> list[dict[str, Any]]:
        if os.environ.get("VISION_FAKE_ENGINE") == "1":
            fake_elements = os.environ.get("VISION_FAKE_ELEMENTS", "")
            if fake_elements:
                return _parse_model_json(fake_elements)
            return []
        if self.framework in {"mlx", "local"}:
            return self._infer_elements_mlx(image_path, max_elements)
        return self._infer_elements_transformers(image_path, max_elements)

    def _infer_elements_mlx(
        self,
        image_path: str,
        max_elements: int,
    ) -> list[dict[str, Any]]:
        try:
            from mlx_vlm import generate
        except ImportError as exc:
            raise RuntimeError("mlx-vlm generate API is unavailable") from exc
        element_limit = int(max_elements)
        prompt = f"{UI_PARSE_PROMPT}\nReturn at most {element_limit} elements."
        output = generate(
            self._model,
            self._processor,
            prompt,
            [image_path],
            verbose=False,
        )
        return _parse_model_json(str(output))

    def _infer_elements_transformers(
        self,
        image_path: str,
        max_elements: int,
    ) -> list[dict[str, Any]]:
        image = Image.open(image_path)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {
                        "type": "text",
                        "text": (
                            f"{UI_PARSE_PROMPT}\nReturn at most "
                            f"{int(max_elements)} elements."
                        ),
                    },
                ],
            },
        ]
        text = self._processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self._processor(
            text=[text],
            images=[image],
            return_tensors="pt",
        ).to(self._model.device)
        generated_ids = self._model.generate(**inputs, max_new_tokens=2048)
        output = self._processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
        )[0]
        return _parse_model_json(output)

    def _normalize_elements(
        self,
        raw_elements: list[dict[str, Any]],
        original_size: tuple[int, int],
        resized_size: tuple[int, int],
        max_elements: int,
    ) -> list[dict[str, Any]]:
        elements = []
        for raw in raw_elements[:max_elements]:
            bbox = raw.get("bbox") or [0, 0, 0, 0]
            restored = restore_coordinates(
                bbox,
                original_size=original_size,
                resized_size=resized_size,
            )
            elements.append(
                {
                    "type": str(raw.get("type") or "other"),
                    "text": str(raw.get("text") or ""),
                    "bbox": restored,
                    "confidence": float(raw.get("confidence") or 0.0),
                },
            )
        return elements


def _parse_model_json(output: str) -> list[dict[str, Any]]:
    """Extract a JSON array from a model response."""
    text = output.strip()
    candidates = [text]
    match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if match:
        candidates.insert(0, match.group(1).strip())
    array_match = re.search(r"\[[\s\S]*\]", text)
    if array_match:
        candidates.insert(0, array_match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    raise RuntimeError("Vision model did not return a JSON array")
