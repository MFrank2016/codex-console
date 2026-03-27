import types

import pytest

from src.config.constants import EmailServiceType
from src.core.email_suffix_blacklist import RegistrationDisallowedSuffixError
from src.core.registration_job import run_registration_job
from src.database import crud
from src.database.models import Base, EmailSuffixBlacklist
from src.database.session import DatabaseSessionManager


@pytest.fixture
def temp_db(tmp_path):
    manager = DatabaseSessionManager(f"sqlite:///{tmp_path / 'registration-job.db'}")
    Base.metadata.create_all(bind=manager.engine)
    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_run_registration_job_retries_full_round_after_auto_blacklisting(temp_db, monkeypatch):
    logs: list[str] = []
    stats = {"service_create": 0, "engine_init": 0, "engine_run": 0}

    class FakeResult:
        def __init__(self, *, success: bool, email: str, error_message: str | None = None):
            self.success = success
            self.email = email
            self.error_message = error_message

        def to_dict(self):
            return {
                "success": self.success,
                "email": self.email,
                "error_message": self.error_message,
            }

    class FakeEngine:
        def __init__(self, **_kwargs):
            stats["engine_init"] += 1

        def run(self):
            stats["engine_run"] += 1
            if stats["engine_run"] == 1:
                raise RegistrationDisallowedSuffixError(
                    email="first@blocked.test",
                    suffix="blocked.test",
                    detail="registration disallowed: blocked.test",
                )
            return FakeResult(success=True, email="second@ok.test")

        def save_to_database(self, result):
            crud.create_account(
                temp_db,
                email=result.email,
                email_service="tempmail",
                password="p",
                client_id="cid",
            )
            return True

        def flush_task_logs(self):
            return None

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: stats.__setitem__("service_create", stats["service_create"] + 1) or object(),
    )
    monkeypatch.setattr("src.core.registration_job.RegistrationEngine", FakeEngine)
    monkeypatch.setattr(
        "src.core.registration_job.get_settings",
        lambda: types.SimpleNamespace(registration_max_retries=1),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy=None,
        email_service_config={},
        callback_logger=logs.append,
    )

    assert result.success is True
    assert result.email == "second@ok.test"
    assert stats["service_create"] == 2
    assert stats["engine_init"] == 2
    assert stats["engine_run"] == 2

    row = temp_db.query(EmailSuffixBlacklist).filter(EmailSuffixBlacklist.suffix == "blocked.test").first()
    assert row is not None
    assert row.enabled is True
    assert any("已将邮箱后缀加入黑名单" in item for item in logs)
    assert any("当前任务将使用新邮箱重新尝试注册" in item for item in logs)


def test_run_registration_job_fails_after_exceeding_max_retries(temp_db, monkeypatch):
    stats = {"service_create": 0, "engine_run": 0}

    class AlwaysDisallowedEngine:
        def __init__(self, **_kwargs):
            return None

        def run(self):
            stats["engine_run"] += 1
            raise RegistrationDisallowedSuffixError(
                email=f"u{stats['engine_run']}@blocked.test",
                suffix="blocked.test",
                detail="registration disallowed forever",
            )

        def flush_task_logs(self):
            return None

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: stats.__setitem__("service_create", stats["service_create"] + 1) or object(),
    )
    monkeypatch.setattr("src.core.registration_job.RegistrationEngine", AlwaysDisallowedEngine)
    monkeypatch.setattr(
        "src.core.registration_job.get_settings",
        lambda: types.SimpleNamespace(registration_max_retries=1),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy=None,
        email_service_config={},
    )

    assert result.success is False
    assert "registration disallowed forever" in (result.error_message or "")
    assert stats["engine_run"] == 2
    assert stats["service_create"] == 2

    row = temp_db.query(EmailSuffixBlacklist).filter(EmailSuffixBlacklist.suffix == "blocked.test").first()
    assert row is not None
    assert row.hit_count == 2
