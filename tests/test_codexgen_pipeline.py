import pytest

from src.config.constants import EmailServiceType
from src.core.email_suffix_blacklist import RegistrationDisallowedSuffixError
from src.core.pipeline import PipelineContext, PipelineRunner
from src.core.pipeline.registry import PIPELINE_REGISTRY, get_pipeline
from src.core.pipeline.steps import common as common_steps
from src.core.pipeline.steps.codexgen import CodexgenPipelineRuntime
from src.core.registration_job import run_registration_job
from src.database import crud
from src.database.models import Base
from src.database.session import DatabaseSessionManager
from src.services.base import BaseEmailService


class FakeSharedEmailService(BaseEmailService):
    def __init__(self):
        super().__init__(EmailServiceType.TEMPMAIL)
        self.create_calls = 0
        self.otp_calls: list[dict] = []
        self._codes = ["123456", "654321"]

    def create_email(self, config=None):
        self.create_calls += 1
        return {
            "email": "tester@example.com",
            "service_id": "mailbox-1",
        }

    def get_verification_code(self, email, email_id=None, timeout=120, pattern=r"(?<!\d)(\d{6})(?!\d)", otp_sent_at=None):
        self.otp_calls.append(
            {
                "email": email,
                "email_id": email_id,
                "otp_sent_at": otp_sent_at,
            }
        )
        return self._codes.pop(0) if self._codes else "111111"

    def list_emails(self, **kwargs):
        return []

    def delete_email(self, email_id):
        return True

    def check_health(self):
        return True


class FakeCodexgenRuntime:
    def __init__(self, email_service: FakeSharedEmailService):
        self.email_service = email_service
        self.email: str | None = None
        self.password = "CodexgenPass123!"
        self.email_info: dict = {}

    def run_check_ip_location_step(self):
        return {"metadata": {"ip_location": "US"}}

    def run_create_email_step(self):
        info = self.email_service.create_email()
        self.email = info["email"]
        self.email_info = info
        return {"email": self.email, "metadata": {"email_info": info}}

    def run_init_auth_session_step(self):
        return {}

    def run_prepare_authorize_flow_step(self):
        return {"metadata": {"auth_device_id": "did-1", "auth_sentinel_token": "sentinel-1"}}

    def run_submit_signup_email_step(self, *, did: str, sentinel_token: str):
        assert did == "did-1"
        assert sentinel_token == "sentinel-1"
        return {}

    def run_register_password_step(self):
        return {"password": self.password}

    def run_send_signup_otp_step(self):
        return {}

    def run_wait_signup_otp_step(self):
        self.email_service.get_verification_code(self.email, email_id=self.email_info.get("service_id"))
        return {}

    def run_validate_signup_otp_step(self):
        return {}

    def run_create_account_profile_step(self):
        return {}

    def run_prepare_token_acquisition_step(self):
        return {"metadata": {"token_acquired_via_relogin": True, "relogin_device_id": "did-1", "relogin_sentinel_token": "sentinel-1"}}

    def run_submit_login_email_step(self, *, did: str, sentinel_token: str):
        assert did == "did-1"
        assert sentinel_token == "sentinel-1"
        return {}

    def run_submit_login_password_step(self):
        return {}

    def run_wait_login_otp_step(self):
        self.email_service.get_verification_code(self.email, email_id=self.email_info.get("service_id"))
        return {}

    def run_validate_login_otp_step(self):
        return {}

    def run_resolve_consent_and_workspace_step(self):
        return {
            "metadata": {
                "workspace_id": "ws-1",
                "oauth_callback_url": "http://localhost:1455/auth/callback?code=code-1&state=state-1",
            }
        }

    def run_exchange_oauth_token_step(self, *, callback_url: str | None):
        assert callback_url and "code=" in callback_url
        return {
            "metadata": {
                "account_id": "acct-1",
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "id_token": "id-1",
                "session_token": "session-1",
            }
        }


@pytest.fixture
def temp_db(tmp_path):
    manager = DatabaseSessionManager(f"sqlite:///{tmp_path / 'codexgen-pipeline.db'}")
    Base.metadata.create_all(bind=manager.engine)
    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_pipeline_registry():
    PIPELINE_REGISTRY.clear()
    try:
        yield
    finally:
        PIPELINE_REGISTRY.clear()


def test_get_codexgen_pipeline_is_available_with_common_step_bindings():
    pipeline = get_pipeline("codexgen_pipeline")
    assert pipeline is not None
    assert get_pipeline("codexgen_pipeline") is pipeline

    steps = {item.step_key: item for item in pipeline.steps}
    assert steps["create_email"].impl_key == "common.create_email"
    assert steps["create_email"].handler is common_steps.create_email_step
    assert steps["wait_signup_otp"].impl_key == "common.wait_signup_otp"
    assert steps["wait_signup_otp"].handler is common_steps.wait_signup_otp_step
    assert steps["wait_login_otp"].impl_key == "common.wait_login_otp"
    assert steps["wait_login_otp"].handler is common_steps.wait_login_otp_step
    assert steps["exchange_oauth_token"].impl_key == "common.exchange_oauth_token"
    assert steps["exchange_oauth_token"].handler is common_steps.exchange_oauth_token_step


def test_codexgen_pipeline_uses_shared_email_service(temp_db):
    pipeline = get_pipeline("codexgen_pipeline")
    assert pipeline is not None

    task_uuid = "task-codexgen-pipeline"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)

    email_service = FakeSharedEmailService()
    runtime = FakeCodexgenRuntime(email_service)
    ctx = PipelineContext(
        task_uuid=task_uuid,
        pipeline_key="codexgen_pipeline",
        proxy_url="http://proxy-a",
        metadata={"registration_engine": runtime},
    )

    PipelineRunner(temp_db).run(pipeline, ctx)

    assert email_service.create_calls == 1
    assert len(email_service.otp_calls) == 2
    assert ctx.email and ctx.email.endswith("@example.com")
    assert ctx.metadata["token_acquired_via_relogin"] is True


def test_run_registration_job_dispatches_to_codexgen_pipeline(temp_db, monkeypatch):
    task_uuid = "task-codexgen-dispatch"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)

    created: dict[str, object] = {}

    def fake_resolve_email_service(**kwargs):
        return EmailServiceType.TEMPMAIL, {}, None

    def fake_create_email_service(service_type, config):
        service = FakeSharedEmailService()
        created["service"] = service
        return service

    def fake_build_codexgen_runtime(*, email_service, proxy_url, callback_logger, task_uuid):
        runtime = FakeCodexgenRuntime(email_service)
        created["runtime"] = runtime
        return runtime

    monkeypatch.setattr("src.core.registration_job._resolve_email_service", fake_resolve_email_service)
    monkeypatch.setattr("src.core.registration_job.EmailServiceFactory.create", fake_create_email_service)
    monkeypatch.setattr("src.core.registration_job.build_codexgen_runtime", fake_build_codexgen_runtime)

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-a",
        email_service_config={},
        pipeline_key="codexgen_pipeline",
        task_uuid=task_uuid,
    )

    assert result.success is True
    assert result.email == "tester@example.com"
    assert result.account_id is not None
    assert created["service"].create_calls == 1
    assert len(created["service"].otp_calls) == 2

    task = crud.get_registration_task_by_uuid(temp_db, task_uuid)
    assert task is not None
    assert task.status == "completed"
    assert task.email_address == "tester@example.com"
    assert task.result is not None
    assert task.result.get("success") is True
    assert task.result.get("access_token", "").endswith("...")
    assert task.result.get("access_token") != "access-1"
    assert task.result.get("metadata", {}).get("access_token", "").endswith("...")
    assert task.result.get("metadata", {}).get("refresh_token", "").endswith("...")
    assert task.completed_at is not None
    assert task.error_message in (None, "")


def test_run_registration_job_marks_task_failed_on_codexgen_pipeline_error(temp_db, monkeypatch):
    task_uuid = "task-codexgen-failed-dispatch"
    crud.create_registration_task(temp_db, task_uuid=task_uuid)

    def fake_resolve_email_service(**kwargs):
        return EmailServiceType.TEMPMAIL, {}, None

    class BrokenRuntime:
        def run_check_ip_location_step(self):
            raise RuntimeError("boom-codexgen")

    monkeypatch.setattr("src.core.registration_job._resolve_email_service", fake_resolve_email_service)
    monkeypatch.setattr(
        "src.core.registration_job.EmailServiceFactory.create",
        lambda *_: FakeSharedEmailService(),
    )
    monkeypatch.setattr(
        "src.core.registration_job.build_codexgen_runtime",
        lambda **_: BrokenRuntime(),
    )

    result = run_registration_job(
        db=temp_db,
        email_service_type="tempmail",
        email_service_id=None,
        proxy="http://proxy-a",
        email_service_config={},
        pipeline_key="codexgen_pipeline",
        task_uuid=task_uuid,
    )

    assert result.success is False
    assert "boom-codexgen" in (result.error_message or "")

    task = crud.get_registration_task_by_uuid(temp_db, task_uuid)
    assert task is not None
    assert task.status == "failed"
    assert task.completed_at is not None
    assert "boom-codexgen" in (task.error_message or "")


def test_codexgen_runtime_signup_otp_passes_otp_sent_at_to_shared_email_service(monkeypatch):
    class DummyResponse:
        def __init__(self, status_code=200):
            self.status_code = status_code

    class DummySession:
        def get(self, *_args, **_kwargs):
            return DummyResponse(200)

    email_service = FakeSharedEmailService()
    runtime = CodexgenPipelineRuntime(email_service=email_service, proxy_url=None, callback_logger=None, task_uuid=None)

    runtime._engine.session = DummySession()  # noqa: SLF001
    runtime._engine._is_existing_account = False  # noqa: SLF001
    runtime._engine.email = "tester@example.com"  # noqa: SLF001
    runtime._engine.email_info = {"service_id": "mailbox-1"}  # noqa: SLF001
    runtime._engine._otp_sent_at = None  # noqa: SLF001

    runtime.run_send_signup_otp_step()
    runtime.run_wait_signup_otp_step()

    assert runtime._engine._otp_sent_at is not None  # noqa: SLF001
    assert email_service.otp_calls
    assert email_service.otp_calls[-1]["otp_sent_at"] == runtime._engine._otp_sent_at  # noqa: SLF001


def test_get_proxy_ip_step_allows_no_proxy_preflight_noop():
    ctx = PipelineContext(
        task_uuid="task-no-proxy",
        pipeline_key="codexgen_pipeline",
        metadata={"registration_engine": object()},
    )
    payload = common_steps.get_proxy_ip_step(ctx)
    assert payload == {}


def test_get_proxy_ip_step_writes_proxy_ip_metadata_from_preflight():
    ctx = PipelineContext(
        task_uuid="task-proxy-ip",
        pipeline_key="codexgen_pipeline",
        metadata={
            "registration_engine": object(),
            "proxy_preflight_results": [
                {
                    "status": "available",
                    "proxy_id": 7,
                    "proxy_url": "http://proxy-a:8000",
                    "ip_address": "8.8.8.8",
                }
            ],
        },
    )
    payload = common_steps.get_proxy_ip_step(ctx)

    assert payload["proxy_url"] == "http://proxy-a:8000"
    assert payload["metadata"]["assigned_proxy_id"] == 7
    assert payload["metadata"]["proxy_ip"] == "8.8.8.8"


class _DummyFallbackResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _DummyCookieJar:
    def __init__(self, did: str | None):
        self._did = did

    def get(self, key: str, default=None):
        if key == "oai-did":
            return self._did
        return default


class _DummyFallbackSession:
    def __init__(self, responses: list[_DummyFallbackResponse], did: str | None = None):
        self._responses = responses
        self.cookies = _DummyCookieJar(did)
        self.post_calls = 0

    def post(self, *_args, **_kwargs):
        self.post_calls += 1
        return self._responses.pop(0)


def test_codexgen_fallback_raises_disallowed_error_when_first_post_blocked():
    runtime = CodexgenPipelineRuntime(email_service=FakeSharedEmailService(), proxy_url=None, callback_logger=None, task_uuid=None)
    runtime._engine.email = "tester@blocked.test"  # noqa: SLF001
    runtime._engine._check_sentinel = lambda _did: "sen-1"  # noqa: SLF001
    runtime._engine.session = _DummyFallbackSession(  # noqa: SLF001
        [
            _DummyFallbackResponse(
                status_code=400,
                payload={"error": {"code": "registration_disallowed", "message": "blocked first"}},
            )
        ],
        did="did-1",
    )

    with pytest.raises(RegistrationDisallowedSuffixError) as exc_info:
        runtime._run_create_account_fallback()  # noqa: SLF001

    assert exc_info.value.suffix == "blocked.test"
    assert runtime._engine.session.post_calls == 1  # noqa: SLF001


def test_codexgen_fallback_raises_disallowed_error_when_second_post_blocked():
    runtime = CodexgenPipelineRuntime(email_service=FakeSharedEmailService(), proxy_url=None, callback_logger=None, task_uuid=None)
    runtime._engine.email = "tester@blocked.test"  # noqa: SLF001
    runtime._engine.session = _DummyFallbackSession(  # noqa: SLF001
        [
            _DummyFallbackResponse(
                status_code=400,
                payload={"error": {"code": "other_error", "message": "retry"}},
            ),
            _DummyFallbackResponse(
                status_code=400,
                payload={"error": {"code": "registration_disallowed", "message": "blocked second"}},
            ),
        ],
        did=None,
    )

    with pytest.raises(RegistrationDisallowedSuffixError) as exc_info:
        runtime._run_create_account_fallback()  # noqa: SLF001

    assert exc_info.value.suffix == "blocked.test"
    assert runtime._engine.session.post_calls == 2  # noqa: SLF001


def test_codexgen_fallback_caches_generated_user_profile(monkeypatch):
    runtime = CodexgenPipelineRuntime(email_service=FakeSharedEmailService(), proxy_url=None, callback_logger=None, task_uuid=None)
    runtime._engine.email = "tester@example.com"  # noqa: SLF001
    runtime._engine.session = _DummyFallbackSession(  # noqa: SLF001
        [_DummyFallbackResponse(status_code=200, payload={})],
        did=None,
    )
    monkeypatch.setattr(
        "src.core.pipeline.steps.codexgen.generate_random_user_info",
        lambda: {"name": "Codex User", "birthdate": "1990-01-02"},
    )

    ok = runtime._run_create_account_fallback()  # noqa: SLF001

    assert ok is True
    assert runtime._engine.generated_user_profile == {"name": "Codex User", "birthdate": "1990-01-02"}  # noqa: SLF001
