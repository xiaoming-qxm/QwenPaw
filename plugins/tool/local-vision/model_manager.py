# -*- coding: utf-8 -*-
"""Model selection and cache helpers for the Local Vision plugin."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAC_7B_MODEL = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
MAC_3B_MODEL = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit"
LINUX_7B_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct-GPTQ-Int4"


@dataclass(frozen=True)
class ModelSelection:
    """Resolved local vision model runtime selection."""

    model_id: str
    model_size: str
    framework: str
    device: str
    degraded: bool
    model_path: str = ""
    warning: str = ""


def _available_memory_gb() -> float:
    try:
        import psutil

        return float(psutil.virtual_memory().available) / (1024**3)
    except Exception:
        return 0.0


def _normalize_requested_model(requested_model: str | None) -> str:
    requested = (requested_model or "auto").strip()
    return requested if requested in {"auto", "7B", "3B"} else "auto"


def select_model(
    requested_model: str = "auto",
    available_memory_gb: float | None = None,
    system: str | None = None,
    machine: str | None = None,
) -> ModelSelection:
    """Select the best local model for the current platform."""
    requested = _normalize_requested_model(requested_model)
    memory_gb = (
        _available_memory_gb()
        if available_memory_gb is None
        else float(available_memory_gb)
    )
    system_name = system or platform.system()
    machine_name = (machine or platform.machine()).lower()

    if system_name == "Darwin" and machine_name in {"arm64", "aarch64"}:
        if requested == "3B" or (requested == "auto" and memory_gb < 8):
            return ModelSelection(
                model_id=MAC_3B_MODEL,
                model_size="3B",
                framework="mlx",
                device="mps",
                degraded=True,
                warning="Available memory is below 8GB; using 3B model.",
            )
        return ModelSelection(
            model_id=MAC_7B_MODEL,
            model_size="7B",
            framework="mlx",
            device="mps",
            degraded=False,
            warning=(
                "Available memory is below 12GB; 7B may be slower."
                if memory_gb < 12
                else ""
            ),
        )

    if system_name == "Linux":
        return ModelSelection(
            model_id=LINUX_7B_MODEL,
            model_size="7B",
            framework="transformers",
            device="cuda",
            degraded=False,
        )

    return ModelSelection(
        model_id=MAC_3B_MODEL,
        model_size="3B",
        framework="unsupported",
        device="cpu",
        degraded=True,
        warning=f"Unsupported platform: {system_name}/{machine_name}",
    )


def model_cache_dir(model_id: str, cache_root: Path | None = None) -> Path:
    """Return the HuggingFace cache directory for a model id."""
    root = cache_root or (Path.home() / ".cache" / "huggingface" / "hub")
    return root / f"models--{model_id.replace('/', '--')}"


def is_model_cached(model_id: str, cache_root: Path | None = None) -> bool:
    """Return whether the HuggingFace cache has a complete snapshot."""
    cache_dir = model_cache_dir(model_id, cache_root)
    if not cache_dir.exists():
        return False
    refs_main = cache_dir / "refs" / "main"
    if not refs_main.exists():
        return False
    snapshot_hash = refs_main.read_text(encoding="utf-8").strip()
    if not snapshot_hash:
        return False
    snapshot_dir = cache_dir / "snapshots" / snapshot_hash
    return snapshot_dir.exists() and any(snapshot_dir.iterdir())


def cached_snapshot_path(
    model_id: str,
    cache_root: Path | None = None,
) -> str:
    """Return the resolved cached snapshot path for a cached model."""
    cache_dir = model_cache_dir(model_id, cache_root)
    refs_main = cache_dir / "refs" / "main"
    snapshot_hash = refs_main.read_text(encoding="utf-8").strip()
    return str(cache_dir / "snapshots" / snapshot_hash)


def ensure_model_available(
    config: dict[str, Any] | None = None,
) -> ModelSelection:
    """Resolve or download a model and return local path metadata."""
    tool_config = config or {}
    model_path = str(tool_config.get("model_path") or "").strip()
    if model_path:
        path = Path(model_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Local model path not found: {path}")
        return ModelSelection(
            model_id="local",
            model_size=str(tool_config.get("model") or "local"),
            framework="local",
            device="auto",
            degraded=False,
            model_path=str(path),
        )

    selection = select_model(str(tool_config.get("model") or "auto"))
    if selection.framework == "unsupported":
        raise RuntimeError(selection.warning)

    if is_model_cached(selection.model_id):
        return ModelSelection(
            **{
                **selection.__dict__,
                "model_path": cached_snapshot_path(selection.model_id),
            },
        )

    from huggingface_hub import snapshot_download

    downloaded_path = snapshot_download(selection.model_id)
    return ModelSelection(
        **{**selection.__dict__, "model_path": str(downloaded_path)},
    )
