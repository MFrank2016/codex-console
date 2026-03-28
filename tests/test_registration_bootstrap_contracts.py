from contextlib import contextmanager

import pytest

from src.application.batch_registration_service import BatchRegistrationService
from src.application.registration_bootstrap_dtos import (
    BatchBootstrapResult,
    OutlookBatchBootstrapResult,
    RegistrationTaskSnapshot,
)
from src.application.registration_service import RegistrationService
from src.database import crud
from src.database.models import Base
from src.database.session import DatabaseSessionManager

from tests.fakes import BatchFakeTaskManager, RegistrationFakeTaskManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "registration-bootstrap-contracts.db"
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


class FakeProxyDispatcher:
    def __init__(self):
        self.prepare_calls: list[tuple[str, str, int, dict]] = []

    def prepare_batch_proxy_pool(self, *, batch_id, task_group, concurrency, overrides):
        self.prepare_calls.append((batch_id, task_group, concurrency, overrides))
        return object()


def test_registration_service_start_task_returns_snapshot_not_live_orm(db_factory):
    service = RegistrationService(
        db_factory=db_factory,
        task_manager=RegistrationFakeTaskManager(),
    )

    snapshot = service.start_task(
        task_uuid="task-bootstrap",
        proxy=None,
        pipeline_key="current_pipeline",
        email_service_id=7,
    )

    assert isinstance(snapshot, RegistrationTaskSnapshot)
    assert snapshot.task_uuid == "task-bootstrap"
    assert snapshot.created_at is not None
    assert not hasattr(snapshot, "_sa_instance_state")


def test_batch_registration_service_start_batch_owns_batch_state_and_proxy_warmup(db_factory):
    dispatcher = FakeProxyDispatcher()
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=BatchFakeTaskManager(),
        proxy_dispatcher=dispatcher,
        uuid_factory=lambda: "batch-001",
    )

    result = service.start_batch(
        count=2,
        proxy=None,
        pipeline_key="current_pipeline",
        concurrency=3,
        use_proxy=True,
        proxy_task_group="batch_registration",
        proxy_overrides={
            "allocation_strategy": "exclusive",
            "probe_url": "https://probe.example.com/ip",
            "dynamic_request_count": 3,
        },
    )

    assert isinstance(result, BatchBootstrapResult)
    assert result.batch_id == "batch-001"
    assert isinstance(result.task_snapshots, tuple)
    assert len(result.task_snapshots) == 2
    assert all(snapshot.created_at is not None for snapshot in result.task_snapshots)
    assert "batch-001" in service.batch_tasks
    assert dispatcher.prepare_calls == [
        (
            "batch-001",
            "batch_registration",
            3,
            {
                "allocation_strategy": "exclusive",
                "probe_url": "https://probe.example.com/ip",
                "dynamic_request_count": 3,
            },
        )
    ]


def test_outlook_batch_bootstrap_filters_registered_accounts_and_returns_dto(db_factory):

    with db_factory() as db:
        registered_email = "registered@example.com"
        registered_service = crud.create_email_service(
            db,
            service_type="outlook",
            name="registered-acc",
            config={"email": registered_email},
        )
        crud.create_account(
            db,
            email=registered_email,
            email_service="outlook",
        )
        unregistered_service_one = crud.create_email_service(
            db,
            service_type="outlook",
            name="unregistered-1",
            config={"email": "first@example.com"},
        )
        unregistered_service_two = crud.create_email_service(
            db,
            service_type="outlook",
            name="unregistered-2",
            config={"email": "second@example.com"},
        )

    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=BatchFakeTaskManager(),
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

    assert isinstance(result, OutlookBatchBootstrapResult)
    assert result.batch_id == "outlook-batch-001"
    assert result.total == 3
    assert result.skipped == 1
    assert isinstance(result.service_ids, tuple)
    assert result.service_ids == (
        unregistered_service_one.id,
        unregistered_service_two.id,
    )
