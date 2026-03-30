"""Query facade for registration read-side use cases."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, ContextManager, Dict, Optional

from ..config.settings import get_settings
from ..core.time import utc_now
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

    # Read-side scaffolding (not implemented yet)

    def list_tasks(
        self,
        *,
        page: int,
        page_size: int,
        status: Optional[str],
    ) -> RegistrationTaskListView:
        raise NotImplementedError("list_tasks is not implemented yet")

    def get_task_detail(self, task_uuid: str) -> Optional[RegistrationTaskView]:
        raise NotImplementedError("get_task_detail is not implemented yet")

    def get_task_logs(self, task_uuid: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("get_task_logs is not implemented yet")

    def get_registration_stats(self) -> RegistrationStatsView:
        raise NotImplementedError("get_registration_stats is not implemented yet")

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
