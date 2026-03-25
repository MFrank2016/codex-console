from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from ..core.registration_batch_metrics import apply_task_outcome, build_domain_stats
from ..core.registration_batch_stats import finalize_batch_statistics
from ..core.time import utc_now_naive
from ..database import crud
from ..database.models import RegistrationRun, RegistrationTask
from .proxy_dispatch_service import ProxyDispatchService, ResolvedProxyCandidate
from .registration_runs_service import RegistrationRunsService

logger = logging.getLogger(__name__)

DEFAULT_BATCH_TASKS_STORE: dict[str, dict] = {}
DEFAULT_BATCH_PROXY_POOLS_STORE: dict[str, Any] = {}


@dataclass
class BatchExecutionSummary:
    batch_id: str
    total: int
    completed: int
    success: int
    failed: int
    cancelled: bool
    finished: bool
    status: str | None
    is_unlimited: bool
    stop_reason: str | None
    domain_stats: list[dict]
    task_uuids: list[str]
    runs: list[RegistrationRun]


class BatchRegistrationService:
    def __init__(
        self,
        *,
        db_factory,
        task_manager=None,
        batch_tasks_store: dict[str, dict] | None = None,
        batch_proxy_pools_store: dict[str, Any] | None = None,
        registration_task_runner: Callable[..., Any] | None = None,
        batch_domain_stats_finalizer: Callable[[str, list[str]], None] | None = None,
        domain_stats_builder: Callable[[list[RegistrationTask]], list[dict]] = build_domain_stats,
        batch_outcome_applier: Callable[[dict, str], None] = apply_task_outcome,
        batch_statistics_finalizer: Callable[..., Any] = finalize_batch_statistics,
        proxy_dispatcher: ProxyDispatchService | None = None,
        utc_now_provider: Callable[[], Any] = utc_now_naive,
    ):
        self.db_factory = db_factory
        if task_manager is None:
            from ..web.task_manager import task_manager as default_task_manager

            task_manager = default_task_manager
        self.task_manager = task_manager
        self.batch_tasks = batch_tasks_store if batch_tasks_store is not None else DEFAULT_BATCH_TASKS_STORE
        self.batch_proxy_pools = (
            batch_proxy_pools_store
            if batch_proxy_pools_store is not None
            else DEFAULT_BATCH_PROXY_POOLS_STORE
        )
        self.registration_task_runner = registration_task_runner
        self.batch_domain_stats_finalizer = batch_domain_stats_finalizer
        self.domain_stats_builder = domain_stats_builder
        self.batch_outcome_applier = batch_outcome_applier
        self.batch_statistics_finalizer = batch_statistics_finalizer
        self.proxy_dispatcher = proxy_dispatcher
        self.utc_now_provider = utc_now_provider

    def create_batch_tasks(
        self,
        *,
        count: int,
        proxy: str | None,
        pipeline_key: str | None,
    ) -> list[RegistrationTask]:
        tasks: list[RegistrationTask] = []
        with self.db_factory() as db:
            for _ in range(count):
                task_uuid = str(uuid.uuid4())
                task = crud.create_registration_task(
                    db,
                    task_uuid=task_uuid,
                    proxy=proxy,
                    pipeline_key=pipeline_key,
                )
                tasks.append(task)
        return tasks

    def create_outlook_task_records(self, *, service_ids: list[int], proxy: str | None) -> list[str]:
        task_uuids: list[str] = []
        with self.db_factory() as db:
            for service_id in service_ids:
                task_uuid = str(uuid.uuid4())
                crud.create_registration_task(
                    db,
                    task_uuid=task_uuid,
                    proxy=proxy,
                    email_service_id=service_id,
                )
                task_uuids.append(task_uuid)
        return task_uuids

    def init_batch_state(
        self,
        batch_id: str,
        task_uuids: list[str],
        *,
        is_unlimited: bool = False,
        total: int | None = None,
        statistics_context: dict | None = None,
    ) -> None:
        computed_total = 0 if is_unlimited else (total if total is not None else len(task_uuids))
        self.task_manager.init_batch(
            batch_id,
            computed_total,
            is_unlimited=is_unlimited,
            consecutive_failures=0,
            max_consecutive_failures=10,
            stop_reason=None,
            domain_stats=[],
        )
        self.batch_tasks[batch_id] = {
            "status": "running",
            "total": computed_total,
            "completed": 0,
            "success": 0,
            "failed": 0,
            "cancelled": False,
            "task_uuids": list(task_uuids),
            "current_index": 0,
            "logs": [],
            "finished": False,
            "is_unlimited": is_unlimited,
            "consecutive_failures": 0,
            "max_consecutive_failures": 10,
            "stop_reason": None,
            "domain_stats": [],
            "statistics_context": statistics_context,
        }

    def prepare_batch_proxy_pool(
        self,
        *,
        batch_id: str,
        task_group: str,
        concurrency: int,
        overrides: dict[str, Any] | None,
    ):
        if self.proxy_dispatcher is None:
            raise RuntimeError("proxy dispatcher is not configured")
        pool = self.proxy_dispatcher.prepare_batch_proxy_pool(
            batch_id=batch_id,
            task_group=task_group,
            concurrency=concurrency,
            overrides=overrides or {},
        )
        self.batch_proxy_pools[batch_id] = pool
        return pool

    def make_batch_helpers(self, batch_id: str):
        def add_batch_log(message: str):
            self.batch_tasks[batch_id]["logs"].append(message)
            self.task_manager.add_batch_log(batch_id, message)

        def update_batch_status(**kwargs):
            for key, value in kwargs.items():
                if key in self.batch_tasks[batch_id]:
                    self.batch_tasks[batch_id][key] = value
            self.task_manager.update_batch_status(batch_id, **kwargs)
            if kwargs.get("finished") and hasattr(self.task_manager, "close_batch_stream"):
                final_status = (
                    kwargs.get("status")
                    or self.batch_tasks.get(batch_id, {}).get("status")
                    or "completed"
                )
                try:
                    self.task_manager.close_batch_stream(batch_id, final_status=final_status)
                except TypeError:
                    self.task_manager.close_batch_stream(batch_id, final_status)

        return add_batch_log, update_batch_status

    def finalize_batch_domain_stats(self, batch_id: str, task_uuids: list[str]) -> None:
        with self.db_factory() as db:
            tasks = (
                db.query(RegistrationTask)
                .filter(RegistrationTask.task_uuid.in_(task_uuids))
                .filter(RegistrationTask.status.in_(["completed", "failed"]))
                .all()
            )

        stats = self.domain_stats_builder(tasks)
        if batch_id in self.batch_tasks:
            self.batch_tasks[batch_id]["domain_stats"] = stats
        self.task_manager.update_batch_status(batch_id, domain_stats=stats)

    def _finalize_domain_stats(self, batch_id: str, task_uuids: list[str]) -> None:
        if self.batch_domain_stats_finalizer is not None:
            self.batch_domain_stats_finalizer(batch_id, task_uuids)
            return
        self.finalize_batch_domain_stats(batch_id, task_uuids)

    def build_batch_statistics_context(
        self,
        *,
        batch_id: str,
        task_uuids: list[str],
        mode: str,
        pipeline_key: str | None,
        email_service_type: str,
        email_service_id: int | None,
        proxy: str | None,
        interval_min: int | None,
        interval_max: int | None,
        concurrency: int,
    ) -> dict:
        return {
            "batch_id": batch_id,
            "mode": mode,
            "pipeline_key": pipeline_key or "current_pipeline",
            "email_service_type": email_service_type,
            "email_service_id": email_service_id,
            "config_snapshot": {
                "proxy": proxy,
                "interval_min": interval_min,
                "interval_max": interval_max,
                "concurrency": concurrency,
            },
            "started_at": self.utc_now_provider(),
            "task_uuids": list(task_uuids),
            "target_count": len(task_uuids),
        }

    def finalize_ordinary_batch_statistics(self, *, batch_id: str, status: str) -> None:
        context = self.batch_tasks.get(batch_id, {}).get("statistics_context")
        if not context:
            logger.warning("Batch %s missing statistics context; skipping stats finalization.", batch_id)
            return

        payload = dict(context)
        payload["status"] = status
        payload["completed_at"] = self.utc_now_provider()

        with self.db_factory() as db:
            try:
                self.batch_statistics_finalizer(db, batch_context=payload)
            except Exception:
                logger.exception("Failed to finalize batch statistics for batch %s", batch_id)

    def build_summary(self, batch_id: str, *, task_uuids: list[str] | None = None) -> BatchExecutionSummary:
        state = self.batch_tasks.get(batch_id, {})
        effective_task_uuids = list(task_uuids or state.get("task_uuids", []))
        runs: list[RegistrationRun] = []
        with self.db_factory() as db:
            runs_service = RegistrationRunsService(db)
            for task_uuid in effective_task_uuids:
                run = runs_service.get_run_by_task_uuid(task_uuid)
                if run is not None:
                    runs.append(run)

        return BatchExecutionSummary(
            batch_id=batch_id,
            total=state.get("total", len(effective_task_uuids)),
            completed=state.get("completed", 0),
            success=state.get("success", 0),
            failed=state.get("failed", 0),
            cancelled=state.get("cancelled", False),
            finished=state.get("finished", False),
            status=state.get("status"),
            is_unlimited=state.get("is_unlimited", False),
            stop_reason=state.get("stop_reason"),
            domain_stats=list(state.get("domain_stats", [])),
            task_uuids=effective_task_uuids,
            runs=runs,
        )

    def _load_outcome_status(self, task_uuid: str) -> str | None:
        with self.db_factory() as db:
            runs_service = RegistrationRunsService(db)
            run = runs_service.get_run_by_task_uuid(task_uuid)
            if run is not None:
                return run.status
            task = crud.get_registration_task(db, task_uuid)
            return task.status if task is not None else None

    def _get_batch_proxy_pool(self, batch_id: str):
        return self.batch_proxy_pools.get(batch_id)

    def _clear_batch_proxy_pool(self, batch_id: str) -> None:
        self.batch_proxy_pools.pop(batch_id, None)

    def _lease_proxy_for_batch_task(
        self,
        *,
        batch_id: str,
        explicit_proxy: str | None,
    ) -> tuple[str | None, ResolvedProxyCandidate | None]:
        if explicit_proxy:
            return explicit_proxy, None
        pool = self._get_batch_proxy_pool(batch_id)
        if pool is None:
            return None, None
        candidate = pool.lease()
        return candidate.proxy_url, candidate

    def _release_batch_proxy(
        self,
        *,
        batch_id: str,
        candidate: ResolvedProxyCandidate | None,
        success: bool,
    ) -> None:
        if candidate is None:
            return
        pool = self._get_batch_proxy_pool(batch_id)
        if pool is None:
            return
        pool.complete(candidate, success=success)

    def _mark_proxy_pool_failure(self, batch_id: str, task_uuid: str, error_message: str) -> None:
        with self.db_factory() as db:
            task = crud.get_registration_task(db, task_uuid)
            if task is None:
                return
            runs_service = RegistrationRunsService(db)
            run = runs_service.get_run_by_task_uuid(task_uuid)
            if run is None:
                run = runs_service.create_run(task_uuid=task_uuid, batch_id=batch_id, trigger_source="batch")
            crud.update_registration_task(
                db,
                task_uuid,
                status="failed",
                pipeline_status="failed",
                completed_at=self.utc_now_provider(),
                error_message=error_message,
            )
            runs_service.mark_failed(run.id, error_message=error_message)
            runs_service.append_event(run.id, level="error", message="failed")

        if hasattr(self.task_manager, "update_status"):
            self.task_manager.update_status(task_uuid, "failed", error=error_message)
        if hasattr(self.task_manager, "clear_task_steps"):
            self.task_manager.clear_task_steps(task_uuid)

    async def _run_single_task(self, *args, **kwargs):
        if self.registration_task_runner is None:
            raise RuntimeError("registration_task_runner is required")
        result = self.registration_task_runner(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    async def run_unlimited_batch_registration(
        self,
        batch_id: str,
        email_service_type: str,
        proxy: str | None,
        email_service_config: dict[str, Any] | None,
        email_service_id: int | None,
        interval_min: int,
        interval_max: int,
        concurrency: int,
        mode: str,
        auto_upload_cpa: bool = False,
        cpa_service_ids: list[int] | None = None,
        auto_upload_sub2api: bool = False,
        sub2api_service_ids: list[int] | None = None,
        auto_upload_tm: bool = False,
        tm_service_ids: list[int] | None = None,
        pipeline_key: str | None = None,
    ) -> BatchExecutionSummary:
        if batch_id not in self.batch_tasks:
            self.init_batch_state(batch_id, [], is_unlimited=True, total=0)

        add_batch_log, update_batch_status = self.make_batch_helpers(batch_id)
        semaphore = asyncio.Semaphore(concurrency)
        counter_lock = asyncio.Lock()
        running: set[asyncio.Task] = set()
        task_uuids: list[str] = list(self.batch_tasks[batch_id]["task_uuids"])
        next_index = 0
        add_batch_log(f"[系统] 无限模式启动，并发数: {concurrency}，模式: {mode}")

        async def _spawn_one(index: int):
            task_uuid = str(uuid.uuid4())
            task_uuids.append(task_uuid)
            self.batch_tasks[batch_id]["task_uuids"].append(task_uuid)
            with self.db_factory() as db:
                crud.create_registration_task(db, task_uuid=task_uuid, proxy=proxy, pipeline_key=pipeline_key)

            leased_candidate = None
            effective_proxy = proxy
            try:
                effective_proxy, leased_candidate = self._lease_proxy_for_batch_task(
                    batch_id=batch_id,
                    explicit_proxy=proxy,
                )
            except RuntimeError as exc:
                self._mark_proxy_pool_failure(batch_id, task_uuid, str(exc))
                async with counter_lock:
                    self.batch_outcome_applier(self.batch_tasks[batch_id], "failed")
                    self.batch_tasks[batch_id]["stop_reason"] = "proxy_pool_exhausted"
                    update_batch_status(
                        completed=self.batch_tasks[batch_id]["completed"],
                        success=self.batch_tasks[batch_id]["success"],
                        failed=self.batch_tasks[batch_id]["failed"],
                        stop_reason="proxy_pool_exhausted",
                    )
                    add_batch_log(f"[任务{index}] [失败] 代理池耗尽: {exc}")
                return

            async with semaphore:
                try:
                    await self._run_single_task(
                        task_uuid,
                        email_service_type,
                        effective_proxy,
                        email_service_config,
                        email_service_id,
                        log_prefix=f"[任务{index}]",
                        batch_id=batch_id,
                        auto_upload_cpa=auto_upload_cpa,
                        cpa_service_ids=cpa_service_ids or [],
                        auto_upload_sub2api=auto_upload_sub2api,
                        sub2api_service_ids=sub2api_service_ids or [],
                        auto_upload_tm=auto_upload_tm,
                        tm_service_ids=tm_service_ids or [],
                        pipeline_key=pipeline_key,
                    )
                finally:
                    status = self._load_outcome_status(task_uuid) or "failed"
                    self._release_batch_proxy(
                        batch_id=batch_id,
                        candidate=leased_candidate,
                        success=status == "completed",
                    )

            status = self._load_outcome_status(task_uuid)
            if status is None:
                return

            async with counter_lock:
                self.batch_outcome_applier(self.batch_tasks[batch_id], status)
                update_batch_status(
                    completed=self.batch_tasks[batch_id]["completed"],
                    success=self.batch_tasks[batch_id]["success"],
                    failed=self.batch_tasks[batch_id]["failed"],
                    consecutive_failures=self.batch_tasks[batch_id]["consecutive_failures"],
                    current_index=index,
                )

                with self.db_factory() as db:
                    task = crud.get_registration_task(db, task_uuid)

                if task is not None:
                    if status == "completed":
                        add_batch_log(f"[任务{index}] [成功] 注册成功")
                    elif status == "failed":
                        add_batch_log(f"[任务{index}] [失败] 注册失败: {task.error_message}")

                if self.batch_tasks[batch_id]["consecutive_failures"] > self.batch_tasks[batch_id]["max_consecutive_failures"]:
                    self.batch_tasks[batch_id]["stop_reason"] = "too_many_consecutive_failures"
                    update_batch_status(stop_reason="too_many_consecutive_failures")
                    add_batch_log("[停止] 连续失败次数过多，停止创建新任务")

        try:
            while not self.task_manager.is_batch_cancelled(batch_id) and self.batch_tasks[batch_id]["stop_reason"] is None:
                next_index += 1
                running.add(asyncio.create_task(_spawn_one(next_index)))

                if mode == "pipeline":
                    await asyncio.sleep(random.randint(interval_min, interval_max))

                if len(running) >= concurrency:
                    done, pending = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                    for completed_task in done:
                        await completed_task
                    running = set(pending)

            if running:
                await asyncio.gather(*running)

            self._finalize_domain_stats(batch_id, task_uuids)
            if self.task_manager.is_batch_cancelled(batch_id):
                update_batch_status(finished=True, status="cancelled")
            else:
                update_batch_status(finished=True, status="completed")
        except Exception as exc:
            logger.exception("无限批量任务 %s 异常", batch_id)
            add_batch_log(f"[错误] 批量任务异常: {exc}")
            if running:
                for running_task in running:
                    if not running_task.done():
                        running_task.cancel()
                await asyncio.gather(*running, return_exceptions=True)
                running.clear()
            self._finalize_domain_stats(batch_id, task_uuids)
            update_batch_status(finished=True, status="failed")
        finally:
            self.batch_tasks[batch_id]["finished"] = True
            self._clear_batch_proxy_pool(batch_id)

        return self.build_summary(batch_id, task_uuids=task_uuids)

    async def run_batch_parallel(
        self,
        batch_id: str,
        task_uuids: list[str],
        email_service_type: str,
        proxy: str | None,
        email_service_config: dict[str, Any] | None,
        email_service_id: int | None,
        concurrency: int,
        interval_min: int = 0,
        interval_max: int = 0,
        auto_upload_cpa: bool = False,
        cpa_service_ids: list[int] | None = None,
        auto_upload_sub2api: bool = False,
        sub2api_service_ids: list[int] | None = None,
        auto_upload_tm: bool = False,
        tm_service_ids: list[int] | None = None,
        pipeline_key: str | None = None,
        enable_stats_finalization: bool = True,
    ) -> BatchExecutionSummary:
        statistics_context = None
        if enable_stats_finalization:
            statistics_context = self.build_batch_statistics_context(
                batch_id=batch_id,
                task_uuids=task_uuids,
                mode="parallel",
                pipeline_key=pipeline_key,
                email_service_type=email_service_type,
                email_service_id=email_service_id,
                proxy=proxy,
                interval_min=interval_min,
                interval_max=interval_max,
                concurrency=concurrency,
            )
        self.init_batch_state(batch_id, task_uuids, statistics_context=statistics_context)
        add_batch_log, update_batch_status = self.make_batch_helpers(batch_id)
        semaphore = asyncio.Semaphore(concurrency)
        counter_lock = asyncio.Lock()
        add_batch_log(f"[系统] 并行模式启动，并发数: {concurrency}，总任务: {len(task_uuids)}")

        async def _run_one(index: int, task_uuid: str):
            prefix = f"[任务{index + 1}]"
            leased_candidate = None
            effective_proxy = proxy
            try:
                effective_proxy, leased_candidate = self._lease_proxy_for_batch_task(
                    batch_id=batch_id,
                    explicit_proxy=proxy,
                )
            except RuntimeError as exc:
                self._mark_proxy_pool_failure(batch_id, task_uuid, str(exc))
                async with counter_lock:
                    self.batch_outcome_applier(self.batch_tasks[batch_id], "failed")
                    add_batch_log(f"{prefix} [失败] 代理池耗尽: {exc}")
                    update_batch_status(
                        completed=self.batch_tasks[batch_id]["completed"],
                        success=self.batch_tasks[batch_id]["success"],
                        failed=self.batch_tasks[batch_id]["failed"],
                        consecutive_failures=self.batch_tasks[batch_id]["consecutive_failures"],
                    )
                return
            async with semaphore:
                try:
                    await self._run_single_task(
                        task_uuid,
                        email_service_type,
                        effective_proxy,
                        email_service_config,
                        email_service_id,
                        log_prefix=prefix,
                        batch_id=batch_id,
                        auto_upload_cpa=auto_upload_cpa,
                        cpa_service_ids=cpa_service_ids or [],
                        auto_upload_sub2api=auto_upload_sub2api,
                        sub2api_service_ids=sub2api_service_ids or [],
                        auto_upload_tm=auto_upload_tm,
                        tm_service_ids=tm_service_ids or [],
                        pipeline_key=pipeline_key,
                    )
                finally:
                    status = self._load_outcome_status(task_uuid) or "failed"
                    self._release_batch_proxy(
                        batch_id=batch_id,
                        candidate=leased_candidate,
                        success=status == "completed",
                    )

            status = self._load_outcome_status(task_uuid)
            if status is None:
                return

            with self.db_factory() as db:
                task = crud.get_registration_task(db, task_uuid)

            if task is not None:
                async with counter_lock:
                    self.batch_outcome_applier(self.batch_tasks[batch_id], status)
                    if status == "completed":
                        add_batch_log(f"{prefix} [成功] 注册成功")
                    elif status == "failed":
                        add_batch_log(f"{prefix} [失败] 注册失败: {task.error_message}")
                    update_batch_status(
                        completed=self.batch_tasks[batch_id]["completed"],
                        success=self.batch_tasks[batch_id]["success"],
                        failed=self.batch_tasks[batch_id]["failed"],
                        consecutive_failures=self.batch_tasks[batch_id]["consecutive_failures"],
                    )

        try:
            await asyncio.gather(*[_run_one(index, task_uuid) for index, task_uuid in enumerate(task_uuids)], return_exceptions=True)
            self._finalize_domain_stats(batch_id, task_uuids)
            if not self.task_manager.is_batch_cancelled(batch_id):
                add_batch_log(
                    f"[完成] 批量任务完成！成功: {self.batch_tasks[batch_id]['success']}, 失败: {self.batch_tasks[batch_id]['failed']}"
                )
                terminal_status = "completed"
            else:
                terminal_status = "cancelled"
            if enable_stats_finalization:
                self.finalize_ordinary_batch_statistics(batch_id=batch_id, status=terminal_status)
            update_batch_status(finished=True, status=terminal_status)
        except Exception as exc:
            logger.exception("批量任务 %s 异常", batch_id)
            add_batch_log(f"[错误] 批量任务异常: {exc}")
            self._finalize_domain_stats(batch_id, task_uuids)
            if enable_stats_finalization:
                self.finalize_ordinary_batch_statistics(batch_id=batch_id, status="failed")
            update_batch_status(finished=True, status="failed")
        finally:
            self.batch_tasks[batch_id]["finished"] = True
            self._clear_batch_proxy_pool(batch_id)

        return self.build_summary(batch_id, task_uuids=task_uuids)

    async def run_batch_pipeline(
        self,
        batch_id: str,
        task_uuids: list[str],
        email_service_type: str,
        proxy: str | None,
        email_service_config: dict[str, Any] | None,
        email_service_id: int | None,
        interval_min: int,
        interval_max: int,
        concurrency: int,
        auto_upload_cpa: bool = False,
        cpa_service_ids: list[int] | None = None,
        auto_upload_sub2api: bool = False,
        sub2api_service_ids: list[int] | None = None,
        auto_upload_tm: bool = False,
        tm_service_ids: list[int] | None = None,
        pipeline_key: str | None = None,
        enable_stats_finalization: bool = True,
    ) -> BatchExecutionSummary:
        statistics_context = None
        if enable_stats_finalization:
            statistics_context = self.build_batch_statistics_context(
                batch_id=batch_id,
                task_uuids=task_uuids,
                mode="pipeline",
                pipeline_key=pipeline_key,
                email_service_type=email_service_type,
                email_service_id=email_service_id,
                proxy=proxy,
                interval_min=interval_min,
                interval_max=interval_max,
                concurrency=concurrency,
            )
        self.init_batch_state(batch_id, task_uuids, statistics_context=statistics_context)
        add_batch_log, update_batch_status = self.make_batch_helpers(batch_id)
        semaphore = asyncio.Semaphore(concurrency)
        counter_lock = asyncio.Lock()
        running_tasks: list[asyncio.Task] = []
        add_batch_log(f"[系统] 流水线模式启动，并发数: {concurrency}，总任务: {len(task_uuids)}")

        async def _run_and_release(index: int, task_uuid: str, prefix: str):
            leased_candidate = None
            effective_proxy = proxy
            try:
                try:
                    effective_proxy, leased_candidate = self._lease_proxy_for_batch_task(
                        batch_id=batch_id,
                        explicit_proxy=proxy,
                    )
                except RuntimeError as exc:
                    self._mark_proxy_pool_failure(batch_id, task_uuid, str(exc))
                    async with counter_lock:
                        self.batch_outcome_applier(self.batch_tasks[batch_id], "failed")
                        add_batch_log(f"{prefix} [失败] 代理池耗尽: {exc}")
                        update_batch_status(
                            completed=self.batch_tasks[batch_id]["completed"],
                            success=self.batch_tasks[batch_id]["success"],
                            failed=self.batch_tasks[batch_id]["failed"],
                            consecutive_failures=self.batch_tasks[batch_id]["consecutive_failures"],
                        )
                    return

                await self._run_single_task(
                    task_uuid,
                    email_service_type,
                    effective_proxy,
                    email_service_config,
                    email_service_id,
                    log_prefix=prefix,
                    batch_id=batch_id,
                    auto_upload_cpa=auto_upload_cpa,
                    cpa_service_ids=cpa_service_ids or [],
                    auto_upload_sub2api=auto_upload_sub2api,
                    sub2api_service_ids=sub2api_service_ids or [],
                    auto_upload_tm=auto_upload_tm,
                    tm_service_ids=tm_service_ids or [],
                    pipeline_key=pipeline_key,
                )
                status = self._load_outcome_status(task_uuid)
                with self.db_factory() as db:
                    task = crud.get_registration_task(db, task_uuid)
                if task is not None and status is not None:
                    async with counter_lock:
                        self.batch_outcome_applier(self.batch_tasks[batch_id], status)
                        if status == "completed":
                            add_batch_log(f"{prefix} [成功] 注册成功")
                        elif status == "failed":
                            add_batch_log(f"{prefix} [失败] 注册失败: {task.error_message}")
                        update_batch_status(
                            completed=self.batch_tasks[batch_id]["completed"],
                            success=self.batch_tasks[batch_id]["success"],
                            failed=self.batch_tasks[batch_id]["failed"],
                            consecutive_failures=self.batch_tasks[batch_id]["consecutive_failures"],
                        )
            finally:
                status = self._load_outcome_status(task_uuid) or "failed"
                self._release_batch_proxy(
                    batch_id=batch_id,
                    candidate=leased_candidate,
                    success=status == "completed",
                )
                semaphore.release()

        try:
            for index, task_uuid in enumerate(task_uuids):
                if self.task_manager.is_batch_cancelled(batch_id) or self.batch_tasks[batch_id]["cancelled"]:
                    with self.db_factory() as db:
                        for remaining_uuid in task_uuids[index:]:
                            crud.update_registration_task(db, remaining_uuid, status="cancelled")
                    add_batch_log("[取消] 批量任务已取消")
                    update_batch_status(status="cancelled")
                    break

                update_batch_status(current_index=index)
                await semaphore.acquire()
                prefix = f"[任务{index + 1}]"
                add_batch_log(f"{prefix} 开始注册...")
                task = asyncio.create_task(_run_and_release(index, task_uuid, prefix))
                running_tasks.append(task)

                if index < len(task_uuids) - 1 and not self.task_manager.is_batch_cancelled(batch_id):
                    await asyncio.sleep(random.randint(interval_min, interval_max))

            if running_tasks:
                await asyncio.gather(*running_tasks, return_exceptions=True)

            self._finalize_domain_stats(batch_id, task_uuids)
            if self.task_manager.is_batch_cancelled(batch_id) or self.batch_tasks[batch_id]["cancelled"]:
                terminal_status = "cancelled"
            else:
                add_batch_log(
                    f"[完成] 批量任务完成！成功: {self.batch_tasks[batch_id]['success']}, 失败: {self.batch_tasks[batch_id]['failed']}"
                )
                terminal_status = "completed"
            if enable_stats_finalization:
                self.finalize_ordinary_batch_statistics(batch_id=batch_id, status=terminal_status)
            update_batch_status(finished=True, status=terminal_status)
        except Exception as exc:
            logger.exception("批量任务 %s 异常", batch_id)
            add_batch_log(f"[错误] 批量任务异常: {exc}")
            self._finalize_domain_stats(batch_id, task_uuids)
            if enable_stats_finalization:
                self.finalize_ordinary_batch_statistics(batch_id=batch_id, status="failed")
            update_batch_status(finished=True, status="failed")
        finally:
            self.batch_tasks[batch_id]["finished"] = True
            self._clear_batch_proxy_pool(batch_id)

        return self.build_summary(batch_id, task_uuids=task_uuids)

    async def run_batch_registration(
        self,
        batch_id: str,
        task_uuids: list[str],
        email_service_type: str,
        proxy: str | None,
        email_service_config: dict[str, Any] | None,
        email_service_id: int | None,
        interval_min: int,
        interval_max: int,
        concurrency: int = 1,
        mode: str = "pipeline",
        auto_upload_cpa: bool = False,
        cpa_service_ids: list[int] | None = None,
        auto_upload_sub2api: bool = False,
        sub2api_service_ids: list[int] | None = None,
        auto_upload_tm: bool = False,
        tm_service_ids: list[int] | None = None,
        pipeline_key: str | None = None,
        enable_stats_finalization: bool = True,
    ) -> BatchExecutionSummary:
        if mode == "parallel":
            return await self.run_batch_parallel(
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
                cpa_service_ids=cpa_service_ids,
                auto_upload_sub2api=auto_upload_sub2api,
                sub2api_service_ids=sub2api_service_ids,
                auto_upload_tm=auto_upload_tm,
                tm_service_ids=tm_service_ids,
                pipeline_key=pipeline_key,
                enable_stats_finalization=enable_stats_finalization,
            )
        return await self.run_batch_pipeline(
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
            cpa_service_ids=cpa_service_ids,
            auto_upload_sub2api=auto_upload_sub2api,
            sub2api_service_ids=sub2api_service_ids,
            auto_upload_tm=auto_upload_tm,
            tm_service_ids=tm_service_ids,
            pipeline_key=pipeline_key,
            enable_stats_finalization=enable_stats_finalization,
        )

    async def run_outlook_batch_registration(
        self,
        batch_id: str,
        service_ids: list[int],
        skip_registered: bool,
        proxy: str | None,
        interval_min: int,
        interval_max: int,
        concurrency: int = 1,
        mode: str = "pipeline",
        auto_upload_cpa: bool = False,
        cpa_service_ids: list[int] | None = None,
        auto_upload_sub2api: bool = False,
        sub2api_service_ids: list[int] | None = None,
        auto_upload_tm: bool = False,
        tm_service_ids: list[int] | None = None,
    ) -> BatchExecutionSummary:
        loop = self.task_manager.get_loop()
        if loop is None:
            try:
                self.task_manager.set_loop(asyncio.get_running_loop())
            except RuntimeError:
                pass

        task_uuids = self.create_outlook_task_records(service_ids=service_ids, proxy=proxy)
        return await self.run_batch_registration(
            batch_id=batch_id,
            task_uuids=task_uuids,
            email_service_type="outlook",
            proxy=proxy,
            email_service_config=None,
            email_service_id=None,
            interval_min=interval_min,
            interval_max=interval_max,
            concurrency=concurrency,
            mode=mode,
            auto_upload_cpa=auto_upload_cpa,
            cpa_service_ids=cpa_service_ids,
            auto_upload_sub2api=auto_upload_sub2api,
            sub2api_service_ids=sub2api_service_ids,
            auto_upload_tm=auto_upload_tm,
            tm_service_ids=tm_service_ids,
            enable_stats_finalization=False,
        )
