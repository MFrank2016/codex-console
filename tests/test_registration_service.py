import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import sessionmaker

from src.application.proxy_dispatch_service import ResolvedProxyCandidate
from src.core.registration_job import RegistrationJobResult
from src.database import crud
from src.database.models import Base, RegistrationRun
from src.database.session import DatabaseSessionManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "registration-service.db"
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




def _load_run_and_events(session, task_uuid: str):
    from src.application.registration_runs_service import RegistrationRunsService

    runs_service = RegistrationRunsService(session)
    run = runs_service.get_run_by_task_uuid(task_uuid)
    assert run is not None
    events = runs_service.get_events(run.id)
    return run, events

class FakeTaskManager:
    def __init__(self):
        self._task_status = {}
        self._task_steps = {}
        self._task_progress = {}
        self._task_cancelled = {}
        self._logs = {}
        self._stream_events = {}
        self._closed_streams = []
        self._loop = None

    def set_loop(self, loop):
        self._loop = loop

    def get_loop(self):
        return self._loop

    def is_cancelled(self, task_uuid):
        return self._task_cancelled.get(task_uuid, False)

    def update_status(self, task_uuid, status, **kwargs):
        self._task_status.setdefault(task_uuid, {}).update({"status": status, **kwargs})

    def get_status(self, task_uuid):
        return self._task_status.get(task_uuid)

    def close_task_stream(self, task_uuid, final_status):
        self._closed_streams.append((task_uuid, final_status))

    def add_log(self, task_uuid, message):
        self._logs.setdefault(task_uuid, []).append(message)
        self._stream_events.setdefault(task_uuid, []).append(
            {
                "kind": "log_appended",
                "payload": {
                    "entry": {
                        "message": message,
                        "stream": f"task:{task_uuid}",
                        "seq": None,
                    }
                },
            }
        )

    def get_logs(self, task_uuid):
        return list(self._logs.get(task_uuid, []))

    def get_stream_events(self, task_uuid):
        return list(self._stream_events.get(task_uuid, []))

    def create_log_callback(self, task_uuid, prefix="", batch_id=""):
        def _callback(message: str):
            full = f"{prefix} {message}" if prefix else message
            self.add_log(task_uuid, full)

        return _callback

    def clear_task_steps(self, task_uuid):
        self._task_steps.pop(task_uuid, None)
        self._task_progress.pop(task_uuid, None)

    def set_task_steps(self, task_uuid, steps, *, task_progress=None):
        self._task_steps[task_uuid] = list(steps or [])
        if task_progress is None:
            self._task_progress.pop(task_uuid, None)
        else:
            self._task_progress[task_uuid] = dict(task_progress)

    @property
    def executor(self):
        return None


def test_registration_service_emits_step_snapshot_and_closes_stream(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-step-stream", pipeline_key="codexgen_pipeline")
    task_manager = FakeTaskManager()

    def fake_job_runner(**kwargs):
        callback = kwargs.get("task_step_callback")
        assert callable(callback)
        callback(
            {
                "current_step": {"step_key": "create_email", "status": "running"},
                "steps": [{"step_key": "create_email", "status": "running"}],
                "task_progress": {"step_index": 1, "total_steps": 2, "progress_percent": 50},
            }
        )
        callback(
            {
                "current_step": {"step_key": "create_email", "status": "completed"},
                "steps": [{"step_key": "create_email", "status": "completed"}],
                "task_progress": {"step_index": 1, "total_steps": 2, "progress_percent": 50},
            }
        )
        return RegistrationJobResult(
            success=True,
            account_id=101,
            email="success@example.com",
            result_payload={"success": True, "email": "success@example.com"},
        )

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    service.run_single_task_sync(
        task_uuid="task-step-stream",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        pipeline_key="codexgen_pipeline",
    )

    assert task_manager._task_steps["task-step-stream"][-1]["status"] == "completed"
    assert task_manager._task_progress["task-step-stream"] == {
        "step_index": 1,
        "total_steps": 2,
        "progress_percent": 50,
    }
    assert task_manager.get_status("task-step-stream")["current_step_key"] == "create_email"
    assert task_manager._closed_streams == [("task-step-stream", "completed")]


def test_registration_service_step_callback_does_not_override_terminal_status(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-terminal-step", pipeline_key="codexgen_pipeline")
    task_manager = FakeTaskManager()

    def fake_job_runner(**kwargs):
        callback = kwargs.get("task_step_callback")
        assert callable(callback)

        # 模拟：任务已进入 terminal 状态，但仍有 step callback（乱序/延迟）到达
        task_manager.update_status(kwargs["task_uuid"], "failed", error="boom")
        callback(
            {
                "current_step": {"step_key": "create_email", "status": "running"},
                "steps": [{"step_key": "create_email", "status": "running"}],
                "task_progress": {"step_index": 1, "total_steps": 3, "progress_percent": 33},
            }
        )
        assert task_manager.get_status(kwargs["task_uuid"])["status"] == "failed"
        assert task_manager.get_status(kwargs["task_uuid"])["current_step_key"] == "create_email"

        return RegistrationJobResult(
            success=False,
            email="failed@example.com",
            error_message="boom",
        )

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    service.run_single_task_sync(
        task_uuid="task-terminal-step",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        pipeline_key="codexgen_pipeline",
    )

    assert task_manager.get_status("task-terminal-step")["status"] == "failed"
    assert task_manager.get_status("task-terminal-step")["current_step_key"] == "create_email"
    assert task_manager._task_progress["task-terminal-step"] == {
        "step_index": 1,
        "total_steps": 3,
        "progress_percent": 33,
    }


def test_registration_service_creates_run_records_and_terminal_status(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-1", pipeline_key="codexgen_pipeline")
    task_manager = FakeTaskManager()

    def fake_job_runner(**kwargs):
        assert kwargs["pipeline_key"] == "codexgen_pipeline"
        kwargs["callback_logger"]("job-started")
        return RegistrationJobResult(
            success=True,
            account_id=101,
            email="success@example.com",
            result_payload={"success": True, "email": "success@example.com"},
        )

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    result = service.run_single_task_sync(
        task_uuid="task-1",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        pipeline_key="codexgen_pipeline",
    )

    assert result.run.task_uuid == "task-1"
    assert result.run.status == "completed"
    assert result.run.started_at is not None
    assert result.run.completed_at is not None
    assert [event.message for event in result.events] == ["queued", "started", "running", "completed"]
    assert task_manager.get_status("task-1")["status"] == "completed"
    assert "job-started" in task_manager.get_logs("task-1")


def test_registration_service_default_run_persistence_survives_fresh_session(db_factory, temp_db):
    from src.application.registration_runs_service import RegistrationRunsService
    from src.application.registration_service import RegistrationService

    task_uuid = "task-fresh-session-run-persistence"
    crud.create_registration_task(temp_db, task_uuid=task_uuid, pipeline_key="codexgen_pipeline")
    task_manager = FakeTaskManager()

    def fake_job_runner(**kwargs):
        return RegistrationJobResult(
            success=True,
            account_id=303,
            email="fresh-session@example.com",
            result_payload={"success": True, "email": "fresh-session@example.com"},
        )

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )
    service.run_single_task_sync(
        task_uuid=task_uuid,
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        pipeline_key="codexgen_pipeline",
    )

    fresh_session = sessionmaker(bind=temp_db.get_bind())()
    try:
        runs_service = RegistrationRunsService(fresh_session)
        run = runs_service.get_run_by_task_uuid(task_uuid)
        assert run is not None
        assert run.status == "completed"
        assert run.completed_at is not None
        events = runs_service.get_events(run.id)
        assert any(event.message == "completed" for event in events)
    finally:
        fresh_session.close()



def test_registration_service_commits_queued_checkpoint_before_job_runner(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    task_uuid = "task-queued-before-job-runner"
    crud.create_registration_task(temp_db, task_uuid=task_uuid, pipeline_key="codexgen_pipeline")
    task_manager = FakeTaskManager()
    observed = {}

    def fake_job_runner(**kwargs):
        fresh_session = sessionmaker(bind=temp_db.get_bind())()
        try:
            run, events = _load_run_and_events(fresh_session, task_uuid)
            observed["status"] = run.status
            observed["events"] = [event.message for event in events]
        finally:
            fresh_session.close()

        return RegistrationJobResult(
            success=True,
            account_id=404,
            email="queued-checkpoint@example.com",
            result_payload={"success": True, "email": "queued-checkpoint@example.com"},
        )

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    service.run_single_task_sync(
        task_uuid=task_uuid,
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        pipeline_key="codexgen_pipeline",
    )

    assert observed["status"] == "running"
    assert observed["events"][0] == "queued"
    assert observed["events"][:3] == ["queued", "started", "running"]



def test_registration_service_persists_run_events_in_owner_defined_order(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    task_uuid = "task-owner-event-order"
    crud.create_registration_task(temp_db, task_uuid=task_uuid, pipeline_key="codexgen_pipeline")
    task_manager = FakeTaskManager()

    def fake_job_runner(**kwargs):
        return RegistrationJobResult(
            success=True,
            account_id=505,
            email="owner-order@example.com",
            result_payload={"success": True, "email": "owner-order@example.com"},
        )

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    result = service.run_single_task_sync(
        task_uuid=task_uuid,
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        pipeline_key="codexgen_pipeline",
    )

    assert [event.message for event in result.events] == ["queued", "started", "running", "completed"]



def test_registration_service_marks_failed_once_when_job_runner_raises(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    task_uuid = "task-job-runner-raises"
    crud.create_registration_task(temp_db, task_uuid=task_uuid, pipeline_key="codexgen_pipeline")
    task_manager = FakeTaskManager()

    def fake_job_runner(**kwargs):
        raise RuntimeError("job-runner-boom")

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    result = service.run_single_task_sync(
        task_uuid=task_uuid,
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        pipeline_key="codexgen_pipeline",
    )

    fresh_session = sessionmaker(bind=temp_db.get_bind())()
    try:
        run, events = _load_run_and_events(fresh_session, task_uuid)
        run_count = fresh_session.query(RegistrationRun).filter(RegistrationRun.task_uuid == task_uuid).count()
    finally:
        fresh_session.close()

    assert run_count == 1
    assert result.task is not None
    assert result.task.status == "failed"
    assert result.run is not None
    assert result.run.status == "failed"
    assert [event.message for event in events] == ["queued", "started", "running", "failed"]
    assert [event.message for event in events].count("failed") == 1
    assert task_manager.get_status(task_uuid)["status"] == "failed"
    assert task_manager._closed_streams == [(task_uuid, "failed")]


def test_registration_service_keeps_legacy_registration_task_in_sync(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-2", pipeline_key="current_pipeline")
    task_manager = FakeTaskManager()

    def fake_job_runner(**kwargs):
        return RegistrationJobResult(
            success=False,
            email="failed@example.com",
            error_message="boom",
        )

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    result = service.run_single_task_sync(
        task_uuid="task-2",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
    )

    persisted = crud.get_registration_task(temp_db, "task-2")
    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.pipeline_status == "failed"
    assert persisted.email_address == "failed@example.com"
    assert persisted.error_message == "boom"
    assert result.task.status == "failed"
    assert result.run.status == "failed"


@pytest.mark.anyio
async def test_registration_service_async_run_initializes_pending_status_and_queue_log(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-3")
    task_manager = FakeTaskManager()
    task_manager.set_loop(asyncio.get_running_loop())

    def fake_sync_runner(**kwargs):
        crud.update_registration_task(
            temp_db,
            kwargs["task_uuid"],
            status="completed",
            pipeline_status="completed",
            completed_at=kwargs["utc_now_provider"](),
        )
        return kwargs["service"].build_result_for_task(kwargs["task_uuid"])

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        sync_runner=fake_sync_runner,
    )

    await service.run_single_task(
        task_uuid="task-3",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
    )

    assert task_manager.get_status("task-3")["status"] == "completed"
    assert any("已加入队列" in line for line in task_manager.get_logs("task-3"))


@pytest.mark.anyio
async def test_registration_service_async_run_uses_executor_for_default_sync_runner(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-executor", pipeline_key="current_pipeline")

    class FakeLoop:
        def __init__(self):
            self.calls = []

        async def run_in_executor(self, executor, fn):
            self.calls.append(executor)
            return fn()

    class ExecutorTaskManager(FakeTaskManager):
        def __init__(self, loop):
            super().__init__()
            self._loop = loop
            self._executor = object()

        @property
        def executor(self):
            return self._executor

    fake_loop = FakeLoop()
    task_manager = ExecutorTaskManager(fake_loop)

    def fake_job_runner(**kwargs):
        return RegistrationJobResult(
            success=True,
            account_id=202,
            email="executor@example.com",
            result_payload={"success": True, "email": "executor@example.com"},
        )

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    result = await service.run_single_task(
        task_uuid="task-executor",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        pipeline_key="current_pipeline",
    )

    assert len(fake_loop.calls) == 1
    assert result.task is not None
    assert result.task.status == "completed"


def test_registration_service_retries_proxy_related_failure_with_next_candidate(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-proxy-retry", pipeline_key="current_pipeline")
    task_manager = FakeTaskManager()
    attempts: list[str | None] = []
    used_proxy_ids: list[int | None] = []

    class FakeDispatcher:
        def resolve_single_candidates(self, task_group, explicit_proxy, overrides):
            assert task_group == "single_registration"
            assert explicit_proxy is None
            assert overrides == {"dynamic_request_count": 2}
            return [
                ResolvedProxyCandidate(proxy_url="http://dynamic-1:8000", source="dynamic_pool"),
                ResolvedProxyCandidate(proxy_url="http://proxy-list-1:8000", source="proxy_list", proxy_id=17),
            ]

        def is_proxy_related_failure(self, error):
            return "timeout" in str(error).lower()

    def fake_job_runner(**kwargs):
        attempts.append(kwargs["proxy"])
        if len(attempts) == 1:
            return RegistrationJobResult(success=False, error_message="connection timeout")
        return RegistrationJobResult(
            success=True,
            email="recovered@example.com",
            account_id=202,
            result_payload={"success": True, "email": "recovered@example.com"},
        )

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
        proxy_dispatcher=FakeDispatcher(),
        proxy_usage_updater=lambda db, proxy_id: used_proxy_ids.append(proxy_id),
    )

    result = service.run_single_task_sync(
        task_uuid="task-proxy-retry",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        use_proxy=True,
        proxy_task_group="single_registration",
        proxy_overrides={"dynamic_request_count": 2},
    )

    persisted = crud.get_registration_task(temp_db, "task-proxy-retry")
    assert attempts == ["http://dynamic-1:8000", "http://proxy-list-1:8000"]
    assert used_proxy_ids == [17]


def test_registration_service_passes_registration_mode_and_batch_id_to_job_runner(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-registration-mode", pipeline_key="current_pipeline")
    task_manager = FakeTaskManager()
    captured: dict[str, object] = {}

    def fake_job_runner(**kwargs):
        captured.update(kwargs)
        return RegistrationJobResult(success=False, error_message="boom")

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    service.run_single_task_sync(
        task_uuid="task-registration-mode",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        batch_id="batch-outlook-1",
        registration_mode="outlook_batch",
        pipeline_key="current_pipeline",
    )

    assert captured["batch_id"] == "batch-outlook-1"
    assert captured["registration_mode"] == "outlook_batch"


def test_registration_service_uses_persisted_email_service_id_for_outlook_tasks(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(
        temp_db,
        task_uuid="task-outlook-persisted-service-id",
        email_service_id=42,
        pipeline_key="current_pipeline",
    )
    task_manager = FakeTaskManager()
    captured: dict[str, object] = {}

    def fake_job_runner(**kwargs):
        captured.update(kwargs)
        return RegistrationJobResult(success=False, error_message="boom")

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
    )

    service.run_single_task_sync(
        task_uuid="task-outlook-persisted-service-id",
        email_service_type="outlook",
        proxy="http://proxy-for-outlook:8000",
        email_service_config=None,
        email_service_id=None,
        use_proxy=True,
        proxy_task_group="outlook_batch",
    )

    assert captured["email_service_id"] == 42
    assert captured["proxy"] == "http://proxy-for-outlook:8000"


def test_registration_service_does_not_retry_non_proxy_failure(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-non-proxy-fail", pipeline_key="current_pipeline")
    task_manager = FakeTaskManager()
    attempts: list[str | None] = []

    class FakeDispatcher:
        def resolve_single_candidates(self, task_group, explicit_proxy, overrides):
            return [
                ResolvedProxyCandidate(proxy_url="http://dynamic-1:8000", source="dynamic_pool"),
                ResolvedProxyCandidate(proxy_url="http://proxy-list-1:8000", source="proxy_list"),
            ]

        def is_proxy_related_failure(self, error):
            return "timeout" in str(error).lower()

    def fake_job_runner(**kwargs):
        attempts.append(kwargs["proxy"])
        return RegistrationJobResult(success=False, error_message="invalid password")

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=fake_job_runner,
        proxy_dispatcher=FakeDispatcher(),
    )

    result = service.run_single_task_sync(
        task_uuid="task-non-proxy-fail",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        use_proxy=True,
        proxy_task_group="single_registration",
        proxy_overrides={},
    )

    assert attempts == ["http://dynamic-1:8000"]
    assert result.run.status == "failed"


def test_registration_service_marks_task_failed_after_creation_when_use_proxy_enabled_but_no_proxy_available(db_factory, temp_db):
    from src.application.registration_service import RegistrationService

    crud.create_registration_task(temp_db, task_uuid="task-proxy-required", pipeline_key="current_pipeline")
    task_manager = FakeTaskManager()

    class FakeDispatcher:
        def resolve_single_candidates(self, task_group, explicit_proxy, overrides, *, use_proxy):
            assert task_group == "single_registration"
            assert explicit_proxy is None
            assert use_proxy is True
            return []

        def is_proxy_related_failure(self, error):
            return False

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=task_manager,
        job_runner=lambda **kwargs: RegistrationJobResult(success=True, email="unexpected@example.com"),
        proxy_dispatcher=FakeDispatcher(),
    )

    result = service.run_single_task_sync(
        task_uuid="task-proxy-required",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
        use_proxy=True,
        proxy_task_group="single_registration",
        proxy_overrides={},
    )

    stream_events = task_manager.get_stream_events("task-proxy-required")
    assert result.task is not None
    assert result.task.status == "failed"
    assert "代理已启用" in (result.task.error_message or "")
    assert any("代理已启用" in item["payload"]["entry"]["message"] for item in stream_events)
