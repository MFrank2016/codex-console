import asyncio
from contextlib import contextmanager
from datetime import datetime

import pytest

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
        self._cancelled = set()
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

    def is_batch_cancelled(self, batch_id):
        return batch_id in self._cancelled or self._batch_status.get(batch_id, {}).get("cancelled", False)

    def cancel_batch(self, batch_id):
        self._cancelled.add(batch_id)
        self._batch_status.setdefault(batch_id, {})["cancelled"] = True


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

    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
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
