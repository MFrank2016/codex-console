import pytest

from src.application.registration_runs_service import RegistrationRunsService
from src.database.models import Base
from src.database.session import DatabaseSessionManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "registration-runs.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_registration_runs_service_creates_run_and_appends_events(temp_db):
    service = RegistrationRunsService(temp_db)

    run = service.create_run(task_uuid="task-1", batch_id="batch-1", trigger_source="manual")
    service.append_event(run.id, level="info", message="queued")

    events = service.get_events(run.id)

    assert run.id is not None
    assert run.task_uuid == "task-1"
    assert len(events) == 1
    assert events[0].message == "queued"


def test_registration_runs_service_marks_running_and_completed(temp_db):
    service = RegistrationRunsService(temp_db)

    run = service.create_run(task_uuid="task-2", batch_id=None, trigger_source="manual")
    service.mark_running(run.id)
    updated = service.mark_completed(run.id)

    assert updated.status == "completed"
    assert updated.started_at is not None
    assert updated.completed_at is not None


def test_registration_runs_service_terminal_status_is_immutable(temp_db):
    service = RegistrationRunsService(temp_db)

    run = service.create_run(task_uuid="task-3", batch_id=None, trigger_source="manual")
    service.mark_completed(run.id)
    updated = service.mark_failed(run.id, error_message="ignored")

    assert updated.status == "completed"
    assert updated.error_message in (None, "")


def test_registration_runs_service_get_run_by_task_uuid(temp_db):
    service = RegistrationRunsService(temp_db)

    created = service.create_run(task_uuid="task-4", batch_id="batch-x", trigger_source="manual")
    loaded = service.get_run_by_task_uuid("task-4")

    assert loaded is not None
    assert loaded.id == created.id
