from __future__ import annotations

from datetime import UTC, datetime
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc

from ...database import crud
from ...database.models import ScheduledRun
from ...database.session import get_db
from ...core.time import utc_now_naive
from ...scheduler.engine import (
    SchedulerDispatchError,
    SchedulerPlanConflictError,
    build_run_realtime_status_payload,
)
from ...scheduler.schemas import (
    ScheduledPlanCreate,
    ScheduledPlanListResponse,
    ScheduledPlanResponse,
    ScheduledPlanUpdate,
    ScheduledRunDetailResponse,
    ScheduledRunListCenterResponse,
    ScheduledRunListItemResponse,
    ScheduledRunLogChunkResponse,
    ScheduledRunResponse,
    ScheduledRunStopResponse,
)
from ...scheduler.service import validate_plan_payload
from ...scheduler.time_utils import SCHEDULER_TZ, compute_next_run_at
from ..task_manager import task_manager


router = APIRouter()
runs_router = APIRouter()
logger = logging.getLogger(__name__)


class ScheduledRunListResponse(BaseModel):
    runs: list[ScheduledRunResponse]


class ScheduledRunLogsResponse(BaseModel):
    run_id: int
    logs: str


def _is_run_running(run: ScheduledRun) -> bool:
    return run.status == "running" and run.finished_at is None


def _can_stop_run(run: ScheduledRun) -> bool:
    return _is_run_running(run) and run.stop_requested_at is None


def _compute_duration_seconds(run: ScheduledRun) -> float | None:
    if run.started_at is None:
        return None
    end_time = run.finished_at or utc_now_naive()
    return float((end_time - run.started_at).total_seconds())


def _to_scheduler_display_time_from_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(SCHEDULER_TZ)


def _to_scheduler_display_time_from_scheduler(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=SCHEDULER_TZ)
    return value.astimezone(SCHEDULER_TZ)


def _to_utc_naive_filter_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=SCHEDULER_TZ)
    return value.astimezone(UTC).replace(tzinfo=None)


def _build_scheduled_plan_response(plan) -> ScheduledPlanResponse:
    return ScheduledPlanResponse(
        id=plan.id,
        name=plan.name,
        task_type=plan.task_type,
        cpa_service_id=plan.cpa_service_id,
        trigger_type=plan.trigger_type,
        cron_expression=plan.cron_expression,
        interval_value=plan.interval_value,
        interval_unit=plan.interval_unit,
        config=plan.config,
        config_meta=plan.config_meta,
        enabled=plan.enabled,
        next_run_at=_to_scheduler_display_time_from_scheduler(plan.next_run_at),
        last_run_started_at=_to_scheduler_display_time_from_utc(plan.last_run_started_at),
        last_run_finished_at=_to_scheduler_display_time_from_utc(plan.last_run_finished_at),
        last_run_status=plan.last_run_status,
        last_success_at=_to_scheduler_display_time_from_utc(plan.last_success_at),
        auto_disabled_reason=plan.auto_disabled_reason,
        created_at=_to_scheduler_display_time_from_utc(plan.created_at),
        updated_at=_to_scheduler_display_time_from_utc(plan.updated_at),
    )


def _build_scheduled_run_response(run: ScheduledRun) -> ScheduledRunResponse:
    return ScheduledRunResponse(
        id=run.id,
        plan_id=run.plan_id,
        trigger_source=run.trigger_source,
        status=run.status,
        started_at=_to_scheduler_display_time_from_utc(run.started_at),
        finished_at=_to_scheduler_display_time_from_utc(run.finished_at),
        summary=run.summary,
        error_message=run.error_message,
        logs=run.logs,
        created_at=_to_scheduler_display_time_from_utc(run.created_at),
    )


def _build_scheduled_run_list_item(run: ScheduledRun) -> ScheduledRunListItemResponse:
    plan_name = run.plan.name if run.plan is not None else None
    task_type = run.task_type or (run.plan.task_type if run.plan is not None else "cpa_cleanup")
    return ScheduledRunListItemResponse(
        id=run.id,
        plan_id=run.plan_id,
        plan_name=plan_name,
        task_type=task_type,
        trigger_source=run.trigger_source,
        status=run.status,
        started_at=_to_scheduler_display_time_from_utc(run.started_at),
        finished_at=_to_scheduler_display_time_from_utc(run.finished_at),
        duration_seconds=_compute_duration_seconds(run),
        stop_requested_at=_to_scheduler_display_time_from_utc(run.stop_requested_at),
        last_log_at=_to_scheduler_display_time_from_utc(run.last_log_at),
        summary=run.summary,
        error_message=run.error_message,
        can_stop=_can_stop_run(run),
    )


def _to_scheduler_naive_time(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(SCHEDULER_TZ).replace(tzinfo=None)


def _resolve_plan_update_payload(plan, request: ScheduledPlanUpdate) -> dict:
    return {
        "name": request.name if request.name is not None else plan.name,
        "task_type": request.task_type if request.task_type is not None else plan.task_type,
        "cpa_service_id": request.cpa_service_id if request.cpa_service_id is not None else plan.cpa_service_id,
        "trigger_type": request.trigger_type if request.trigger_type is not None else plan.trigger_type,
        "cron_expression": request.cron_expression if request.cron_expression is not None else plan.cron_expression,
        "interval_value": request.interval_value if request.interval_value is not None else plan.interval_value,
        "interval_unit": request.interval_unit if request.interval_unit is not None else plan.interval_unit,
        "config": request.config if request.config is not None else plan.config,
        "config_meta": request.config_meta if request.config_meta is not None else plan.config_meta,
        "enabled": request.enabled if request.enabled is not None else plan.enabled,
    }


class _PlanLike:
    def __init__(self, payload: dict):
        self.trigger_type = payload["trigger_type"]
        self.cron_expression = payload["cron_expression"]
        self.interval_value = payload["interval_value"]
        self.interval_unit = payload["interval_unit"]


@runs_router.get("/scheduled-runs", response_model=ScheduledRunListCenterResponse)
async def list_all_scheduled_runs(
    task_type: str | None = Query(None),
    status: str | None = Query(None),
    plan_id: int | None = Query(None, ge=1),
    started_from: datetime | None = Query(None),
    started_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    started_after = _to_utc_naive_filter_time(started_from)
    started_before = _to_utc_naive_filter_time(started_to)
    with get_db() as db:
        total = crud.count_scheduled_runs(
            db,
            plan_id=plan_id,
            task_type=task_type,
            status=status,
            started_after=started_after,
            started_before=started_before,
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        normalized_page = min(page, total_pages)
        skip = (normalized_page - 1) * page_size
        runs = crud.get_scheduled_runs(
            db,
            plan_id=plan_id,
            task_type=task_type,
            status=status,
            started_after=started_after,
            started_before=started_before,
            skip=skip,
            limit=page_size,
        )
        return ScheduledRunListCenterResponse(
            items=[_build_scheduled_run_list_item(run) for run in runs],
            total=total,
            page=normalized_page,
            page_size=page_size,
        )


@runs_router.get("/scheduled-runs/{run_id}", response_model=ScheduledRunDetailResponse)
async def get_scheduled_run_detail(run_id: int):
    with get_db() as db:
        run = crud.get_scheduled_run_by_id(db, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行记录不存在")

        plan = crud.get_scheduled_plan_by_id(db, run.plan_id)
        plan_name = plan.name if plan is not None else None
        plan_enabled = plan.enabled if plan is not None else None
        task_type = run.task_type or (plan.task_type if plan is not None else "cpa_cleanup")

        return ScheduledRunDetailResponse(
            id=run.id,
            plan_id=run.plan_id,
            plan_name=plan_name,
            plan_enabled=plan_enabled,
            task_type=task_type,
            trigger_source=run.trigger_source,
            status=run.status,
            started_at=_to_scheduler_display_time_from_utc(run.started_at),
            finished_at=_to_scheduler_display_time_from_utc(run.finished_at),
            duration_seconds=_compute_duration_seconds(run),
            summary=run.summary,
            error_message=run.error_message,
            stop_requested_at=_to_scheduler_display_time_from_utc(run.stop_requested_at),
            stop_requested_by=run.stop_requested_by,
            stop_reason=run.stop_reason,
            log_version=int(run.log_version or 0),
            last_log_at=_to_scheduler_display_time_from_utc(run.last_log_at),
            is_running=_is_run_running(run),
            can_stop=_can_stop_run(run),
        )


@runs_router.get("/scheduled-runs/{run_id}/logs", response_model=ScheduledRunLogChunkResponse)
async def get_scheduled_run_logs_chunk(
    run_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(4096, ge=1, le=65536),
):
    with get_db() as db:
        run = crud.get_scheduled_run_by_id(db, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行记录不存在")

        chunk = crud.get_scheduled_run_log_chunk(db, run_id, offset=offset, limit=limit)
        if chunk is None:
            raise HTTPException(status_code=404, detail="运行记录不存在")

        return ScheduledRunLogChunkResponse(
            run_id=run.id,
            status=run.status,
            offset=int(chunk["offset"]),
            next_offset=int(chunk["next_offset"]),
            chunk=str(chunk["content"]),
            has_more=bool(chunk["has_more"]),
            is_running=_is_run_running(run),
            stop_requested_at=_to_scheduler_display_time_from_utc(run.stop_requested_at),
            log_version=int(chunk["log_version"]),
            last_log_at=_to_scheduler_display_time_from_utc(chunk["last_log_at"]),
        )


@runs_router.post("/scheduled-runs/{run_id}/stop", response_model=ScheduledRunStopResponse)
async def stop_scheduled_run(run_id: int):
    realtime_payload: dict | None = None
    with get_db() as db:
        run = crud.get_scheduled_run_by_id(db, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行记录不存在")
        if run.stop_requested_at is not None:
            raise HTTPException(status_code=409, detail="运行已请求停止")
        if not _is_run_running(run):
            raise HTTPException(status_code=409, detail="运行已结束，不能停止")

        requested_at = utc_now_naive()
        updated, did_mark = crud.mark_scheduled_run_stop_requested_result(
            db,
            run_id,
            requested_by="manual",
            reason="user_requested",
            requested_at=requested_at,
        )
        if updated is None:
            raise HTTPException(status_code=409, detail="运行已结束，不能停止")
        if not did_mark:
            raise HTTPException(status_code=409, detail="运行已请求停止")
        plan = crud.get_scheduled_plan_by_id(db, updated.plan_id)
        realtime_payload = build_run_realtime_status_payload(
            updated,
            plan_name=plan.name if plan is not None else None,
            task_type=updated.task_type or (plan.task_type if plan is not None else None),
            status="stopping",
        )

    try:
        if realtime_payload is None:
            task_manager.update_run_status(run_id, status="stopping")
        else:
            task_manager.update_run_status(run_id, **realtime_payload)
    except Exception:
        logger.exception("failed to emit realtime stopping status (run_id=%s)", run_id)

    return ScheduledRunStopResponse(success=True, run_id=run.id, status="stopping")


@router.post("", response_model=ScheduledPlanResponse)
async def create_scheduled_plan(request: ScheduledPlanCreate):
    try:
        validate_plan_payload(
            task_type=request.task_type,
            trigger_type=request.trigger_type,
            config=request.config,
            cron_expression=request.cron_expression,
            interval_value=request.interval_value,
            interval_unit=request.interval_unit,
        )
        next_run_at = _to_scheduler_naive_time(compute_next_run_at(request)) if request.enabled else None

        with get_db() as db:
            plan = crud.create_scheduled_plan(
                db,
                name=request.name,
                task_type=request.task_type,
                cpa_service_id=request.cpa_service_id,
                trigger_type=request.trigger_type,
                cron_expression=request.cron_expression,
                interval_value=request.interval_value,
                interval_unit=request.interval_unit,
                config=request.config,
                config_meta=request.config_meta,
                enabled=request.enabled,
                next_run_at=next_run_at,
            )
            return _build_scheduled_plan_response(plan)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{plan_id}", response_model=ScheduledPlanResponse)
async def update_scheduled_plan(plan_id: int, request: ScheduledPlanUpdate):
    with get_db() as db:
        plan = crud.get_scheduled_plan_by_id(db, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="定时计划不存在")

        merged = _resolve_plan_update_payload(plan, request)
        try:
            validate_plan_payload(
                task_type=merged["task_type"],
                trigger_type=merged["trigger_type"],
                config=merged["config"],
                cron_expression=merged["cron_expression"],
                interval_value=merged["interval_value"],
                interval_unit=merged["interval_unit"],
            )
            if crud.get_cpa_service_by_id(db, merged["cpa_service_id"]) is None:
                raise ValueError(f"cpa service {merged['cpa_service_id']} does not exist")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        update_values = request.model_dump(exclude_unset=True)

        should_recompute = (
            merged["enabled"]
            and (
                request.enabled is True and plan.enabled is False
                or plan.next_run_at is None
                or any(
                    getattr(request, field) is not None
                    for field in ("trigger_type", "cron_expression", "interval_value", "interval_unit")
                )
            )
        )
        if merged["enabled"]:
            if should_recompute:
                update_values["next_run_at"] = _to_scheduler_naive_time(compute_next_run_at(_PlanLike(merged)))
            if request.enabled is True:
                update_values["auto_disabled_reason"] = None
        else:
            update_values["next_run_at"] = None

        updated = crud.update_scheduled_plan(db, plan_id, **update_values)
        if updated is None:
            raise HTTPException(status_code=404, detail="定时计划不存在")
        return _build_scheduled_plan_response(updated)


@router.get("", response_model=ScheduledPlanListResponse)
async def list_scheduled_plans(
    enabled: bool | None = Query(None),
    cpa_service_id: int | None = Query(None, ge=1),
):
    with get_db() as db:
        plans = crud.get_scheduled_plans(
            db,
            enabled=enabled,
            cpa_service_id=cpa_service_id,
        )
        return ScheduledPlanListResponse(
            items=[_build_scheduled_plan_response(plan) for plan in plans],
            total=len(plans),
        )


@router.get("/{plan_id}/runs", response_model=ScheduledRunListResponse)
async def list_scheduled_runs(plan_id: int, limit: int = Query(20, ge=1, le=200)):
    with get_db() as db:
        plan = crud.get_scheduled_plan_by_id(db, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="定时计划不存在")

        runs = (
            db.query(ScheduledRun)
            .filter(ScheduledRun.plan_id == plan_id)
            .order_by(desc(ScheduledRun.started_at), desc(ScheduledRun.id))
            .limit(limit)
            .all()
        )
        return ScheduledRunListResponse(runs=[_build_scheduled_run_response(run) for run in runs])


@router.get("/runs/{run_id}/logs", response_model=ScheduledRunLogsResponse)
async def get_scheduled_run_logs(run_id: int):
    with get_db() as db:
        run = db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
        if run is None:
            raise HTTPException(status_code=404, detail="运行记录不存在")

        return ScheduledRunLogsResponse(run_id=run.id, logs=run.logs or "")


@router.post("/{plan_id}/enable", response_model=ScheduledPlanResponse)
async def enable_scheduled_plan(plan_id: int):
    with get_db() as db:
        plan = crud.get_scheduled_plan_by_id(db, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="定时计划不存在")

        try:
            next_run_at = _to_scheduler_naive_time(compute_next_run_at(plan))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        updated = crud.update_scheduled_plan(
            db,
            plan_id,
            enabled=True,
            next_run_at=next_run_at,
            auto_disabled_reason=None,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="定时计划不存在")
        return _build_scheduled_plan_response(updated)


@router.post("/{plan_id}/disable", response_model=ScheduledPlanResponse)
async def disable_scheduled_plan(plan_id: int):
    with get_db() as db:
        plan = crud.get_scheduled_plan_by_id(db, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="定时计划不存在")

        updated = crud.update_scheduled_plan(
            db,
            plan_id,
            enabled=False,
            next_run_at=None,
            auto_disabled_reason=None,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="定时计划不存在")
        return _build_scheduled_plan_response(updated)


@router.post("/{plan_id}/run")
async def run_scheduled_plan(plan_id: int, request: Request):
    with get_db() as db:
        plan = crud.get_scheduled_plan_by_id(db, plan_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="定时计划不存在")

    scheduler_engine = getattr(request.app.state, "scheduler_engine", None)
    if scheduler_engine is None:
        raise HTTPException(status_code=500, detail="scheduler engine is not initialized")

    try:
        run_id = scheduler_engine.trigger_plan_now(plan_id)
    except SchedulerPlanConflictError as exc:
        reason = str(exc).strip().lower()
        detail = "计划正在运行"
        if reason == "cpa already busy":
            detail = "关联 CPA 服务正在执行其他计划"
        raise HTTPException(status_code=409, detail=detail)
    except SchedulerDispatchError as exc:
        message = str(exc).strip()
        if "does not exist" in message.lower():
            raise HTTPException(status_code=404, detail="定时计划不存在") from exc
        raise HTTPException(status_code=500, detail=str(exc) or "计划触发失败") from exc

    return {"success": True, "plan_id": plan_id, "run_id": int(run_id)}
