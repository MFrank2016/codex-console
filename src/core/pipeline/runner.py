from __future__ import annotations

import time
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.database import crud
from src.database.models import PipelineStepRun

from .context import PipelineContext
from .definitions import PipelineDefinition, StepDefinition
from .errors import PipelineStepExecutionError, PipelineStepFailureContext


class PipelineRunner:
    _ALLOWED_CONTEXT_FIELDS = {field.name for field in fields(PipelineContext)}

    def __init__(self, db: Session):
        self.db = db

    def run(self, pipeline: PipelineDefinition, ctx: PipelineContext) -> PipelineContext:
        pipeline_started_at = self._utc_now()
        ctx.pipeline_key = pipeline.pipeline_key
        crud.update_registration_task(
            self.db,
            ctx.task_uuid,
            pipeline_key=pipeline.pipeline_key,
            pipeline_status="running",
            started_at=pipeline_started_at,
        )

        steps_snapshot: list[dict[str, Any]] = []

        for order, step in enumerate(pipeline.steps, start=1):
            started_at = self._utc_now()
            crud.update_registration_task(
                self.db,
                ctx.task_uuid,
                current_step_key=step.step_key,
                pipeline_status="running",
            )
            step_run = crud.create_pipeline_step_run(
                self.db,
                task_uuid=ctx.task_uuid,
                pipeline_key=pipeline.pipeline_key,
                step_key=step.step_key,
                step_order=order,
                step_impl=step.impl_key,
                status="running",
                started_at=started_at,
            )
            step_snapshot: dict[str, Any] = {
                "step_key": step.step_key,
                "step_order": order,
                "status": "running",
                "duration_ms": None,
                "error_message": None,
            }
            steps_snapshot.append(step_snapshot)
            self._emit_step_snapshot(
                ctx,
                current_step=step_snapshot,
                steps_snapshot=steps_snapshot,
                pipeline_started_at=pipeline_started_at,
                total_steps=len(pipeline.steps),
            )

            try:
                payload, retry_metadata = self._execute_step_with_retry(step, ctx)
                self._apply_payload(ctx, payload)
            except Exception as exc:
                retry_metadata = getattr(exc, "_pipeline_retry_metadata", None) or self._build_default_retry_metadata(step)
                failure_metadata = {
                    **retry_metadata,
                    "failure_stage": step.step_key,
                    "step_key": step.step_key,
                    "retryable": bool(retry_metadata.get("retry_attempts_used")),
                }
                self._finalize_step(
                    step_run,
                    started_at,
                    status="failed",
                    error_message=str(exc),
                    metadata_json=failure_metadata,
                )
                step_snapshot.update(
                    {
                        "status": "failed",
                        "duration_ms": step_run.duration_ms,
                        "error_message": step_run.error_message,
                    }
                )
                failed_at = self._utc_now()
                crud.update_registration_task(
                    self.db,
                    ctx.task_uuid,
                    pipeline_status="failed",
                    total_duration_ms=self._duration_ms(pipeline_started_at, failed_at),
                    completed_at=failed_at,
                    error_message=str(exc),
                )
                self._emit_step_snapshot(
                    ctx,
                    current_step=step_snapshot,
                    steps_snapshot=steps_snapshot,
                    pipeline_started_at=pipeline_started_at,
                    total_steps=len(pipeline.steps),
                )
                raise PipelineStepExecutionError(
                    PipelineStepFailureContext(
                        pipeline_key=pipeline.pipeline_key,
                        step_key=step.step_key,
                        failure_stage=step.step_key,
                        error_message=str(exc),
                        retryable=bool(retry_metadata.get("retry_attempts_used")),
                        attempt_count=int(retry_metadata.get("attempt_count") or 1),
                        retry_reasons=list(retry_metadata.get("retry_reasons") or []),
                        metadata=failure_metadata,
                    )
                ) from exc

            self._finalize_step(
                step_run,
                started_at,
                status="completed",
                metadata_json=retry_metadata,
            )
            step_snapshot.update(
                {
                    "status": "completed",
                    "duration_ms": step_run.duration_ms,
                    "error_message": step_run.error_message,
                }
            )
            self._emit_step_snapshot(
                ctx,
                current_step=step_snapshot,
                steps_snapshot=steps_snapshot,
                pipeline_started_at=pipeline_started_at,
                total_steps=len(pipeline.steps),
            )

        completed_at = self._utc_now()
        crud.update_registration_task(
            self.db,
            ctx.task_uuid,
            pipeline_status="completed",
            total_duration_ms=self._duration_ms(pipeline_started_at, completed_at),
            completed_at=completed_at,
        )
        return ctx

    def _emit_step_snapshot(
        self,
        ctx: PipelineContext,
        *,
        current_step: dict[str, Any],
        steps_snapshot: list[dict[str, Any]],
        pipeline_started_at: datetime,
        total_steps: int,
    ) -> None:
        callback = ctx.task_step_callback
        if not callable(callback):
            return

        steps = [dict(item) for item in steps_snapshot]
        current_step_payload = {"step_key": current_step.get("step_key"), "status": current_step.get("status")}
        step_index = int(current_step.get("step_order") or total_steps)
        emitted_at = self._utc_now()
        callback(
            {
                "current_step": current_step_payload,
                "steps": steps,
                "task_progress": {
                    "step_index": step_index,
                    "total_steps": total_steps,
                    "progress_percent": int(step_index / total_steps * 100),
                    "elapsed_ms": self._duration_ms(pipeline_started_at, emitted_at),
                },
            }
        )

    def _normalize_transient_markers(self, markers: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            str(marker).strip().lower()
            for marker in markers
            if str(marker).strip()
        )

    def _build_default_retry_metadata(self, step: StepDefinition) -> dict[str, Any]:
        return {
            "attempt_count": 1,
            "retry_attempts_used": 0,
            "retry_reasons": [],
            "matched_transient_marker": None,
        }

    def _should_retry_step(self, exc: Exception, step: StepDefinition) -> tuple[bool, str | None]:
        markers = self._normalize_transient_markers(step.transient_markers)
        if int(step.retry_attempts or 1) <= 1 or not markers:
            return False, None

        error_text = str(exc).lower()
        matched_marker = next((marker for marker in markers if marker in error_text), None)
        return matched_marker is not None, matched_marker

    def _execute_step_with_retry(
        self,
        step: StepDefinition,
        ctx: PipelineContext,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        max_attempts = max(1, int(step.retry_attempts or 1))
        retry_backoff_seconds = max(0.0, float(step.retry_backoff_seconds or 0.0))
        retry_reasons: list[str] = []
        matched_transient_marker: str | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                payload = step.handler(ctx) or {}
                return payload, {
                    "attempt_count": attempt,
                    "retry_attempts_used": attempt - 1,
                    "retry_reasons": retry_reasons,
                    "matched_transient_marker": matched_transient_marker,
                }
            except Exception as exc:
                should_retry, current_marker = self._should_retry_step(exc, step)
                if current_marker is not None:
                    matched_transient_marker = current_marker

                if not should_retry or attempt >= max_attempts:
                    setattr(
                        exc,
                        "_pipeline_retry_metadata",
                        {
                            "attempt_count": attempt,
                            "retry_attempts_used": len(retry_reasons),
                            "retry_reasons": retry_reasons,
                            "matched_transient_marker": matched_transient_marker,
                        },
                    )
                    raise

                retry_reasons.append(str(exc))
                if retry_backoff_seconds > 0:
                    time.sleep(retry_backoff_seconds)

        raise RuntimeError(f"step retry loop exhausted unexpectedly: {step.step_key}")

    def _finalize_step(
        self,
        step_run: PipelineStepRun,
        started_at: datetime,
        *,
        status: str,
        error_message: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        completed_at = self._utc_now()
        step_run.status = status
        step_run.completed_at = completed_at
        step_run.duration_ms = self._duration_ms(started_at, completed_at)
        step_run.error_message = error_message
        step_run.metadata_json = metadata_json or {}
        self.db.commit()
        self.db.refresh(step_run)

    def _apply_payload(self, ctx: PipelineContext, payload: dict[str, Any]) -> None:
        for key, value in payload.items():
            if key == "task_step_callback":
                raise ValueError("PipelineContext.task_step_callback is runtime-only and cannot be updated by steps")
            if key not in self._ALLOWED_CONTEXT_FIELDS:
                raise ValueError(f"Unknown PipelineContext field: {key}")

            if key == "metadata":
                if value is None:
                    continue
                if not isinstance(value, dict):
                    raise ValueError("PipelineContext metadata update must be a dict")
                ctx.metadata.update(value)
                continue

            setattr(ctx, key, value)

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _duration_ms(started_at: datetime, completed_at: datetime) -> int:
        return max(0, int((completed_at - started_at).total_seconds() * 1000))
