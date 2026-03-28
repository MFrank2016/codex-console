from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable

from ..core.registration_job import RegistrationJobResult, run_registration_job
from ..core.time import utc_now_naive
from ..database import crud
from ..database.models import Account, RegistrationRun, RegistrationRunEvent, RegistrationTask
from .proxy_dispatch_service import ProxyDispatchService, ResolvedProxyCandidate
from .registration_runs_service import RegistrationRunsService

logger = logging.getLogger(__name__)


@dataclass
class SingleTaskExecutionResult:
    task: RegistrationTask | None
    run: RegistrationRun | None
    events: list[RegistrationRunEvent]
    job_result: RegistrationJobResult | None = None


class RegistrationService:
    def __init__(
        self,
        *,
        db_factory,
        task_manager=None,
        job_runner: Callable[..., RegistrationJobResult] = run_registration_job,
        sync_runner: Callable[..., SingleTaskExecutionResult] | None = None,
        proxy_resolver: Callable[[Any], tuple[str | None, int | None]] | None = None,
        proxy_usage_updater: Callable[[Any, int | None], None] | None = None,
        proxy_dispatcher: ProxyDispatchService | None = None,
        utc_now_provider: Callable[[], Any] = utc_now_naive,
    ):
        self.db_factory = db_factory
        if task_manager is None:
            from ..web.task_manager import task_manager as default_task_manager

            task_manager = default_task_manager
        self.task_manager = task_manager
        self.job_runner = job_runner
        self._uses_default_sync_runner = sync_runner is None
        self.sync_runner = sync_runner or self._run_single_task_sync_impl
        self.proxy_resolver = proxy_resolver or self._resolve_proxy_for_registration
        self.proxy_usage_updater = proxy_usage_updater or self._update_proxy_usage
        self.proxy_dispatcher = proxy_dispatcher
        self.utc_now_provider = utc_now_provider

    def create_task(
        self,
        *,
        task_uuid: str,
        proxy: str | None = None,
        pipeline_key: str | None = None,
        email_service_id: int | None = None,
    ) -> RegistrationTask:
        with self.db_factory() as db:
            return crud.create_registration_task(
                db,
                task_uuid=task_uuid,
                proxy=proxy,
                pipeline_key=pipeline_key,
                email_service_id=email_service_id,
            )

    def build_result_for_task(
        self,
        task_uuid: str,
        *,
        db=None,
        job_result: RegistrationJobResult | None = None,
    ) -> SingleTaskExecutionResult:
        if db is not None:
            task = crud.get_registration_task(db, task_uuid)
            runs_service = RegistrationRunsService(db)
            run = runs_service.get_run_by_task_uuid(task_uuid)
            events = runs_service.get_events(run.id) if run is not None else []
            return SingleTaskExecutionResult(task=task, run=run, events=events, job_result=job_result)

        with self.db_factory() as session:
            return self.build_result_for_task(task_uuid, db=session, job_result=job_result)

    async def run_single_task(
        self,
        task_uuid: str,
        email_service_type: str,
        proxy: str | None,
        email_service_config: dict[str, Any] | None,
        email_service_id: int | None = None,
        log_prefix: str = "",
        batch_id: str = "",
        registration_mode: str = "single",
        auto_upload_cpa: bool = False,
        cpa_service_ids: list[int] | None = None,
        auto_upload_sub2api: bool = False,
        sub2api_service_ids: list[int] | None = None,
        auto_upload_tm: bool = False,
        tm_service_ids: list[int] | None = None,
        pipeline_key: str | None = None,
        use_proxy: bool = False,
        proxy_task_group: str = "single_registration",
        proxy_overrides: dict[str, Any] | None = None,
        resolved_proxy_candidate: ResolvedProxyCandidate | None = None,
    ) -> SingleTaskExecutionResult:
        loop = self.task_manager.get_loop()
        if loop is None:
            loop = asyncio.get_running_loop()
            self.task_manager.set_loop(loop)

        queued_message = (
            f"{log_prefix} [系统] 任务 {task_uuid[:8]} 已加入队列"
            if log_prefix
            else f"[系统] 任务 {task_uuid[:8]} 已加入队列"
        )
        self.task_manager.update_status(task_uuid, "pending")
        self.task_manager.add_log(task_uuid, queued_message)

        payload = {
            "service": self,
            "task_uuid": task_uuid,
            "email_service_type": email_service_type,
            "proxy": proxy,
            "email_service_config": email_service_config,
            "email_service_id": email_service_id,
            "log_prefix": log_prefix,
            "batch_id": batch_id,
            "registration_mode": registration_mode,
            "auto_upload_cpa": auto_upload_cpa,
            "cpa_service_ids": cpa_service_ids or [],
            "auto_upload_sub2api": auto_upload_sub2api,
            "sub2api_service_ids": sub2api_service_ids or [],
            "auto_upload_tm": auto_upload_tm,
            "tm_service_ids": tm_service_ids or [],
            "pipeline_key": pipeline_key,
            "use_proxy": use_proxy,
            "proxy_task_group": proxy_task_group,
            "proxy_overrides": proxy_overrides or {},
            "resolved_proxy_candidate": resolved_proxy_candidate,
            "utc_now_provider": self.utc_now_provider,
        }

        runner = self.sync_runner
        if getattr(self.task_manager, "executor", None) is not None and self._uses_default_sync_runner:
            result = await loop.run_in_executor(
                self.task_manager.executor,
                lambda: runner(**payload),
            )
        else:
            result = runner(**payload)

        if result is None:
            result = self.build_result_for_task(task_uuid)

        status_snapshot = getattr(self.task_manager, "get_status", lambda _task_uuid: None)(task_uuid) or {}
        if result.task is not None and status_snapshot.get("status") == "pending":
            extra: dict[str, Any] = {}
            if result.task.status == "completed" and result.task.email_address:
                extra["email"] = result.task.email_address
            if result.task.status == "failed" and result.task.error_message:
                extra["error"] = result.task.error_message
            self.task_manager.update_status(task_uuid, result.task.status, **extra)

        return result

    def run_single_task_sync(
        self,
        task_uuid: str,
        email_service_type: str,
        proxy: str | None,
        email_service_config: dict[str, Any] | None,
        email_service_id: int | None = None,
        log_prefix: str = "",
        batch_id: str = "",
        registration_mode: str = "single",
        auto_upload_cpa: bool = False,
        cpa_service_ids: list[int] | None = None,
        auto_upload_sub2api: bool = False,
        sub2api_service_ids: list[int] | None = None,
        auto_upload_tm: bool = False,
        tm_service_ids: list[int] | None = None,
        pipeline_key: str | None = None,
        use_proxy: bool = False,
        proxy_task_group: str = "single_registration",
        proxy_overrides: dict[str, Any] | None = None,
        resolved_proxy_candidate: ResolvedProxyCandidate | None = None,
    ) -> SingleTaskExecutionResult:
        return self.sync_runner(
            service=self,
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
            utc_now_provider=self.utc_now_provider,
        )

    def _run_single_task_sync_impl(
        self,
        *,
        service: RegistrationService,
        task_uuid: str,
        email_service_type: str,
        proxy: str | None,
        email_service_config: dict[str, Any] | None,
        email_service_id: int | None = None,
        log_prefix: str = "",
        batch_id: str = "",
        registration_mode: str = "single",
        auto_upload_cpa: bool = False,
        cpa_service_ids: list[int] | None = None,
        auto_upload_sub2api: bool = False,
        sub2api_service_ids: list[int] | None = None,
        auto_upload_tm: bool = False,
        tm_service_ids: list[int] | None = None,
        pipeline_key: str | None = None,
        use_proxy: bool = False,
        proxy_task_group: str = "single_registration",
        proxy_overrides: dict[str, Any] | None = None,
        resolved_proxy_candidate: ResolvedProxyCandidate | None = None,
        utc_now_provider: Callable[[], Any] | None = None,
    ) -> SingleTaskExecutionResult:
        now = utc_now_provider or service.utc_now_provider
        cpa_service_ids = cpa_service_ids or []
        sub2api_service_ids = sub2api_service_ids or []
        tm_service_ids = tm_service_ids or []

        def _close_task_stream(final_status: str) -> None:
            if not hasattr(service.task_manager, "close_task_stream"):
                return
            try:
                service.task_manager.close_task_stream(task_uuid, final_status=final_status)
            except TypeError:
                service.task_manager.close_task_stream(task_uuid, final_status)

        def _task_step_callback(payload: dict) -> None:
            """接收 pipeline runner 的步骤快照，并同步到 task stream。"""
            try:
                steps = payload.get("steps") if isinstance(payload, dict) else None
                if steps is not None and hasattr(service.task_manager, "set_task_steps"):
                    service.task_manager.set_task_steps(
                        task_uuid,
                        steps,
                        task_progress=payload.get("task_progress"),
                    )

                current_step = payload.get("current_step") if isinstance(payload, dict) else None
                step_key = (current_step or {}).get("step_key")
                if step_key:
                    current_step_status = (current_step or {}).get("status")
                    status_snapshot = getattr(
                        service.task_manager,
                        "get_status",
                        lambda _task_uuid: None,
                    )(task_uuid) or {}
                    current_task_status = status_snapshot.get("status")
                    if current_task_status:
                        effective_status = current_task_status
                    else:
                        effective_status = "running" if current_step_status == "running" else "pending"
                    service.task_manager.update_status(task_uuid, effective_status, current_step_key=step_key)
            except Exception as exc:
                logger.warning("任务 %s 写入步骤快照失败: %s", task_uuid, exc)

        def _sync_task_manager_from_result(result: SingleTaskExecutionResult) -> str | None:
            final_status: str | None = None
            extra: dict[str, Any] = {}

            if result.task is not None and result.task.status in RegistrationRunsService.TERMINAL_STATUSES:
                final_status = result.task.status
                if final_status == "completed" and result.task.email_address:
                    extra["email"] = result.task.email_address
                elif final_status in {"failed", "cancelled"} and result.task.error_message:
                    extra["error"] = result.task.error_message
            elif result.run is not None and result.run.status in RegistrationRunsService.TERMINAL_STATUSES:
                final_status = result.run.status
                if final_status in {"failed", "cancelled"} and result.run.error_message:
                    extra["error"] = result.run.error_message

            if final_status is not None:
                service.task_manager.update_status(task_uuid, final_status, **extra)
                _close_task_stream(final_status)

            return final_status

        def _commit_queued_checkpoint(
            runs_service: RegistrationRunsService,
        ) -> tuple[RegistrationRun, bool]:
            run = runs_service.create_run(
                task_uuid=task_uuid,
                batch_id=batch_id or None,
                trigger_source="batch" if batch_id else "manual",
                commit=False,
            )
            if run.status in runs_service.TERMINAL_STATUSES:
                return run, False
            runs_service.append_event(run.id, level="info", message="queued", commit=True)
            return run, True

        def _commit_execution_start_checkpoint(
            runs_service: RegistrationRunsService,
            run_id: int,
        ) -> None:
            runs_service.mark_started(run_id, commit=False)
            runs_service.append_event(run_id, level="info", message="started", commit=False)
            runs_service.mark_running(run_id, commit=False)
            runs_service.append_event(run_id, level="info", message="running", commit=True)

        def _commit_terminal_checkpoint(
            runs_service: RegistrationRunsService,
            run_id: int,
            *,
            status: str,
            error_message: str | None = None,
        ) -> RegistrationRun | None:
            run = runs_service.get_run(run_id)
            if run is None:
                return None
            if run.status in runs_service.TERMINAL_STATUSES:
                return run

            if status == "completed":
                run = runs_service.mark_completed(run_id, commit=False)
                level = "info"
            elif status == "failed":
                run = runs_service.mark_failed(run_id, error_message=error_message, commit=False)
                level = "error"
            elif status == "cancelled":
                run = runs_service.mark_cancelled(run_id, error_message=error_message, commit=False)
                level = "warning"
            else:
                raise ValueError(f"unsupported terminal checkpoint status: {status}")

            runs_service.append_event(run_id, level=level, message=status, commit=True)
            return run

        try:
            with service.db_factory() as db:
                runs_service = RegistrationRunsService(db)
                run, should_execute = _commit_queued_checkpoint(runs_service)
                if not should_execute:
                    result = service.build_result_for_task(task_uuid, db=db)
                    _sync_task_manager_from_result(result)
                    return result

                if service.task_manager.is_cancelled(task_uuid):
                    logger.info("任务 %s 已取消，跳过执行", task_uuid)
                    crud.update_registration_task(
                        db,
                        task_uuid,
                        status="cancelled",
                        pipeline_status="cancelled",
                        completed_at=now(),
                    )
                    _commit_terminal_checkpoint(
                        runs_service,
                        run.id,
                        status="cancelled",
                        error_message="cancelled",
                    )
                    service.task_manager.update_status(task_uuid, "cancelled")
                    _close_task_stream("cancelled")
                    return service.build_result_for_task(task_uuid, db=db)

                task = crud.update_registration_task(
                    db,
                    task_uuid,
                    status="running",
                    pipeline_status="running",
                    started_at=now(),
                )
                if task is None:
                    logger.error("任务不存在: %s", task_uuid)
                    _commit_terminal_checkpoint(
                        runs_service,
                        run.id,
                        status="failed",
                        error_message="task missing",
                    )
                    service.task_manager.update_status(task_uuid, "failed", error="task missing")
                    _close_task_stream("failed")
                    return service.build_result_for_task(task_uuid, db=db)

                _commit_execution_start_checkpoint(runs_service, run.id)
                service.task_manager.update_status(task_uuid, "running")

                effective_pipeline_key = pipeline_key or task.pipeline_key or "current_pipeline"
                effective_email_service_id = (
                    email_service_id
                    if email_service_id is not None
                    else task.email_service_id
                )
                if task.pipeline_key != effective_pipeline_key:
                    task = crud.update_registration_task(
                        db,
                        task_uuid,
                        pipeline_key=effective_pipeline_key,
                    ) or task

                log_callback = service.task_manager.create_log_callback(
                    task_uuid,
                    prefix=log_prefix,
                    batch_id=batch_id,
                )
                candidates = service._resolve_proxy_candidates(
                    db,
                    explicit_proxy=proxy,
                    use_proxy=use_proxy,
                    task_group=proxy_task_group,
                    overrides=proxy_overrides or {},
                    resolved_proxy_candidate=resolved_proxy_candidate,
                )
                if use_proxy and not candidates:
                    error_message = "代理已启用，但当前没有可用代理"
                    log_callback(f"[错误] {error_message}")
                    crud.update_registration_task(
                        db,
                        task_uuid,
                        status="failed",
                        pipeline_status="failed",
                        completed_at=now(),
                        error_message=error_message,
                    )
                    _commit_terminal_checkpoint(
                        runs_service,
                        run.id,
                        status="failed",
                        error_message=error_message,
                    )
                    service.task_manager.update_status(task_uuid, "failed", error=error_message)
                    _close_task_stream("failed")
                    return service.build_result_for_task(task_uuid, db=db)
                candidate_sequence: list[ResolvedProxyCandidate | None] = candidates or [None]
                job_result: RegistrationJobResult | None = None
                selected_candidate: ResolvedProxyCandidate | None = None

                for index, candidate in enumerate(candidate_sequence):
                    selected_candidate = candidate
                    actual_proxy_url = candidate.proxy_url if candidate is not None else None
                    crud.update_registration_task(db, task_uuid, proxy=actual_proxy_url)

                    try:
                        job_result = service.job_runner(
                            db=db,
                            email_service_type=email_service_type,
                            email_service_id=effective_email_service_id,
                            proxy=actual_proxy_url,
                            email_service_config=email_service_config,
                            pipeline_key=effective_pipeline_key,
                            callback_logger=log_callback,
                            task_uuid=task_uuid,
                            task_step_callback=_task_step_callback,
                            batch_id=batch_id or None,
                            registration_mode=registration_mode,
                        )
                    except Exception as exc:
                        should_retry = (
                            candidate is not None
                            and service.proxy_dispatcher is not None
                            and index < len(candidate_sequence) - 1
                            and service.proxy_dispatcher.is_proxy_related_failure(exc)
                        )
                        if should_retry:
                            log_callback(f"[代理] 当前代理失败，切换下一个候选: {exc}")
                            continue
                        raise

                    if (
                        candidate is not None
                        and service.proxy_dispatcher is not None
                        and not job_result.success
                        and index < len(candidate_sequence) - 1
                        and service.proxy_dispatcher.is_proxy_related_failure(job_result.error_message or "")
                    ):
                        log_callback(f"[代理] 当前代理失败，切换下一个候选: {job_result.error_message}")
                        continue

                    break

                if job_result is None:
                    job_result = RegistrationJobResult(success=False, error_message="proxy dispatch exhausted")

                if job_result.email:
                    crud.update_registration_task(db, task_uuid, email_address=job_result.email)

                if job_result.email_service_id:
                    crud.update_registration_task(db, task_uuid, email_service_id=job_result.email_service_id)

                if job_result.success:
                    proxy_id = selected_candidate.proxy_id if selected_candidate is not None else None
                    service.proxy_usage_updater(db, proxy_id)
                    service._run_auto_uploads(
                        db,
                        job_result=job_result,
                        log_callback=log_callback,
                        auto_upload_cpa=auto_upload_cpa,
                        cpa_service_ids=cpa_service_ids,
                        auto_upload_sub2api=auto_upload_sub2api,
                        sub2api_service_ids=sub2api_service_ids,
                        auto_upload_tm=auto_upload_tm,
                        tm_service_ids=tm_service_ids,
                        now=now,
                    )
                    crud.update_registration_task(
                        db,
                        task_uuid,
                        status="completed",
                        pipeline_status="completed",
                        completed_at=now(),
                        result=job_result.result_payload
                        or {
                            "success": True,
                            "email": job_result.email,
                            "account_id": job_result.account_id,
                        },
                    )
                    _commit_terminal_checkpoint(runs_service, run.id, status="completed")
                    service.task_manager.update_status(task_uuid, "completed", email=job_result.email)
                    _close_task_stream("completed")
                else:
                    crud.update_registration_task(
                        db,
                        task_uuid,
                        status="failed",
                        pipeline_status="failed",
                        completed_at=now(),
                        error_message=job_result.error_message,
                    )
                    _commit_terminal_checkpoint(
                        runs_service,
                        run.id,
                        status="failed",
                        error_message=job_result.error_message,
                    )
                    service.task_manager.update_status(task_uuid, "failed", error=job_result.error_message)
                    _close_task_stream("failed")

                return service.build_result_for_task(task_uuid, db=db, job_result=job_result)
        except Exception as exc:
            logger.exception("注册任务异常: %s", task_uuid)
            persisted_task = None
            final_status = "failed"
            final_error = str(exc)
            try:
                with service.db_factory() as db:
                    runs_service = RegistrationRunsService(db)
                    run = runs_service.get_run_by_task_uuid(task_uuid)
                    if run is None:
                        run = _commit_queued_checkpoint(runs_service)
                    if run is not None and run.status not in runs_service.TERMINAL_STATUSES:
                        persisted_task = crud.update_registration_task(
                            db,
                            task_uuid,
                            status="failed",
                            pipeline_status="failed",
                            completed_at=now(),
                            error_message=str(exc),
                        )
                        run = _commit_terminal_checkpoint(
                            runs_service,
                            run.id,
                            status="failed",
                            error_message=str(exc),
                        ) or run
                    else:
                        persisted_task = crud.get_registration_task_by_uuid(db, task_uuid)

                    if run is not None and run.status in runs_service.TERMINAL_STATUSES:
                        final_status = run.status
                        final_error = run.error_message or final_error
                    elif persisted_task is not None and persisted_task.status in runs_service.TERMINAL_STATUSES:
                        final_status = persisted_task.status
            except Exception:
                logger.exception("注册任务异常后写回失败: %s", task_uuid)

            status_snapshot = getattr(self.task_manager, "get_status", lambda _task_uuid: None)(task_uuid) or {}
            if status_snapshot.get("status") not in RegistrationRunsService.TERMINAL_STATUSES:
                extra: dict[str, Any] = {}
                if final_status == "failed" and final_error:
                    extra["error"] = final_error
                if final_status == "completed" and persisted_task is not None and persisted_task.email_address:
                    extra["email"] = persisted_task.email_address
                self.task_manager.update_status(task_uuid, final_status, **extra)
                _close_task_stream(final_status)
            failed_result = RegistrationJobResult(success=False, error_message=str(exc))
            return service.build_result_for_task(task_uuid, job_result=failed_result)

    def _resolve_proxy_for_registration(self, db) -> tuple[str | None, int | None]:
        proxy = crud.get_random_proxy(db)
        if proxy:
            return proxy.proxy_url, proxy.id

        from ..core.dynamic_proxy import get_proxy_url_for_task

        proxy_url = get_proxy_url_for_task()
        if proxy_url:
            return proxy_url, None
        return None, None

    def _resolve_proxy_candidates(
        self,
        db,
        *,
        explicit_proxy: str | None,
        use_proxy: bool,
        task_group: str,
        overrides: dict[str, Any],
        resolved_proxy_candidate: ResolvedProxyCandidate | None = None,
    ) -> list[ResolvedProxyCandidate]:
        if resolved_proxy_candidate is not None:
            return [resolved_proxy_candidate]

        if not use_proxy:
            return []

        if self.proxy_dispatcher is not None:
            return self._dispatch_proxy_candidates(
                task_group=task_group,
                explicit_proxy=explicit_proxy,
                overrides=overrides,
                use_proxy=use_proxy,
            )

        candidates: list[ResolvedProxyCandidate] = []
        proxy_url, proxy_id = self.proxy_resolver(db)
        if proxy_url:
            candidates.append(
                ResolvedProxyCandidate(
                    proxy_url=proxy_url,
                    source="legacy",
                    proxy_id=proxy_id,
                )
            )

        if explicit_proxy and all(item.proxy_url != explicit_proxy for item in candidates):
            candidates.append(
                ResolvedProxyCandidate(
                    proxy_url=explicit_proxy,
                    source="static",
                )
            )

        return candidates

    def _dispatch_proxy_candidates(
        self,
        *,
        task_group: str,
        explicit_proxy: str | None,
        overrides: dict[str, Any],
        use_proxy: bool,
    ) -> list[ResolvedProxyCandidate]:
        resolver = self.proxy_dispatcher.resolve_single_candidates
        try:
            signature = inspect.signature(resolver)
        except (TypeError, ValueError):
            signature = None

        if signature is not None and "use_proxy" not in signature.parameters:
            return resolver(task_group, explicit_proxy, overrides)

        return resolver(
            task_group,
            explicit_proxy,
            overrides,
            use_proxy=use_proxy,
        )

    def _update_proxy_usage(self, db, proxy_id: int | None) -> None:
        if proxy_id:
            crud.update_proxy_last_used(db, proxy_id)

    def _run_auto_uploads(
        self,
        db,
        *,
        job_result: RegistrationJobResult,
        log_callback: Callable[[str], None],
        auto_upload_cpa: bool,
        cpa_service_ids: list[int],
        auto_upload_sub2api: bool,
        sub2api_service_ids: list[int],
        auto_upload_tm: bool,
        tm_service_ids: list[int],
        now: Callable[[], Any],
    ) -> None:
        saved_account = None
        if job_result.account_id:
            saved_account = db.query(Account).filter_by(id=job_result.account_id).first()
        elif job_result.email:
            saved_account = db.query(Account).filter_by(email=job_result.email).first()

        if not saved_account or not saved_account.access_token:
            return

        if auto_upload_cpa:
            try:
                from ..core.upload.cpa_upload import generate_token_json, upload_to_cpa

                token_data = generate_token_json(saved_account)
                service_ids = cpa_service_ids or [service.id for service in crud.get_cpa_services(db, enabled=True)]
                if not service_ids:
                    log_callback("[CPA] 无可用 CPA 服务，跳过上传")
                for service_id in service_ids:
                    try:
                        service = crud.get_cpa_service_by_id(db, service_id)
                        if service is None:
                            continue
                        log_callback(f"[CPA] 正在把账号打包发往服务站: {service.name}")
                        ok, message = upload_to_cpa(
                            token_data,
                            api_url=service.api_url,
                            api_token=service.api_token,
                        )
                        if ok:
                            saved_account.cpa_uploaded = True
                            saved_account.cpa_uploaded_at = now()
                            db.commit()
                            log_callback(f"[CPA] 投递成功，服务站已签收: {service.name}")
                        else:
                            log_callback(f"[CPA] 上传失败({service.name}): {message}")
                    except Exception as exc:
                        log_callback(f"[CPA] 异常({service_id}): {exc}")
            except Exception as exc:
                log_callback(f"[CPA] 上传异常: {exc}")

        if auto_upload_sub2api:
            try:
                from ..core.upload.sub2api_upload import upload_to_sub2api

                service_ids = sub2api_service_ids or [
                    service.id for service in crud.get_sub2api_services(db, enabled=True)
                ]
                if not service_ids:
                    log_callback("[Sub2API] 无可用 Sub2API 服务，跳过上传")
                for service_id in service_ids:
                    try:
                        service = crud.get_sub2api_service_by_id(db, service_id)
                        if service is None:
                            continue
                        log_callback(f"[Sub2API] 正在把账号发往服务站: {service.name}")
                        ok, message = upload_to_sub2api([saved_account], service.api_url, service.api_key)
                        log_callback(f"[Sub2API] {'成功' if ok else '失败'}({service.name}): {message}")
                    except Exception as exc:
                        log_callback(f"[Sub2API] 异常({service_id}): {exc}")
            except Exception as exc:
                log_callback(f"[Sub2API] 上传异常: {exc}")

        if auto_upload_tm:
            try:
                from ..core.upload.team_manager_upload import upload_to_team_manager

                service_ids = tm_service_ids or [service.id for service in crud.get_tm_services(db, enabled=True)]
                if not service_ids:
                    log_callback("[TM] 无可用 Team Manager 服务，跳过上传")
                for service_id in service_ids:
                    try:
                        service = crud.get_tm_service_by_id(db, service_id)
                        if service is None:
                            continue
                        log_callback(f"[TM] 正在把账号发往服务站: {service.name}")
                        ok, message = upload_to_team_manager(saved_account, service.api_url, service.api_key)
                        log_callback(f"[TM] {'成功' if ok else '失败'}({service.name}): {message}")
                    except Exception as exc:
                        log_callback(f"[TM] 异常({service_id}): {exc}")
            except Exception as exc:
                log_callback(f"[TM] 上传异常: {exc}")
