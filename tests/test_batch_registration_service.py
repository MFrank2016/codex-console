import asyncio
from contextlib import contextmanager
from datetime import datetime

import pytest

from src.application.proxy_dispatch_service import ResolvedProxyCandidate
from src.application.registration_runs_service import RegistrationRunsService
from src.core.time import utc_now_naive
from src.database import crud
from src.database.models import Base
from src.database.session import DatabaseSessionManager


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


class FakeTaskManager:
    def __init__(self):
        self._batch_status = {}
        self._batch_logs = {}
        self._task_status = {}
        self._task_logs = {}
        self._cancelled = set()
        self._closed_streams = []
        self._loop = None

    def set_loop(self, loop):
        self._loop = loop

    def get_loop(self):
        return self._loop

    def init_batch(self, batch_id, total, **kwargs):
        self._batch_status[batch_id] = {
            "status": "running",
            "total": total,
            "completed": 0,
            "success": 0,
            "failed": 0,
            "current_index": 0,
            "finished": False,
            **kwargs,
        }

    def update_batch_status(self, batch_id, **kwargs):
        self._batch_status.setdefault(batch_id, {}).update(kwargs)

    def get_batch_status(self, batch_id):
        return self._batch_status.get(batch_id)

    def add_batch_log(self, batch_id, message):
        self._batch_logs.setdefault(batch_id, []).append(message)

    def get_batch_logs(self, batch_id):
        return list(self._batch_logs.get(batch_id, []))

    def update_status(self, task_uuid, status, **kwargs):
        self._task_status.setdefault(task_uuid, {}).update({"status": status, **kwargs})

    def add_log(self, task_uuid, message):
        self._task_logs.setdefault(task_uuid, []).append(message)

    def get_logs(self, task_uuid):
        return list(self._task_logs.get(task_uuid, []))

    def clear_task_steps(self, task_uuid):
        return None

    def close_task_stream(self, task_uuid, final_status):
        return None

    def is_batch_cancelled(self, batch_id):
        return batch_id in self._cancelled or self._batch_status.get(batch_id, {}).get("cancelled", False)

    def cancel_batch(self, batch_id):
        self._cancelled.add(batch_id)
        self._batch_status.setdefault(batch_id, {})["cancelled"] = True

    def close_batch_stream(self, batch_id, final_status):
        self._closed_streams.append((batch_id, final_status))


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
