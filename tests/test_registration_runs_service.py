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


def test_registration_runs_service_supports_service_owned_commit_boundaries(temp_db):
    service = RegistrationRunsService(temp_db)

    transient = service.create_run(
        task_uuid="task-boundary-transient",
        batch_id="batch-x",
        trigger_source="manual",
        commit=False,
    )
    temp_db.rollback()

    assert service.get_run(transient.id) is None

    persisted = service.create_run(
        task_uuid="task-boundary-persisted",
        batch_id="batch-y",
        trigger_source="manual",
        commit=True,
    )
    service.append_event(
        persisted.id,
        level="info",
        message="uncommitted-event",
        commit=False,
    )
    temp_db.rollback()

    assert service.get_run(persisted.id) is not None
    assert service.get_events(persisted.id) == []

    service.append_event(
        persisted.id,
        level="info",
        message="committed-event",
        commit=True,
    )
    temp_db.rollback()

    events = service.get_events(persisted.id)
    assert len(events) == 1
    assert events[0].message == "committed-event"


def test_registration_runs_service_marks_running_and_completed(temp_db):
    service = RegistrationRunsService(temp_db)

    run = service.create_run(task_uuid="task-2", batch_id=None, trigger_source="manual")
    service.mark_running(run.id)
    updated = service.mark_completed(run.id)

    assert updated.status == "completed"
    assert updated.started_at is not None
    assert updated.completed_at is not None


def test_registration_runs_service_mark_started_is_idempotent(temp_db):
    service = RegistrationRunsService(temp_db)

    run = service.create_run(task_uuid="task-started-1", batch_id=None, trigger_source="manual", commit=True)
    first = service.mark_started(run.id, commit=True)
    second = service.mark_started(run.id, commit=True)

    assert first is not None
    assert first.status == "pending"
    assert first.started_at is not None
    assert second.started_at == first.started_at
    assert second.status == "pending"


def test_registration_runs_service_terminal_status_is_immutable(temp_db):
    service = RegistrationRunsService(temp_db)

    run = service.create_run(task_uuid="task-3", batch_id=None, trigger_source="manual", commit=True)
    completed = service.mark_completed(run.id, commit=True)
    service.mark_started(run.id, commit=True)
    service.mark_running(run.id, commit=True)
    service.mark_failed(run.id, error_message="ignored", commit=True)
    updated = service.mark_cancelled(run.id, error_message="ignored-too", commit=True)

    assert updated.status == "completed"
    assert completed is not None
    assert updated.completed_at == completed.completed_at
    assert updated.started_at == completed.started_at
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


def test_registration_repository_get_run_by_task_uuid_uses_latest_id_desc_order():
    class _FakeQuery:
        def __init__(self):
            self.order_by_clause = None
            self.result = object()

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, clause):
            self.order_by_clause = clause
            return self

        def first(self):
            return self.result

    class _FakeSession:
        def __init__(self, query_obj):
            self.query_obj = query_obj

        def query(self, _model):
            return self.query_obj

    fake_query = _FakeQuery()
    repository = RegistrationRepository(_FakeSession(fake_query))

    loaded = repository.get_run_by_task_uuid("task-ordered")

    assert loaded is fake_query.result
    assert fake_query.order_by_clause is not None
    assert "DESC" in str(fake_query.order_by_clause).upper()


def test_registration_repository_bulk_lookup_returns_keyed_rows_by_task_uuid(temp_db):
    repository = RegistrationRepository(temp_db)
    first = repository.create_run(task_uuid="task-repo-2a", batch_id="batch-a", trigger_source="manual")
    second = repository.create_run(task_uuid="task-repo-2b", batch_id="batch-b", trigger_source="manual")

    rows_by_task_uuid = repository.list_latest_runs_by_task_uuids(
        ["task-repo-2a", "task-repo-2b", "task-repo-2a", "task-missing"]
    )

    assert isinstance(rows_by_task_uuid, dict)
    assert set(rows_by_task_uuid.keys()) == {"task-repo-2a", "task-repo-2b"}
    assert rows_by_task_uuid["task-repo-2a"].id == first.id
    assert rows_by_task_uuid["task-repo-2b"].id == second.id


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


def test_registration_repository_append_event_rejects_orphan_run_id(temp_db):
    repository = RegistrationRepository(temp_db)

    with pytest.raises(ValueError, match="run_id=999999"):
        repository.append_event(
            run_id=999999,
            level="info",
            message="orphan event",
        )
