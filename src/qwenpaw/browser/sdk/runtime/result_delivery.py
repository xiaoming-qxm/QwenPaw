# -*- coding: utf-8 -*-
"""Single collector and projector for canonical Browser execution facts."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..canonical.contracts import (
    ActionResult,
    Problem,
    RichBrowserResult,
    SnapshotResult,
    TransportProblemDetails,
    issue_operation_id,
    validate_result_contract,
)

if TYPE_CHECKING:
    from qwenpaw.agents.provider_blocks import ProviderBlockProfile


BlockKind = Literal["text", "data", "image", "artifact"]


@dataclass(frozen=True, slots=True)
class RequiredBlock:
    """Required sidecar selected by a truth-bearing rich result."""

    kind: BlockKind
    resource_id: str = ""
    media_type: str = ""
    payload: object | None = None


@dataclass(frozen=True, slots=True)
class ProjectedBlock:
    """Protected one-way projection plan for model transport."""

    kind: BlockKind
    operation_id: str
    text: str = ""
    resource_id: str = ""
    media_type: str = ""
    payload: object | None = None
    protected: bool = True


@dataclass(frozen=True, slots=True)
class BrowserOperationRecord:
    ordinal: int
    result: RichBrowserResult
    required_blocks: tuple[RequiredBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class BrowserExecutionEnvelope:
    records: tuple[BrowserOperationRecord, ...]

    @property
    def terminal_result(self) -> RichBrowserResult:
        """Return the latest non-success fact, else the latest result."""
        for record in reversed(self.records):
            if record.result.status != "SUCCEEDED":
                return record.result
        return self.records[-1].result


def _transport_problem(message: str) -> Problem:
    return Problem(
        code="transport_failure",
        phase="TRANSPORT",
        safe_message=message,
        details=TransportProblemDetails(block_kind="data"),
    )


def _synthetic_failure(message: str) -> ActionResult:
    return ActionResult(
        operation_id=issue_operation_id(),
        status="FAILED",
        problem=_transport_problem(message),
        retry="FORBIDDEN",
    )


def _synthetic_uncertain() -> ActionResult:
    return ActionResult(
        operation_id=issue_operation_id(),
        status="UNCERTAIN",
        problem=Problem(
            code="terminal_fact_missing",
            phase="VERIFY",
            safe_message="Browser code completed without a terminal result.",
        ),
        retry="RECONCILE_ONLY",
    )


class BrowserExecutionCollector:
    """Collect every canonical operation result in execution order."""

    def __init__(self) -> None:
        self._records: list[BrowserOperationRecord] = []

    def record(
        self,
        result: object,
        *,
        required_blocks: tuple[RequiredBlock, ...] = (),
    ) -> None:
        """Record a result, converting malformed input to a closed failure."""
        if not isinstance(
            result,
            RichBrowserResult.__args__,  # type: ignore[attr-defined]
        ):
            result = _synthetic_failure("Malformed canonical Browser result.")
            required_blocks = ()
        else:
            try:
                validate_result_contract(result)
            except Exception:  # defensive producer boundary
                result = _synthetic_failure(
                    "Canonical Browser result failed contract validation.",
                )
                required_blocks = ()
        self._records.append(
            BrowserOperationRecord(
                ordinal=len(self._records) + 1,
                result=result,
                required_blocks=required_blocks,
            ),
        )

    def finalize(
        self,
        *,
        python_value: object,
        error: BaseException | None,
    ) -> BrowserExecutionEnvelope:
        """Freeze facts; Python final values are never terminal truth."""
        del python_value
        if error is not None:
            self.record(
                _synthetic_failure(
                    "Browser code raised before result delivery completed.",
                ),
            )
        if not self._records:
            self.record(_synthetic_uncertain())
        return BrowserExecutionEnvelope(records=tuple(self._records))


class BrowserResultProjector:
    """Project an envelope to ordered protected transport blocks."""

    def project(
        self,
        envelope: BrowserExecutionEnvelope,
        *,
        profile: "ProviderBlockProfile | object",
    ) -> tuple[ProjectedBlock, ...]:
        if not isinstance(envelope, BrowserExecutionEnvelope):
            envelope = BrowserExecutionEnvelope(
                records=(
                    BrowserOperationRecord(
                        ordinal=1,
                        result=_synthetic_failure(
                            "Malformed Browser execution envelope.",
                        ),
                    ),
                ),
            )
        blocks: list[ProjectedBlock] = []
        seen_snapshot_text: set[str] = set()
        for record in envelope.records:
            result = record.result
            summary = _result_summary(result, seen_snapshot_text)
            blocks.append(
                ProjectedBlock(
                    kind="text",
                    operation_id=result.operation_id,
                    text=summary,
                ),
            )
            for required in record.required_blocks:
                if not bool(getattr(profile, required.kind, False)):
                    blocks.append(
                        ProjectedBlock(
                            kind="text",
                            operation_id=result.operation_id,
                            text=(
                                "FAILED TRANSPORT: required "
                                f"{required.kind} block is unsupported"
                            ),
                        ),
                    )
                    continue
                blocks.append(
                    ProjectedBlock(
                        kind=required.kind,
                        operation_id=result.operation_id,
                        resource_id=required.resource_id,
                        media_type=required.media_type,
                        payload=required.payload,
                    ),
                )
        return tuple(blocks)


def _result_summary(
    result: RichBrowserResult,
    seen_snapshot_text: set[str],
) -> str:
    parts = [result.status, f"operation={result.operation_id}"]
    if result.problem is not None:
        parts.extend(
            (
                f"problem={result.problem.code}",
                f"message={result.problem.safe_message}",
            ),
        )
    parts.append(f"retry={result.retry}")
    if isinstance(result, SnapshotResult) and result.model_text:
        if result.model_text not in seen_snapshot_text:
            parts.append(result.model_text)
            seen_snapshot_text.add(result.model_text)
    return " | ".join(parts)


_CURRENT_COLLECTOR: ContextVar[BrowserExecutionCollector | None] = ContextVar(
    "qwenpaw_browser_result_collector",
    default=None,
)


def install_result_collector(
    collector: BrowserExecutionCollector,
) -> Token[BrowserExecutionCollector | None]:
    """Install the sole collector for one canonical execution."""
    return _CURRENT_COLLECTOR.set(collector)


def reset_result_collector(
    token: Token[BrowserExecutionCollector | None],
) -> None:
    """Restore the prior execution collector."""
    _CURRENT_COLLECTOR.reset(token)


def record_browser_result(
    result: RichBrowserResult,
    *,
    required_blocks: tuple[RequiredBlock, ...] = (),
) -> None:
    """Record through the current canonical collector when installed."""
    collector = _CURRENT_COLLECTOR.get()
    if collector is None:
        raise RuntimeError(
            "canonical Browser result collector is not installed",
        )
    collector.record(result, required_blocks=required_blocks)


__all__ = [
    "BrowserExecutionCollector",
    "BrowserExecutionEnvelope",
    "BrowserOperationRecord",
    "BrowserResultProjector",
    "ProjectedBlock",
    "RequiredBlock",
    "install_result_collector",
    "record_browser_result",
    "reset_result_collector",
]
