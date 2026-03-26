from __future__ import annotations

from datetime import timedelta

from src.core.openai import token_refresh as token_refresh_module
from src.core.openai.token_refresh import TokenRefreshManager, TokenRefreshResult
from src.core.time import utc_now_naive
from src.database import crud
from src.database.models import Base
from src.database.session import DatabaseSessionManager
from src.database import session as session_module


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

    def post(self, *args, **kwargs):
        return self._response


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
