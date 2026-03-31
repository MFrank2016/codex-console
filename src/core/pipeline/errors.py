from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PipelineStepFailureContext:
    pipeline_key: str
    step_key: str
    failure_stage: str
    error_message: str
    retryable: bool
    attempt_count: int
    retry_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PipelineStepExecutionError(RuntimeError):
    def __init__(self, context: PipelineStepFailureContext):
        super().__init__(context.error_message)
        self.context = context
