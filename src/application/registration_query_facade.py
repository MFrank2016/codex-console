"""Query facade for registration read-side use cases."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, ContextManager, Dict, List, Optional

from ..config.settings import get_settings
from ..core.time import utc_now
from ..database import crud
from ..database.models import RegistrationTask
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
        view = RegistrationTaskView(
            id=task.id,
            task_uuid=task.task_uuid,
            status=task.status,
            steps=list(steps or []),
            result=task.result,
            logs=task.logs,
        )
        extra_fields = {
            "email": email,
            "email_service_id": task.email_service_id,
            "pipeline_key": task.pipeline_key,
            "current_step_key": task.current_step_key,
            "pipeline_status": task.pipeline_status,
            "total_duration_ms": task.total_duration_ms,
            "proxy": task.proxy,
            "proxy_ip": str(proxy_ip).strip() if proxy_ip else None,
            "error_message": task.error_message,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }
        for field_name, field_value in extra_fields.items():
            object.__setattr__(view, field_name, field_value)
        return view

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
        failed_from: Optional[datetime] = None,
        failed_to: Optional[datetime] = None,
    ) -> RegistrationFailureSummaryView:
        raise NotImplementedError("build_failure_summary is not implemented yet")

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
        failed_from: Optional[datetime] = None,
        failed_to: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> RegistrationFailureListView:
        raise NotImplementedError("list_failures is not implemented yet")

    def get_batch_status(self, batch_id: str) -> RegistrationBatchStatusView:
        raise NotImplementedError("get_batch_status is not implemented yet")

    def get_outlook_batch_status(self, batch_id: str) -> RegistrationBatchStatusView:
        raise NotImplementedError("get_outlook_batch_status is not implemented yet")

    def get_available_email_services(self) -> Dict[str, Any]:
        raise NotImplementedError("get_available_email_services is not implemented yet")

    def get_outlook_accounts_for_registration(self) -> Dict[str, Any]:
        raise NotImplementedError("get_outlook_accounts_for_registration is not implemented yet")


__all__ = ["RegistrationQueryFacade"]
