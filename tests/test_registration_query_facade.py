from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import UTC, datetime

import pytest

from src.application.registration_query_facade import RegistrationQueryFacade
from src.database import crud
from src.database.models import Base
from src.database.repositories import registration_failure_repository as failure_repo
from src.database.session import DatabaseSessionManager
from tests.fakes import RegistrationFakeTaskManager as FakeTaskManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "registration-query-facade.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.expunge_all()
        session.close()


@pytest.fixture
def db_factory(temp_db):
    @contextmanager
    def _factory():
        yield temp_db

    return _factory


class _FakeSettings:
    custom_domain_base_url = "https://mail.example.com"
    custom_domain_api_key = "secret"


def _settings_reader():
    return _FakeSettings()


def _create_failure(
    db,
    *,
    task_uuid: str,
    failed_at: datetime,
    email: str,
    email_suffix: str,
    email_service_id: int | None = None,
    proxy_ip: str | None = None,
    error_code: str = "registration_disallowed",
    error_detail: str = "registration_disallowed detail",
):
    row = failure_repo.upsert_registration_failure_record(
        db,
        task_uuid=task_uuid,
        attempt_no=1,
        batch_id="batch-1",
        pipeline_key="current_pipeline",
        registration_mode="batch",
        email=email,
        email_suffix=email_suffix,
        email_service_id=email_service_id,
        email_service_type="tempmail",
        display_name="Alice Smith",
        birthdate="1994-02-03",
        proxy="http://proxy-a",
        proxy_ip=proxy_ip,
        error_code=error_code,
        error_detail=error_detail,
        failed_at=failed_at,
        extra_json={"step": "create_account_profile"},
    )
    db.commit()
    return row


def test_registration_query_facade_list_tasks_prefers_runtime_steps_when_db_steps_missing(
    db_factory, temp_db
):
    crud.create_registration_task(
        temp_db, task_uuid="task-facade-1", pipeline_key="current_pipeline"
    )
    task_manager = FakeTaskManager()
    task_manager.get_task_steps = lambda task_uuid: list(task_manager._task_steps.get(task_uuid, []))
    task_manager.set_task_steps(
        "task-facade-1",
        [{"step_key": "runtime-only", "status": "running"}],
        task_progress={"step_index": 1, "total_steps": 2, "progress_percent": 50},
    )

    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=task_manager,
    )

    view = facade.list_tasks(page=1, page_size=20, status=None)

    assert view.total == 1
    assert view.tasks[0].task_uuid == "task-facade-1"
    assert view.tasks[0].steps == [{"step_key": "runtime-only", "status": "running"}]


def test_registration_query_facade_get_task_detail_returns_none_for_missing_task(db_factory):
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
    )

    assert facade.get_task_detail("missing-task") is None


def test_registration_query_facade_get_batch_status_reads_store_without_db_access():
    db_calls = {"count": 0}

    @contextmanager
    def _db_factory():
        db_calls["count"] += 1
        raise AssertionError("get_batch_status should not touch database")
        yield  # pragma: no cover

    facade = RegistrationQueryFacade(
        db_factory=_db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={
            "batch-ordinary-1": {
                "total": 5,
                "completed": 2,
                "success": 1,
                "failed": 1,
                "current_index": 2,
                "cancelled": False,
                "finished": False,
                "started_at": "2026-03-30T08:00:00",
                "is_unlimited": True,
                "consecutive_failures": 3,
                "max_consecutive_failures": 9,
                "stop_reason": "manual_stop",
                "domain_stats": [{"domain": "gmail.com", "count": 2}],
            }
        },
    )

    view = facade.get_batch_status("batch-ordinary-1")

    assert db_calls["count"] == 0
    assert view is not None
    assert view.batch_id == "batch-ordinary-1"
    assert view.payload == {
        "batch_id": "batch-ordinary-1",
        "total": 5,
        "completed": 2,
        "success": 1,
        "failed": 1,
        "current_index": 2,
        "cancelled": False,
        "finished": False,
        "started_at": "2026-03-30T08:00:00",
        "progress": "2/5",
        "is_unlimited": True,
        "consecutive_failures": 3,
        "max_consecutive_failures": 9,
        "stop_reason": "manual_stop",
        "domain_stats": [{"domain": "gmail.com", "count": 2}],
    }


def test_registration_query_facade_get_batch_status_returns_none_for_missing_batch():
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={},
    )

    assert facade.get_batch_status("missing-batch") is None


def test_registration_query_facade_get_outlook_batch_status_keeps_skipped_logs_and_domain_stats():
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={
            "batch-outlook-1": {
                "total": 8,
                "completed": 3,
                "success": 2,
                "failed": 1,
                "skipped": 4,
                "current_index": 3,
                "cancelled": False,
                "finished": True,
                "started_at": "2026-03-30T09:00:00",
                "logs": ["log-1", "log-2"],
                "domain_stats": [{"domain": "outlook.com", "count": 2}],
            }
        },
    )

    view = facade.get_outlook_batch_status("batch-outlook-1")

    assert view is not None
    assert view.batch_id == "batch-outlook-1"
    assert view.payload["progress"] == "3/8"
    assert view.payload["skipped"] == 4
    assert view.payload["logs"] == ["log-1", "log-2"]
    assert view.payload["domain_stats"] == [{"domain": "outlook.com", "count": 2}]


def test_registration_query_facade_task_logs_keeps_legacy_split_lines(db_factory, temp_db):
    task = crud.create_registration_task(temp_db, task_uuid="task-log-1")
    crud.update_registration_task(temp_db, task.task_uuid, logs="line-1\nline-2")

    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
    )

    payload = facade.get_task_logs("task-log-1")
    assert payload["task_uuid"] == "task-log-1"
    assert payload["logs"] == ["line-1", "line-2"]


def test_registration_query_facade_list_tasks_prefers_db_steps_over_runtime_when_rows_exist(
    db_factory, temp_db
):
    task = crud.create_registration_task(temp_db, task_uuid="task-db-steps-1")
    crud.create_pipeline_step_run(
        temp_db,
        task_uuid=task.task_uuid,
        pipeline_key="current_pipeline",
        step_key="db-step",
        step_order=1,
        step_impl="demo",
        status="completed",
    )
    task_manager = FakeTaskManager()
    task_manager.get_task_steps = lambda task_uuid: list(task_manager._task_steps.get(task_uuid, []))
    task_manager.set_task_steps(
        task.task_uuid,
        [{"step_key": "runtime-step", "status": "running"}],
        task_progress={"step_index": 1, "total_steps": 2, "progress_percent": 50},
    )

    facade = RegistrationQueryFacade(db_factory=db_factory, task_manager=task_manager)

    view = facade.list_tasks(page=1, page_size=20, status=None)

    assert view.tasks[0].steps[0]["step_key"] == "db-step"


def test_registration_query_facade_task_view_exposes_explicit_contract_fields(
    db_factory, temp_db
):
    task = crud.create_registration_task(
        temp_db,
        task_uuid="task-dto-contract",
        pipeline_key="codexgen_pipeline",
        email_address="contract@example.com",
        email_service_id=42,
        proxy="http://proxy.example.com:8080",
    )
    crud.update_registration_task(
        temp_db,
        task.task_uuid,
        result={"metadata": {"proxy_ip": "8.8.4.4"}},
    )

    facade = RegistrationQueryFacade(db_factory=db_factory, task_manager=FakeTaskManager())

    view = facade.get_task_detail(task.task_uuid)

    assert view is not None
    declared_fields = {item.name for item in fields(type(view))}
    expected_fields = {
        "email",
        "email_service_id",
        "pipeline_key",
        "current_step_key",
        "pipeline_status",
        "total_duration_ms",
        "proxy",
        "proxy_ip",
        "error_message",
        "created_at",
        "started_at",
        "completed_at",
    }
    assert expected_fields.issubset(declared_fields)

    payload = asdict(view)
    assert payload["email"] == "contract@example.com"
    assert payload["proxy_ip"] == "8.8.4.4"
    assert payload["pipeline_key"] == "codexgen_pipeline"
    assert payload["created_at"] is not None


def test_registration_query_facade_build_failure_summary_defaults_to_recent_7_days_and_today_intersection(
    db_factory, temp_db
):
    _create_failure(
        temp_db,
        task_uuid="task-today",
        failed_at=datetime(2026, 3, 28, 2, 0, 0),
        email="today@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.1",
    )
    _create_failure(
        temp_db,
        task_uuid="task-window",
        failed_at=datetime(2026, 3, 24, 2, 0, 0),
        email="window@other.test",
        email_suffix="other.test",
        proxy_ip="2.2.2.2",
        error_code="proxy_error",
        error_detail="proxy timeout",
    )
    _create_failure(
        temp_db,
        task_uuid="task-old",
        failed_at=datetime(2026, 3, 20, 1, 59, 59),
        email="old@old.test",
        email_suffix="old.test",
        proxy_ip="3.3.3.3",
    )
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        utc_now_provider=lambda: datetime(2026, 3, 28, 4, 0, 0, tzinfo=UTC),
    )

    summary = facade.build_failure_summary()

    assert summary.total_failed_attempts == 2
    assert summary.today_failed_attempts == 1


def test_registration_query_facade_build_failure_summary_today_count_honors_proxy_ip_and_email_service_id_filters(
    db_factory, temp_db
):
    _create_failure(
        temp_db,
        task_uuid="task-hit",
        failed_at=datetime(2026, 3, 28, 3, 0, 0),
        email="hit@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="8.8.8.8",
        email_service_id=42,
    )
    _create_failure(
        temp_db,
        task_uuid="task-proxy-miss",
        failed_at=datetime(2026, 3, 28, 3, 1, 0),
        email="proxy-miss@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.1",
        email_service_id=42,
    )
    _create_failure(
        temp_db,
        task_uuid="task-service-miss",
        failed_at=datetime(2026, 3, 28, 3, 2, 0),
        email="service-miss@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="8.8.8.8",
        email_service_id=7,
    )
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        utc_now_provider=lambda: datetime(2026, 3, 28, 4, 0, 0, tzinfo=UTC),
    )

    summary = facade.build_failure_summary(proxy_ip="8.8.8.8", email_service_id=42)

    assert summary.total_failed_attempts == 1
    assert summary.today_failed_attempts == 1


def test_registration_query_facade_build_failure_summary_uses_single_now_for_window_and_today_count(
    db_factory, temp_db
):
    _create_failure(
        temp_db,
        task_uuid="task-shanghai-day-edge",
        failed_at=datetime(2026, 3, 28, 15, 30, 0),
        email="edge@blocked.test",
        email_suffix="blocked.test",
    )

    now_values = iter(
        [
            datetime(2026, 3, 28, 15, 59, 59, tzinfo=UTC),  # 上海 2026-03-28 23:59:59
            datetime(2026, 3, 28, 16, 0, 1, tzinfo=UTC),  # 上海 2026-03-29 00:00:01
        ]
    )
    provider_call_count = 0

    def _utc_now_provider():
        nonlocal provider_call_count
        provider_call_count += 1
        return next(now_values)

    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        utc_now_provider=_utc_now_provider,
    )

    summary = facade.build_failure_summary()

    assert summary.total_failed_attempts == 1
    assert summary.today_failed_attempts == 1
    assert provider_call_count == 1


def test_registration_query_facade_list_failures_treats_naive_datetime_as_asia_shanghai(
    db_factory, temp_db
):
    _create_failure(
        temp_db,
        task_uuid="task-shanghai-hit",
        failed_at=datetime(2026, 3, 28, 2, 0, 0),
        email="hit@blocked.test",
        email_suffix="blocked.test",
    )
    _create_failure(
        temp_db,
        task_uuid="task-shanghai-miss",
        failed_at=datetime(2026, 3, 28, 10, 0, 0),
        email="miss@blocked.test",
        email_suffix="blocked.test",
    )
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
    )

    result = facade.list_failures(
        failed_from="2026-03-28T10:00:00",
        failed_to="2026-03-28T10:00:00",
    )

    assert result.total == 1
    assert result.items[0]["task_uuid"] == "task-shanghai-hit"


def test_registration_query_facade_list_failures_rejects_failed_from_greater_than_failed_to(
    db_factory,
):
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
    )

    with pytest.raises(ValueError, match="failed_from must be less than or equal to failed_to"):
        facade.list_failures(
            failed_from="2026-03-29T10:00:00",
            failed_to="2026-03-28T10:00:00",
        )


def test_registration_query_facade_get_available_email_services_keeps_settings_fallback(
    db_factory, temp_db
):
    crud.create_email_service(
        temp_db,
        service_type="temp_mail",
        name="Temp Mail Worker",
        config={"domain": "temp.worker.test"},
        enabled=True,
        priority=2,
    )
    crud.create_email_service(
        temp_db,
        service_type="duck_mail",
        name="Duck Mail",
        config={"default_domain": "duck.test"},
        enabled=True,
        priority=3,
    )
    crud.create_email_service(
        temp_db,
        service_type="freemail",
        name="Free Mail",
        config={"domain": "free.test"},
        enabled=True,
        priority=4,
    )
    crud.create_email_service(
        temp_db,
        service_type="imap_mail",
        name="IMAP Mail",
        config={"email": "imap@test.dev", "host": "imap.test.dev"},
        enabled=True,
        priority=5,
    )

    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        settings_reader=_settings_reader,
    )

    payload = facade.get_available_email_services()

    assert payload["tempmail"]["available"] is True
    assert payload["moe_mail"]["available"] is True
    assert payload["moe_mail"]["services"][0]["from_settings"] is True

    assert payload["temp_mail"]["available"] is True
    assert payload["temp_mail"]["services"][0]["domain"] == "temp.worker.test"
    assert payload["duck_mail"]["services"][0]["default_domain"] == "duck.test"
    assert payload["freemail"]["services"][0]["domain"] == "free.test"
    assert payload["imap_mail"]["services"][0]["email"] == "imap@test.dev"
    assert payload["imap_mail"]["services"][0]["host"] == "imap.test.dev"


def test_registration_query_facade_get_outlook_accounts_for_registration_marks_registered_accounts(
    db_factory, temp_db
):
    registered_outlook = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="registered-outlook",
        config={
            "email": "registered@outlook.test",
            "client_id": "client-1",
            "refresh_token": "refresh-1",
        },
        enabled=True,
        priority=1,
    )
    fallback_name_outlook = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="name-as-email-outlook",
        config={"client_id": "client-2"},
        enabled=True,
        priority=2,
    )

    existing = crud.create_account(
        temp_db,
        email="registered@outlook.test",
        email_service="outlook",
        email_service_id=str(registered_outlook.id),
    )

    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
    )

    payload = facade.get_outlook_accounts_for_registration()

    assert payload["total"] == 2
    assert payload["registered_count"] == 1
    assert payload["unregistered_count"] == 1

    registered_item = payload["accounts"][0]
    assert registered_item["id"] == registered_outlook.id
    assert registered_item["email"] == "registered@outlook.test"
    assert registered_item["has_oauth"] is True
    assert registered_item["is_registered"] is True
    assert registered_item["registered_account_id"] == existing.id

    unregistered_item = payload["accounts"][1]
    assert unregistered_item["id"] == fallback_name_outlook.id
    assert unregistered_item["email"] == "name-as-email-outlook"
    assert unregistered_item["has_oauth"] is False
    assert unregistered_item["is_registered"] is False
    assert unregistered_item["registered_account_id"] is None
