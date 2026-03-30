import asyncio
from contextlib import contextmanager
from copy import deepcopy

import pytest
from fastapi import BackgroundTasks, HTTPException

from src.core.registration_job import RegistrationJobResult
from src.core.time import utc_now_naive
from src.web import task_manager as task_manager_module
from src.web.routes import registration as registration_routes

from src.application.registration_bootstrap_dtos import (
    BatchBootstrapResult,
    OutlookBatchBootstrapResult,
    RegistrationTaskSnapshot,
)
from src.database import crud
from src.database.models import Base
from src.database.session import DatabaseSessionManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "registration-batch-routes.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def route_db(monkeypatch, temp_db):
    @contextmanager
    def _get_db():
        yield temp_db

    monkeypatch.setattr(registration_routes, "get_db", _get_db)
    return temp_db


@pytest.fixture
def batch_state():
    original_batch_tasks = deepcopy(registration_routes.batch_tasks)
    original_batch_proxy_pools = deepcopy(getattr(registration_routes, "batch_proxy_pools", {}))
    original_batch_status = deepcopy(task_manager_module._batch_status)
    original_batch_logs = deepcopy(task_manager_module._batch_logs)
    original_task_steps = deepcopy(getattr(task_manager_module, "_task_steps", {}))
    registration_routes.batch_tasks.clear()
    if hasattr(registration_routes, "batch_proxy_pools"):
        registration_routes.batch_proxy_pools.clear()
    task_manager_module._batch_status.clear()
    task_manager_module._batch_logs.clear()
    if hasattr(task_manager_module, "_task_steps"):
        task_manager_module._task_steps.clear()
    try:
        yield
    finally:
        registration_routes.batch_tasks.clear()
        registration_routes.batch_tasks.update(original_batch_tasks)
        if hasattr(registration_routes, "batch_proxy_pools"):
            registration_routes.batch_proxy_pools.clear()
            registration_routes.batch_proxy_pools.update(original_batch_proxy_pools)
        task_manager_module._batch_status.clear()
        task_manager_module._batch_status.update(original_batch_status)
        task_manager_module._batch_logs.clear()
        task_manager_module._batch_logs.update(original_batch_logs)
        if hasattr(task_manager_module, "_task_steps"):
            task_manager_module._task_steps.clear()
            task_manager_module._task_steps.update(original_task_steps)


def test_create_and_update_registration_task_persist_email_address(temp_db):
    task = crud.create_registration_task(
        temp_db,
        task_uuid="task-1",
        email_address="first@gmail.com",
    )

    assert task.email_address == "first@gmail.com"

    updated = crud.update_registration_task(
        temp_db,
        "task-1",
        email_address="second@gmail.com",
    )

    assert updated.email_address == "second@gmail.com"


def test_start_registration_persists_pipeline_key(route_db, batch_state, monkeypatch):
    monkeypatch.setattr(registration_routes, "task_manager", FakeTaskManager())
    background = BackgroundTasks()

    response = asyncio.run(
        registration_routes.start_registration(
            registration_routes.RegistrationTaskCreate(
                email_service_type="tempmail",
                pipeline_key="codexgen_pipeline",
            ),
            background,
        )
    )

    task = crud.get_registration_task(route_db, response.task_uuid)
    assert task is not None
    assert task.pipeline_key == "codexgen_pipeline"


def test_start_registration_delegates_bootstrap_to_start_task(route_db, batch_state, monkeypatch):
    class FakeRegistrationService:
        def __init__(self):
            self.calls: list[dict] = []

        def create_task(self, **kwargs):
            raise AssertionError("route should not call create_task directly")

        def start_task(self, **kwargs):
            self.calls.append(kwargs)
            return RegistrationTaskSnapshot(
                id=99,
                task_uuid=kwargs["task_uuid"],
                status="pending",
                proxy=kwargs["proxy"],
                pipeline_key=kwargs["pipeline_key"],
                email_service_id=kwargs["email_service_id"],
                created_at="2026-03-29T00:00:00",
            )

    fake_service = FakeRegistrationService()
    monkeypatch.setattr(registration_routes, "_build_registration_service", lambda: fake_service)
    background = BackgroundTasks()

    response = asyncio.run(
        registration_routes.start_registration(
            registration_routes.RegistrationTaskCreate(
                email_service_type="tempmail",
                use_proxy=False,
                pipeline_key="current_pipeline",
                email_service_id=12,
            ),
            background,
        )
    )

    assert fake_service.calls, "route should delegate single-start bootstrap to service.start_task"
    assert response.id == 99
    assert response.status == "pending"
    assert response.pipeline_key == "current_pipeline"
    assert response.email_service_id == 12
    assert response.created_at == "2026-03-29T00:00:00"


def test_start_batch_registration_persists_pipeline_key_for_each_task(route_db, batch_state, monkeypatch):
    monkeypatch.setattr(registration_routes, "task_manager", FakeTaskManager())
    background = BackgroundTasks()

    response = asyncio.run(
        registration_routes.start_batch_registration(
            registration_routes.BatchRegistrationRequest(
                count=2,
                email_service_type="tempmail",
                pipeline_key="codexgen_pipeline",
                proxy="http://manual-batch:8000",
            ),
            background,
        )
    )

    assert len(response.tasks) == 2
    for item in response.tasks:
        task = crud.get_registration_task(route_db, item.task_uuid)
        assert task is not None
        assert task.pipeline_key == "codexgen_pipeline"
        assert item.created_at is not None


def test_start_batch_registration_delegates_bootstrap_to_service(route_db, batch_state, monkeypatch):
    bootstrap_result = BatchBootstrapResult(
        batch_id="batch-from-service",
        task_snapshots=[RegistrationTaskSnapshot(id=1, task_uuid="task-1", status="pending")],
        is_unlimited=False,
    )

    class FakeBatchService:
        def __init__(self):
            self.calls: list[dict] = []

        def prepare_batch_proxy_pool(self, **kwargs):
            raise AssertionError("route should not call old bootstrap path")

        def create_batch_tasks(self, *, count, proxy, pipeline_key):
            raise AssertionError("route should not call old bootstrap path")

        def start_batch(self, **kwargs):
            self.calls.append(kwargs)
            return bootstrap_result

    fake_service = FakeBatchService()
    monkeypatch.setattr(registration_routes, "_build_batch_registration_service", lambda: fake_service)
    background = BackgroundTasks()

    assert registration_routes.batch_tasks == {}

    response = asyncio.run(
        registration_routes.start_batch_registration(
            registration_routes.BatchRegistrationRequest(count=1, concurrency=1, mode="pipeline"),
            background,
        )
    )

    assert isinstance(response, registration_routes.BatchRegistrationResponse)
    assert response.batch_id == "batch-from-service"
    assert fake_service.calls, "route should delegate bootstrapping to service"
    assert fake_service.calls[0]["count"] == 1
    assert registration_routes.batch_tasks == {}


def test_start_batch_registration_serializes_tasks_with_fresh_db_sessions(tmp_path, batch_state, monkeypatch):
    db_path = tmp_path / "registration-batch-detached.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    @contextmanager
    def isolated_get_db():
        session = manager.SessionLocal()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(registration_routes, "get_db", isolated_get_db)
    monkeypatch.setattr(registration_routes, "task_manager", FakeTaskManager())
    background = BackgroundTasks()

    response = asyncio.run(
        registration_routes.start_batch_registration(
            registration_routes.BatchRegistrationRequest(
                count=2,
                email_service_type="tempmail",
                pipeline_key="current_pipeline",
            ),
            background,
        )
    )

    assert [item.status for item in response.tasks] == ["pending", "pending"]
    assert len({item.task_uuid for item in response.tasks}) == 2


def test_get_task_returns_step_aware_pipeline_payload(route_db):
    task = crud.create_registration_task(route_db, task_uuid="task-step-aware")
    crud.update_registration_task(
        route_db,
        task.task_uuid,
        pipeline_key="codexgen_pipeline",
        current_step_key="submit_login_email",
        pipeline_status="running",
        total_duration_ms=3210,
    )
    crud.create_pipeline_step_run(
        route_db,
        task_uuid=task.task_uuid,
        pipeline_key="codexgen_pipeline",
        step_key="create_email",
        step_order=1,
        status="completed",
        duration_ms=123,
    )
    crud.create_pipeline_step_run(
        route_db,
        task_uuid=task.task_uuid,
        pipeline_key="codexgen_pipeline",
        step_key="submit_login_email",
        step_order=2,
        status="running",
        duration_ms=456,
    )

    response = asyncio.run(registration_routes.get_task(task.task_uuid))

    assert response.pipeline_key == "codexgen_pipeline"
    assert response.current_step_key == "submit_login_email"
    assert response.pipeline_status == "running"
    assert response.total_duration_ms == 3210
    assert [item["step_key"] for item in response.steps] == ["create_email", "submit_login_email"]


def test_get_task_returns_proxy_ip_from_result_metadata(route_db):
    task = crud.create_registration_task(route_db, task_uuid="task-proxy-ip")
    crud.update_registration_task(
        route_db,
        task.task_uuid,
        result={
            "success": True,
            "metadata": {
                "proxy_ip": "8.8.8.8",
            },
        },
    )

    response = asyncio.run(registration_routes.get_task(task.task_uuid))

    assert response.proxy_ip == "8.8.8.8"


def test_list_tasks_returns_proxy_ip_from_result_metadata(route_db):
    task = crud.create_registration_task(route_db, task_uuid="task-list-proxy-ip")
    crud.update_registration_task(
        route_db,
        task.task_uuid,
        result={
            "success": False,
            "metadata": {
                "proxy_ip": "7.7.7.7",
            },
        },
    )

    response = asyncio.run(registration_routes.list_tasks(page=1, page_size=20, status=None))

    assert response.total >= 1
    matched = next(item for item in response.tasks if item.task_uuid == "task-list-proxy-ip")
    assert matched.proxy_ip == "7.7.7.7"


def test_list_tasks_route_delegates_to_query_facade(monkeypatch):
    captured: dict = {}

    class FakeFacade:
        def list_tasks(self, **kwargs):
            captured.update(kwargs)
            task_view = type(
                "TaskView",
                (),
                {
                    "id": 1,
                    "task_uuid": "task-via-facade",
                    "status": "pending",
                    "email": None,
                    "email_service_id": None,
                    "pipeline_key": None,
                    "current_step_key": None,
                    "pipeline_status": None,
                    "total_duration_ms": None,
                    "proxy": None,
                    "proxy_ip": None,
                    "steps": [],
                    "result": None,
                    "logs": None,
                    "error_message": None,
                    "created_at": None,
                    "started_at": None,
                    "completed_at": None,
                },
            )()
            return type("TaskListView", (), {"total": 1, "tasks": [task_view]})()

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    monkeypatch.setattr(
        registration_routes,
        "get_db",
        lambda: (_ for _ in ()).throw(AssertionError("route should delegate to facade")),
    )

    response = asyncio.run(registration_routes.list_tasks(page=2, page_size=7, status="running"))

    assert captured == {"page": 2, "page_size": 7, "status": "running"}
    assert response.total == 1
    assert response.tasks[0].task_uuid == "task-via-facade"


def test_get_task_route_delegates_to_query_facade(monkeypatch):
    captured: dict = {}

    class FakeFacade:
        def get_task_detail(self, task_uuid):
            captured["task_uuid"] = task_uuid
            view = type(
                "TaskView",
                (),
                {
                    "id": 2,
                    "task_uuid": task_uuid,
                    "status": "completed",
                    "email": "demo@example.com",
                    "email_service_id": 1,
                    "pipeline_key": "current_pipeline",
                    "current_step_key": "done",
                    "pipeline_status": "completed",
                    "total_duration_ms": 1000,
                    "proxy": "http://proxy.example.com:8080",
                    "proxy_ip": "1.1.1.1",
                    "steps": [{"step_key": "done"}],
                    "result": {"success": True},
                    "logs": "line-1",
                    "error_message": None,
                    "created_at": "2026-03-30T00:00:00",
                    "started_at": "2026-03-30T00:00:01",
                    "completed_at": "2026-03-30T00:00:02",
                },
            )()
            return view

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    monkeypatch.setattr(
        registration_routes,
        "get_db",
        lambda: (_ for _ in ()).throw(AssertionError("route should delegate to facade")),
    )

    response = asyncio.run(registration_routes.get_task("task-via-facade"))

    assert captured == {"task_uuid": "task-via-facade"}
    assert response.task_uuid == "task-via-facade"
    assert response.steps[0]["step_key"] == "done"


def test_get_task_route_returns_404_when_facade_returns_none(monkeypatch):
    class FakeFacade:
        def get_task_detail(self, task_uuid):
            return None

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(registration_routes.get_task("missing-task"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "任务不存在"


def test_get_task_logs_route_delegates_to_query_facade(monkeypatch):
    captured: dict = {}

    class FakeFacade:
        def get_task_logs(self, task_uuid):
            captured["task_uuid"] = task_uuid
            return {
                "task_uuid": task_uuid,
                "status": "running",
                "logs": ["line-1", "line-2"],
            }

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    monkeypatch.setattr(
        registration_routes,
        "get_db",
        lambda: (_ for _ in ()).throw(AssertionError("route should delegate to facade")),
    )

    payload = asyncio.run(registration_routes.get_task_logs("task-log-via-facade"))

    assert captured == {"task_uuid": "task-log-via-facade"}
    assert payload["logs"] == ["line-1", "line-2"]


def test_get_task_logs_route_returns_404_when_facade_returns_none(monkeypatch):
    class FakeFacade:
        def get_task_logs(self, task_uuid):
            return None

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(registration_routes.get_task_logs("missing-task"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "任务不存在"


def test_registration_stats_route_delegates_to_query_facade(monkeypatch):
    class FakeFacade:
        def get_registration_stats(self):
            return type(
                "StatsView",
                (),
                {"by_status": {"pending": 3, "completed": 2}, "today_count": 5},
            )()

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    monkeypatch.setattr(
        registration_routes,
        "get_db",
        lambda: (_ for _ in ()).throw(AssertionError("route should delegate to facade")),
    )

    payload = asyncio.run(registration_routes.get_registration_stats())

    assert payload == {
        "by_status": {"pending": 3, "completed": 2},
        "today_count": 5,
    }


class FakeTaskManager:
    def __init__(self):
        self._status = {}
        self._task_status = {}
        self._batch_logs = {}
        self._task_steps = {}
        self.set_task_steps_calls = 0

    def is_cancelled(self, task_uuid):
        return self._task_status.get(task_uuid, {}).get("cancelled", False)

    def update_status(self, task_uuid, status, **kwargs):
        self._task_status.setdefault(task_uuid, {}).update({"status": status, **kwargs})

    def create_log_callback(self, task_uuid, prefix="", batch_id=""):
        return lambda message: None

    def init_batch(
        self,
        batch_id,
        total,
        *,
        started_at=None,
        is_unlimited=False,
        consecutive_failures=0,
        max_consecutive_failures=10,
        stop_reason=None,
        domain_stats=None,
    ):
        self._status[batch_id] = {
            "status": "running",
            "total": total,
            "started_at": started_at,
            "is_unlimited": is_unlimited,
            "consecutive_failures": consecutive_failures,
            "max_consecutive_failures": max_consecutive_failures,
            "stop_reason": stop_reason,
            "domain_stats": [] if domain_stats is None else list(domain_stats),
        }

    def update_batch_status(self, batch_id, **kwargs):
        self._status.setdefault(batch_id, {}).update(kwargs)

    def get_batch_status(self, batch_id):
        return self._status.get(batch_id)

    def add_batch_log(self, batch_id, log_message):
        self._batch_logs.setdefault(batch_id, []).append(log_message)

    def is_batch_cancelled(self, batch_id):
        return self._status.get(batch_id, {}).get("cancelled", False)

    def set_task_steps(self, task_uuid, steps):
        self.set_task_steps_calls += 1
        self._task_steps[task_uuid] = list(steps or [])

    def get_task_steps(self, task_uuid):
        return list(self._task_steps.get(task_uuid, []))

    def clear_task_steps(self, task_uuid):
        self._task_steps.pop(task_uuid, None)


@pytest.fixture
def fake_task_manager(monkeypatch, batch_state):
    manager = FakeTaskManager()
    monkeypatch.setattr(registration_routes, "task_manager", manager)
    return manager


def test_start_batch_registration_accepts_zero_and_queues_unlimited_runner(route_db, batch_state, monkeypatch):
    monkeypatch.setattr(registration_routes, "task_manager", FakeTaskManager())
    background = BackgroundTasks()

    response = asyncio.run(
        registration_routes.start_batch_registration(
            registration_routes.BatchRegistrationRequest(
                count=0,
                email_service_type="tempmail",
                proxy="http://manual-unlimited:8000",
            ),
            background,
        )
    )

    assert response.count == 0
    assert response.is_unlimited is True
    assert response.tasks == []
    assert background.tasks[0].func is registration_routes.run_unlimited_batch_registration
    batch = registration_routes.batch_tasks[response.batch_id]
    assert batch["is_unlimited"] is True
    assert batch["total"] == 0
    assert batch["consecutive_failures"] == 0
    assert batch["max_consecutive_failures"] == 10
    assert batch["stop_reason"] is None
    assert batch["domain_stats"] == []


def test_start_batch_registration_rejects_counts_outside_zero_to_500():
    with pytest.raises(HTTPException):
        asyncio.run(
            registration_routes.start_batch_registration(
                registration_routes.BatchRegistrationRequest(count=501, email_service_type="tempmail"),
                BackgroundTasks(),
            )
        )


def test_start_registration_queues_proxy_override_metadata(route_db, batch_state, monkeypatch):
    monkeypatch.setattr(registration_routes, "task_manager", FakeTaskManager())
    background = BackgroundTasks()

    asyncio.run(
        registration_routes.start_registration(
            registration_routes.RegistrationTaskCreate(
                email_service_type="tempmail",
                use_proxy=True,
                dynamic_proxy_request_count=4,
                proxy_list_candidate_limit=2,
            ),
            background,
        )
    )

    queued = background.tasks[0]
    assert queued.kwargs["proxy_task_group"] == "single_registration"
    assert queued.kwargs["use_proxy"] is True
    assert queued.kwargs["proxy_overrides"] == {
        "dynamic_request_count": 4,
        "proxy_list_candidate_limit": 2,
    }


def test_start_batch_registration_prepares_proxy_pool_with_overrides(route_db, batch_state, monkeypatch):
    monkeypatch.setattr(registration_routes, "task_manager", FakeTaskManager())
    captured: dict = {}

    class FakeBatchService:
        def start_batch(self, **kwargs):
            captured.update(kwargs)
            return BatchBootstrapResult(
                batch_id="prepared-batch",
                task_snapshots=tuple(
                    RegistrationTaskSnapshot(
                        id=idx + 1,
                        task_uuid=f"prepared-task-{idx}",
                        status="pending",
                        proxy=kwargs["proxy"],
                        pipeline_key=kwargs["pipeline_key"],
                    )
                    for idx in range(kwargs["count"])
                ),
                is_unlimited=False,
            )

    monkeypatch.setattr(registration_routes, "_build_batch_registration_service", lambda: FakeBatchService())
    background = BackgroundTasks()

    response = asyncio.run(
        registration_routes.start_batch_registration(
            registration_routes.BatchRegistrationRequest(
                count=2,
                email_service_type="tempmail",
                use_proxy=True,
                concurrency=3,
                dynamic_proxy_request_count=9,
                dynamic_proxy_probe_url="https://probe.example.com/ip",
                dynamic_proxy_strategy="exclusive",
            ),
            background,
        )
    )

    assert response.count == 2
    assert response.batch_id == "prepared-batch"
    assert captured["proxy_task_group"] == "batch_registration"
    assert captured["concurrency"] == 3
    assert captured["proxy_overrides"] == {
        "dynamic_request_count": 9,
        "probe_url": "https://probe.example.com/ip",
        "allocation_strategy": "exclusive",
    }


def test_start_batch_registration_keeps_queued_flow_when_proxy_pool_prepare_fails(route_db, batch_state, monkeypatch):
    monkeypatch.setattr(registration_routes, "task_manager", FakeTaskManager())

    class FakeBatchService:
        def start_batch(self, **kwargs):
            return BatchBootstrapResult(
                batch_id="proxy-fallback-batch",
                task_snapshots=tuple(
                    RegistrationTaskSnapshot(
                        id=idx + 1,
                        task_uuid=f"proxy-fallback-task-{idx}",
                        status="pending",
                        proxy=kwargs["proxy"],
                        pipeline_key=kwargs["pipeline_key"],
                    )
                    for idx in range(kwargs["count"])
                ),
                is_unlimited=False,
            )

    monkeypatch.setattr(registration_routes, "_build_batch_registration_service", lambda: FakeBatchService())
    background = BackgroundTasks()

    response = asyncio.run(
        registration_routes.start_batch_registration(
            registration_routes.BatchRegistrationRequest(
                count=2,
                email_service_type="tempmail",
                use_proxy=True,
                concurrency=2,
                dynamic_proxy_strategy="exclusive",
            ),
            background,
        )
    )

    assert response.count == 2
    assert len(response.tasks) == 2
    assert background.tasks[0].func is registration_routes.run_batch_registration


def test_start_outlook_batch_registration_delegates_bootstrap_to_service(route_db, batch_state, monkeypatch):
    monkeypatch.setattr(registration_routes, "task_manager", FakeTaskManager())
    captured: dict = {}

    class FakeBatchService:
        def start_outlook_batch(self, **kwargs):
            captured.update(kwargs)
            return OutlookBatchBootstrapResult(
                batch_id="outlook-batch-001",
                total=len(kwargs["service_ids"]),
                skipped=1,
                service_ids=(kwargs["service_ids"][-1],),
            )

    monkeypatch.setattr(registration_routes, "_build_batch_registration_service", lambda: FakeBatchService())

    from src.database.models import EmailService as EmailServiceModel

    route_db.add(
        EmailServiceModel(
            service_type="outlook",
            name="acc-1",
            config={"email": "user1@example.com"},
            enabled=True,
        )
    )
    route_db.add(
        EmailServiceModel(
            service_type="outlook",
            name="acc-2",
            config={"email": "user2@example.com"},
            enabled=True,
        )
    )
    route_db.commit()
    services = route_db.query(EmailServiceModel).order_by(EmailServiceModel.id.asc()).all()
    background = BackgroundTasks()

    response = asyncio.run(
        registration_routes.start_outlook_batch_registration(
            registration_routes.OutlookBatchRegistrationRequest(
                service_ids=[services[0].id, services[1].id],
                use_proxy=True,
                proxy="http://manual-outlook:8000",
                concurrency=2,
                dynamic_proxy_request_count=6,
                dynamic_proxy_probe_url="https://probe.example.com/outlook",
                dynamic_proxy_strategy="strict_isolation",
            ),
            background,
        )
    )

    assert captured["proxy_task_group"] == "outlook_batch"
    assert captured["concurrency"] == 2
    assert "proxy" not in captured
    assert captured["proxy_overrides"] == {
        "dynamic_request_count": 6,
        "probe_url": "https://probe.example.com/outlook",
        "allocation_strategy": "strict_isolation",
    }
    assert response.batch_id == "outlook-batch-001"
    assert response.total == 2
    assert response.skipped == 1
    assert response.to_register == 1
    assert response.service_ids == [services[1].id]


def test_get_batch_status_includes_unlimited_metadata(batch_state):
    background = BackgroundTasks()
    response = asyncio.run(
        registration_routes.start_batch_registration(
            registration_routes.BatchRegistrationRequest(
                count=0,
                email_service_type="tempmail",
                proxy="http://manual-unlimited:8000",
            ),
            background,
        )
    )

    result = asyncio.run(registration_routes.get_batch_status(response.batch_id))

    assert result["is_unlimited"] is True
    assert result["consecutive_failures"] == 0
    assert result["max_consecutive_failures"] == 10
    assert result["stop_reason"] is None
    assert result["domain_stats"] == []
    assert result["started_at"] is not None


def test_get_batch_status_route_delegates_to_query_facade(monkeypatch):
    captured = {}

    class FakeFacade:
        def get_batch_status(self, batch_id):
            captured["batch_id"] = batch_id
            return type(
                "BatchView",
                (),
                {
                    "batch_id": batch_id,
                    "payload": {
                        "batch_id": batch_id,
                        "total": 6,
                        "completed": 4,
                        "success": 3,
                        "failed": 1,
                        "current_index": 4,
                        "cancelled": False,
                        "finished": False,
                        "started_at": "2026-03-30T10:00:00",
                        "progress": "4/6",
                        "is_unlimited": False,
                        "consecutive_failures": 0,
                        "max_consecutive_failures": 10,
                        "stop_reason": None,
                        "domain_stats": [{"domain": "gmail.com", "count": 3}],
                    },
                },
            )()

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    monkeypatch.setattr(registration_routes, "batch_tasks", None)

    payload = asyncio.run(registration_routes.get_batch_status("batch-from-facade"))

    assert captured == {"batch_id": "batch-from-facade"}
    assert payload["batch_id"] == "batch-from-facade"
    assert payload["progress"] == "4/6"
    assert payload["is_unlimited"] is False


def test_get_batch_status_route_returns_404_when_facade_returns_none(monkeypatch):
    class FakeFacade:
        def get_batch_status(self, batch_id):
            return None

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    monkeypatch.setattr(registration_routes, "batch_tasks", None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(registration_routes.get_batch_status("missing-batch"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "批量任务不存在"


def test_get_outlook_batch_status_route_delegates_to_query_facade(monkeypatch):
    captured = {}

    class FakeFacade:
        def get_outlook_batch_status(self, batch_id):
            captured["batch_id"] = batch_id
            return type(
                "BatchView",
                (),
                {
                    "batch_id": batch_id,
                    "payload": {
                        "batch_id": batch_id,
                        "total": 8,
                        "completed": 5,
                        "success": 4,
                        "failed": 1,
                        "skipped": 2,
                        "current_index": 5,
                        "cancelled": False,
                        "finished": False,
                        "started_at": "2026-03-30T10:10:00",
                        "logs": ["line-1"],
                        "progress": "5/8",
                        "domain_stats": [{"domain": "outlook.com", "count": 4}],
                    },
                },
            )()

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    monkeypatch.setattr(registration_routes, "batch_tasks", None)

    payload = asyncio.run(registration_routes.get_outlook_batch_status("outlook-batch-from-facade"))

    assert captured == {"batch_id": "outlook-batch-from-facade"}
    assert payload["progress"] == "5/8"
    assert payload["skipped"] == 2
    assert payload["logs"] == ["line-1"]
    assert payload["domain_stats"] == [{"domain": "outlook.com", "count": 4}]


def test_get_outlook_batch_status_route_returns_404_when_facade_returns_none(monkeypatch):
    class FakeFacade:
        def get_outlook_batch_status(self, batch_id):
            return None

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    monkeypatch.setattr(registration_routes, "batch_tasks", None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(registration_routes.get_outlook_batch_status("missing-outlook-batch"))

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "批量任务不存在"


def test_run_sync_registration_task_persists_email_address_even_on_failure(route_db, fake_task_manager, monkeypatch):
    crud.create_registration_task(route_db, task_uuid="task-1")

    monkeypatch.setattr(
        registration_routes,
        "run_registration_job",
        lambda **_: RegistrationJobResult(
            success=False,
            email="failed@gmail.com",
            error_message="boom",
        ),
    )

    registration_routes._run_sync_registration_task("task-1", "tempmail", None, None)

    task = crud.get_registration_task(route_db, "task-1")
    assert task.status == "failed"
    assert task.email_address == "failed@gmail.com"


def test_run_sync_registration_task_passes_pipeline_key_to_registration_job(route_db, fake_task_manager, monkeypatch):
    crud.create_registration_task(route_db, task_uuid="task-pipeline-key")
    crud.update_registration_task(route_db, "task-pipeline-key", pipeline_key="codexgen_pipeline")

    captured = {}

    def fake_run_registration_job(**kwargs):
        captured.update(kwargs)
        return RegistrationJobResult(
            success=False,
            email="failed@gmail.com",
            error_message="boom",
        )

    monkeypatch.setattr(registration_routes, "run_registration_job", fake_run_registration_job)

    registration_routes._run_sync_registration_task("task-pipeline-key", "tempmail", None, None)

    assert captured.get("pipeline_key") == "codexgen_pipeline"


def test_task_manager_step_state_roundtrip():
    manager = task_manager_module.task_manager
    task_uuid = "task-step-state"

    manager.set_task_steps(task_uuid, [{"step_key": "create_email"}])
    assert manager.get_task_steps(task_uuid) == [{"step_key": "create_email"}]
    manager.clear_task_steps(task_uuid)
    assert manager.get_task_steps(task_uuid) == []


def test_get_task_prefers_task_manager_steps_when_db_steps_missing(route_db, fake_task_manager):
    task = crud.create_registration_task(route_db, task_uuid="task-step-fallback")
    fake_task_manager.set_task_steps(task.task_uuid, [{"step_key": "memory-step"}])

    response = asyncio.run(registration_routes.get_task(task.task_uuid))

    assert [item["step_key"] for item in response.steps] == ["memory-step"]


def test_get_task_prefers_db_steps_over_task_manager_snapshot(route_db, fake_task_manager):
    task = crud.create_registration_task(route_db, task_uuid="task-step-db-priority")
    fake_task_manager.set_task_steps(task.task_uuid, [{"step_key": "memory-step"}])
    crud.create_pipeline_step_run(
        route_db,
        task_uuid=task.task_uuid,
        pipeline_key="current_pipeline",
        step_key="db-step",
        step_order=1,
        status="completed",
    )

    response = asyncio.run(registration_routes.get_task(task.task_uuid))

    assert [item["step_key"] for item in response.steps] == ["db-step"]


def test_run_sync_registration_task_does_not_cache_terminal_task_steps(route_db, fake_task_manager, monkeypatch):
    crud.create_registration_task(route_db, task_uuid="task-no-terminal-cache")
    monkeypatch.setattr(
        registration_routes,
        "run_registration_job",
        lambda **_: RegistrationJobResult(
            success=True,
            account_id=101,
            email="ok@gmail.com",
            result_payload={"success": True, "email": "ok@gmail.com"},
        ),
    )

    registration_routes._run_sync_registration_task("task-no-terminal-cache", "tempmail", None, None)

    assert fake_task_manager.set_task_steps_calls == 0


def test_run_sync_registration_task_persists_full_result_payload_on_success(route_db, fake_task_manager, monkeypatch):
    crud.create_registration_task(route_db, task_uuid="task-success-1")
    rich_result = {
        "success": True,
        "email": "ok@gmail.com",
        "password": "pw123",
        "account_id": "acc-1",
        "workspace_id": "ws-1",
        "access_token": "tok...",
        "refresh_token": "ref...",
        "id_token": "id...",
        "session_token": "sess...",
        "error_message": "",
        "logs": ["a", "b"],
        "metadata": {"k": "v"},
        "source": "register",
    }

    monkeypatch.setattr(
        registration_routes,
        "run_registration_job",
        lambda **_: RegistrationJobResult(
            success=True,
            account_id=101,
            email="ok@gmail.com",
            result_payload=rich_result,
        ),
    )

    registration_routes._run_sync_registration_task("task-success-1", "tempmail", None, None)

    task = crud.get_registration_task(route_db, "task-success-1")
    assert task.status == "completed"
    assert task.result == rich_result


def test_run_batch_registration_attaches_sorted_domain_stats(route_db, fake_task_manager, monkeypatch):
    task_ids = []
    for name in ["a", "b", "c"]:
        task = crud.create_registration_task(route_db, task_uuid=f"task-{name}")
        task_ids.append(task.task_uuid)

    outcomes = iter([
        ("completed", "one@yahoo.com"),
        ("failed", "two@gmail.com"),
        ("completed", "three@gmail.com"),
    ])

    async def fake_run_registration_task(task_uuid, *args, **kwargs):
        status, email = next(outcomes)
        crud.update_registration_task(
            route_db,
            task_uuid,
            status=status,
            email_address=email,
            completed_at=utc_now_naive(),
            result={"email": email} if status == "completed" else None,
            error_message=None if status == "completed" else "boom",
        )

    monkeypatch.setattr(registration_routes, "run_registration_task", fake_run_registration_task)

    asyncio.run(
        registration_routes.run_batch_registration(
            batch_id="fixed-1",
            task_uuids=task_ids,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            interval_min=0,
            interval_max=0,
            concurrency=1,
            mode="parallel",
        )
    )

    stats = registration_routes.batch_tasks["fixed-1"]["domain_stats"]
    assert [row["domain"] for row in stats] == ["yahoo.com", "gmail.com"]


def test_run_batch_parallel_finalizes_statistics_on_completed_batch(route_db, fake_task_manager, monkeypatch):
    task_ids = []
    for idx in range(2):
        task = crud.create_registration_task(route_db, task_uuid=f"stats-complete-{idx}")
        task_ids.append(task.task_uuid)

    async def fake_run_registration_task(task_uuid, *args, **kwargs):
        crud.update_registration_task(
            route_db,
            task_uuid,
            status="completed",
            completed_at=utc_now_naive(),
            total_duration_ms=1200,
        )

    monkeypatch.setattr(registration_routes, "run_registration_task", fake_run_registration_task)

    asyncio.run(
        registration_routes.run_batch_registration(
            batch_id="stats-completed-1",
            task_uuids=task_ids,
            email_service_type="tempmail",
            proxy="http://proxy.local",
            email_service_config=None,
            email_service_id=42,
            interval_min=3,
            interval_max=5,
            concurrency=2,
            mode="parallel",
            pipeline_key="stats_pipeline",
        )
    )

    stat = crud.get_registration_batch_stat_by_batch_id(route_db, "stats-completed-1")
    assert stat is not None
    assert stat.status == "completed"
    assert stat.mode == "parallel"
    assert stat.pipeline_key == "stats_pipeline"
    assert stat.email_service_type == "tempmail"
    assert stat.email_service_id == 42
    assert stat.target_count == len(task_ids)
    assert stat.config_snapshot == {
        "proxy": "http://proxy.local",
        "interval_min": 3,
        "interval_max": 5,
        "concurrency": 2,
    }
    assert stat.started_at is not None
    assert stat.completed_at is not None


def test_run_batch_pipeline_finalizes_statistics_on_cancelled_batch(route_db, fake_task_manager, monkeypatch):
    task_ids = []
    for idx in range(2):
        task = crud.create_registration_task(route_db, task_uuid=f"stats-cancel-{idx}")
        task_ids.append(task.task_uuid)

    monkeypatch.setattr(fake_task_manager, "is_batch_cancelled", lambda batch_id: True)

    asyncio.run(
        registration_routes.run_batch_pipeline(
            batch_id="stats-cancelled-1",
            task_uuids=task_ids,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            interval_min=1,
            interval_max=2,
            concurrency=1,
            pipeline_key="cancel_pipeline",
        )
    )

    stat = crud.get_registration_batch_stat_by_batch_id(route_db, "stats-cancelled-1")
    assert stat is not None
    assert stat.status == "cancelled"
    assert stat.mode == "pipeline"
    assert stat.pipeline_key == "cancel_pipeline"
    assert stat.target_count == len(task_ids)
    assert stat.finished_count == len(task_ids)
    assert stat.config_snapshot == {
        "proxy": None,
        "interval_min": 1,
        "interval_max": 2,
        "concurrency": 1,
    }


def test_run_batch_parallel_finalizes_statistics_on_failed_batch(route_db, fake_task_manager, monkeypatch):
    task_ids = []
    for idx in range(2):
        task = crud.create_registration_task(route_db, task_uuid=f"stats-failed-{idx}")
        task_ids.append(task.task_uuid)

    async def fake_run_registration_task(task_uuid, *args, **kwargs):
        crud.update_registration_task(
            route_db,
            task_uuid,
            status="failed",
            completed_at=utc_now_naive(),
            error_message="boom",
        )

    calls = {"count": 0}

    def flaky_finalize(batch_id, task_uuids):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(registration_routes, "run_registration_task", fake_run_registration_task)
    monkeypatch.setattr(registration_routes, "_finalize_batch_domain_stats", flaky_finalize)

    asyncio.run(
        registration_routes.run_batch_parallel(
            batch_id="stats-failed-1",
            task_uuids=task_ids,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            concurrency=1,
            interval_min=0,
            interval_max=0,
            pipeline_key="failed_pipeline",
        )
    )

    stat = crud.get_registration_batch_stat_by_batch_id(route_db, "stats-failed-1")
    assert stat is not None
    assert stat.status == "failed"
    assert stat.mode == "parallel"
    assert fake_task_manager.get_batch_status("stats-failed-1")["status"] == "failed"


def test_run_batch_parallel_finalizes_statistics_failure_does_not_override_status(route_db, fake_task_manager, monkeypatch):
    task_ids = []
    for idx in range(2):
        task = crud.create_registration_task(route_db, task_uuid=f"stats-error-{idx}")
        task_ids.append(task.task_uuid)

    async def fake_run_registration_task(task_uuid, *args, **kwargs):
        crud.update_registration_task(
            route_db,
            task_uuid,
            status="completed",
            completed_at=utc_now_naive(),
            total_duration_ms=900,
        )

    def exploding_finalize(*args, **kwargs):
        raise RuntimeError("stats boom")

    monkeypatch.setattr(registration_routes, "run_registration_task", fake_run_registration_task)
    monkeypatch.setattr(registration_routes, "finalize_batch_statistics", exploding_finalize)

    asyncio.run(
        registration_routes.run_batch_registration(
            batch_id="stats-error-1",
            task_uuids=task_ids,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            interval_min=0,
            interval_max=0,
            concurrency=1,
            mode="parallel",
        )
    )

    assert fake_task_manager.get_batch_status("stats-error-1")["status"] == "completed"
    assert crud.get_registration_batch_stat_by_batch_id(route_db, "stats-error-1") is None


def test_run_batch_pipeline_finalizes_domain_stats_before_marking_cancelled_batch_finished(route_db, fake_task_manager, monkeypatch):
    task_ids = []
    for name in ["a", "b"]:
        task = crud.create_registration_task(route_db, task_uuid=f"cancel-{name}")
        task_ids.append(task.task_uuid)

    monkeypatch.setattr(fake_task_manager, "is_batch_cancelled", lambda batch_id: True)

    observed = {}

    def fake_finalize(batch_id, task_uuids):
        observed["route_finished"] = registration_routes.batch_tasks[batch_id]["finished"]
        observed["manager_finished"] = fake_task_manager.get_batch_status(batch_id).get("finished", False)
        observed["task_uuids"] = list(task_uuids)

    monkeypatch.setattr(registration_routes, "_finalize_batch_domain_stats", fake_finalize)

    asyncio.run(
        registration_routes.run_batch_pipeline(
            batch_id="cancelled-fixed-1",
            task_uuids=task_ids,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            interval_min=0,
            interval_max=0,
            concurrency=1,
        )
    )

    assert observed == {
        "route_finished": False,
        "manager_finished": False,
        "task_uuids": task_ids,
    }
    assert registration_routes.batch_tasks["cancelled-fixed-1"]["finished"] is True
    assert fake_task_manager.get_batch_status("cancelled-fixed-1")["finished"] is True
    assert fake_task_manager.get_batch_status("cancelled-fixed-1")["status"] == "cancelled"


def test_run_unlimited_batch_registration_stops_after_eleven_consecutive_failures(route_db, fake_task_manager, monkeypatch):
    outcomes = iter([("failed", f"user{i}@bad.com") for i in range(11)] + [("completed", "late@good.com")])

    async def fake_run_registration_task(task_uuid, *args, **kwargs):
        status, email = next(outcomes)
        crud.update_registration_task(
            route_db,
            task_uuid,
            status=status,
            email_address=email,
            completed_at=utc_now_naive(),
            result={"email": email} if status == "completed" else None,
            error_message=None if status == "completed" else "boom",
        )

    monkeypatch.setattr(registration_routes, "run_registration_task", fake_run_registration_task)

    asyncio.run(
        registration_routes.run_unlimited_batch_registration(
            batch_id="unlimited-1",
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            interval_min=0,
            interval_max=0,
            concurrency=1,
            mode="parallel",
        )
    )

    state = registration_routes.batch_tasks["unlimited-1"]
    assert state["completed"] == 11
    assert state["failed"] == 11
    assert state["consecutive_failures"] == 11
    assert state["stop_reason"] == "too_many_consecutive_failures"


def test_run_unlimited_batch_registration_preserves_pre_start_cancellation(route_db, fake_task_manager, monkeypatch):
    batch_id = "unlimited-pre-cancelled"
    registration_routes._build_batch_registration_service().init_batch_state(
        batch_id,
        [],
        is_unlimited=True,
        total=0,
    )
    registration_routes.batch_tasks[batch_id]["cancelled"] = True
    fake_task_manager._status[batch_id]["cancelled"] = True
    calls = []

    async def fake_run_registration_task(task_uuid, *args, **kwargs):
        calls.append(task_uuid)
        crud.update_registration_task(
            route_db,
            task_uuid,
            status="failed",
            completed_at=utc_now_naive(),
            error_message="should-not-run",
        )

    monkeypatch.setattr(registration_routes, "run_registration_task", fake_run_registration_task)

    asyncio.run(
        registration_routes.run_unlimited_batch_registration(
            batch_id=batch_id,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            interval_min=0,
            interval_max=0,
            concurrency=1,
            mode="parallel",
        )
    )

    assert calls == []
    state = registration_routes.batch_tasks[batch_id]
    assert state["cancelled"] is True
    assert state["finished"] is True
    assert state["completed"] == 0
    assert state["domain_stats"] == []
    assert fake_task_manager.get_batch_status(batch_id)["status"] == "cancelled"
    assert fake_task_manager.get_batch_status(batch_id)["finished"] is True


def test_run_unlimited_batch_registration_propagates_child_task_exception_and_finalizes(route_db, fake_task_manager, monkeypatch):
    batch_id = "unlimited-child-exception"
    calls = []
    wait_calls = 0
    original_wait = registration_routes.asyncio.wait

    async def fake_run_registration_task(task_uuid, *args, **kwargs):
        calls.append(task_uuid)
        raise RuntimeError("boom")

    async def counting_wait(*args, **kwargs):
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls > 1:
            raise AssertionError("runner kept waiting after a child task exception")
        return await original_wait(*args, **kwargs)

    monkeypatch.setattr(registration_routes, "run_registration_task", fake_run_registration_task)
    monkeypatch.setattr(registration_routes.asyncio, "wait", counting_wait)

    asyncio.run(
        registration_routes.run_unlimited_batch_registration(
            batch_id=batch_id,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            interval_min=0,
            interval_max=0,
            concurrency=1,
            mode="parallel",
        )
    )

    assert len(calls) == 1
    assert wait_calls == 1
    state = registration_routes.batch_tasks[batch_id]
    assert state["finished"] is True
    assert state["domain_stats"] == []
    assert fake_task_manager.get_batch_status(batch_id)["status"] == "failed"
    assert fake_task_manager.get_batch_status(batch_id)["finished"] is True


def test_start_outlook_batch_registration_persists_skipped_into_batch_state(route_db, batch_state, monkeypatch):
    monkeypatch.setattr(registration_routes, "task_manager", FakeTaskManager())

    from src.database.models import EmailService as EmailServiceModel

    route_db.add(
        EmailServiceModel(
            service_type="outlook",
            name="registered-acc",
            config={"email": "registered@example.com"},
            enabled=True,
        )
    )
    route_db.add(
        EmailServiceModel(
            service_type="outlook",
            name="fresh-acc",
            config={"email": "fresh@example.com"},
            enabled=True,
        )
    )
    route_db.commit()
    services = route_db.query(EmailServiceModel).order_by(EmailServiceModel.id.asc()).all()

    crud.create_account(route_db, email="registered@example.com", email_service="outlook")

    background = BackgroundTasks()
    response = asyncio.run(
        registration_routes.start_outlook_batch_registration(
            registration_routes.OutlookBatchRegistrationRequest(
                service_ids=[services[0].id, services[1].id],
                skip_registered=True,
                use_proxy=False,
            ),
            background,
        )
    )

    assert response.skipped == 1
    assert registration_routes.batch_tasks[response.batch_id]["skipped"] == 1
    assert registration_routes.batch_tasks[response.batch_id]["service_ids"] == [services[1].id]

    status = asyncio.run(registration_routes.get_outlook_batch_status(response.batch_id))
    assert status["skipped"] == 1


def test_get_outlook_batch_status_includes_domain_stats_if_present(batch_state):
    registration_routes.batch_tasks["outlook-1"] = {
        "total": 2,
        "completed": 2,
        "success": 1,
        "failed": 1,
        "skipped": 0,
        "current_index": 1,
        "cancelled": False,
        "finished": True,
        "logs": [],
        "domain_stats": [{"domain": "gmail.com", "total": 2, "success": 1, "failed": 1}],
    }

    result = asyncio.run(registration_routes.get_outlook_batch_status("outlook-1"))

    assert result["domain_stats"] == [{"domain": "gmail.com", "total": 2, "success": 1, "failed": 1}]


def test_run_outlook_batch_registration_does_not_finalize_ordinary_batch_stats(route_db, fake_task_manager, monkeypatch):
    service_ids = [11, 12]
    monkeypatch.setattr(fake_task_manager, "get_loop", lambda: None, raising=False)
    monkeypatch.setattr(fake_task_manager, "set_loop", lambda loop: None, raising=False)

    async def fake_run_registration_task(task_uuid, *args, **kwargs):
        crud.update_registration_task(
            route_db,
            task_uuid,
            status="completed",
            completed_at=utc_now_naive(),
            total_duration_ms=500,
        )

    monkeypatch.setattr(registration_routes, "run_registration_task", fake_run_registration_task)

    asyncio.run(
        registration_routes.run_outlook_batch_registration(
            batch_id="outlook-no-stats",
            service_ids=service_ids,
            proxy=None,
            interval_min=0,
            interval_max=0,
            concurrency=1,
            mode="parallel",
        )
    )

    assert crud.get_registration_batch_stat_by_batch_id(route_db, "outlook-no-stats") is None
    batch_status = fake_task_manager.get_batch_status("outlook-no-stats")
    assert isinstance(batch_status.get("task_uuids"), list)
    assert len(batch_status["task_uuids"]) == len(service_ids)
