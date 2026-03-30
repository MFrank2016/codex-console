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
