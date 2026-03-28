import asyncio
from contextlib import contextmanager
from datetime import datetime

import pytest

from src.application.proxy_dispatch_service import ResolvedProxyCandidate
from src.application.registration_runs_service import RegistrationRunsService
from src.core.time import utc_now_naive
from src.database import crud
from src.database.models import Account, Base, EmailService, RegistrationRunEvent
from src.database.session import DatabaseSessionManager

from tests.fakes import BatchFakeTaskManager as FakeTaskManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "batch-registration-service.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def db_factory(temp_db):
    @contextmanager
    def _factory():
        yield temp_db

    return _factory




def test_batch_registration_service_start_outlook_batch_filters_registered_accounts(db_factory, temp_db):
    from src.application.batch_registration_service import BatchRegistrationService

    registered_email = "registered@example.com"
    registered_service = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="registered",
        config={"email": registered_email},
    )
    crud.create_account(
        temp_db,
        email=registered_email,
        email_service="outlook",
    )
    unregistered_service_one = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="unregistered-1",
        config={"email": "first@example.com"},
    )
    unregistered_service_two = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="unregistered-2",
        config={"email": "second@example.com"},
    )

    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={},
        uuid_factory=lambda: "outlook-batch-001",
    )

    result = service.start_outlook_batch(
        service_ids=[
            registered_service.id,
            unregistered_service_one.id,
            unregistered_service_two.id,
        ],
        skip_registered=True,
        concurrency=2,
        use_proxy=False,
        proxy_task_group="outlook_batch",
        proxy_overrides={},
    )

    assert result.batch_id == "outlook-batch-001"
    assert result.total == 3
    assert result.skipped == 1
    assert result.service_ids == (
        unregistered_service_one.id,
        unregistered_service_two.id,
    )

def test_filter_outlook_service_ids_uses_batched_queries(db_factory, temp_db, monkeypatch):
    from src.application.batch_registration_service import BatchRegistrationService

    svc1 = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="one",
        config={"email": "one@example.com"},
    )
    svc2 = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="two",
        config={"email": "two@example.com"},
    )
    svc3 = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="three",
        config={"email": "three@example.com"},
    )
    crud.create_account(temp_db, email="two@example.com", email_service="outlook")

    service_query_calls = 0
    account_query_calls = 0
    original_query = temp_db.query

    def tracked_query(*entities, **kwargs):
        nonlocal service_query_calls, account_query_calls
        if len(entities) == 1 and entities[0] is EmailService:
            service_query_calls += 1
        if len(entities) == 1 and entities[0] is Account.email:
            account_query_calls += 1
        return original_query(*entities, **kwargs)

    monkeypatch.setattr(temp_db, "query", tracked_query)

    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={},
    )

    actual_ids, skipped = service._filter_outlook_service_ids(
        service_ids=[svc1.id, svc2.id, svc3.id],
        skip_registered=True,
    )

    assert service_query_calls == 1
    assert account_query_calls == 1
    assert skipped == 1
    assert actual_ids == [svc1.id, svc3.id]


@pytest.mark.anyio
async def test_outlook_bootstrap_fields_survive_second_init(db_factory, temp_db):
    from src.application.batch_registration_service import BatchRegistrationService

    registered_email = "registered-survive@example.com"
    registered_service = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="registered-survive",
        config={"email": registered_email},
    )
    crud.create_account(temp_db, email=registered_email, email_service="outlook")
    fresh_service = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="fresh-survive",
        config={"email": "fresh-survive@example.com"},
    )

    async def fake_runner(task_uuid, *args, **kwargs):
        runs = RegistrationRunsService(temp_db)
        run = runs.create_run(task_uuid=task_uuid, batch_id="outlook-preserve", trigger_source="batch")
        crud.update_registration_task(
            temp_db,
            task_uuid,
            status="completed",
            pipeline_status="completed",
            completed_at=utc_now_naive(),
        )
        runs.mark_completed(run.id)

    task_manager = FakeTaskManager()
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        batch_tasks_store={},
        registration_task_runner=fake_runner,
        uuid_factory=lambda: "outlook-preserve",
    )

    bootstrap = service.start_outlook_batch(
        service_ids=[registered_service.id, fresh_service.id],
        skip_registered=True,
        concurrency=1,
        use_proxy=False,
        proxy_task_group="outlook_batch",
        proxy_overrides={},
    )

    await service.run_outlook_batch_registration(
        batch_id=bootstrap.batch_id,
        service_ids=list(bootstrap.service_ids),
        proxy=None,
        interval_min=0,
        interval_max=0,
        concurrency=1,
        mode="parallel",
    )

    state = service.batch_tasks[bootstrap.batch_id]
    assert state["skipped"] == 1
    assert state["service_ids"] == [fresh_service.id]

    status = task_manager.get_batch_status(bootstrap.batch_id)
    assert status["skipped"] == 1
    assert status["service_ids"] == [fresh_service.id]


def test_batch_registration_service_build_summary_uses_bulk_run_lookup(
    db_factory, temp_db, monkeypatch
):
    from src.application.batch_registration_service import BatchRegistrationService
    from src.database.repositories.registration_repository import RegistrationRepository

    batch_id = "batch-summary-bulk"
    task_uuids: list[str] = []
    expected_run_ids: list[int] = []
    for idx in range(3):
        task_uuid = f"summary-task-{idx}"
        crud.create_registration_task(temp_db, task_uuid=task_uuid)
        run = RegistrationRunsService(temp_db).create_run(
            task_uuid=task_uuid,
            batch_id=batch_id,
            trigger_source="batch",
        )
        task_uuids.append(task_uuid)
        expected_run_ids.append(run.id)

    bulk_calls: list[list[str]] = []
    original_bulk_lookup = RegistrationRepository.list_latest_runs_by_task_uuids

    def track_bulk_lookup(self, ordered_task_uuids):
        bulk_calls.append(list(ordered_task_uuids))
        return original_bulk_lookup(self, ordered_task_uuids)

    def fail_on_single_lookup(self, task_uuid):
        raise AssertionError(f"unexpected per-task run lookup: {task_uuid}")

    monkeypatch.setattr(
        RegistrationRepository,
        "list_latest_runs_by_task_uuids",
        track_bulk_lookup,
    )
    monkeypatch.setattr(
        RegistrationRunsService,
        "get_run_by_task_uuid",
        fail_on_single_lookup,
    )

    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={},
    )
    service.init_batch_state(batch_id, task_uuids)

    summary = service.build_summary(batch_id)

    assert bulk_calls == [task_uuids]
    assert [run.task_uuid for run in summary.runs] == task_uuids
    assert [run.id for run in summary.runs] == expected_run_ids


def test_batch_registration_service_proxy_pool_failure_persists_failed_run_and_event(
    db_factory, temp_db, monkeypatch
):
    from src.application.batch_registration_service import BatchRegistrationService

    task_uuid = "proxy-failure-task"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)

    commit_calls: list[tuple[str, bool]] = []
    original_create_run = RegistrationRunsService.create_run
    original_mark_failed = RegistrationRunsService.mark_failed
    original_append_event = RegistrationRunsService.append_event

    def fail_on_single_lookup(self, task_uuid):
        raise AssertionError(f"unexpected single run lookup for {task_uuid}")

    def track_create_run(self, *args, **kwargs):
        commit_calls.append(("create_run", kwargs.get("commit")))
        return original_create_run(self, *args, **kwargs)

    def track_mark_failed(self, *args, **kwargs):
        commit_calls.append(("mark_failed", kwargs.get("commit")))
        return original_mark_failed(self, *args, **kwargs)

    def track_append_event(self, *args, **kwargs):
        commit_calls.append(("append_event", kwargs.get("commit")))
        return original_append_event(self, *args, **kwargs)

    monkeypatch.setattr(
        RegistrationRunsService,
        "get_run_by_task_uuid",
        fail_on_single_lookup,
    )
    monkeypatch.setattr(RegistrationRunsService, "create_run", track_create_run)
    monkeypatch.setattr(RegistrationRunsService, "mark_failed", track_mark_failed)
    monkeypatch.setattr(RegistrationRunsService, "append_event", track_append_event)

    task_manager = FakeTaskManager()
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        batch_tasks_store={},
    )

    service._mark_proxy_pool_failure(
        batch_id="batch-proxy-failure",
        task_uuid=task_uuid,
        error_message="batch proxy pool exhausted: batch-proxy-failure",
    )

    run = RegistrationRunsService(temp_db).repository.get_run_by_task_uuid(task_uuid)
    assert run is not None
    assert run.status == "failed"
    assert run.batch_id == "batch-proxy-failure"
    assert run.error_message == "batch proxy pool exhausted: batch-proxy-failure"

    events = (
        temp_db.query(RegistrationRunEvent)
        .filter(RegistrationRunEvent.run_id == run.id)
        .order_by(RegistrationRunEvent.id.asc())
        .all()
    )
    assert [(event.level, event.message) for event in events] == [("error", "failed")]
    assert commit_calls == [
        ("create_run", False),
        ("mark_failed", False),
        ("append_event", True),
    ]
    assert task_manager._task_status[task_uuid]["status"] == "failed"
    assert "batch proxy pool exhausted" in task_manager.get_logs(task_uuid)[0]


@pytest.mark.anyio
async def test_batch_registration_service_updates_batch_progress_from_run_records(db_factory, temp_db):
    from src.application.batch_registration_service import BatchRegistrationService

    task_ids = []
    for idx in range(2):
        task = crud.create_registration_task(temp_db, task_uuid=f"task-{idx}")
        task_ids.append(task.task_uuid)

    async def fake_runner(task_uuid, *args, **kwargs):
        runs = RegistrationRunsService(temp_db)
        run = runs.create_run(task_uuid=task_uuid, batch_id="batch-1", trigger_source="batch")
        crud.update_registration_task(
            temp_db,
            task_uuid,
            status="completed",
            pipeline_status="completed",
            completed_at=utc_now_naive(),
            total_duration_ms=1200,
        )
        runs.mark_completed(run.id)

    task_manager = FakeTaskManager()
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        batch_tasks_store={},
        registration_task_runner=fake_runner,
    )

    summary = await service.run_batch_registration(
        batch_id="batch-1",
        task_uuids=task_ids,
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        email_service_id=None,
        interval_min=0,
        interval_max=0,
        concurrency=1,
        mode="parallel",
        pipeline_key="stats_pipeline",
    )

    assert summary.completed == 2
    assert summary.success == 2
    assert summary.failed == 0
    assert summary.status == "completed"
    assert [run.status for run in summary.runs] == ["completed", "completed"]
    assert task_manager._closed_streams == [("batch-1", "completed")]


@pytest.mark.anyio
async def test_batch_registration_service_finalizes_ordinary_batch_stats(db_factory, temp_db):
    from src.application.batch_registration_service import BatchRegistrationService

    task_ids = []
    for idx in range(2):
        task = crud.create_registration_task(temp_db, task_uuid=f"stats-task-{idx}")
        task_ids.append(task.task_uuid)

    async def fake_runner(task_uuid, *args, **kwargs):
        runs = RegistrationRunsService(temp_db)
        run = runs.create_run(task_uuid=task_uuid, batch_id="batch-stats", trigger_source="batch")
        crud.update_registration_task(
            temp_db,
            task_uuid,
            status="completed",
            pipeline_status="completed",
            completed_at=utc_now_naive(),
            total_duration_ms=800,
        )
        runs.mark_completed(run.id)

    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={},
        registration_task_runner=fake_runner,
    )

    summary = await service.run_batch_parallel(
        batch_id="batch-stats",
        task_uuids=task_ids,
        email_service_type="tempmail",
        proxy="http://proxy.local",
        email_service_config=None,
        email_service_id=7,
        concurrency=2,
        interval_min=3,
        interval_max=5,
        pipeline_key="stats_pipeline",
    )

    stat = crud.get_registration_batch_stat_by_batch_id(temp_db, "batch-stats")
    assert summary.status == "completed"
    assert stat is not None
    assert stat.status == "completed"
    assert stat.mode == "parallel"
    assert stat.pipeline_key == "stats_pipeline"
    assert stat.email_service_id == 7
    assert stat.target_count == 2
    assert stat.config_snapshot == {
        "proxy": "http://proxy.local",
        "interval_min": 3,
        "interval_max": 5,
        "concurrency": 2,
    }


@pytest.mark.anyio
async def test_batch_registration_service_uses_batch_proxy_pool_for_parallel_batch(db_factory, temp_db):
    from src.application.batch_registration_service import BatchRegistrationService

    task_ids = []
    for idx in range(2):
        task = crud.create_registration_task(temp_db, task_uuid=f"proxy-batch-task-{idx}")
        task_ids.append(task.task_uuid)

    proxies_seen: list[str | None] = []

    class FakePool:
        def __init__(self):
            self._queue = [
                ResolvedProxyCandidate(proxy_url="http://pool-1:8000", source="dynamic_pool"),
                ResolvedProxyCandidate(proxy_url="http://pool-2:8000", source="dynamic_pool"),
            ]
            self.completed: list[tuple[str, bool]] = []

        def lease(self):
            return self._queue.pop(0)

        def complete(self, candidate, *, success):
            self.completed.append((candidate.proxy_url, success))

    async def fake_runner(task_uuid, *args, **kwargs):
        proxies_seen.append(args[1])
        runs = RegistrationRunsService(temp_db)
        run = runs.create_run(task_uuid=task_uuid, batch_id="batch-proxy", trigger_source="batch")
        crud.update_registration_task(
            temp_db,
            task_uuid,
            status="completed",
            pipeline_status="completed",
            completed_at=utc_now_naive(),
        )
        runs.mark_completed(run.id)

    pool = FakePool()
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={},
        batch_proxy_pools_store={"batch-proxy": pool},
        registration_task_runner=fake_runner,
    )

    summary = await service.run_batch_parallel(
        batch_id="batch-proxy",
        task_uuids=task_ids,
        email_service_type="tempmail",
        proxy=None,
        use_proxy=True,
        email_service_config=None,
        email_service_id=None,
        concurrency=1,
    )

    assert summary.success == 2
    assert proxies_seen == ["http://pool-1:8000", "http://pool-2:8000"]
    assert pool.completed == [
        ("http://pool-1:8000", True),
        ("http://pool-2:8000", True),
    ]


@pytest.mark.anyio
async def test_batch_registration_service_marks_task_failed_when_proxy_pool_exhausts(db_factory, temp_db):
    from src.application.batch_registration_service import BatchRegistrationService

    task_ids = []
    for idx in range(2):
        task = crud.create_registration_task(temp_db, task_uuid=f"proxy-exhaust-task-{idx}")
        task_ids.append(task.task_uuid)

    class ExhaustingPool:
        def __init__(self):
            self._leased = False

        def lease(self):
            if self._leased:
                raise RuntimeError("batch proxy pool exhausted: batch-exhaust")
            self._leased = True
            return ResolvedProxyCandidate(proxy_url="http://pool-only:8000", source="dynamic_pool")

        def complete(self, candidate, *, success):
            return None

    async def fake_runner(task_uuid, *args, **kwargs):
        runs = RegistrationRunsService(temp_db)
        run = runs.create_run(task_uuid=task_uuid, batch_id="batch-exhaust", trigger_source="batch")
        crud.update_registration_task(
            temp_db,
            task_uuid,
            status="completed",
            pipeline_status="completed",
            completed_at=utc_now_naive(),
        )
        runs.mark_completed(run.id)

    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={},
        batch_proxy_pools_store={"batch-exhaust": ExhaustingPool()},
        registration_task_runner=fake_runner,
    )

    summary = await service.run_batch_pipeline(
        batch_id="batch-exhaust",
        task_uuids=task_ids,
        email_service_type="tempmail",
        proxy=None,
        use_proxy=True,
        email_service_config=None,
        email_service_id=None,
        interval_min=0,
        interval_max=0,
        concurrency=1,
    )

    failed_task = crud.get_registration_task(temp_db, task_ids[1])
    assert summary.success == 1
    assert summary.failed == 1
    assert failed_task is not None
    assert failed_task.status == "failed"
    assert "proxy pool exhausted" in (failed_task.error_message or "")


@pytest.mark.anyio
async def test_batch_registration_service_marks_task_failed_when_use_proxy_enabled_but_no_proxy_available(db_factory, temp_db):
    from src.application.batch_registration_service import BatchRegistrationService

    task_ids = []
    for idx in range(2):
        task = crud.create_registration_task(temp_db, task_uuid=f"proxy-required-task-{idx}")
        task_ids.append(task.task_uuid)

    async def fake_runner(task_uuid, *args, **kwargs):
        raise AssertionError("runner should not be called when no proxy candidates are available")

    class FakeDispatcher:
        def resolve_single_candidates(self, task_group, explicit_proxy, overrides, *, use_proxy):
            assert task_group == "batch_registration"
            assert explicit_proxy is None
            assert use_proxy is True
            return []

    task_manager = FakeTaskManager()
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        batch_tasks_store={},
        registration_task_runner=fake_runner,
        proxy_dispatcher=FakeDispatcher(),
    )

    summary = await service.run_batch_parallel(
        batch_id="batch-proxy-required",
        task_uuids=task_ids,
        email_service_type="tempmail",
        proxy=None,
        use_proxy=True,
        email_service_config=None,
        email_service_id=None,
        concurrency=1,
        proxy_task_group="batch_registration",
        proxy_overrides={},
    )

    failed_tasks = [crud.get_registration_task(temp_db, task_uuid) for task_uuid in task_ids]
    assert summary.failed == 2
    assert all(task is not None and task.status == "failed" for task in failed_tasks)
    assert all("代理已启用" in (task.error_message or "") for task in failed_tasks if task is not None)
    assert any("代理已启用" in line for line in task_manager.get_batch_logs("batch-proxy-required"))
