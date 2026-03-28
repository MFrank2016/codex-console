import pytest

from src.application.registration_runs_service import RegistrationRunsService
from src.database.models import Base
from src.database.repositories.registration_repository import RegistrationRepository
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


def test_registration_repository_create_run_does_not_commit_implicitly(temp_db):
    repository = RegistrationRepository(temp_db)

    created = repository.create_run(task_uuid="task-repo-1", batch_id="batch-1", trigger_source="manual")
    temp_db.rollback()

    assert repository.get_run(created.id) is None


def test_registration_repository_bulk_lookup_returns_latest_rows_by_task_uuid(temp_db):
    repository = RegistrationRepository(temp_db)
    first = repository.create_run(task_uuid="task-repo-2a", batch_id="batch-a", trigger_source="manual")
    second = repository.create_run(task_uuid="task-repo-2b", batch_id="batch-b", trigger_source="manual")

    rows = repository.list_latest_runs_by_task_uuids(
        ["task-repo-2a", "task-repo-2b", "task-repo-2a", "task-missing"]
    )
    by_task_uuid = {row.task_uuid: row for row in rows}

    assert set(by_task_uuid.keys()) == {"task-repo-2a", "task-repo-2b"}
    assert by_task_uuid["task-repo-2a"].id == first.id
    assert by_task_uuid["task-repo-2b"].id == second.id


def test_registration_repository_refuses_to_override_terminal_status(temp_db):
    repository = RegistrationRepository(temp_db)
    run = repository.create_run(
        task_uuid="task-repo-3",
        batch_id="batch-terminal",
        trigger_source="manual",
        status="completed",
    )

    updated = repository.update_status_if_not_terminal(
        run.id,
        status="failed",
        error_message="should-be-ignored",
    )

    assert updated is not None
    assert updated.status == "completed"
    assert updated.error_message in (None, "")
