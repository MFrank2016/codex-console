import types

import pytest

from src.config.constants import EmailServiceType
from src.core.email_suffix_blacklist import RegistrationDisallowedSuffixError
from src.core.pipeline.errors import PipelineStepExecutionError, PipelineStepFailureContext
from src.core.pipeline.context import PipelineContext
from src.core.registration_job import _build_pipeline_result_payload, _resolve_email_service, run_registration_job
from src.database import crud
from src.database.models import Base, EmailService, EmailSuffixBlacklist
from src.database.repositories import registration_failure_repository as failure_repo
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
    stats = {"service_create": 0, "pipeline_runs": 0}

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: stats.__setitem__("service_create", stats["service_create"] + 1) or object(),
    )
    
    def fake_run_pipeline_registration(*, runtime_ref=None, **_kwargs):
        stats["pipeline_runs"] += 1
        if runtime_ref is not None:
            runtime_ref["runtime"] = types.SimpleNamespace(proxy_ip=None)
        if stats["pipeline_runs"] == 1:
            raise RegistrationDisallowedSuffixError(
                email="first@blocked.test",
                suffix="blocked.test",
                detail="registration disallowed: blocked.test",
            )
        return (
            types.SimpleNamespace(id=101, email="second@ok.test"),
            {"success": True, "email": "second@ok.test"},
        )

    monkeypatch.setattr("src.core.registration_job._run_pipeline_registration", fake_run_pipeline_registration)
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
    assert stats["pipeline_runs"] == 2

    row = temp_db.query(EmailSuffixBlacklist).filter(EmailSuffixBlacklist.suffix == "blocked.test").first()
    assert row is not None
    assert row.enabled is True
    assert any("已将邮箱后缀加入黑名单" in item for item in logs)
    assert any("当前任务将使用新邮箱重新尝试注册" in item for item in logs)


def test_resolve_email_service_auto_selected_outlook_injects_proxy_url(temp_db):
    temp_db.add(
        EmailService(
            service_type="outlook",
            name="outlook-auto-selected",
            config={
                "email": "outlook-user@example.com",
                "password": "secret-pass",
            },
            enabled=True,
            priority=0,
        )
    )
    temp_db.commit()

    service_type, config, resolved_service_id = _resolve_email_service(
        db=temp_db,
        email_service_type="outlook",
        email_service_id=None,
        proxy="http://proxy-outlook-auto:9000",
        email_service_config=None,
    )

    assert service_type == EmailServiceType.OUTLOOK
    assert resolved_service_id is not None
    assert config["email"] == "outlook-user@example.com"
    assert config["proxy_url"] == "http://proxy-outlook-auto:9000"


def test_run_registration_job_logs_runtime_context_for_current_pipeline(temp_db, monkeypatch):
    logs: list[str] = []

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, 33),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )
    
    def fake_run_pipeline_registration(*, runtime_ref=None, **_kwargs):
        if runtime_ref is not None:
            runtime_ref["runtime"] = types.SimpleNamespace(proxy_ip="8.8.8.8")
        return (
            types.SimpleNamespace(id=303, email="logger@test.dev"),
            {
                "success": True,
                "email": "logger@test.dev",
                "metadata": {"proxy_ip": "8.8.8.8"},
            },
        )

    monkeypatch.setattr("src.core.registration_job._run_pipeline_registration", fake_run_pipeline_registration)
    monkeypatch.setattr(
        "src.core.registration_job.get_settings",
        lambda: types.SimpleNamespace(registration_max_retries=0),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-a:8000",
        email_service_config={},
        callback_logger=logs.append,
    )

    assert result.success is True
    assert any(
        "[运行上下文]" in item
        and "email_service_id=33" in item
        and "proxy_url=http://proxy-a:8000" in item
        for item in logs
    )
    assert any("[运行上下文]" in item and "proxy_ip=8.8.8.8" in item for item in logs)


def test_run_registration_job_logs_runtime_context_for_codexgen_pipeline(temp_db, monkeypatch):
    logs: list[str] = []

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, 44),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "src.core.registration_job._run_pipeline_registration",
        lambda **_kwargs: (
            types.SimpleNamespace(id=101, email="pipeline@test.dev"),
            {
                "success": True,
                "email": "pipeline@test.dev",
                "metadata": {
                    "proxy_ip": "9.9.9.9",
                },
            },
        ),
    )
    monkeypatch.setattr(
        "src.core.registration_job.get_settings",
        lambda: types.SimpleNamespace(registration_max_retries=0),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-b:9000",
        email_service_config={},
        pipeline_key="codexgen_pipeline",
        callback_logger=logs.append,
    )

    assert result.success is True
    assert any(
        "[运行上下文]" in item
        and "email_service_id=44" in item
        and "proxy_url=http://proxy-b:9000" in item
        for item in logs
    )
    assert any("[运行上下文]" in item and "proxy_ip=9.9.9.9" in item for item in logs)


def test_run_registration_job_dispatches_current_pipeline_through_shared_pipeline_runner(temp_db, monkeypatch):
    task_uuid = "task-current-dispatch"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "src.core.registration_job._run_pipeline_registration",
        lambda **kwargs: captured.update({"pipeline_key": kwargs["pipeline_key"]}) or (
            types.SimpleNamespace(id=202, email="current@test.dev"),
            {
                "success": True,
                "email": "current@test.dev",
                "metadata": {"proxy_ip": "7.7.7.7"},
            },
        ),
    )
    monkeypatch.setattr(
        "src.core.registration_job.get_settings",
        lambda: types.SimpleNamespace(registration_max_retries=0),
    )

    class LegacyEngineShouldNotRun:
        def __init__(self, **_kwargs):
            raise AssertionError("legacy RegistrationEngine path should not run for current_pipeline")

    monkeypatch.setattr("src.core.registration_job.RegistrationEngine", LegacyEngineShouldNotRun)

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-current",
        email_service_config={},
        pipeline_key="current_pipeline",
        task_uuid=task_uuid,
    )

    assert result.success is True
    assert result.email == "current@test.dev"
    assert captured["pipeline_key"] == "current_pipeline"


def test_run_registration_job_records_structured_pipeline_failure_fields(temp_db, monkeypatch):
    task_uuid = "task-structured-pipeline-failure"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )

    def fake_run_pipeline_registration(*, runtime_ref=None, **_kwargs):
        if runtime_ref is not None:
            runtime_ref["runtime"] = types.SimpleNamespace(proxy_ip="4.4.4.4")
        raise PipelineStepExecutionError(
            PipelineStepFailureContext(
                pipeline_key="current_pipeline",
                step_key="submit_login_password",
                failure_stage="submit_login_password",
                error_message="unexpected login page type",
                retryable=True,
                attempt_count=2,
                retry_reasons=["timed out"],
                metadata={"foo": "bar"},
            )
        )

    monkeypatch.setattr("src.core.registration_job._run_pipeline_registration", fake_run_pipeline_registration)
    monkeypatch.setattr(
        "src.core.registration_job.get_settings",
        lambda: types.SimpleNamespace(registration_max_retries=0),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-structured",
        email_service_config={},
        pipeline_key="current_pipeline",
        task_uuid=task_uuid,
    )

    rows = failure_repo.list_registration_failure_records(temp_db)

    assert result.success is False
    assert len(rows) == 1
    assert rows[0].failure_stage == "submit_login_password"
    assert rows[0].step_key == "submit_login_password"
    assert rows[0].retryable is True


def test_build_pipeline_result_payload_promotes_token_source_to_top_level():
    ctx = PipelineContext(
        task_uuid="task-token-source",
        pipeline_key="current_pipeline",
        email="tester@example.com",
        password="StrongPass123!",
        metadata={
            "token_source": "registration_capture",
            "account_id": "acct-captured",
            "access_token": "access-captured",
            "session_token": "session-captured",
        },
    )

    payload = _build_pipeline_result_payload(ctx)

    assert payload["metadata"]["token_source"] == "registration_capture"
    assert payload["token_source"] == "registration_capture"


def test_run_registration_job_logs_unknown_proxy_ip_when_failure_has_no_ip(temp_db, monkeypatch):
    logs: list[str] = []

    class FailingEngine:
        def __init__(self, **_kwargs):
            self.proxy_ip = None

        def run(self):
            raise RuntimeError("boom")

        def flush_task_logs(self):
            return None

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, 55),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr("src.core.registration_job.RegistrationEngine", FailingEngine)
    monkeypatch.setattr(
        "src.core.registration_job.get_settings",
        lambda: types.SimpleNamespace(registration_max_retries=0),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-c:7000",
        email_service_config={},
        callback_logger=logs.append,
    )

    assert result.success is False
    assert any(
        "[运行上下文]" in item
        and "email_service_id=55" in item
        and "proxy_url=http://proxy-c:7000" in item
        for item in logs
    )
    assert any("[运行上下文]" in item and "proxy_ip=unknown" in item for item in logs)


def test_run_registration_job_fails_after_exceeding_max_retries(temp_db, monkeypatch):
    stats = {"service_create": 0, "pipeline_runs": 0}

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: stats.__setitem__("service_create", stats["service_create"] + 1) or object(),
    )
    
    def fake_run_pipeline_registration(*, runtime_ref=None, **_kwargs):
        stats["pipeline_runs"] += 1
        if runtime_ref is not None:
            runtime_ref["runtime"] = types.SimpleNamespace(proxy_ip=None)
        raise RegistrationDisallowedSuffixError(
            email=f"u{stats['pipeline_runs']}@blocked.test",
            suffix="blocked.test",
            detail="registration disallowed forever",
        )

    monkeypatch.setattr("src.core.registration_job._run_pipeline_registration", fake_run_pipeline_registration)
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
    assert stats["pipeline_runs"] == 2
    assert stats["service_create"] == 2

    row = temp_db.query(EmailSuffixBlacklist).filter(EmailSuffixBlacklist.suffix == "blocked.test").first()
    assert row is not None
    assert row.hit_count == 2


def test_run_registration_job_auto_blacklist_uses_email_suffix_fallback_and_resets_task_for_retry(
    temp_db, monkeypatch
):
    task_uuid = "task-retry-reset"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)

    stats = {"engine_run": 0, "rollback": 0}
    update_calls: list[dict] = []

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )

    def fake_run_pipeline_registration(*, runtime_ref=None, **_kwargs):
        stats["engine_run"] += 1
        if runtime_ref is not None:
            runtime_ref["runtime"] = types.SimpleNamespace(proxy_ip=None)
        if stats["engine_run"] == 1:
            raise RegistrationDisallowedSuffixError(
                email="u@blocked.test",
                suffix=None,
                detail="registration disallowed without suffix",
            )
        return (
            types.SimpleNamespace(id=404, email="retry-ok@test.dev"),
            {"success": True, "email": "retry-ok@test.dev"},
        )

    monkeypatch.setattr("src.core.registration_job._run_pipeline_registration", fake_run_pipeline_registration)
    monkeypatch.setattr(
        "src.core.registration_job.get_settings",
        lambda: types.SimpleNamespace(registration_max_retries=1),
    )

    def fake_rollback():
        stats["rollback"] += 1

    monkeypatch.setattr(temp_db, "rollback", fake_rollback)

    def fake_update_registration_task(_db, _task_uuid, **fields):
        update_calls.append({"task_uuid": _task_uuid, **fields})

    monkeypatch.setattr("src.core.registration_job.crud.update_registration_task", fake_update_registration_task)

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy=None,
        email_service_config={},
        task_uuid=task_uuid,
    )

    assert result.success is True
    assert stats["rollback"] >= 1
    row = temp_db.query(EmailSuffixBlacklist).filter(EmailSuffixBlacklist.suffix == "blocked.test").first()
    assert row is not None
    assert any(
        call.get("task_uuid") == task_uuid
        and call.get("status") == "running"
        and call.get("pipeline_status") == "running"
        and call.get("error_message") is None
        and call.get("completed_at") is None
        for call in update_calls
    )


def test_run_registration_job_records_failure_attempt_before_retry_success(temp_db, monkeypatch):
    task_uuid = "task-retry-failure-record"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)
    stats = {"run_calls": 0}

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )

    def fake_run_pipeline_registration(*, runtime_ref=None, **_kwargs):
        stats["run_calls"] += 1
        if runtime_ref is not None:
            runtime_ref["runtime"] = types.SimpleNamespace(
                generated_user_profile={"name": "Alice Smith", "birthdate": "1994-02-03"},
                proxy_ip="1.1.1.1",
            )
        if stats["run_calls"] == 1:
            raise RegistrationDisallowedSuffixError(
                email="first@blocked.test",
                suffix="blocked.test",
                detail="registration disallowed: blocked.test",
            )
        return (
            types.SimpleNamespace(id=505, email="second@ok.test"),
            {"success": True, "email": "second@ok.test"},
        )

    monkeypatch.setattr("src.core.registration_job._run_pipeline_registration", fake_run_pipeline_registration)
    monkeypatch.setattr(
        "src.core.registration_job.get_settings",
        lambda: types.SimpleNamespace(registration_max_retries=1),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-a",
        email_service_config={},
        pipeline_key="current_pipeline",
        task_uuid=task_uuid,
        batch_id="batch-1",
        registration_mode="batch",
    )

    rows = failure_repo.list_registration_failure_records(temp_db)

    assert result.success is True
    assert len(rows) == 1
    assert rows[0].task_uuid == task_uuid
    assert rows[0].attempt_no == 1
    assert rows[0].batch_id == "batch-1"
    assert rows[0].registration_mode == "batch"
    assert rows[0].error_code == "registration_disallowed"
    assert rows[0].display_name == "Alice Smith"
    assert rows[0].birthdate == "1994-02-03"
    assert rows[0].proxy_ip == "1.1.1.1"


def test_run_registration_job_records_codexgen_failure_from_result_payload_metadata(temp_db, monkeypatch):
    task_uuid = "task-codexgen-failure-record"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "src.core.registration_job._run_pipeline_registration",
        lambda **_kwargs: (
            None,
            {
                "success": False,
                "email": "tester@example.com",
                "access_token": "access-plain-token",
                "error_message": "boom-codexgen",
                "metadata": {
                    "user_profile": {"name": "Test User", "birthdate": "1990-01-02"},
                    "proxy_ip": "9.9.9.9",
                    "refresh_token": "refresh-plain-token",
                },
            },
        ),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-a",
        email_service_config={},
        pipeline_key="codexgen_pipeline",
        task_uuid=task_uuid,
        batch_id="batch-codexgen-1",
        registration_mode="batch",
    )

    rows = failure_repo.list_registration_failure_records(temp_db)

    assert result.success is False
    assert len(rows) == 1
    assert rows[0].pipeline_key == "codexgen_pipeline"
    assert rows[0].task_uuid == task_uuid
    assert rows[0].display_name == "Test User"
    assert rows[0].birthdate == "1990-01-02"
    assert rows[0].proxy_ip == "9.9.9.9"
    assert rows[0].extra_json["result_payload"]["access_token"].endswith("...")
    assert rows[0].extra_json["result_payload"]["access_token"] != "access-plain-token"
    assert rows[0].extra_json["result_payload"]["metadata"]["refresh_token"].endswith("...")


def test_run_registration_job_records_codexgen_exception_with_runtime_snapshot(temp_db, monkeypatch):
    task_uuid = "task-codexgen-exception-record"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )

    def fake_run_pipeline_registration(**kwargs):
        kwargs["runtime_ref"]["runtime"] = types.SimpleNamespace(
            _engine=types.SimpleNamespace(
                generated_user_profile={"name": "Runtime User", "birthdate": "1991-02-03"},
                proxy_ip="7.7.7.7",
            )
        )
        raise RuntimeError("boom-codexgen-exception")

    monkeypatch.setattr(
        "src.core.registration_job._run_pipeline_registration",
        fake_run_pipeline_registration,
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-a",
        email_service_config={},
        pipeline_key="codexgen_pipeline",
        task_uuid=task_uuid,
        batch_id="batch-codexgen-ex-1",
        registration_mode="batch",
    )

    rows = failure_repo.list_registration_failure_records(temp_db)

    assert result.success is False
    assert len(rows) == 1
    assert rows[0].display_name == "Runtime User"
    assert rows[0].birthdate == "1991-02-03"
    assert rows[0].proxy_ip == "7.7.7.7"


def test_run_registration_job_logs_exception_with_stack_for_unexpected_error(temp_db, monkeypatch):
    task_uuid = "task-exception-log"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)
    exception_calls: list[tuple[str, tuple]] = []
    error_calls: list[tuple[str, tuple]] = []

    monkeypatch.setattr(
        "src.core.registration_job._resolve_email_service",
        lambda **_kwargs: (EmailServiceType.TEMPMAIL, {}, None),
    )
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "src.core.registration_job._run_pipeline_registration",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom-stack")),
    )
    monkeypatch.setattr(
        "src.core.registration_job.logger.exception",
        lambda message, *args: exception_calls.append((message, args)),
    )
    monkeypatch.setattr(
        "src.core.registration_job.logger.error",
        lambda message, *args: error_calls.append((message, args)),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-a",
        email_service_config={},
        pipeline_key="codexgen_pipeline",
        task_uuid=task_uuid,
        batch_id="batch-log-1",
        registration_mode="batch",
    )

    assert result.success is False
    assert exception_calls
    assert error_calls == []
