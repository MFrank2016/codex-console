from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import src.core.register as register_module
from src.database import crud
from src.database.models import Base
from src.database.session import DatabaseSessionManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "registration-engine-logging.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def engine_factory(monkeypatch):
    monkeypatch.setattr(
        register_module,
        "OpenAIHTTPClient",
        lambda proxy_url=None: SimpleNamespace(session=None, close=lambda: None),
    )
    monkeypatch.setattr(register_module, "OAuthManager", lambda **kwargs: SimpleNamespace())

    def _build(task_uuid: str):
        email_service = SimpleNamespace(service_type=SimpleNamespace(value="tempmail"))
        return register_module.RegistrationEngine(
            email_service=email_service,
            task_uuid=task_uuid,
            callback_logger=lambda message: None,
        )

    return _build


def test_registration_logging_does_not_commit_per_message(monkeypatch, temp_db, engine_factory):
    crud.create_registration_task(temp_db, task_uuid="task-log-1")

    @contextmanager
    def fake_get_db():
        yield temp_db

    monkeypatch.setattr(register_module, "get_db", fake_get_db)

    commits = []
    original_commit = temp_db.commit

    def tracked_commit():
        commits.append("commit")
        return original_commit()

    monkeypatch.setattr(temp_db, "commit", tracked_commit)

    engine = engine_factory("task-log-1")
    engine._log("line 1")
    engine._log("line 2")

    assert commits == []

    engine.flush_task_logs()

    assert len(commits) == 1


def test_registration_log_buffer_flushes_all_lines(monkeypatch, temp_db, engine_factory):
    crud.create_registration_task(temp_db, task_uuid="task-log-2")

    @contextmanager
    def fake_get_db():
        yield temp_db

    monkeypatch.setattr(register_module, "get_db", fake_get_db)

    engine = engine_factory("task-log-2")
    engine._log("line 1")
    engine._log("line 2")
    engine.flush_task_logs()

    task = crud.get_registration_task(temp_db, "task-log-2")
    assert task is not None
    assert "line 1" in (task.logs or "")
    assert "line 2" in (task.logs or "")
    assert (task.logs or "").count("\n") == 1
