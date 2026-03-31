"""
注册任务 API 路由
"""

import asyncio
import logging
import uuid
from typing import Any, List, Optional, Dict

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Request
from pydantic import BaseModel, ConfigDict, Field

from ...database import crud
from ...database.session import get_db
from ...core.registration_batch_metrics import apply_task_outcome, build_domain_stats
from ...core.registration_batch_stats import finalize_batch_statistics
from ...core.registration_job import run_registration_job
from ...application import (
    BatchRegistrationService,
    ProxyDispatchService,
    RegistrationQueryFacade,
    RegistrationService,
)
from ...application.registration_bootstrap_dtos import RegistrationTaskSnapshot
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




def _build_registration_query_facade() -> RegistrationQueryFacade:
    return RegistrationQueryFacade(
        db_factory=get_db,
        task_manager=task_manager,
        batch_tasks_store=batch_tasks,  # 测试中如需隔离，调用方应传入独立 dict 副本
        utc_now_provider=utc_now,
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
    email: Optional[str] = None
    email_service_id: Optional[int] = None
    pipeline_key: Optional[str] = None
    current_step_key: Optional[str] = None
    pipeline_status: Optional[str] = None
    total_duration_ms: Optional[int] = None
    proxy: Optional[str] = None
    proxy_ip: Optional[str] = None
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
    email_service_id: Optional[int] = None
    email_service_type: Optional[str] = None
    display_name: Optional[str] = None
    birthdate: Optional[str] = None
    proxy: Optional[str] = None
    proxy_ip: Optional[str] = None
    failure_stage: Optional[str] = None
    step_key: Optional[str] = None
    retryable: bool = False
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
    top_email_suffixes: List[dict] = Field(default_factory=list)
    top_error_codes: List[dict] = Field(default_factory=list)
    top_proxy_ips: List[dict] = Field(default_factory=list)
    top_failure_stages: List[dict] = Field(default_factory=list)
    top_step_keys: List[dict] = Field(default_factory=list)
    retryable_breakdown: List[dict] = Field(default_factory=list)


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

def _task_view_to_response(task_view: Any) -> RegistrationTaskResponse:
    return RegistrationTaskResponse(
        id=task_view.id,
        task_uuid=task_view.task_uuid,
        status=task_view.status,
        email=task_view.email,
        email_service_id=task_view.email_service_id,
        pipeline_key=task_view.pipeline_key,
        current_step_key=task_view.current_step_key,
        pipeline_status=task_view.pipeline_status,
        total_duration_ms=task_view.total_duration_ms,
        proxy=task_view.proxy,
        proxy_ip=task_view.proxy_ip,
        logs=task_view.logs,
        result=task_view.result,
        error_message=task_view.error_message,
        steps=list(task_view.steps or []),
        created_at=task_view.created_at,
        started_at=task_view.started_at,
        completed_at=task_view.completed_at,
    )


def snapshot_to_response(snapshot: RegistrationTaskSnapshot) -> RegistrationTaskResponse:
    return RegistrationTaskResponse(
        id=snapshot.id,
        task_uuid=snapshot.task_uuid,
        status=snapshot.status,
        created_at=snapshot.created_at,
        email_service_id=snapshot.email_service_id,
        pipeline_key=snapshot.pipeline_key,
        proxy=snapshot.proxy,
    )


@router.get("/failures/summary", response_model=RegistrationFailureSummaryResponse)
async def get_registration_failures_summary(
    request: Request,
    pipeline_key: Optional[str] = None,
    registration_mode: Optional[str] = None,
    email_service_type: Optional[str] = None,
    email_suffix: Optional[str] = None,
    email_service_id: Optional[int] = None,
    proxy_ip: Optional[str] = None,
    failure_stage: Optional[str] = None,
    step_key: Optional[str] = None,
    retryable: Optional[bool] = None,
    error_keyword: Optional[str] = None,
    failed_from: Optional[str] = None,
    failed_to: Optional[str] = None,
):
    require_authenticated(request)
    facade = _build_registration_query_facade()
    try:
        summary = facade.build_failure_summary(
            pipeline_key=pipeline_key,
            registration_mode=registration_mode,
            email_service_type=email_service_type,
            email_suffix=email_suffix,
            email_service_id=email_service_id,
            proxy_ip=proxy_ip,
            failure_stage=failure_stage,
            step_key=step_key,
            retryable=retryable,
            error_keyword=error_keyword,
            failed_from=failed_from,
            failed_to=failed_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "total_failed_attempts": summary.total_failed_attempts,
        "today_failed_attempts": summary.today_failed_attempts,
        "top_email_suffixes": summary.top_email_suffixes,
        "top_error_codes": summary.top_error_codes,
        "top_proxy_ips": summary.top_proxy_ips,
        "top_failure_stages": summary.top_failure_stages,
        "top_step_keys": summary.top_step_keys,
        "retryable_breakdown": summary.retryable_breakdown,
    }


@router.get("/failures", response_model=RegistrationFailureListResponse)
async def get_registration_failures(
    request: Request,
    pipeline_key: Optional[str] = None,
    registration_mode: Optional[str] = None,
    email_service_type: Optional[str] = None,
    email_suffix: Optional[str] = None,
    email_service_id: Optional[int] = None,
    proxy_ip: Optional[str] = None,
    failure_stage: Optional[str] = None,
    step_key: Optional[str] = None,
    retryable: Optional[bool] = None,
    error_keyword: Optional[str] = None,
    failed_from: Optional[str] = None,
    failed_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    require_authenticated(request)
    facade = _build_registration_query_facade()
    try:
        result = facade.list_failures(
            pipeline_key=pipeline_key,
            registration_mode=registration_mode,
            email_service_type=email_service_type,
            email_suffix=email_suffix,
            email_service_id=email_service_id,
            proxy_ip=proxy_ip,
            failure_stage=failure_stage,
            step_key=step_key,
            retryable=retryable,
            error_keyword=error_keyword,
            failed_from=failed_from,
            failed_to=failed_to,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "total": result.total,
        "items": result.items,
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
    snapshot = _build_registration_service().start_task(
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

    return snapshot_to_response(snapshot)


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

    batch_service = _build_batch_registration_service()
    batch_proxy_overrides = _build_batch_proxy_overrides(request)
    bootstrap = batch_service.start_batch(
        count=request.count,
        proxy=request.proxy if request.use_proxy else None,
        pipeline_key=request.pipeline_key,
        concurrency=request.concurrency,
        use_proxy=request.use_proxy,
        proxy_task_group="batch_registration" if request.count else "unlimited_registration",
        proxy_overrides=batch_proxy_overrides,
    )
    batch_id = bootstrap.batch_id
    is_unlimited = bootstrap.is_unlimited

    if is_unlimited:
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

    task_uuids = [snapshot.task_uuid for snapshot in bootstrap.task_snapshots]

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
        tasks=[snapshot_to_response(snapshot) for snapshot in bootstrap.task_snapshots]
    )


@router.get("/batch/{batch_id}")
async def get_batch_status(batch_id: str):
    """获取批量任务状态"""
    view = _build_registration_query_facade().get_batch_status(batch_id)
    if view is None:
        raise HTTPException(status_code=404, detail="批量任务不存在")
    return view.payload


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
    view = _build_registration_query_facade().list_tasks(
        page=page,
        page_size=page_size,
        status=status,
    )
    return TaskListResponse(
        total=view.total,
        tasks=[_task_view_to_response(task_view) for task_view in view.tasks],
    )


@router.get("/tasks/{task_uuid}", response_model=RegistrationTaskResponse)
async def get_task(task_uuid: str):
    """获取任务详情"""
    task_view = _build_registration_query_facade().get_task_detail(task_uuid)
    if task_view is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_view_to_response(task_view)


@router.get("/tasks/{task_uuid}/logs")
async def get_task_logs(task_uuid: str):
    """获取任务日志（旧接口）

    说明：
    - 注册工作台（registration-workbench）主实时链路已切换到 shared realtime console
    - 前端主链路通过 `/registration/streams/*` alias 消费统一 stream contract
    - alias 底层委托给共享 realtime stream helper，本接口仅为旧页面/脚本保留
    - 不应再作为实时主来源
    """
    payload = _build_registration_query_facade().get_task_logs(task_uuid)
    if payload is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return payload


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
    stats = _build_registration_query_facade().get_registration_stats()
    return {
        "by_status": stats.by_status,
        "today_count": stats.today_count,
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
    return _build_registration_query_facade().get_available_email_services()


# ============== Outlook 批量注册 API ==============

@router.get("/outlook-accounts", response_model=OutlookAccountsListResponse)
async def get_outlook_accounts_for_registration():
    """
    获取可用于注册的 Outlook 账户列表

    返回所有已启用的 Outlook 服务，并检查每个邮箱是否已在 accounts 表中注册
    """
    payload = _build_registration_query_facade().get_outlook_accounts_for_registration()
    return OutlookAccountsListResponse(**payload)


async def run_outlook_batch_registration(
    batch_id: str,
    service_ids: List[int],
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

    batch_service = _build_batch_registration_service()
    batch_proxy_overrides = _build_batch_proxy_overrides(request)
    bootstrap = batch_service.start_outlook_batch(
        service_ids=request.service_ids,
        skip_registered=request.skip_registered,
        concurrency=request.concurrency,
        use_proxy=request.use_proxy,
        proxy_task_group="outlook_batch",
        proxy_overrides=batch_proxy_overrides,
    )

    if not bootstrap.service_ids:
        return OutlookBatchRegistrationResponse(
            batch_id="",
            total=bootstrap.total,
            skipped=bootstrap.skipped,
            to_register=0,
            service_ids=[],
        )

    # 在后台运行批量注册
    background_tasks.add_task(
        run_outlook_batch_registration,
        bootstrap.batch_id,
        list(bootstrap.service_ids),
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
        batch_id=bootstrap.batch_id,
        total=bootstrap.total,
        skipped=bootstrap.skipped,
        to_register=len(bootstrap.service_ids),
        service_ids=list(bootstrap.service_ids),
    )


@router.get("/outlook-batch/{batch_id}")
async def get_outlook_batch_status(batch_id: str):
    """获取 Outlook 批量任务状态"""
    view = _build_registration_query_facade().get_outlook_batch_status(batch_id)
    if view is None:
        raise HTTPException(status_code=404, detail="批量任务不存在")
    return view.payload


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
