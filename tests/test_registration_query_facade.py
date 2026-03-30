from contextlib import contextmanager
from dataclasses import asdict, fields

import pytest

from src.application.registration_query_facade import RegistrationQueryFacade
from src.database import crud
from src.database.models import Base
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
