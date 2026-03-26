import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Event

import pytest
from fastapi.testclient import TestClient

from src.core.time import utc_now_naive
from src.database import crud
from src.database import session as session_module
from src.database.models import Base, ScheduledRun
from src.database.session import DatabaseSessionManager
from src.scheduler import engine as engine_module
from src.scheduler import run_logger
from src.scheduler.engine import SchedulerDispatchError, SchedulerEngine, SchedulerPlanConflictError
from src.web.realtime_streams import run_stream_id
from src.web.task_manager import reset_state_for_tests, task_manager
from src.web.app import create_app


@dataclass
class FakePlan:
    id: int
    cpa_service_id: int = 1
    task_type: str = "cpa_cleanup"


class FakeRepo:
    def __init__(self, due_plan_ids=None, due_plans=None):
        if due_plans is None:
            due_plans = [FakePlan(id=plan_id, cpa_service_id=plan_id) for plan_id in (due_plan_ids or [])]
        self._due_plans = list(due_plans)
        self.created_runs = []

    def get_due_enabled_plans(self, now):
        return list(self._due_plans)

    def create_skipped_run(self, plan_id, trigger_source, reason):
        self.created_runs.append((plan_id, trigger_source, "skipped", reason))


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler-engine.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)
    manager.migrate_tables()
    monkeypatch.setattr(session_module, "_db_manager", manager)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_realtime_state():
    reset_state_for_tests()
    yield
    reset_state_for_tests()


def _get_run_stream_events(run_id: int) -> list[dict]:
    return task_manager.get_stream_events_after(run_stream_id(run_id), after_seq=0)


def _create_plan(temp_db, *, task_type: str = "cpa_cleanup", due: bool = True):
    service = crud.create_cpa_service(
        temp_db,
        name=f"svc-{task_type}",
        api_url="https://cpa.example.com/api",
        api_token="token",
    )
    next_run_at = utc_now_naive() - timedelta(minutes=5) if due else utc_now_naive() + timedelta(hours=1)
    return crud.create_scheduled_plan(
        temp_db,
        name=f"plan-{task_type}",
        task_type=task_type,
        cpa_service_id=service.id,
        trigger_type="interval",
        interval_value=1,
        interval_unit="hours",
        config={"max_consecutive_failures": 3},
        enabled=True,
        next_run_at=next_run_at,
    )


def test_scheduler_engine_skips_plan_when_same_plan_is_running(monkeypatch):
    repo = FakeRepo(due_plan_ids=[1])
    engine = SchedulerEngine(repo=repo)
    engine._plan_locks.add(1)

    engine.dispatch_due_plans_once()

    assert repo.created_runs == [(1, "scheduled", "skipped", "plan already running")]


def test_scheduler_engine_start_is_idempotent():
    engine = SchedulerEngine(repo=FakeRepo())
    assert engine.start() is True
    assert engine.start() is False


def test_scheduler_engine_skips_plan_when_same_cpa_is_locked():
    repo = FakeRepo(due_plans=[FakePlan(id=2, cpa_service_id=8)])
    engine = SchedulerEngine(repo=repo)
    engine._cpa_locks.add(8)

    engine.dispatch_due_plans_once()

    assert repo.created_runs == [(2, "scheduled", "skipped", "cpa already busy")]


def test_scheduler_engine_dispatches_due_plan_to_matching_runner_and_records_run(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=True)
    calls = []

    def _cleanup_runner(*, plan_id: int, run_id: int):
        calls.append((plan_id, run_id))
        with session_module.get_db() as db:
            crud.finish_scheduled_run(db, run_id=run_id, status="success", summary={"dispatched": True})

    engine = SchedulerEngine(
        runner_map={"cpa_cleanup": _cleanup_runner},
        worker_spawner=lambda fn, _name: fn(),
    )

    engine.dispatch_due_plans_once()

    assert calls
    assert calls[0][0] == plan.id

    temp_db.expire_all()
    runs = temp_db.query(ScheduledRun).filter(ScheduledRun.plan_id == plan.id).all()
    assert len(runs) == 1
    assert runs[0].trigger_source == "scheduled"
    assert runs[0].status == "success"
    assert runs[0].summary == {"dispatched": True}

    persisted_plan = crud.get_scheduled_plan_by_id(temp_db, plan.id)
    assert persisted_plan is not None
    assert persisted_plan.last_run_status == "success"
    assert persisted_plan.last_run_started_at is not None
    assert persisted_plan.last_run_finished_at is not None
    assert persisted_plan.next_run_at is not None
    assert persisted_plan.next_run_at > utc_now_naive() - timedelta(minutes=1)


def test_scheduler_engine_manual_trigger_creates_run_and_dispatches_runner(temp_db):
    plan = _create_plan(temp_db, task_type="account_refresh", due=False)
    calls = []

    def _refresh_runner(*, plan_id: int, run_id: int):
        calls.append((plan_id, run_id))
        with session_module.get_db() as db:
            crud.finish_scheduled_run(db, run_id=run_id, status="success", summary={"manual": True})

    engine = SchedulerEngine(
        runner_map={"account_refresh": _refresh_runner},
        worker_spawner=lambda fn, _name: fn(),
    )

    run_id = engine.trigger_plan_now(plan.id)

    assert isinstance(run_id, int)
    assert calls == [(plan.id, run_id)]

    temp_db.expire_all()
    run = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
    assert run is not None
    assert run.trigger_source == "manual"
    assert run.status == "success"
    assert run.summary == {"manual": True}


def test_scheduler_engine_request_run_stop_marks_running_run(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    engine = SchedulerEngine(
        runner_map={"cpa_cleanup": lambda **kwargs: None},
        worker_spawner=lambda _fn, _name: None,
    )

    run_id = engine.trigger_plan_now(plan.id)
    updated = engine.request_run_stop(run_id)

    assert updated is True
    assert engine.is_run_stop_requested(run_id) is True
    temp_db.expire_all()
    run = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
    assert run is not None
    assert run.stop_requested_at is not None

    events = _get_run_stream_events(run_id)
    assert [event["kind"] for event in events] == ["run_status_changed", "run_status_changed"]
    assert [event["payload"]["status"] for event in events] == ["running", "stopping"]
    assert events[-1]["payload"]["plan_name"] == plan.name
    assert events[-1]["payload"]["task_type"] == "cpa_cleanup"
    assert events[-1]["payload"]["is_running"] is True
    assert events[-1]["payload"]["can_stop"] is False
    assert events[-1]["payload"]["stop_requested_at"] is not None

    snapshot = task_manager.build_run_stream_snapshot(run_id)
    run_snapshot = snapshot["payload"]["run"]
    assert run_snapshot["id"] == run_id
    assert run_snapshot["plan_id"] == plan.id
    assert run_snapshot["plan_name"] == plan.name
    assert run_snapshot["task_type"] == "cpa_cleanup"
    assert run_snapshot["status"] == "stopping"
    assert run_snapshot["started_at"] is not None
    assert run_snapshot["finished_at"] is None
    assert run_snapshot["stop_requested_at"] is not None
    assert run_snapshot["is_running"] is True
    assert run_snapshot["can_stop"] is False
    assert run_snapshot["last_log_at"] is None
    assert run_snapshot["log_version"] == 0
    assert run_snapshot["error_message"] is None


def test_scheduler_module_stop_helpers_work_without_engine_instance(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    with session_module.get_db() as db:
        run = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="running")

    assert engine_module.is_run_stop_requested(run.id) is False
    assert engine_module.request_run_stop(run.id, requested_by="tester", reason="stop now") is True
    assert engine_module.is_run_stop_requested(run.id) is True


def test_scheduler_engine_request_run_stop_emits_stopping_only_once(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    engine = SchedulerEngine(
        runner_map={"cpa_cleanup": lambda **kwargs: None},
        worker_spawner=lambda _fn, _name: None,
    )

    run_id = engine.trigger_plan_now(plan.id)

    assert engine.request_run_stop(run_id, requested_by="tester", reason="first") is True
    assert engine.request_run_stop(run_id, requested_by="tester", reason="second") is True

    status_events = [
        event["payload"]["status"]
        for event in _get_run_stream_events(run_id)
        if event["kind"] == "run_status_changed"
    ]
    assert status_events == ["running", "stopping"]


def test_scheduler_engine_request_run_stop_rejects_finished_or_missing_runs(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    with session_module.get_db() as db:
        run = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="success")
        crud.finish_scheduled_run(db, run_id=run.id, status="success")

    engine = SchedulerEngine()
    assert engine.request_run_stop(run.id) is False
    assert engine.request_run_stop(run.id + 9999) is False
    assert engine.is_run_stop_requested(run.id) is False
    assert engine.is_run_stop_requested(run.id + 9999) is False


def test_scheduler_engine_request_run_stop_rejects_non_running_states(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    with session_module.get_db() as db:
        skipped = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="skipped")
        failed = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="failed")
        cancelled = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="cancelled")
        skipped_id = skipped.id
        failed_id = failed.id
        cancelled_id = cancelled.id

    engine = SchedulerEngine()
    assert engine.request_run_stop(skipped_id) is False
    assert engine.request_run_stop(failed_id) is False
    assert engine.request_run_stop(cancelled_id) is False
    assert engine.is_run_stop_requested(skipped_id) is False
    assert engine.is_run_stop_requested(failed_id) is False
    assert engine.is_run_stop_requested(cancelled_id) is False


def test_scheduler_engine_dispatch_persists_task_type_on_created_run(temp_db):
    plan = _create_plan(temp_db, task_type="account_refresh", due=False)

    engine = SchedulerEngine(
        runner_map={"account_refresh": lambda **kwargs: None},
        worker_spawner=lambda fn, _name: fn(),
    )

    run_id = engine.trigger_plan_now(plan.id)

    temp_db.expire_all()
    run = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
    assert run is not None
    assert run.task_type == "account_refresh"


def test_scheduler_engine_manual_trigger_rejects_running_plan(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    engine = SchedulerEngine()
    engine._plan_locks.add(plan.id)

    with pytest.raises(SchedulerPlanConflictError):
        engine.trigger_plan_now(plan.id)

    temp_db.expire_all()
    runs = temp_db.query(ScheduledRun).filter(ScheduledRun.plan_id == plan.id).all()
    assert len(runs) == 1
    assert runs[0].status == "skipped"
    assert runs[0].trigger_source == "manual"


def test_scheduler_engine_manual_trigger_raises_dispatch_error_on_internal_failure(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)

    engine = SchedulerEngine(
        runner_map={"cpa_cleanup": lambda **kwargs: None},
        worker_spawner=lambda _fn, _name: (_ for _ in ()).throw(RuntimeError("spawn failed")),
    )

    with pytest.raises(SchedulerDispatchError):
        engine.trigger_plan_now(plan.id)

    temp_db.expire_all()
    runs = temp_db.query(ScheduledRun).filter(ScheduledRun.plan_id == plan.id).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"


def test_scheduler_engine_dispatch_failure_does_not_create_extra_skipped_run(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=True)
    engine = SchedulerEngine(
        runner_map={"cpa_cleanup": lambda **kwargs: None},
        worker_spawner=lambda _fn, _name: (_ for _ in ()).throw(RuntimeError("spawn failed")),
    )

    engine.dispatch_due_plans_once()

    temp_db.expire_all()
    runs = (
        temp_db.query(ScheduledRun)
        .filter(ScheduledRun.plan_id == plan.id)
        .order_by(ScheduledRun.id.asc())
        .all()
    )
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].trigger_source == "scheduled"


def test_scheduler_engine_runner_cancellation_marks_run_cancelled_and_updates_plan(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    allow_raise = Event()

    def _cleanup_runner(*, plan_id: int, run_id: int):
        allow_raise.wait(timeout=1.0)
        raise engine_module.ScheduledRunCancelledError("stop requested")

    engine = SchedulerEngine(runner_map={"cpa_cleanup": _cleanup_runner})

    run_id = engine.trigger_plan_now(plan.id)
    assert engine.request_run_stop(run_id) is True
    allow_raise.set()

    deadline = utc_now_naive() + timedelta(seconds=2)
    run = None
    persisted_plan = None
    while utc_now_naive() < deadline:
        temp_db.expire_all()
        run = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
        persisted_plan = crud.get_scheduled_plan_by_id(temp_db, plan.id)
        if (
            run is not None
            and run.status == "cancelled"
            and persisted_plan is not None
            and persisted_plan.last_run_status == "cancelled"
        ):
            break
    assert run is not None
    assert run.status == "cancelled"
    assert run.error_message == "user requested stop"
    assert run.finished_at is not None

    assert persisted_plan is not None
    assert persisted_plan.last_run_status == "cancelled"
    assert persisted_plan.last_run_finished_at is not None


def test_scheduler_engine_runner_cancellation_overrides_failed_status_from_runner(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)

    def _cleanup_runner(*, plan_id: int, run_id: int):
        engine_module.request_run_stop(run_id, requested_by="runner", reason="stop requested")
        with session_module.get_db() as db:
            crud.finish_scheduled_run(db, run_id=run_id, status="failed", error_message="runner generic fail")
        raise engine_module.ScheduledRunCancelledError("stop requested")

    engine = SchedulerEngine(
        runner_map={"cpa_cleanup": _cleanup_runner},
        worker_spawner=lambda fn, _name: fn(),
    )

    run_id = engine.trigger_plan_now(plan.id)

    temp_db.expire_all()
    run = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
    assert run is not None
    assert run.status == "cancelled"
    assert run.error_message == "user requested stop"

    persisted_plan = crud.get_scheduled_plan_by_id(temp_db, plan.id)
    assert persisted_plan is not None
    assert persisted_plan.last_run_status == "cancelled"


def test_scheduler_engine_runner_cancellation_without_stop_request_is_not_user_cancelled(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)

    def _cleanup_runner(*, plan_id: int, run_id: int):
        raise engine_module.ScheduledRunCancelledError("stop requested")

    engine = SchedulerEngine(
        runner_map={"cpa_cleanup": _cleanup_runner},
        worker_spawner=lambda fn, _name: fn(),
    )

    run_id = engine.trigger_plan_now(plan.id)

    temp_db.expire_all()
    run = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
    assert run is not None
    assert run.status == "failed"
    assert run.error_message == "stop requested"

    persisted_plan = crud.get_scheduled_plan_by_id(temp_db, plan.id)
    assert persisted_plan is not None
    assert persisted_plan.last_run_status == "failed"


def test_run_logger_append_log_uses_logged_at_for_last_log_timestamp(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    with session_module.get_db() as db:
        run = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="running")
        run_id = run.id

    logged_at = datetime(2025, 1, 2, 3, 4, 5, 123000)
    assert run_logger.append_run_log(run_id, "hello", logged_at=logged_at) is True

    temp_db.expire_all()
    persisted = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
    assert persisted is not None
    assert persisted.logs == "2025-01-02 03:04:05.123 [INFO] hello"
    assert persisted.last_log_at == logged_at


def test_run_logger_append_log_supports_custom_level(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    with session_module.get_db() as db:
        run = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="running")
        run_id = run.id

    logged_at = datetime(2025, 1, 2, 3, 4, 5, 123000)
    assert run_logger.append_run_log(run_id, "boom", level="ERROR", logged_at=logged_at) is True

    temp_db.expire_all()
    persisted = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
    assert persisted is not None
    assert persisted.logs == "2025-01-02 03:04:05.123 [ERROR] boom"


def test_run_logger_append_log_normalizes_level_to_supported_uppercase(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    with session_module.get_db() as db:
        run = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="running")
        run_id = run.id

    logged_at = datetime(2025, 1, 2, 3, 4, 5, 123000)
    assert run_logger.append_run_log(run_id, "careful", level="warn", logged_at=logged_at) is True

    temp_db.expire_all()
    persisted = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
    assert persisted is not None
    assert persisted.logs == "2025-01-02 03:04:05.123 [WARN] careful"


def test_append_run_log_emits_structured_realtime_entry(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    run = crud.create_scheduled_run(temp_db, plan_id=plan.id, task_type="cpa_cleanup", trigger_source="manual")

    logged_at = datetime(2026, 3, 26, 10, 0, 0, 123000)
    assert run_logger.append_run_log(run.id, "hello", level="WARN", logged_at=logged_at) is True

    events = _get_run_stream_events(run.id)
    assert len(events) == 1
    event = events[0]
    assert event["kind"] == "log_appended"
    assert event["stream"] == f"run:{run.id}"

    entry = event["payload"]["entry"]
    assert entry["level"] == "WARN"
    assert entry["message"] == "hello"
    assert entry["display_time"] == "10:00:00"
    assert entry["raw"].endswith("[WARN] hello")
    assert entry["source"] == "scheduler"
    assert entry["timestamp"] == logged_at.isoformat()
    assert entry["seq"] == event["seq"]
    assert entry["stream"] == event["stream"]


def test_run_logger_append_log_expands_multiline_message_with_prefixed_physical_lines(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    with session_module.get_db() as db:
        run = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="running")
        run_id = run.id

    logged_at = datetime(2025, 1, 2, 3, 4, 5, 123000)
    assert run_logger.append_run_log(run_id, "line 1\nline 2\n\nline 4", level="ERROR", logged_at=logged_at) is True

    temp_db.expire_all()
    persisted = temp_db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
    assert persisted is not None
    assert persisted.logs == "\n".join(
        [
            "2025-01-02 03:04:05.123 [ERROR] line 1",
            "2025-01-02 03:04:05.123 [ERROR] line 2",
            "2025-01-02 03:04:05.123 [ERROR] ",
            "2025-01-02 03:04:05.123 [ERROR] line 4",
        ]
    )


def test_run_logger_append_log_rejects_unknown_level(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    with session_module.get_db() as db:
        run = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="running")
        run_id = run.id

    logged_at = datetime(2025, 1, 2, 3, 4, 5, 123000)
    with pytest.raises(ValueError):
        run_logger.append_run_log(run_id, "unknown", level="DEBUG", logged_at=logged_at)


def test_run_logger_append_log_rejects_non_string_level(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)
    with session_module.get_db() as db:
        run = crud.create_scheduled_run(db, plan_id=plan.id, trigger_source="manual", status="running")
        run_id = run.id

    with pytest.raises(ValueError):
        run_logger.append_run_log(run_id, "invalid", level=None)


def test_scheduler_engine_marks_stream_closed_on_failed_run(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)

    def _boom_runner(*, plan_id: int, run_id: int):
        raise RuntimeError("boom")

    engine = SchedulerEngine(runner_map={"cpa_cleanup": _boom_runner}, worker_spawner=lambda fn, _name: fn())
    run_id = engine.trigger_plan_now(plan.id)

    events = _get_run_stream_events(run_id)
    assert [event["kind"] for event in events] == [
        "run_status_changed",
        "run_status_changed",
        "stream_closed",
    ]
    assert [event["payload"]["status"] for event in events if event["kind"] == "run_status_changed"] == [
        "running",
        "failed",
    ]
    assert events[-1]["payload"] == {"run_id": run_id, "final_status": "failed"}
    assert [event["seq"] for event in events] == sorted(event["seq"] for event in events)

    snapshot = task_manager.build_run_stream_snapshot(run_id)
    run_snapshot = snapshot["payload"]["run"]
    assert run_snapshot["id"] == run_id
    assert run_snapshot["plan_id"] == plan.id
    assert run_snapshot["plan_name"] == plan.name
    assert run_snapshot["task_type"] == "cpa_cleanup"
    assert run_snapshot["status"] == "failed"
    assert run_snapshot["is_running"] is False
    assert run_snapshot["can_stop"] is False
    assert run_snapshot["stream_closed"] is True
    assert run_snapshot["stream_final_status"] == "failed"
    assert run_snapshot["error_message"] == "boom"


def test_scheduler_engine_emits_stopping_and_success_statuses(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)

    def _success_runner(*, plan_id: int, run_id: int):
        engine_module.request_run_stop(run_id, requested_by="tester", reason="manual")
        with session_module.get_db() as db:
            crud.finish_scheduled_run(db, run_id=run_id, status="success", summary={"ok": True})

    engine = SchedulerEngine(runner_map={"cpa_cleanup": _success_runner}, worker_spawner=lambda fn, _name: fn())
    run_id = engine.trigger_plan_now(plan.id)

    events = _get_run_stream_events(run_id)
    status_events = [event for event in events if event["kind"] == "run_status_changed"]
    assert [event["payload"]["status"] for event in status_events] == ["running", "stopping", "success"]
    assert events[-1]["kind"] == "stream_closed"
    assert events[-1]["payload"] == {"run_id": run_id, "final_status": "success"}

    snapshot = task_manager.build_run_stream_snapshot(run_id)
    assert snapshot["payload"]["run"]["status"] == "success"
    assert snapshot["payload"]["run"]["stream_closed"] is True
    assert snapshot["payload"]["run"]["stream_final_status"] == "success"


def test_scheduler_engine_marks_cancelled_run_as_terminal_stream(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=False)

    def _cancel_runner(*, plan_id: int, run_id: int):
        engine_module.request_run_stop(run_id, requested_by="tester", reason="manual")
        raise engine_module.ScheduledRunCancelledError("stop requested")

    engine = SchedulerEngine(runner_map={"cpa_cleanup": _cancel_runner}, worker_spawner=lambda fn, _name: fn())
    run_id = engine.trigger_plan_now(plan.id)

    events = _get_run_stream_events(run_id)
    status_events = [event for event in events if event["kind"] == "run_status_changed"]
    assert [event["payload"]["status"] for event in status_events] == ["running", "stopping", "cancelled"]
    assert events[-1]["kind"] == "stream_closed"
    assert events[-1]["payload"] == {"run_id": run_id, "final_status": "cancelled"}

    snapshot = task_manager.build_run_stream_snapshot(run_id)
    assert snapshot["payload"]["run"]["status"] == "cancelled"
    assert snapshot["payload"]["run"]["stream_closed"] is True
    assert snapshot["payload"]["run"]["stream_final_status"] == "cancelled"


def test_scheduler_engine_skipped_run_updates_plan_summary_fields(temp_db):
    plan = _create_plan(temp_db, task_type="cpa_cleanup", due=True)
    engine = SchedulerEngine()
    engine._plan_locks.add(plan.id)

    engine.dispatch_due_plans_once()

    temp_db.expire_all()
    runs = temp_db.query(ScheduledRun).filter(ScheduledRun.plan_id == plan.id).all()
    assert len(runs) == 1
    assert runs[0].status == "skipped"

    persisted_plan = crud.get_scheduled_plan_by_id(temp_db, plan.id)
    assert persisted_plan is not None
    assert persisted_plan.last_run_status == "skipped"
    assert persisted_plan.last_run_started_at is not None
    assert persisted_plan.last_run_finished_at is not None


def test_scheduler_engine_start_launches_single_background_poll_loop(monkeypatch):
    repo = FakeRepo()
    engine = SchedulerEngine(repo=repo, poll_seconds=60)
    called = Event()

    def _dispatch_once():
        called.set()

    monkeypatch.setattr(engine, "dispatch_due_plans_once", _dispatch_once)

    assert engine.start() is True
    assert called.wait(timeout=1.0)

    first_thread = engine._poll_thread
    assert first_thread is not None
    assert first_thread.is_alive()
    assert engine.start() is False
    assert engine._poll_thread is first_thread

    assert engine.stop() is True
    first_thread.join(timeout=1.0)
    assert not first_thread.is_alive()


def test_create_app_startup_shutdown_uses_isolated_scheduler_engine_instances(monkeypatch):
    monkeypatch.setattr("src.boot.lifespan.initialize_database", lambda: None)

    app_one = create_app()
    app_two = create_app()

    engine_one = app_one.state.scheduler_engine
    engine_two = app_two.state.scheduler_engine

    assert engine_one is not engine_two
    assert engine_one._started is False
    assert engine_two._started is False

    with TestClient(app_one):
        assert engine_one._started is True
        assert engine_two._started is False

    assert engine_one._started is False
    assert engine_two._started is False

    with TestClient(app_two):
        assert engine_one._started is False
        assert engine_two._started is True

    assert engine_one._started is False
    assert engine_two._started is False
