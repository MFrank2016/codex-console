from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from src.database import crud
from src.database.models import PipelineStepRun

from .context import PipelineContext
from .definitions import PipelineDefinition


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
            self._emit_step_snapshot(ctx, current_step=step_snapshot, steps_snapshot=steps_snapshot)

            try:
                payload = step.handler(ctx) or {}
                self._apply_payload(ctx, payload)
            except Exception as exc:
                self._finalize_step(step_run, started_at, status="failed", error_message=str(exc))
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
                self._emit_step_snapshot(ctx, current_step=step_snapshot, steps_snapshot=steps_snapshot)
                raise

            self._finalize_step(step_run, started_at, status="completed")
            step_snapshot.update(
                {
                    "status": "completed",
                    "duration_ms": step_run.duration_ms,
                    "error_message": step_run.error_message,
                }
            )
            self._emit_step_snapshot(ctx, current_step=step_snapshot, steps_snapshot=steps_snapshot)

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
    ) -> None:
        callback = ctx.task_step_callback
        if not callable(callback):
            return

        steps = [dict(item) for item in steps_snapshot]
        current_step_payload = {"step_key": current_step.get("step_key"), "status": current_step.get("status")}
        callback(
            {
                "current_step": current_step_payload,
                "steps": steps,
            }
        )

    def _finalize_step(
        self,
        step_run: PipelineStepRun,
        started_at: datetime,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        completed_at = self._utc_now()
        step_run.status = status
        step_run.completed_at = completed_at
        step_run.duration_ms = self._duration_ms(started_at, completed_at)
        step_run.error_message = error_message
        self.db.commit()
        self.db.refresh(step_run)

    def _apply_payload(self, ctx: PipelineContext, payload: dict[str, Any]) -> None:
        for key, value in payload.items():
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
