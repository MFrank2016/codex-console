"""Query facade for registration read-side use cases."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, ContextManager, Dict, List, Optional

from ..config.settings import get_settings
from ..core.registration_failure_records import (
    RegistrationFailureQuery,
    current_shanghai_day_window_utc_naive,
    resolve_failure_window,
)
from ..core.time import utc_now
from ..database import crud
from ..database.models import Account, EmailService, RegistrationTask
from ..database.repositories import registration_failure_repository as failure_repo
from .batch_registration_service import DEFAULT_BATCH_TASKS_STORE
from .registration_query_dtos import (
    RegistrationBatchStatusView,
    RegistrationFailureListView,
    RegistrationFailureSummaryView,
    RegistrationStatsView,
    RegistrationTaskListView,
    RegistrationTaskView,
)


DbFactory = Callable[[], ContextManager[Any]]


class RegistrationQueryFacade:
    def __init__(
        self,
        *,
        db_factory: DbFactory,
        task_manager: Any,
        failure_repository: Any = failure_repo,
        utc_now_provider: Callable[[], datetime] = utc_now,
        settings_reader: Callable[[], Any] = get_settings,
        batch_tasks_store: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.db_factory = db_factory
        self.task_manager = task_manager
        self.failure_repository = failure_repository
        self.utc_now_provider = utc_now_provider
        self.settings_reader = settings_reader
        self.batch_tasks = batch_tasks_store if batch_tasks_store is not None else DEFAULT_BATCH_TASKS_STORE

    def _step_run_to_dict(self, step_run: Any) -> Dict[str, Any]:
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

    def _collect_task_steps(self, db: Any, task_uuid: str) -> List[Dict[str, Any]]:
        step_rows = crud.get_pipeline_step_runs_by_task_uuid(db, task_uuid)
        if step_rows:
            return [self._step_run_to_dict(row) for row in step_rows]

        if hasattr(self.task_manager, "get_task_steps"):
            return self.task_manager.get_task_steps(task_uuid)
        return []

    def task_to_response(
        self,
        task: RegistrationTask,
        *,
        steps: Optional[List[Dict[str, Any]]] = None,
    ) -> RegistrationTaskView:
        result_payload = task.result if isinstance(task.result, dict) else {}
        metadata = result_payload.get("metadata") if isinstance(result_payload, dict) else {}
        proxy_ip = metadata.get("proxy_ip") if isinstance(metadata, dict) else None
        email = str(task.email_address or result_payload.get("email") or "").strip() or None
        return RegistrationTaskView(
            id=task.id,
            task_uuid=task.task_uuid,
            status=task.status,
            email=email,
            email_service_id=task.email_service_id,
            pipeline_key=task.pipeline_key,
            current_step_key=task.current_step_key,
            pipeline_status=task.pipeline_status,
            total_duration_ms=task.total_duration_ms,
            proxy=task.proxy,
            proxy_ip=str(proxy_ip).strip() if proxy_ip else None,
            error_message=task.error_message,
            steps=list(steps or []),
            result=task.result,
            logs=task.logs,
            created_at=task.created_at.isoformat() if task.created_at else None,
            started_at=task.started_at.isoformat() if task.started_at else None,
            completed_at=task.completed_at.isoformat() if task.completed_at else None,
        )

    def list_tasks(
        self,
        *,
        page: int,
        page_size: int,
        status: Optional[str],
    ) -> RegistrationTaskListView:
        with self.db_factory() as db:
            query = db.query(RegistrationTask)
            if status:
                query = query.filter(RegistrationTask.status == status)

            total = query.count()
            offset = (page - 1) * page_size
            tasks = (
                query.order_by(RegistrationTask.created_at.desc())
                .offset(offset)
                .limit(page_size)
                .all()
            )

            return RegistrationTaskListView(
                total=total,
                tasks=[
                    self.task_to_response(
                        task,
                        steps=self._collect_task_steps(db, task.task_uuid),
                    )
                    for task in tasks
                ],
            )

    def get_task_detail(self, task_uuid: str) -> Optional[RegistrationTaskView]:
        with self.db_factory() as db:
            task = crud.get_registration_task(db, task_uuid)
            if not task:
                return None
            return self.task_to_response(task, steps=self._collect_task_steps(db, task_uuid))

    def get_task_logs(self, task_uuid: str) -> Optional[Dict[str, Any]]:
        with self.db_factory() as db:
            task = crud.get_registration_task(db, task_uuid)
            if not task:
                return None

            logs = task.logs or ""
            return {
                "task_uuid": task_uuid,
                "status": task.status,
                "logs": logs.split("\n") if logs else [],
            }

    def get_registration_stats(self) -> RegistrationStatsView:
        from sqlalchemy import func

        with self.db_factory() as db:
            status_stats = (
                db.query(
                    RegistrationTask.status,
                    func.count(RegistrationTask.id),
                )
                .group_by(RegistrationTask.status)
                .all()
            )
            today = self.utc_now_provider().date()
            today_count = db.query(func.count(RegistrationTask.id)).filter(
                func.date(RegistrationTask.created_at) == today
            ).scalar()
            return RegistrationStatsView(
                by_status={status: count for status, count in status_stats},
                today_count=int(today_count or 0),
            )

    def _coerce_window_raw_value(self, value: Optional[str | datetime]) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def _resolve_failure_window(
        self,
        *,
        failed_from_raw: Optional[str | datetime],
        failed_to_raw: Optional[str | datetime],
        now: Optional[datetime] = None,
    ) -> tuple[datetime, datetime]:
        return resolve_failure_window(
            failed_from_raw=self._coerce_window_raw_value(failed_from_raw),
            failed_to_raw=self._coerce_window_raw_value(failed_to_raw),
            now=now if now is not None else self.utc_now_provider(),
        )

    def _build_failure_filters(
        self,
        *,
        pipeline_key: Optional[str],
        registration_mode: Optional[str],
        email_service_type: Optional[str],
        email_suffix: Optional[str],
        email_service_id: Optional[int],
        proxy_ip: Optional[str],
        error_keyword: Optional[str],
        failed_from: datetime,
        failed_to: datetime,
    ) -> RegistrationFailureQuery:
        return RegistrationFailureQuery(
            pipeline_key=str(pipeline_key or "").strip() or None,
            registration_mode=str(registration_mode or "").strip() or None,
            email_service_type=str(email_service_type or "").strip() or None,
            email_suffix=str(email_suffix or "").strip() or None,
            email_service_id=int(email_service_id) if email_service_id is not None else None,
            proxy_ip=str(proxy_ip or "").strip() or None,
            error_keyword=str(error_keyword or "").strip() or None,
            failed_from=failed_from,
            failed_to=failed_to,
        )

    def _current_day_intersection_count(
        self,
        db: Any,
        *,
        now: datetime,
        filters: RegistrationFailureQuery,
    ) -> int:
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
            email_service_id=filters.email_service_id,
            proxy_ip=filters.proxy_ip,
            error_keyword=filters.error_keyword,
            failed_from=effective_from,
            failed_to=effective_to,
        )
        return int(
            self.failure_repository.count_registration_failure_records(
                db,
                filters=today_filters,
            )
        )

    def build_failure_summary(
        self,
        *,
        pipeline_key: Optional[str] = None,
        registration_mode: Optional[str] = None,
        email_service_type: Optional[str] = None,
        email_suffix: Optional[str] = None,
        email_service_id: Optional[int] = None,
        proxy_ip: Optional[str] = None,
        error_keyword: Optional[str] = None,
        failed_from: Optional[str | datetime] = None,
        failed_to: Optional[str | datetime] = None,
    ) -> RegistrationFailureSummaryView:
        now = self.utc_now_provider()
        window_from, window_to = self._resolve_failure_window(
            failed_from_raw=failed_from,
            failed_to_raw=failed_to,
            now=now,
        )
        filters = self._build_failure_filters(
            pipeline_key=pipeline_key,
            registration_mode=registration_mode,
            email_service_type=email_service_type,
            email_suffix=email_suffix,
            email_service_id=email_service_id,
            proxy_ip=proxy_ip,
            error_keyword=error_keyword,
            failed_from=window_from,
            failed_to=window_to,
        )

        with self.db_factory() as db:
            summary = self.failure_repository.build_registration_failure_summary(
                db,
                filters=filters,
            )
            today_failed_attempts = self._current_day_intersection_count(
                db,
                now=now,
                filters=filters,
            )

        return RegistrationFailureSummaryView(
            total_failed_attempts=int(summary.get("total_failed_attempts", 0)),
            top_email_suffixes=list(summary.get("top_email_suffixes", [])),
            top_error_codes=list(summary.get("top_error_codes", [])),
            top_proxy_ips=list(summary.get("top_proxy_ips", [])),
            today_failed_attempts=today_failed_attempts,
        )

    def list_failures(
        self,
        *,
        pipeline_key: Optional[str] = None,
        registration_mode: Optional[str] = None,
        email_service_type: Optional[str] = None,
        email_suffix: Optional[str] = None,
        email_service_id: Optional[int] = None,
        proxy_ip: Optional[str] = None,
        error_keyword: Optional[str] = None,
        failed_from: Optional[str | datetime] = None,
        failed_to: Optional[str | datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> RegistrationFailureListView:
        window_from, window_to = self._resolve_failure_window(
            failed_from_raw=failed_from,
            failed_to_raw=failed_to,
        )
        safe_page = max(1, int(page or 1))
        safe_page_size = min(100, max(1, int(page_size or 20)))
        filters = self._build_failure_filters(
            pipeline_key=pipeline_key,
            registration_mode=registration_mode,
            email_service_type=email_service_type,
            email_suffix=email_suffix,
            email_service_id=email_service_id,
            proxy_ip=proxy_ip,
            error_keyword=error_keyword,
            failed_from=window_from,
            failed_to=window_to,
        )

        with self.db_factory() as db:
            total = self.failure_repository.count_registration_failure_records(db, filters=filters)
            items = self.failure_repository.list_registration_failure_records(
                db,
                filters=filters,
                page=safe_page,
                page_size=safe_page_size,
            )

        serialized_items: List[Dict[str, Any]] = []
        for item in items:
            if hasattr(item, "to_dict"):
                serialized_items.append(item.to_dict())
            else:
                serialized_items.append(dict(item))

        return RegistrationFailureListView(
            total=int(total or 0),
            items=serialized_items,
        )

    def get_batch_status(self, batch_id: str) -> Optional[RegistrationBatchStatusView]:
        batch = self.batch_tasks.get(batch_id)
        if batch is None:
            return None

        payload = {
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
        return RegistrationBatchStatusView(batch_id=batch_id, payload=payload)

    def get_outlook_batch_status(self, batch_id: str) -> Optional[RegistrationBatchStatusView]:
        batch = self.batch_tasks.get(batch_id)
        if batch is None:
            return None

        payload = {
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
        return RegistrationBatchStatusView(batch_id=batch_id, payload=payload)

    def get_available_email_services(self) -> Dict[str, Any]:
        settings = self.settings_reader()
        result = {
            "tempmail": {
                "available": True,
                "count": 1,
                "services": [{
                    "id": None,
                    "name": "Tempmail.lol",
                    "type": "tempmail",
                    "description": "临时邮箱，自动创建",
                }],
            },
            "outlook": {
                "available": False,
                "count": 0,
                "services": [],
            },
            "moe_mail": {
                "available": False,
                "count": 0,
                "services": [],
            },
            "temp_mail": {
                "available": False,
                "count": 0,
                "services": [],
            },
            "duck_mail": {
                "available": False,
                "count": 0,
                "services": [],
            },
            "freemail": {
                "available": False,
                "count": 0,
                "services": [],
            },
            "imap_mail": {
                "available": False,
                "count": 0,
                "services": [],
            },
        }

        with self.db_factory() as db:
            outlook_services = (
                db.query(EmailService)
                .filter(
                    EmailService.service_type == "outlook",
                    EmailService.enabled.is_(True),
                )
                .order_by(EmailService.priority.asc())
                .all()
            )
            for service in outlook_services:
                config = service.config or {}
                result["outlook"]["services"].append(
                    {
                        "id": service.id,
                        "name": service.name,
                        "type": "outlook",
                        "has_oauth": bool(config.get("client_id") and config.get("refresh_token")),
                        "priority": service.priority,
                    }
                )

            result["outlook"]["count"] = len(outlook_services)
            result["outlook"]["available"] = len(outlook_services) > 0

            moe_mail_services = (
                db.query(EmailService)
                .filter(
                    EmailService.service_type == "moe_mail",
                    EmailService.enabled.is_(True),
                )
                .order_by(EmailService.priority.asc())
                .all()
            )
            for service in moe_mail_services:
                config = service.config or {}
                result["moe_mail"]["services"].append(
                    {
                        "id": service.id,
                        "name": service.name,
                        "type": "moe_mail",
                        "default_domain": config.get("default_domain"),
                        "priority": service.priority,
                    }
                )

            result["moe_mail"]["count"] = len(moe_mail_services)
            result["moe_mail"]["available"] = len(moe_mail_services) > 0

            if not result["moe_mail"]["available"]:
                if (
                    getattr(settings, "custom_domain_base_url", None)
                    and getattr(settings, "custom_domain_api_key", None)
                ):
                    result["moe_mail"]["available"] = True
                    result["moe_mail"]["count"] = 1
                    result["moe_mail"]["services"].append(
                        {
                            "id": None,
                            "name": "默认自定义域名服务",
                            "type": "moe_mail",
                            "from_settings": True,
                        }
                    )

            temp_mail_services = (
                db.query(EmailService)
                .filter(
                    EmailService.service_type == "temp_mail",
                    EmailService.enabled.is_(True),
                )
                .order_by(EmailService.priority.asc())
                .all()
            )
            for service in temp_mail_services:
                config = service.config or {}
                result["temp_mail"]["services"].append(
                    {
                        "id": service.id,
                        "name": service.name,
                        "type": "temp_mail",
                        "domain": config.get("domain"),
                        "priority": service.priority,
                    }
                )

            result["temp_mail"]["count"] = len(temp_mail_services)
            result["temp_mail"]["available"] = len(temp_mail_services) > 0

            duck_mail_services = (
                db.query(EmailService)
                .filter(
                    EmailService.service_type == "duck_mail",
                    EmailService.enabled.is_(True),
                )
                .order_by(EmailService.priority.asc())
                .all()
            )
            for service in duck_mail_services:
                config = service.config or {}
                result["duck_mail"]["services"].append(
                    {
                        "id": service.id,
                        "name": service.name,
                        "type": "duck_mail",
                        "default_domain": config.get("default_domain"),
                        "priority": service.priority,
                    }
                )

            result["duck_mail"]["count"] = len(duck_mail_services)
            result["duck_mail"]["available"] = len(duck_mail_services) > 0

            freemail_services = (
                db.query(EmailService)
                .filter(
                    EmailService.service_type == "freemail",
                    EmailService.enabled.is_(True),
                )
                .order_by(EmailService.priority.asc())
                .all()
            )
            for service in freemail_services:
                config = service.config or {}
                result["freemail"]["services"].append(
                    {
                        "id": service.id,
                        "name": service.name,
                        "type": "freemail",
                        "domain": config.get("domain"),
                        "priority": service.priority,
                    }
                )

            result["freemail"]["count"] = len(freemail_services)
            result["freemail"]["available"] = len(freemail_services) > 0

            imap_mail_services = (
                db.query(EmailService)
                .filter(
                    EmailService.service_type == "imap_mail",
                    EmailService.enabled.is_(True),
                )
                .order_by(EmailService.priority.asc())
                .all()
            )
            for service in imap_mail_services:
                config = service.config or {}
                result["imap_mail"]["services"].append(
                    {
                        "id": service.id,
                        "name": service.name,
                        "type": "imap_mail",
                        "email": config.get("email"),
                        "host": config.get("host"),
                        "priority": service.priority,
                    }
                )

            result["imap_mail"]["count"] = len(imap_mail_services)
            result["imap_mail"]["available"] = len(imap_mail_services) > 0

        return result

    def get_outlook_accounts_for_registration(self) -> Dict[str, Any]:
        with self.db_factory() as db:
            outlook_services = (
                db.query(EmailService)
                .filter(
                    EmailService.service_type == "outlook",
                    EmailService.enabled.is_(True),
                )
                .order_by(EmailService.priority.asc())
                .all()
            )

            accounts: List[Dict[str, Any]] = []
            registered_count = 0
            unregistered_count = 0

            for service in outlook_services:
                config = service.config or {}
                email = config.get("email") or service.name
                existing_account = (
                    db.query(Account)
                    .filter(Account.email == email)
                    .first()
                )

                is_registered = existing_account is not None
                if is_registered:
                    registered_count += 1
                else:
                    unregistered_count += 1

                accounts.append(
                    {
                        "id": service.id,
                        "email": email,
                        "name": service.name,
                        "has_oauth": bool(config.get("client_id") and config.get("refresh_token")),
                        "is_registered": is_registered,
                        "registered_account_id": existing_account.id if existing_account else None,
                    }
                )

            return {
                "total": len(accounts),
                "registered_count": registered_count,
                "unregistered_count": unregistered_count,
                "accounts": accounts,
            }


__all__ = ["RegistrationQueryFacade"]
