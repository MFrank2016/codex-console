from contextlib import contextmanager

import pytest

from src.application.registration_query_facade import RegistrationQueryFacade
from src.database import crud
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


def test_registration_query_facade_list_tasks_prefers_runtime_steps_when_db_steps_missing(
    db_factory, temp_db
):
    crud.create_registration_task(
        temp_db, task_uuid="task-facade-1", pipeline_key="current_pipeline"
    )
    task_manager = FakeTaskManager()
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
