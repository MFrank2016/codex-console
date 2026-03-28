"""
注册任务 API 路由
"""

import asyncio
import logging
import uuid
import random
from datetime import datetime, timedelta
from typing import Any, List, Optional, Dict, Tuple

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Request
from pydantic import BaseModel, ConfigDict, Field

from ...database import crud
from ...database.repositories import registration_failure_repository as failure_repo
from ...database.session import get_db
from ...database.models import RegistrationTask, Proxy
from ...core.registration_batch_metrics import apply_task_outcome, build_domain_stats
from ...core.registration_batch_stats import finalize_batch_statistics
from ...core.registration_job import run_registration_job
from ...core.registration_failure_records import (
    RegistrationFailureQuery,
    current_shanghai_day_window_utc_naive,
    resolve_failure_window,
)
from ...application import BatchRegistrationService, ProxyDispatchService, RegistrationService
from ...application.batch_registration_service import (
    DEFAULT_BATCH_PROXY_POOLS_STORE,
    DEFAULT_BATCH_TASKS_STORE,
)
from ...services import EmailServiceType
from ...core.time import utc_now, utc_now_naive
from ..auth import require_authenticated
from ..task_manager import task_manager

logger = logging.getLogger(__name__)
router = APIRouter()

# 批量任务运行态存储由 application 层持有，route 仅保留兼容别名。
batch_tasks: Dict[str, dict] = DEFAULT_BATCH_TASKS_STORE
batch_proxy_pools: Dict[str, object] = DEFAULT_BATCH_PROXY_POOLS_STORE


def _proxy_list_provider(limit: int) -> List[dict]:
    with get_db() as db:
        proxies = crud.get_enabled_proxies(db)
        return [
            {
                "proxy_url": proxy.proxy_url,
                "proxy_id": proxy.id,
                "proxy_key": f"proxy-list:{proxy.id}",
            }
            for proxy in proxies
        ]


def _build_proxy_dispatch_service() -> ProxyDispatchService:
    return ProxyDispatchService(
        proxy_list_provider=_proxy_list_provider,
    )


def _build_registration_service() -> RegistrationService:
    return RegistrationService(
        db_factory=get_db,
        task_manager=task_manager,
        job_runner=run_registration_job,
        proxy_dispatcher=_build_proxy_dispatch_service(),
        utc_now_provider=utc_now_naive,
    )


def _build_batch_registration_service() -> BatchRegistrationService:
    return BatchRegistrationService(
        db_factory=get_db,
        task_manager=task_manager,
        batch_tasks_store=batch_tasks,
        batch_proxy_pools_store=batch_proxy_pools,
        registration_task_runner=run_registration_task,
        batch_domain_stats_finalizer=_finalize_batch_domain_stats,
        domain_stats_builder=build_domain_stats,
        batch_outcome_applier=apply_task_outcome,
        batch_statistics_finalizer=finalize_batch_statistics,
        proxy_dispatcher=_build_proxy_dispatch_service(),
        utc_now_provider=utc_now_naive,
    )


# ============== Pydantic Models ==============

class RegistrationTaskCreate(BaseModel):
    """创建注册任务请求"""
    email_service_type: str = "tempmail"
    pipeline_key: str = "current_pipeline"
    use_proxy: bool = False
    proxy: Optional[str] = None
    email_service_config: Optional[dict] = None
    email_service_id: Optional[int] = None
    auto_upload_cpa: bool = False
    cpa_service_ids: List[int] = []  # 指定 CPA 服务 ID 列表，空则取第一个启用的
    auto_upload_sub2api: bool = False
    sub2api_service_ids: List[int] = []  # 指定 Sub2API 服务 ID 列表
    auto_upload_tm: bool = False
    tm_service_ids: List[int] = []  # 指定 TM 服务 ID 列表
    dynamic_proxy_request_count: Optional[int] = None
    proxy_list_candidate_limit: Optional[int] = None


class BatchRegistrationRequest(BaseModel):
    """批量注册请求"""
    count: int = 1
    email_service_type: str = "tempmail"
    pipeline_key: str = "current_pipeline"
    use_proxy: bool = False
    proxy: Optional[str] = None
    email_service_config: Optional[dict] = None
    email_service_id: Optional[int] = None
    interval_min: int = 5
    interval_max: int = 30
    concurrency: int = 1
    mode: str = "pipeline"
    auto_upload_cpa: bool = False
    cpa_service_ids: List[int] = []
    auto_upload_sub2api: bool = False
    sub2api_service_ids: List[int] = []
    auto_upload_tm: bool = False
    tm_service_ids: List[int] = []
    dynamic_proxy_request_count: Optional[int] = None
    dynamic_proxy_probe_url: Optional[str] = None
    dynamic_proxy_strategy: Optional[str] = None


class RegistrationTaskResponse(BaseModel):
    """注册任务响应"""
    id: int
    task_uuid: str
    status: str
    email_service_id: Optional[int] = None
    pipeline_key: Optional[str] = None
    current_step_key: Optional[str] = None
    pipeline_status: Optional[str] = None
    total_duration_ms: Optional[int] = None
    proxy: Optional[str] = None
    logs: Optional[str] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    steps: List[dict] = Field(default_factory=list)
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BatchRegistrationResponse(BaseModel):
    """批量注册响应"""
    batch_id: str
    count: int
    is_unlimited: bool = False
    tasks: List[RegistrationTaskResponse]


class TaskListResponse(BaseModel):
    """任务列表响应"""
    total: int
    tasks: List[RegistrationTaskResponse]


class RegistrationFailureItemResponse(BaseModel):
    id: int
    task_uuid: str
    attempt_no: int
    batch_id: Optional[str] = None
    pipeline_key: str
    registration_mode: str
    email: Optional[str] = None
    email_suffix: Optional[str] = None
    email_service_type: Optional[str] = None
    display_name: Optional[str] = None
    birthdate: Optional[str] = None
    proxy: Optional[str] = None
    proxy_ip: Optional[str] = None
    error_code: str
    error_detail: str
    failed_at: Optional[str] = None
    created_at: Optional[str] = None
    extra_json: Optional[dict] = None


class RegistrationFailureListResponse(BaseModel):
    total: int
    items: List[RegistrationFailureItemResponse]


class RegistrationFailureSummaryResponse(BaseModel):
    total_failed_attempts: int
    today_failed_attempts: int
    top_email_suffixes: List[dict]
    top_error_codes: List[dict]
    top_proxy_ips: List[dict]


# ============== Outlook 批量注册模型 ==============

class OutlookAccountForRegistration(BaseModel):
    """可用于注册的 Outlook 账户"""
    id: int                      # EmailService 表的 ID
    email: str
    name: str
    has_oauth: bool              # 是否有 OAuth 配置
    is_registered: bool          # 是否已注册
    registered_account_id: Optional[int] = None


class OutlookAccountsListResponse(BaseModel):
    """Outlook 账户列表响应"""
    total: int
    registered_count: int        # 已注册数量
    unregistered_count: int      # 未注册数量
    accounts: List[OutlookAccountForRegistration]


class OutlookBatchRegistrationRequest(BaseModel):
    """Outlook 批量注册请求"""
    service_ids: List[int]
    skip_registered: bool = True
    use_proxy: bool = False
    proxy: Optional[str] = None
    interval_min: int = 5
    interval_max: int = 30
    concurrency: int = 1
    mode: str = "pipeline"
    auto_upload_cpa: bool = False
    cpa_service_ids: List[int] = []
    auto_upload_sub2api: bool = False
    sub2api_service_ids: List[int] = []
    auto_upload_tm: bool = False
    tm_service_ids: List[int] = []
    dynamic_proxy_request_count: Optional[int] = None
    dynamic_proxy_probe_url: Optional[str] = None
    dynamic_proxy_strategy: Optional[str] = None


class OutlookBatchRegistrationResponse(BaseModel):
    """Outlook 批量注册响应"""
    batch_id: str
    total: int                   # 总数
    skipped: int                 # 跳过数（已注册）
    to_register: int             # 待注册数
    service_ids: List[int]       # 实际要注册的服务 ID


# ============== Helper Functions ==============

def _step_run_to_dict(step_run) -> dict:
    return {
        "id": step_run.id,
        "step_key": step_run.step_key,
        "step_order": step_run.step_order,
        "step_impl": step_run.step_impl,
        "status": step_run.status,
        "duration_ms": step_run.duration_ms,
        "error_message": step_run.error_message,
        "started_at": step_run.started_at.isoformat() if step_run.started_at else None,
        "completed_at": step_run.completed_at.isoformat() if step_run.completed_at else None,
    }


def _collect_task_steps(db, task_uuid: str) -> List[dict]:
    step_rows = crud.get_pipeline_step_runs_by_task_uuid(db, task_uuid)
    if step_rows:
        return [_step_run_to_dict(row) for row in step_rows]

    if hasattr(task_manager, "get_task_steps"):
        return task_manager.get_task_steps(task_uuid)
    return []


def task_to_response(task: RegistrationTask, *, steps: Optional[List[dict]] = None) -> RegistrationTaskResponse:
    """转换任务模型为响应"""
    return RegistrationTaskResponse(
        id=task.id,
        task_uuid=task.task_uuid,
        status=task.status,
        email_service_id=task.email_service_id,
        pipeline_key=task.pipeline_key,
        current_step_key=task.current_step_key,
        pipeline_status=task.pipeline_status,
        total_duration_ms=task.total_duration_ms,
        proxy=task.proxy,
        logs=task.logs,
        result=task.result,
        error_message=task.error_message,
        steps=list(steps or []),
        created_at=task.created_at.isoformat() if task.created_at else None,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


def _build_failure_filters(
    *,
    pipeline_key: Optional[str],
    registration_mode: Optional[str],
    email_service_type: Optional[str],
    email_suffix: Optional[str],
    error_keyword: Optional[str],
    failed_from: datetime,
    failed_to: datetime,
) -> RegistrationFailureQuery:
    return RegistrationFailureQuery(
        pipeline_key=str(pipeline_key or "").strip() or None,
        registration_mode=str(registration_mode or "").strip() or None,
        email_service_type=str(email_service_type or "").strip() or None,
        email_suffix=str(email_suffix or "").strip() or None,
        error_keyword=str(error_keyword or "").strip() or None,
        failed_from=failed_from,
        failed_to=failed_to,
    )


def _current_day_intersection_count(db, *, now: datetime, filters: RegistrationFailureQuery) -> int:
    day_start, day_end_exclusive = current_shanghai_day_window_utc_naive(now)
    # repository 层使用 <= failed_to，因此这里把“次日 00:00:00 的开区间上界”
    # 转成“当天 23:59:59.999999 的闭区间上界”，避免出现 off-by-one。
    day_end_inclusive = day_end_exclusive - timedelta(microseconds=1)

    effective_from = max(filters.failed_from, day_start) if filters.failed_from else day_start
    effective_to = min(filters.failed_to, day_end_inclusive) if filters.failed_to else day_end_inclusive
    if effective_from > effective_to:
        return 0

    today_filters = RegistrationFailureQuery(
        pipeline_key=filters.pipeline_key,
        registration_mode=filters.registration_mode,
        email_service_type=filters.email_service_type,
        email_suffix=filters.email_suffix,
        error_keyword=filters.error_keyword,
        failed_from=effective_from,
        failed_to=effective_to,
    )
    return failure_repo.count_registration_failure_records(db, filters=today_filters)


@router.get("/failures/summary", response_model=RegistrationFailureSummaryResponse)
async def get_registration_failures_summary(
    request: Request,
    pipeline_key: Optional[str] = None,
    registration_mode: Optional[str] = None,
    email_service_type: Optional[str] = None,
    email_suffix: Optional[str] = None,
    error_keyword: Optional[str] = None,
    failed_from: Optional[str] = None,
    failed_to: Optional[str] = None,
):
    require_authenticated(request)
    now = utc_now()
    try:
        window_from, window_to = resolve_failure_window(
            failed_from_raw=failed_from,
            failed_to_raw=failed_to,
            now=now,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    filters = _build_failure_filters(
        pipeline_key=pipeline_key,
        registration_mode=registration_mode,
        email_service_type=email_service_type,
        email_suffix=email_suffix,
        error_keyword=error_keyword,
        failed_from=window_from,
        failed_to=window_to,
    )

    with get_db() as db:
        summary = failure_repo.build_registration_failure_summary(db, filters=filters)
        today_failed_attempts = _current_day_intersection_count(db, now=now, filters=filters)

    return {
        **summary,
        "today_failed_attempts": today_failed_attempts,
    }


@router.get("/failures", response_model=RegistrationFailureListResponse)
async def get_registration_failures(
    request: Request,
    pipeline_key: Optional[str] = None,
    registration_mode: Optional[str] = None,
    email_service_type: Optional[str] = None,
    email_suffix: Optional[str] = None,
    error_keyword: Optional[str] = None,
    failed_from: Optional[str] = None,
    failed_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    require_authenticated(request)
    try:
        window_from, window_to = resolve_failure_window(
            failed_from_raw=failed_from,
            failed_to_raw=failed_to,
            now=utc_now(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    safe_page = max(1, int(page or 1))
    safe_page_size = min(100, max(1, int(page_size or 20)))
    filters = _build_failure_filters(
        pipeline_key=pipeline_key,
        registration_mode=registration_mode,
        email_service_type=email_service_type,
        email_suffix=email_suffix,
        error_keyword=error_keyword,
        failed_from=window_from,
        failed_to=window_to,
    )

    with get_db() as db:
        total = failure_repo.count_registration_failure_records(db, filters=filters)
        items = failure_repo.list_registration_failure_records(
            db,
            filters=filters,
            page=safe_page,
            page_size=safe_page_size,
        )

    return {
        "total": total,
        "items": [item.to_dict() for item in items],
    }


def _run_sync_registration_task(task_uuid: str, email_service_type: str, proxy: Optional[str], email_service_config: Optional[dict], email_service_id: Optional[int] = None, log_prefix: str = "", batch_id: str = "", registration_mode: str = "single", auto_upload_cpa: bool = False, cpa_service_ids: List[int] = None, auto_upload_sub2api: bool = False, sub2api_service_ids: List[int] = None, auto_upload_tm: bool = False, tm_service_ids: List[int] = None, pipeline_key: Optional[str] = None, *, use_proxy: bool = False, proxy_task_group: str = "single_registration", proxy_overrides: Optional[dict] = None, resolved_proxy_candidate: Any = None):
    return _build_registration_service().run_single_task_sync(
        task_uuid=task_uuid,
        email_service_type=email_service_type,
        proxy=proxy,
        email_service_config=email_service_config,
        email_service_id=email_service_id,
        log_prefix=log_prefix,
        batch_id=batch_id,
        registration_mode=registration_mode,
        auto_upload_cpa=auto_upload_cpa,
        cpa_service_ids=cpa_service_ids or [],
        auto_upload_sub2api=auto_upload_sub2api,
        sub2api_service_ids=sub2api_service_ids or [],
        auto_upload_tm=auto_upload_tm,
        tm_service_ids=tm_service_ids or [],
        pipeline_key=pipeline_key,
        use_proxy=use_proxy,
        proxy_task_group=proxy_task_group,
        proxy_overrides=proxy_overrides or {},
        resolved_proxy_candidate=resolved_proxy_candidate,
    )

async def run_registration_task(task_uuid: str, email_service_type: str, proxy: Optional[str], email_service_config: Optional[dict], email_service_id: Optional[int] = None, log_prefix: str = "", batch_id: str = "", registration_mode: str = "single", auto_upload_cpa: bool = False, cpa_service_ids: List[int] = None, auto_upload_sub2api: bool = False, sub2api_service_ids: List[int] = None, auto_upload_tm: bool = False, tm_service_ids: List[int] = None, pipeline_key: Optional[str] = None, *, use_proxy: bool = False, proxy_task_group: str = "single_registration", proxy_overrides: Optional[dict] = None, resolved_proxy_candidate: Any = None):
    return await _build_registration_service().run_single_task(
        task_uuid=task_uuid,
        email_service_type=email_service_type,
        proxy=proxy,
        email_service_config=email_service_config,
        email_service_id=email_service_id,
        log_prefix=log_prefix,
        batch_id=batch_id,
        registration_mode=registration_mode,
        auto_upload_cpa=auto_upload_cpa,
        cpa_service_ids=cpa_service_ids or [],
        auto_upload_sub2api=auto_upload_sub2api,
        sub2api_service_ids=sub2api_service_ids or [],
        auto_upload_tm=auto_upload_tm,
        tm_service_ids=tm_service_ids or [],
        pipeline_key=pipeline_key,
        use_proxy=use_proxy,
        proxy_task_group=proxy_task_group,
        proxy_overrides=proxy_overrides or {},
        resolved_proxy_candidate=resolved_proxy_candidate,
    )

def _init_batch_state(
    batch_id: str,
    task_uuids: List[str],
    *,
    is_unlimited: bool = False,
    total: Optional[int] = None,
    statistics_context: Optional[dict] = None,
):
    _build_batch_registration_service().init_batch_state(
        batch_id,
        task_uuids,
        is_unlimited=is_unlimited,
        total=total,
        statistics_context=statistics_context,
    )

def _make_batch_helpers(batch_id: str):
    return _build_batch_registration_service().make_batch_helpers(batch_id)

def _finalize_batch_domain_stats(batch_id: str, task_uuids: List[str]) -> None:
    _build_batch_registration_service().finalize_batch_domain_stats(batch_id, task_uuids)

def _build_batch_statistics_context(
    *,
    batch_id: str,
    task_uuids: List[str],
    mode: str,
    pipeline_key: Optional[str],
    email_service_type: str,
    email_service_id: Optional[int],
    proxy: Optional[str],
    interval_min: Optional[int],
    interval_max: Optional[int],
    concurrency: int,
) -> dict:
    return _build_batch_registration_service().build_batch_statistics_context(
        batch_id=batch_id,
        task_uuids=task_uuids,
        mode=mode,
        pipeline_key=pipeline_key,
        email_service_type=email_service_type,
        email_service_id=email_service_id,
        proxy=proxy,
        interval_min=interval_min,
        interval_max=interval_max,
        concurrency=concurrency,
    )

def _finalize_ordinary_batch_statistics(*, batch_id: str, status: str) -> None:
    _build_batch_registration_service().finalize_ordinary_batch_statistics(batch_id=batch_id, status=status)


def _build_single_proxy_overrides(request: RegistrationTaskCreate) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if request.dynamic_proxy_request_count is not None:
        overrides["dynamic_request_count"] = request.dynamic_proxy_request_count
    if request.proxy_list_candidate_limit is not None:
        overrides["proxy_list_candidate_limit"] = request.proxy_list_candidate_limit
    return overrides


def _build_batch_proxy_overrides(
    request: BatchRegistrationRequest | OutlookBatchRegistrationRequest,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if request.dynamic_proxy_request_count is not None:
        overrides["dynamic_request_count"] = request.dynamic_proxy_request_count
    if request.dynamic_proxy_probe_url:
        overrides["probe_url"] = request.dynamic_proxy_probe_url
    if request.dynamic_proxy_strategy:
        overrides["allocation_strategy"] = request.dynamic_proxy_strategy
    return overrides

async def run_unlimited_batch_registration(
    batch_id: str,
    email_service_type: str,
    proxy: Optional[str],
    email_service_config: Optional[dict],
    email_service_id: Optional[int],
    interval_min: int,
    interval_max: int,
    concurrency: int,
    mode: str,
    auto_upload_cpa: bool = False,
    cpa_service_ids: List[int] = None,
    auto_upload_sub2api: bool = False,
    sub2api_service_ids: List[int] = None,
    auto_upload_tm: bool = False,
    tm_service_ids: List[int] = None,
    pipeline_key: Optional[str] = None,
    *,
    use_proxy: bool = False,
    proxy_task_group: str = "unlimited_registration",
    proxy_overrides: Optional[dict] = None,
):
    return await _build_batch_registration_service().run_unlimited_batch_registration(
        batch_id=batch_id,
        email_service_type=email_service_type,
        proxy=proxy,
        email_service_config=email_service_config,
        email_service_id=email_service_id,
        interval_min=interval_min,
        interval_max=interval_max,
        concurrency=concurrency,
        mode=mode,
        auto_upload_cpa=auto_upload_cpa,
        cpa_service_ids=cpa_service_ids or [],
        auto_upload_sub2api=auto_upload_sub2api,
        sub2api_service_ids=sub2api_service_ids or [],
        auto_upload_tm=auto_upload_tm,
        tm_service_ids=tm_service_ids or [],
        pipeline_key=pipeline_key,
        use_proxy=use_proxy,
        proxy_task_group=proxy_task_group,
        proxy_overrides=proxy_overrides or {},
    )

async def run_batch_parallel(
    batch_id: str,
    task_uuids: List[str],
    email_service_type: str,
    proxy: Optional[str],
    email_service_config: Optional[dict],
    email_service_id: Optional[int],
    concurrency: int,
    interval_min: int = 0,
    interval_max: int = 0,
    auto_upload_cpa: bool = False,
    cpa_service_ids: List[int] = None,
    auto_upload_sub2api: bool = False,
    sub2api_service_ids: List[int] = None,
    auto_upload_tm: bool = False,
    tm_service_ids: List[int] = None,
    pipeline_key: Optional[str] = None,
    enable_stats_finalization: bool = True,
    *,
    use_proxy: bool = False,
    proxy_task_group: str = "batch_registration",
    proxy_overrides: Optional[dict] = None,
):
    return await _build_batch_registration_service().run_batch_parallel(
        batch_id=batch_id,
        task_uuids=task_uuids,
        email_service_type=email_service_type,
        proxy=proxy,
        email_service_config=email_service_config,
        email_service_id=email_service_id,
        concurrency=concurrency,
        interval_min=interval_min,
        interval_max=interval_max,
        auto_upload_cpa=auto_upload_cpa,
        cpa_service_ids=cpa_service_ids or [],
        auto_upload_sub2api=auto_upload_sub2api,
        sub2api_service_ids=sub2api_service_ids or [],
        auto_upload_tm=auto_upload_tm,
        tm_service_ids=tm_service_ids or [],
        pipeline_key=pipeline_key,
        enable_stats_finalization=enable_stats_finalization,
        use_proxy=use_proxy,
        proxy_task_group=proxy_task_group,
        proxy_overrides=proxy_overrides or {},
    )

async def run_batch_pipeline(
    batch_id: str,
    task_uuids: List[str],
    email_service_type: str,
    proxy: Optional[str],
    email_service_config: Optional[dict],
    email_service_id: Optional[int],
    interval_min: int,
    interval_max: int,
    concurrency: int,
    auto_upload_cpa: bool = False,
    cpa_service_ids: List[int] = None,
    auto_upload_sub2api: bool = False,
    sub2api_service_ids: List[int] = None,
    auto_upload_tm: bool = False,
    tm_service_ids: List[int] = None,
    pipeline_key: Optional[str] = None,
    enable_stats_finalization: bool = True,
    *,
    use_proxy: bool = False,
    proxy_task_group: str = "batch_registration",
    proxy_overrides: Optional[dict] = None,
):
    return await _build_batch_registration_service().run_batch_pipeline(
        batch_id=batch_id,
        task_uuids=task_uuids,
        email_service_type=email_service_type,
        proxy=proxy,
        email_service_config=email_service_config,
        email_service_id=email_service_id,
        interval_min=interval_min,
        interval_max=interval_max,
        concurrency=concurrency,
        auto_upload_cpa=auto_upload_cpa,
        cpa_service_ids=cpa_service_ids or [],
        auto_upload_sub2api=auto_upload_sub2api,
        sub2api_service_ids=sub2api_service_ids or [],
        auto_upload_tm=auto_upload_tm,
        tm_service_ids=tm_service_ids or [],
        pipeline_key=pipeline_key,
        enable_stats_finalization=enable_stats_finalization,
        use_proxy=use_proxy,
        proxy_task_group=proxy_task_group,
        proxy_overrides=proxy_overrides or {},
    )

async def run_batch_registration(
    batch_id: str,
    task_uuids: List[str],
    email_service_type: str,
    proxy: Optional[str],
    email_service_config: Optional[dict],
    email_service_id: Optional[int],
    interval_min: int,
    interval_max: int,
    concurrency: int = 1,
    mode: str = "pipeline",
    auto_upload_cpa: bool = False,
    cpa_service_ids: List[int] = None,
    auto_upload_sub2api: bool = False,
    sub2api_service_ids: List[int] = None,
    auto_upload_tm: bool = False,
    tm_service_ids: List[int] = None,
    pipeline_key: Optional[str] = None,
    enable_stats_finalization: bool = True,
    *,
    use_proxy: bool = False,
    proxy_task_group: str = "batch_registration",
    proxy_overrides: Optional[dict] = None,
):
    return await _build_batch_registration_service().run_batch_registration(
        batch_id=batch_id,
        task_uuids=task_uuids,
        email_service_type=email_service_type,
        proxy=proxy,
        email_service_config=email_service_config,
        email_service_id=email_service_id,
        interval_min=interval_min,
        interval_max=interval_max,
        concurrency=concurrency,
        mode=mode,
        auto_upload_cpa=auto_upload_cpa,
        cpa_service_ids=cpa_service_ids or [],
        auto_upload_sub2api=auto_upload_sub2api,
        sub2api_service_ids=sub2api_service_ids or [],
        auto_upload_tm=auto_upload_tm,
        tm_service_ids=tm_service_ids or [],
        pipeline_key=pipeline_key,
        enable_stats_finalization=enable_stats_finalization,
        use_proxy=use_proxy,
        proxy_task_group=proxy_task_group,
        proxy_overrides=proxy_overrides or {},
    )

# ============== API Endpoints ==============

@router.post("/start", response_model=RegistrationTaskResponse)
async def start_registration(
    request: RegistrationTaskCreate,
    background_tasks: BackgroundTasks
):
    """
    启动注册任务

    - email_service_type: 邮箱服务类型 (tempmail, outlook, moe_mail)
    - proxy: 代理地址
    - email_service_config: 邮箱服务配置（outlook 需要提供账户信息）
    """
    # 验证邮箱服务类型
    try:
        EmailServiceType(request.email_service_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的邮箱服务类型: {request.email_service_type}"
        )

    # 创建任务
    task_uuid = str(uuid.uuid4())
    task = _build_registration_service().create_task(
        task_uuid=task_uuid,
        proxy=request.proxy if request.use_proxy else None,
        pipeline_key=request.pipeline_key,
        email_service_id=request.email_service_id,
    )

    # 在后台运行注册任务
    background_tasks.add_task(
        run_registration_task,
        task_uuid,
        request.email_service_type,
        request.proxy if request.use_proxy else None,
        request.email_service_config,
        request.email_service_id,
        "",
        "",
        request.auto_upload_cpa,
        request.cpa_service_ids,
        request.auto_upload_sub2api,
        request.sub2api_service_ids,
        request.auto_upload_tm,
        request.tm_service_ids,
        request.pipeline_key,
        use_proxy=request.use_proxy,
        proxy_task_group="single_registration",
        proxy_overrides=_build_single_proxy_overrides(request),
    )

    return task_to_response(task)


@router.post("/batch", response_model=BatchRegistrationResponse)
async def start_batch_registration(
    request: BatchRegistrationRequest,
    background_tasks: BackgroundTasks
):
    """
    启动批量注册任务

    - count: 注册数量 (0-500)
    - email_service_type: 邮箱服务类型
    - proxy: 代理地址
    - interval_min: 最小间隔秒数
    - interval_max: 最大间隔秒数
    """
    # 验证参数
    if request.count < 0 or request.count > 500:
        raise HTTPException(status_code=400, detail="注册数量必须在 0-500 之间")

    try:
        EmailServiceType(request.email_service_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的邮箱服务类型: {request.email_service_type}"
        )

    if request.interval_min < 0 or request.interval_max < request.interval_min:
        raise HTTPException(status_code=400, detail="间隔时间参数无效")

    if not 1 <= request.concurrency <= 50:
        raise HTTPException(status_code=400, detail="并发数必须在 1-50 之间")

    if request.mode not in ("parallel", "pipeline"):
        raise HTTPException(status_code=400, detail="模式必须为 parallel 或 pipeline")
    if request.dynamic_proxy_strategy and request.dynamic_proxy_strategy not in {"random", "exclusive", "consume_once", "strict_isolation"}:
        raise HTTPException(status_code=400, detail="动态代理策略无效")

    is_unlimited = request.count == 0

    # 创建批量任务
    batch_id = str(uuid.uuid4())
    batch_service = _build_batch_registration_service()
    batch_proxy_overrides = _build_batch_proxy_overrides(request)
    batch_proxy_overrides = _build_batch_proxy_overrides(request)

    if is_unlimited:
        if request.use_proxy:
            try:
                batch_service.prepare_batch_proxy_pool(
                    batch_id=batch_id,
                    task_group="unlimited_registration",
                    concurrency=request.concurrency,
                    overrides=batch_proxy_overrides,
                )
            except RuntimeError as exc:
                logger.warning("批量任务 %s 预热动态代理池失败，将在运行时回退: %s", batch_id, exc)
        _init_batch_state(batch_id, [], is_unlimited=True, total=0)
        background_tasks.add_task(
            run_unlimited_batch_registration,
            batch_id,
            request.email_service_type,
            request.proxy if request.use_proxy else None,
            request.email_service_config,
            request.email_service_id,
            request.interval_min,
            request.interval_max,
            request.concurrency,
            request.mode,
            request.auto_upload_cpa,
            request.cpa_service_ids,
            request.auto_upload_sub2api,
            request.sub2api_service_ids,
            request.auto_upload_tm,
            request.tm_service_ids,
            request.pipeline_key,
            use_proxy=request.use_proxy,
            proxy_task_group="unlimited_registration",
            proxy_overrides=batch_proxy_overrides,
        )
        return BatchRegistrationResponse(
            batch_id=batch_id,
            count=request.count,
            is_unlimited=True,
            tasks=[],
        )

    if request.use_proxy:
        try:
            batch_service.prepare_batch_proxy_pool(
                batch_id=batch_id,
                task_group="batch_registration",
                concurrency=request.concurrency,
                overrides=batch_proxy_overrides,
            )
        except RuntimeError as exc:
            logger.warning("批量任务 %s 预热动态代理池失败，将在运行时回退: %s", batch_id, exc)

    tasks = batch_service.create_batch_tasks(
        count=request.count,
        proxy=request.proxy if request.use_proxy else None,
        pipeline_key=request.pipeline_key,
    )
    task_uuids = [task.task_uuid for task in tasks]

    # 在后台运行批量注册
    background_tasks.add_task(
        run_batch_registration,
        batch_id,
        task_uuids,
        request.email_service_type,
        request.proxy if request.use_proxy else None,
        request.email_service_config,
        request.email_service_id,
        request.interval_min,
        request.interval_max,
        request.concurrency,
        request.mode,
        request.auto_upload_cpa,
        request.cpa_service_ids,
        request.auto_upload_sub2api,
        request.sub2api_service_ids,
        request.auto_upload_tm,
        request.tm_service_ids,
        request.pipeline_key,
        use_proxy=request.use_proxy,
        proxy_task_group="batch_registration",
        proxy_overrides=batch_proxy_overrides,
    )

    return BatchRegistrationResponse(
        batch_id=batch_id,
        count=request.count,
        is_unlimited=False,
        tasks=[task_to_response(t) for t in tasks if t]
    )


@router.get("/batch/{batch_id}")
async def get_batch_status(batch_id: str):
    """获取批量任务状态"""
    if batch_id not in batch_tasks:
        raise HTTPException(status_code=404, detail="批量任务不存在")

    batch = batch_tasks[batch_id]
    return {
        "batch_id": batch_id,
        "total": batch["total"],
        "completed": batch["completed"],
        "success": batch["success"],
        "failed": batch["failed"],
        "current_index": batch["current_index"],
        "cancelled": batch["cancelled"],
        "finished": batch.get("finished", False),
        "started_at": batch.get("started_at"),
        "progress": f"{batch['completed']}/{batch['total']}",
        "is_unlimited": batch.get("is_unlimited", False),
        "consecutive_failures": batch.get("consecutive_failures", 0),
        "max_consecutive_failures": batch.get("max_consecutive_failures", 10),
        "stop_reason": batch.get("stop_reason"),
        "domain_stats": batch.get("domain_stats", []),
    }


@router.post("/batch/{batch_id}/cancel")
async def cancel_batch(batch_id: str):
    """取消批量任务"""
    if batch_id not in batch_tasks:
        raise HTTPException(status_code=404, detail="批量任务不存在")

    batch = batch_tasks[batch_id]
    if batch.get("finished"):
        raise HTTPException(status_code=400, detail="批量任务已完成")

    batch["cancelled"] = True
    task_manager.cancel_batch(batch_id)
    return {"success": True, "message": "批量任务取消请求已提交，正在让它们有序收工"}


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
):
    """获取任务列表"""
    with get_db() as db:
        query = db.query(RegistrationTask)

        if status:
            query = query.filter(RegistrationTask.status == status)

        total = query.count()
        offset = (page - 1) * page_size
        tasks = query.order_by(RegistrationTask.created_at.desc()).offset(offset).limit(page_size).all()

        response_tasks: List[RegistrationTaskResponse] = []
        for task in tasks:
            response_tasks.append(task_to_response(task, steps=_collect_task_steps(db, task.task_uuid)))

        return TaskListResponse(
            total=total,
            tasks=response_tasks
        )


@router.get("/tasks/{task_uuid}", response_model=RegistrationTaskResponse)
async def get_task(task_uuid: str):
    """获取任务详情"""
    with get_db() as db:
        task = crud.get_registration_task(db, task_uuid)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task_to_response(task, steps=_collect_task_steps(db, task_uuid))


@router.get("/tasks/{task_uuid}/logs")
async def get_task_logs(task_uuid: str):
    """获取任务日志（旧接口）

    说明：
    - 注册工作台（registration-workbench）主实时链路已切换到 shared realtime console
    - 前端主链路通过 `/registration/streams/*` alias 消费统一 stream contract
    - alias 底层委托给共享 realtime stream helper，本接口仅为旧页面/脚本保留
    - 不应再作为实时主来源
    """
    with get_db() as db:
        task = crud.get_registration_task(db, task_uuid)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        logs = task.logs or ""
        return {
            "task_uuid": task_uuid,
            "status": task.status,
            "logs": logs.split("\n") if logs else []
        }


@router.post("/tasks/{task_uuid}/cancel")
async def cancel_task(task_uuid: str):
    """取消任务"""
    with get_db() as db:
        task = crud.get_registration_task(db, task_uuid)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        if task.status not in ["pending", "running"]:
            raise HTTPException(status_code=400, detail="任务已完成或已取消")

        task = crud.update_registration_task(db, task_uuid, status="cancelled")

        return {"success": True, "message": "任务已取消"}


@router.delete("/tasks/{task_uuid}")
async def delete_task(task_uuid: str):
    """删除任务"""
    with get_db() as db:
        task = crud.get_registration_task(db, task_uuid)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        if task.status == "running":
            raise HTTPException(status_code=400, detail="无法删除运行中的任务")

        crud.delete_registration_task(db, task_uuid)

        return {"success": True, "message": "任务已删除"}


@router.get("/stats")
async def get_registration_stats():
    """获取注册统计信息"""
    with get_db() as db:
        from sqlalchemy import func

        # 按状态统计
        status_stats = db.query(
            RegistrationTask.status,
            func.count(RegistrationTask.id)
        ).group_by(RegistrationTask.status).all()

        # 今日注册数
        today = utc_now_naive().date()
        today_count = db.query(func.count(RegistrationTask.id)).filter(
            func.date(RegistrationTask.created_at) == today
        ).scalar()

        return {
            "by_status": {status: count for status, count in status_stats},
            "today_count": today_count
        }


@router.get("/available-services")
async def get_available_email_services():
    """
    获取可用于注册的邮箱服务列表

    返回所有已启用的邮箱服务，包括：
    - tempmail: 临时邮箱（无需配置）
    - outlook: 已导入的 Outlook 账户
    - moe_mail: 已配置的自定义域名服务
    """
    from ...database.models import EmailService as EmailServiceModel
    from ...config.settings import get_settings

    settings = get_settings()
    result = {
        "tempmail": {
            "available": True,
            "count": 1,
            "services": [{
                "id": None,
                "name": "Tempmail.lol",
                "type": "tempmail",
                "description": "临时邮箱，自动创建"
            }]
        },
        "outlook": {
            "available": False,
            "count": 0,
            "services": []
        },
        "moe_mail": {
            "available": False,
            "count": 0,
            "services": []
        },
        "temp_mail": {
            "available": False,
            "count": 0,
            "services": []
        },
        "duck_mail": {
            "available": False,
            "count": 0,
            "services": []
        },
        "freemail": {
            "available": False,
            "count": 0,
            "services": []
        },
        "imap_mail": {
            "available": False,
            "count": 0,
            "services": []
        }
    }

    with get_db() as db:
        # 获取 Outlook 账户
        outlook_services = db.query(EmailServiceModel).filter(
            EmailServiceModel.service_type == "outlook",
            EmailServiceModel.enabled == True
        ).order_by(EmailServiceModel.priority.asc()).all()

        for service in outlook_services:
            config = service.config or {}
            result["outlook"]["services"].append({
                "id": service.id,
                "name": service.name,
                "type": "outlook",
                "has_oauth": bool(config.get("client_id") and config.get("refresh_token")),
                "priority": service.priority
            })

        result["outlook"]["count"] = len(outlook_services)
        result["outlook"]["available"] = len(outlook_services) > 0

        # 获取自定义域名服务
        custom_services = db.query(EmailServiceModel).filter(
            EmailServiceModel.service_type == "moe_mail",
            EmailServiceModel.enabled == True
        ).order_by(EmailServiceModel.priority.asc()).all()

        for service in custom_services:
            config = service.config or {}
            result["moe_mail"]["services"].append({
                "id": service.id,
                "name": service.name,
                "type": "moe_mail",
                "default_domain": config.get("default_domain"),
                "priority": service.priority
            })

        result["moe_mail"]["count"] = len(custom_services)
        result["moe_mail"]["available"] = len(custom_services) > 0

        # 如果数据库中没有自定义域名服务，检查 settings
        if not result["moe_mail"]["available"]:
            if settings.custom_domain_base_url and settings.custom_domain_api_key:
                result["moe_mail"]["available"] = True
                result["moe_mail"]["count"] = 1
                result["moe_mail"]["services"].append({
                    "id": None,
                    "name": "默认自定义域名服务",
                    "type": "moe_mail",
                    "from_settings": True
                })

        # 获取 TempMail 服务（自部署 Cloudflare Worker 临时邮箱）
        temp_mail_services = db.query(EmailServiceModel).filter(
            EmailServiceModel.service_type == "temp_mail",
            EmailServiceModel.enabled == True
        ).order_by(EmailServiceModel.priority.asc()).all()

        for service in temp_mail_services:
            config = service.config or {}
            result["temp_mail"]["services"].append({
                "id": service.id,
                "name": service.name,
                "type": "temp_mail",
                "domain": config.get("domain"),
                "priority": service.priority
            })

        result["temp_mail"]["count"] = len(temp_mail_services)
        result["temp_mail"]["available"] = len(temp_mail_services) > 0

        duck_mail_services = db.query(EmailServiceModel).filter(
            EmailServiceModel.service_type == "duck_mail",
            EmailServiceModel.enabled == True
        ).order_by(EmailServiceModel.priority.asc()).all()

        for service in duck_mail_services:
            config = service.config or {}
            result["duck_mail"]["services"].append({
                "id": service.id,
                "name": service.name,
                "type": "duck_mail",
                "default_domain": config.get("default_domain"),
                "priority": service.priority
            })

        result["duck_mail"]["count"] = len(duck_mail_services)
        result["duck_mail"]["available"] = len(duck_mail_services) > 0

        freemail_services = db.query(EmailServiceModel).filter(
            EmailServiceModel.service_type == "freemail",
            EmailServiceModel.enabled == True
        ).order_by(EmailServiceModel.priority.asc()).all()

        for service in freemail_services:
            config = service.config or {}
            result["freemail"]["services"].append({
                "id": service.id,
                "name": service.name,
                "type": "freemail",
                "domain": config.get("domain"),
                "priority": service.priority
            })

        result["freemail"]["count"] = len(freemail_services)
        result["freemail"]["available"] = len(freemail_services) > 0

        imap_mail_services = db.query(EmailServiceModel).filter(
            EmailServiceModel.service_type == "imap_mail",
            EmailServiceModel.enabled == True
        ).order_by(EmailServiceModel.priority.asc()).all()

        for service in imap_mail_services:
            config = service.config or {}
            result["imap_mail"]["services"].append({
                "id": service.id,
                "name": service.name,
                "type": "imap_mail",
                "email": config.get("email"),
                "host": config.get("host"),
                "priority": service.priority
            })

        result["imap_mail"]["count"] = len(imap_mail_services)
        result["imap_mail"]["available"] = len(imap_mail_services) > 0

    return result


# ============== Outlook 批量注册 API ==============

@router.get("/outlook-accounts", response_model=OutlookAccountsListResponse)
async def get_outlook_accounts_for_registration():
    """
    获取可用于注册的 Outlook 账户列表

    返回所有已启用的 Outlook 服务，并检查每个邮箱是否已在 accounts 表中注册
    """
    from ...database.models import EmailService as EmailServiceModel
    from ...database.models import Account

    with get_db() as db:
        # 获取所有启用的 Outlook 服务
        outlook_services = db.query(EmailServiceModel).filter(
            EmailServiceModel.service_type == "outlook",
            EmailServiceModel.enabled == True
        ).order_by(EmailServiceModel.priority.asc()).all()

        accounts = []
        registered_count = 0
        unregistered_count = 0

        for service in outlook_services:
            config = service.config or {}
            email = config.get("email") or service.name

            # 检查是否已注册（查询 accounts 表）
            existing_account = db.query(Account).filter(
                Account.email == email
            ).first()

            is_registered = existing_account is not None
            if is_registered:
                registered_count += 1
            else:
                unregistered_count += 1

            accounts.append(OutlookAccountForRegistration(
                id=service.id,
                email=email,
                name=service.name,
                has_oauth=bool(config.get("client_id") and config.get("refresh_token")),
                is_registered=is_registered,
                registered_account_id=existing_account.id if existing_account else None
            ))

        return OutlookAccountsListResponse(
            total=len(accounts),
            registered_count=registered_count,
            unregistered_count=unregistered_count,
            accounts=accounts
        )


async def run_outlook_batch_registration(
    batch_id: str,
    service_ids: List[int],
    skip_registered: bool,
    proxy: Optional[str],
    interval_min: int,
    interval_max: int,
    concurrency: int = 1,
    mode: str = "pipeline",
    auto_upload_cpa: bool = False,
    cpa_service_ids: List[int] = None,
    auto_upload_sub2api: bool = False,
    sub2api_service_ids: List[int] = None,
    auto_upload_tm: bool = False,
    tm_service_ids: List[int] = None,
    *,
    use_proxy: bool = False,
    proxy_task_group: str = "outlook_batch",
    proxy_overrides: Optional[dict] = None,
):
    return await _build_batch_registration_service().run_outlook_batch_registration(
        batch_id=batch_id,
        service_ids=service_ids,
        skip_registered=skip_registered,
        proxy=proxy,
        interval_min=interval_min,
        interval_max=interval_max,
        concurrency=concurrency,
        mode=mode,
        auto_upload_cpa=auto_upload_cpa,
        cpa_service_ids=cpa_service_ids or [],
        auto_upload_sub2api=auto_upload_sub2api,
        sub2api_service_ids=sub2api_service_ids or [],
        auto_upload_tm=auto_upload_tm,
        tm_service_ids=tm_service_ids or [],
        use_proxy=use_proxy,
        proxy_task_group=proxy_task_group,
        proxy_overrides=proxy_overrides or {},
    )

@router.post("/outlook-batch", response_model=OutlookBatchRegistrationResponse)
async def start_outlook_batch_registration(
    request: OutlookBatchRegistrationRequest,
    background_tasks: BackgroundTasks
):
    """
    启动 Outlook 批量注册任务

    - service_ids: 选中的 EmailService ID 列表
    - skip_registered: 是否自动跳过已注册邮箱（默认 True）
    - proxy: 代理地址
    - interval_min: 最小间隔秒数
    - interval_max: 最大间隔秒数
    """
    from ...database.models import EmailService as EmailServiceModel
    from ...database.models import Account

    # 验证参数
    if not request.service_ids:
        raise HTTPException(status_code=400, detail="请选择至少一个 Outlook 账户")

    if request.interval_min < 0 or request.interval_max < request.interval_min:
        raise HTTPException(status_code=400, detail="间隔时间参数无效")

    if not 1 <= request.concurrency <= 50:
        raise HTTPException(status_code=400, detail="并发数必须在 1-50 之间")

    if request.mode not in ("parallel", "pipeline"):
        raise HTTPException(status_code=400, detail="模式必须为 parallel 或 pipeline")
    if request.dynamic_proxy_strategy and request.dynamic_proxy_strategy not in {"random", "exclusive", "consume_once", "strict_isolation"}:
        raise HTTPException(status_code=400, detail="动态代理策略无效")

    # 过滤掉已注册的邮箱
    actual_service_ids = request.service_ids
    skipped_count = 0

    if request.skip_registered:
        actual_service_ids = []
        with get_db() as db:
            for service_id in request.service_ids:
                service = db.query(EmailServiceModel).filter(
                    EmailServiceModel.id == service_id
                ).first()

                if not service:
                    continue

                config = service.config or {}
                email = config.get("email") or service.name

                # 检查是否已注册
                existing_account = db.query(Account).filter(
                    Account.email == email
                ).first()

                if existing_account:
                    skipped_count += 1
                else:
                    actual_service_ids.append(service_id)

    if not actual_service_ids:
        return OutlookBatchRegistrationResponse(
            batch_id="",
            total=len(request.service_ids),
            skipped=skipped_count,
            to_register=0,
            service_ids=[]
        )

    # 创建批量任务
    batch_id = str(uuid.uuid4())
    batch_service = _build_batch_registration_service()
    batch_proxy_overrides = _build_batch_proxy_overrides(request)

    # 初始化批量任务状态
    batch_tasks[batch_id] = {
        "total": len(actual_service_ids),
        "completed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "cancelled": False,
        "service_ids": actual_service_ids,
        "current_index": 0,
        "logs": [],
        "finished": False
    }

    if request.use_proxy:
        try:
            batch_service.prepare_batch_proxy_pool(
                batch_id=batch_id,
                task_group="outlook_batch",
                concurrency=request.concurrency,
                overrides=batch_proxy_overrides,
            )
        except RuntimeError as exc:
            logger.warning("Outlook 批量任务 %s 预热动态代理池失败，将在运行时回退: %s", batch_id, exc)

    # 在后台运行批量注册
    background_tasks.add_task(
        run_outlook_batch_registration,
        batch_id,
        actual_service_ids,
        request.skip_registered,
        request.proxy if request.use_proxy else None,
        request.interval_min,
        request.interval_max,
        request.concurrency,
        request.mode,
        request.auto_upload_cpa,
        request.cpa_service_ids,
        request.auto_upload_sub2api,
        request.sub2api_service_ids,
        request.auto_upload_tm,
        request.tm_service_ids,
        use_proxy=request.use_proxy,
        proxy_task_group="outlook_batch",
        proxy_overrides=batch_proxy_overrides,
    )

    return OutlookBatchRegistrationResponse(
        batch_id=batch_id,
        total=len(request.service_ids),
        skipped=skipped_count,
        to_register=len(actual_service_ids),
        service_ids=actual_service_ids
    )


@router.get("/outlook-batch/{batch_id}")
async def get_outlook_batch_status(batch_id: str):
    """获取 Outlook 批量任务状态"""
    if batch_id not in batch_tasks:
        raise HTTPException(status_code=404, detail="批量任务不存在")

    batch = batch_tasks[batch_id]
    return {
        "batch_id": batch_id,
        "total": batch["total"],
        "completed": batch["completed"],
        "success": batch["success"],
        "failed": batch["failed"],
        "skipped": batch.get("skipped", 0),
        "current_index": batch["current_index"],
        "cancelled": batch["cancelled"],
        "finished": batch.get("finished", False),
        "started_at": batch.get("started_at"),
        "logs": batch.get("logs", []),
        "progress": f"{batch['completed']}/{batch['total']}",
        "domain_stats": batch.get("domain_stats", []),
    }


@router.post("/outlook-batch/{batch_id}/cancel")
async def cancel_outlook_batch(batch_id: str):
    """取消 Outlook 批量任务"""
    if batch_id not in batch_tasks:
        raise HTTPException(status_code=404, detail="批量任务不存在")

    batch = batch_tasks[batch_id]
    if batch.get("finished"):
        raise HTTPException(status_code=400, detail="批量任务已完成")

    # 同时更新两个系统的取消状态
    batch["cancelled"] = True
    task_manager.cancel_batch(batch_id)

    return {"success": True, "message": "批量任务取消请求已提交，正在让它们有序收工"}
