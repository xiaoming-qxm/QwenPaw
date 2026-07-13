# -*- coding: utf-8 -*-
"""Trusted provider block profile and side-effect-free prepare seam."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from qwenpaw.browser.sdk.canonical.contracts import (
    Problem,
    TransportProblemDetails,
)
from qwenpaw.browser.sdk.runtime.result_delivery import (
    BlockKind,
    ProjectedBlock,
)


@dataclass(frozen=True, slots=True)
class ProviderBlockProfile:
    text: bool
    data: bool
    image: bool
    artifact: bool
    image_media_types: frozenset[str]
    artifact_media_types: frozenset[str]
    model_fingerprint: str
    formatter_fingerprint: str
    formatter: Any = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class PreparedBlocks:
    blocks: tuple[Any, ...] = ()
    problem: Problem | None = None

    @property
    def ok(self) -> bool:
        return self.problem is None


def build_provider_block_profile(
    model: Any,
    formatter: Any,
) -> ProviderBlockProfile:
    """Intersect explicit immutable model and formatter declarations."""
    model_blocks = _declared_blocks(model)
    formatter_blocks = _declared_blocks(formatter)
    supported = model_blocks & formatter_blocks
    model_images = _declared_media(model, "image_media_types")
    formatter_images = _declared_media(formatter, "image_media_types")
    model_artifacts = _declared_media(model, "artifact_media_types")
    formatter_artifacts = _declared_media(formatter, "artifact_media_types")
    return ProviderBlockProfile(
        text="text" in supported,
        data="data" in supported,
        image="image" in supported,
        artifact="artifact" in supported,
        image_media_types=model_images & formatter_images,
        artifact_media_types=model_artifacts & formatter_artifacts,
        model_fingerprint=str(
            getattr(model, "model_key", "")
            or getattr(model, "model_fingerprint", "")
            or type(model).__qualname__,
        ),
        formatter_fingerprint=str(
            getattr(formatter, "formatter_fingerprint", "")
            or type(formatter).__qualname__,
        ),
        formatter=formatter,
    )


def prepare_required_blocks(
    blocks: tuple[ProjectedBlock, ...],
    profile: ProviderBlockProfile,
    formatter: Any,
) -> PreparedBlocks:
    """Prepare every required block without invoking the provider API."""
    for block in blocks:
        problem = _support_problem(block, profile)
        if problem is not None:
            return PreparedBlocks(problem=problem)
    prepare = getattr(formatter, "prepare_blocks", None)
    if not callable(prepare):
        return PreparedBlocks(
            problem=_transport_problem(
                blocks[0].kind if blocks else "data",
                "Formatter has no side-effect-free "
                "required-block prepare seam.",
            ),
        )
    try:
        prepared = tuple(prepare(blocks))
    except Exception:
        return PreparedBlocks(
            problem=_transport_problem(
                blocks[0].kind if blocks else "data",
                "Formatter failed to prepare a required Browser block.",
            ),
        )
    if len(prepared) != len(blocks):
        return PreparedBlocks(
            problem=_transport_problem(
                blocks[0].kind if blocks else "data",
                "Formatter silently dropped a required Browser block.",
            ),
        )
    for source, mapped in zip(blocks, prepared):
        mapped_kind = _mapped_field(mapped, "kind")
        mapped_resource = _mapped_field(mapped, "resource_id")
        if mapped_kind != source.kind or mapped_resource != source.resource_id:
            return PreparedBlocks(
                problem=_transport_problem(
                    source.kind,
                    "Formatter changed required Browser block identity.",
                ),
            )
    return PreparedBlocks(blocks=prepared)


def _declared_blocks(value: Any) -> frozenset[str]:
    declared = getattr(value, "supported_blocks", ())
    if not isinstance(declared, (set, frozenset, tuple, list)):
        return frozenset()
    return frozenset(
        str(kind)
        for kind in declared
        if str(kind) in {"text", "data", "image", "artifact"}
    )


def _declared_media(value: Any, attribute: str) -> frozenset[str]:
    declared = getattr(value, attribute, ())
    if not isinstance(declared, (set, frozenset, tuple, list)):
        return frozenset()
    return frozenset(str(media_type) for media_type in declared)


def _support_problem(
    block: ProjectedBlock,
    profile: ProviderBlockProfile,
) -> Problem | None:
    if not bool(getattr(profile, block.kind, False)):
        return _transport_problem(
            block.kind,
            f"Provider does not support required {block.kind} blocks.",
        )
    allowed = (
        profile.image_media_types
        if block.kind == "image"
        else profile.artifact_media_types
        if block.kind == "artifact"
        else frozenset()
    )
    if allowed and block.media_type not in allowed:
        return _transport_problem(
            block.kind,
            "Provider does not support required media type "
            f"{block.media_type}.",
        )
    return None


def _transport_problem(kind: BlockKind | str, message: str) -> Problem:
    return Problem(
        code="transport_failure",
        phase="TRANSPORT",
        safe_message=message,
        details=TransportProblemDetails(
            block_kind=cast(BlockKind, kind),
        ),
    )


def _mapped_field(value: Any, name: str) -> str:
    if isinstance(value, dict):
        return str(value.get(name) or "")
    return str(getattr(value, name, "") or "")


__all__ = [
    "PreparedBlocks",
    "ProviderBlockProfile",
    "build_provider_block_profile",
    "prepare_required_blocks",
]
