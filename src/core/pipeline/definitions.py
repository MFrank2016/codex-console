from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .context import PipelineContext


@dataclass(frozen=True)
class StepDefinition:
    step_key: str
    handler: Callable[[PipelineContext], dict[str, Any] | None]
    impl_key: str | None = None
    retry_attempts: int = 1
    retry_backoff_seconds: float = 0.0
    transient_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class PipelineDefinition:
    pipeline_key: str
    steps: Sequence[StepDefinition]
