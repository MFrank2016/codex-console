from __future__ import annotations

from datetime import datetime
from datetime import timedelta

from src.core.openai import token_refresh as token_refresh_module
from src.core.openai.token_refresh import TokenRefreshManager, TokenRefreshResult
from src.core.time import utc_now_naive
from src.database import crud
from src.database.models import Base
from src.database.session import DatabaseSessionManager
from src.database import session as session_module


def _build_temp_session_manager(tmp_path) -> DatabaseSessionManager:
    db_path = tmp_path / "token-refresh-extra.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)
    return manager


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return dict(self._payload)


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.cookies = type(
            "_CookieJar",
            (),
            {"set": lambda self, *args, **kwargs: None},
        )()

    def get(self, *args, **kwargs):
        return self._response

    def post(self, *args, **kwargs):
        return self._response


def test_refresh_by_session_token_normalizes_expiry_to_naive_utc(monkeypatch):
    manager = TokenRefreshManager(proxy_url="http://proxy.local:8000")
    fake_response = _FakeResponse(
        200,
        {
            "accessToken": "new-session-access-token",
            "expires": "2026-03-26T12:34:56Z",
        },
    )
    monkeypatch.setattr(manager, "_create_session", lambda: _FakeSession(fake_response))

    result = manager.refresh_by_session_token("session-token")

    assert result.success is True
    assert result.expires_at == datetime(2026, 3, 26, 12, 34, 56)
    assert result.expires_at.tzinfo is None


def test_refresh_by_oauth_token_returns_naive_expiry(monkeypatch):
    manager = TokenRefreshManager(proxy_url="http://proxy.local:8000")
    fake_response = _FakeResponse(
        200,
        {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 7200,
        },
    )
    monkeypatch.setattr(manager, "_create_session", lambda: _FakeSession(fake_response))

    result = manager.refresh_by_oauth_token(
        refresh_token="old-refresh-token",
        client_id="client-id",
    )

    assert result.success is True
    assert result.expires_at is not None
    assert result.expires_at.tzinfo is None


def test_refresh_account_token_persists_naive_last_refresh(tmp_path, monkeypatch):
    db_path = tmp_path / "token-refresh.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)
    monkeypatch.setattr(session_module, "_db_manager", manager)

    session = manager.SessionLocal()
    try:
        account = crud.create_account(
            session,
            email="refresh@example.com",
            email_service="tempmail",
            refresh_token="refresh-token",
            access_token="old-access-token",
        )
    finally:
        session.close()

    fake_result = TokenRefreshResult(
        success=True,
        access_token="updated-access-token",
        refresh_token="updated-refresh-token",
        expires_at=utc_now_naive() + timedelta(hours=1),
    )
    monkeypatch.setattr(
        token_refresh_module.TokenRefreshManager,
        "refresh_account",
        lambda self, account: fake_result,
    )

    result = token_refresh_module.refresh_account_token(account.id, proxy_url="http://proxy.local:8000")

    assert result.success is True

    verify_session = manager.SessionLocal()
    try:
        persisted = crud.get_account_by_id(verify_session, account.id)
        assert persisted is not None
        assert persisted.access_token == "updated-access-token"
        assert persisted.refresh_token == "updated-refresh-token"
        assert persisted.last_refresh is not None
        assert persisted.last_refresh.tzinfo is None
    finally:
        verify_session.close()


def test_refresh_by_oauth_token_returns_http_failure(monkeypatch):
    manager = TokenRefreshManager(proxy_url="http://proxy.local:8000")
    fake_response = _FakeResponse(500, {"error": "upstream failed"})
    monkeypatch.setattr(manager, "_create_session", lambda: _FakeSession(fake_response))

    result = manager.refresh_by_oauth_token(
        refresh_token="old-refresh-token",
        client_id="client-id",
    )

    assert result.success is False
    assert "HTTP 500" in result.error_message


def test_refresh_by_oauth_token_accepts_string_expires_in(monkeypatch):
    manager = TokenRefreshManager(proxy_url="http://proxy.local:8000")
    fake_response = _FakeResponse(
        200,
        {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": "7200",
        },
    )
    monkeypatch.setattr(manager, "_create_session", lambda: _FakeSession(fake_response))

    result = manager.refresh_by_oauth_token(
        refresh_token="old-refresh-token",
        client_id="client-id",
    )

    assert result.success is True
    assert result.expires_at is not None
    assert result.expires_at.tzinfo is None


def test_refresh_account_token_returns_not_found_for_missing_account(tmp_path, monkeypatch):
    manager = _build_temp_session_manager(tmp_path)
    monkeypatch.setattr(session_module, "_db_manager", manager)

    result = token_refresh_module.refresh_account_token(999999, proxy_url="http://proxy.local:8000")

    assert result.success is False
    assert result.error_message == "账号不存在"


def test_validate_token_maps_http_statuses(monkeypatch):
    manager = TokenRefreshManager(proxy_url="http://proxy.local:8000")

    monkeypatch.setattr(manager, "_create_session", lambda: _FakeSession(_FakeResponse(401, {})))
    assert manager.validate_token("access-token") == (False, "Token 无效或已过期")

    monkeypatch.setattr(manager, "_create_session", lambda: _FakeSession(_FakeResponse(403, {})))
    assert manager.validate_token("access-token") == (False, "账号可能被封禁")

    monkeypatch.setattr(manager, "_create_session", lambda: _FakeSession(_FakeResponse(500, {})))
    assert manager.validate_token("access-token") == (False, "验证失败: HTTP 500")


def test_validate_account_token_handles_missing_account_and_missing_access_token(tmp_path, monkeypatch):
    manager = _build_temp_session_manager(tmp_path)
    monkeypatch.setattr(session_module, "_db_manager", manager)

    missing_result = token_refresh_module.validate_account_token(999999, proxy_url="http://proxy.local:8000")
    assert missing_result == (False, "账号不存在")

    session = manager.SessionLocal()
    try:
        account = crud.create_account(
            session,
            email="no-access-token@example.com",
            email_service="tempmail",
        )
        account_id = account.id
    finally:
        session.close()

    no_access_token_result = token_refresh_module.validate_account_token(account_id, proxy_url="http://proxy.local:8000")
    assert no_access_token_result == (False, "账号没有 access_token")


def test_refresh_account_token_marks_refresh_failure_and_clears_transient_invalid_state_on_success(tmp_path, monkeypatch):
    manager = _build_temp_session_manager(tmp_path)
    monkeypatch.setattr(session_module, "_db_manager", manager)

    session = manager.SessionLocal()
    try:
        account = crud.create_account(
            session,
            email="refresh-state@example.com",
            email_service="tempmail",
            refresh_token="refresh-token",
            access_token="old-access-token",
        )
        account_id = account.id
    finally:
        session.close()

    monkeypatch.setattr(
        token_refresh_module.TokenRefreshManager,
        "refresh_account",
        lambda self, account: TokenRefreshResult(success=False, error_message="boom"),
    )

    failed = token_refresh_module.refresh_account_token(account_id, proxy_url="http://proxy.local:8000")
    assert failed.success is False

    verify_session = manager.SessionLocal()
    try:
        persisted = crud.get_account_by_id(verify_session, account_id)
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.invalid_reason == "refresh_failed"
        assert persisted.invalidated_at is not None
    finally:
        verify_session.close()

    monkeypatch.setattr(
        token_refresh_module.TokenRefreshManager,
        "refresh_account",
        lambda self, account: TokenRefreshResult(
            success=True,
            access_token="updated-access-token",
            refresh_token="updated-refresh-token",
            expires_at=utc_now_naive() + timedelta(hours=1),
        ),
    )

    refreshed = token_refresh_module.refresh_account_token(account_id, proxy_url="http://proxy.local:8000")
    assert refreshed.success is True

    verify_session = manager.SessionLocal()
    try:
        persisted = crud.get_account_by_id(verify_session, account_id)
        assert persisted is not None
        assert persisted.status == "active"
        assert persisted.invalid_reason is None
        assert persisted.invalidated_at is None
        assert persisted.last_refresh is not None
    finally:
        verify_session.close()


def test_validate_account_token_persists_invalid_reason_and_clears_it_after_recovery(tmp_path, monkeypatch):
    manager = _build_temp_session_manager(tmp_path)
    monkeypatch.setattr(session_module, "_db_manager", manager)

    session = manager.SessionLocal()
    try:
        account = crud.create_account(
            session,
            email="validate-state@example.com",
            email_service="tempmail",
            access_token="access-token",
        )
        account_id = account.id
    finally:
        session.close()

    monkeypatch.setattr(
        token_refresh_module.TokenRefreshManager,
        "validate_token",
        lambda self, access_token: (False, "Token 无效或已过期"),
    )
    invalid_result = token_refresh_module.validate_account_token(account_id, proxy_url="http://proxy.local:8000")
    assert invalid_result == (False, "Token 无效或已过期")

    verify_session = manager.SessionLocal()
    try:
        persisted = crud.get_account_by_id(verify_session, account_id)
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.invalid_reason == "token_invalid"
        assert persisted.invalidated_at is not None
    finally:
        verify_session.close()

    monkeypatch.setattr(
        token_refresh_module.TokenRefreshManager,
        "validate_token",
        lambda self, access_token: (True, None),
    )
    valid_result = token_refresh_module.validate_account_token(account_id, proxy_url="http://proxy.local:8000")
    assert valid_result == (True, None)

    verify_session = manager.SessionLocal()
    try:
        persisted = crud.get_account_by_id(verify_session, account_id)
        assert persisted is not None
        assert persisted.status == "active"
        assert persisted.invalid_reason is None
        assert persisted.invalidated_at is None
    finally:
        verify_session.close()
