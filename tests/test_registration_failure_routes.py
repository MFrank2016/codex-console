from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.registration_query_dtos import (
    RegistrationFailureListView,
    RegistrationFailureSummaryView,
)
from src.database.models import Base
from src.database.repositories import registration_failure_repository as failure_repo
from src.database import session as session_module
from src.database.session import DatabaseSessionManager
from src.web.auth import auth_token, effective_access_password
from src.web.routes import api_router
from src.web.routes import registration as registration_routes


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "registration-failure-routes.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)
    manager.migrate_tables()
    monkeypatch.setattr(session_module, "_db_manager", manager)

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
def client(route_db):
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_cookie():
    return {"webui_auth": auth_token(effective_access_password())}


def _create_failure(
    db,
    *,
    task_uuid: str,
    failed_at: datetime,
    email: str,
    email_suffix: str,
    email_service_id: int | None = None,
    error_code: str = "registration_disallowed",
    error_detail: str = "registration_disallowed detail",
    proxy_ip: str | None = None,
    failure_stage: str | None = None,
    step_key: str | None = None,
    retryable: bool = False,
):
    row = failure_repo.upsert_registration_failure_record(
        db,
        task_uuid=task_uuid,
        attempt_no=1,
        batch_id="batch-1",
        pipeline_key="current_pipeline",
        registration_mode="batch",
        email=email,
        email_suffix=email_suffix,
        email_service_id=email_service_id,
        email_service_type="tempmail",
        display_name="Alice Smith",
        birthdate="1994-02-03",
        proxy="http://proxy-a",
        proxy_ip=proxy_ip,
        failure_stage=failure_stage,
        step_key=step_key,
        retryable=retryable,
        error_code=error_code,
        error_detail=error_detail,
        failed_at=failed_at,
        extra_json={"step": "create_account_profile"},
    )
    db.commit()
    return row


def test_registration_failures_summary_requires_auth(client):
    response = client.get("/api/registration/failures/summary")
    assert response.status_code == 401


def test_registration_failures_summary_defaults_to_recent_7_days(client, auth_cookie, route_db, monkeypatch):
    fixed_now = datetime(2026, 3, 28, 4, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(registration_routes, "utc_now", lambda: fixed_now)

    _create_failure(
        route_db,
        task_uuid="task-today",
        failed_at=datetime(2026, 3, 28, 2, 0, 0),
        email="today@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.1",
    )
    _create_failure(
        route_db,
        task_uuid="task-window",
        failed_at=datetime(2026, 3, 24, 2, 0, 0),
        email="window@other.test",
        email_suffix="other.test",
        proxy_ip="2.2.2.2",
        error_code="proxy_error",
        error_detail="proxy timeout",
    )
    _create_failure(
        route_db,
        task_uuid="task-old",
        failed_at=datetime(2026, 3, 20, 1, 59, 59),
        email="old@old.test",
        email_suffix="old.test",
        proxy_ip="3.3.3.3",
    )

    response = client.get("/api/registration/failures/summary", cookies=auth_cookie)
    body = response.json()

    assert response.status_code == 200
    assert body["total_failed_attempts"] == 2
    assert body["today_failed_attempts"] == 1


def test_registration_failures_summary_returns_zero_today_when_window_excludes_current_shanghai_day(client, auth_cookie, route_db, monkeypatch):
    fixed_now = datetime(2026, 3, 28, 4, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(registration_routes, "utc_now", lambda: fixed_now)

    _create_failure(
        route_db,
        task_uuid="task-history",
        failed_at=datetime(2026, 3, 20, 12, 0, 0),
        email="history@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.1",
    )

    response = client.get(
        "/api/registration/failures/summary?failed_from=2026-03-20T00:00:00&failed_to=2026-03-20T23:59:59",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    assert response.json()["today_failed_attempts"] == 0


def test_registration_failures_list_supports_failed_to_only_window(client, auth_cookie, route_db):
    _create_failure(
        route_db,
        task_uuid="task-before-window",
        failed_at=datetime(2026, 3, 21, 1, 59, 59),
        email="before@a.test",
        email_suffix="a.test",
    )
    _create_failure(
        route_db,
        task_uuid="task-window-start",
        failed_at=datetime(2026, 3, 21, 2, 0, 0),
        email="start@b.test",
        email_suffix="b.test",
    )
    _create_failure(
        route_db,
        task_uuid="task-window-end",
        failed_at=datetime(2026, 3, 28, 2, 0, 0),
        email="end@c.test",
        email_suffix="c.test",
    )

    response = client.get(
        "/api/registration/failures?failed_to=2026-03-28T10:00:00",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_registration_failures_list_treats_naive_datetime_as_asia_shanghai(client, auth_cookie, route_db):
    _create_failure(
        route_db,
        task_uuid="task-shanghai-hit",
        failed_at=datetime(2026, 3, 28, 2, 0, 0),
        email="hit@blocked.test",
        email_suffix="blocked.test",
    )
    _create_failure(
        route_db,
        task_uuid="task-shanghai-miss",
        failed_at=datetime(2026, 3, 28, 10, 0, 0),
        email="miss@blocked.test",
        email_suffix="blocked.test",
    )

    response = client.get(
        "/api/registration/failures?failed_from=2026-03-28T10:00:00&failed_to=2026-03-28T10:00:00",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["task_uuid"] == "task-shanghai-hit"


def test_registration_failures_list_uses_closed_interval_boundaries(client, auth_cookie, route_db):
    _create_failure(
        route_db,
        task_uuid="task-edge-from",
        failed_at=datetime(2026, 3, 28, 0, 0, 0),
        email="from@blocked.test",
        email_suffix="blocked.test",
    )
    _create_failure(
        route_db,
        task_uuid="task-edge-to",
        failed_at=datetime(2026, 3, 28, 1, 0, 0),
        email="to@blocked.test",
        email_suffix="blocked.test",
    )

    response = client.get(
        "/api/registration/failures?failed_from=2026-03-28T00:00:00Z&failed_to=2026-03-28T01:00:00Z",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    assert [item["task_uuid"] for item in response.json()["items"]] == ["task-edge-to", "task-edge-from"]


def test_registration_failures_list_uses_request_time_as_now_when_only_failed_from(client, auth_cookie, route_db, monkeypatch):
    fixed_now = datetime(2026, 3, 28, 4, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(registration_routes, "utc_now", lambda: fixed_now)

    _create_failure(
        route_db,
        task_uuid="task-after-from",
        failed_at=datetime(2026, 3, 28, 3, 0, 0),
        email="after@blocked.test",
        email_suffix="blocked.test",
    )
    _create_failure(
        route_db,
        task_uuid="task-after-now",
        failed_at=datetime(2026, 3, 28, 4, 0, 1),
        email="late@blocked.test",
        email_suffix="blocked.test",
    )

    response = client.get(
        "/api/registration/failures?failed_from=2026-03-28T09:00:00",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["task_uuid"] == "task-after-from"


def test_registration_failures_list_rejects_failed_from_greater_than_failed_to(client, auth_cookie):
    response = client.get(
        "/api/registration/failures?failed_from=2026-03-29T10:00:00&failed_to=2026-03-28T10:00:00",
        cookies=auth_cookie,
    )
    assert response.status_code == 400


def test_registration_failures_list_filters_by_keyword_suffix_and_page(client, auth_cookie, route_db, monkeypatch):
    fixed_now = datetime(2026, 3, 28, 4, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(registration_routes, "utc_now", lambda: fixed_now)

    _create_failure(
        route_db,
        task_uuid="task-blocked-1",
        failed_at=datetime(2026, 3, 28, 3, 0, 0),
        email="one@blocked.test",
        email_suffix="blocked.test",
        error_code="registration_disallowed",
        error_detail="blocked one",
    )
    _create_failure(
        route_db,
        task_uuid="task-blocked-2",
        failed_at=datetime(2026, 3, 28, 3, 1, 0),
        email="two@semi-blocked.test",
        email_suffix="semi-blocked.test",
        error_code="REGISTRATION_DISALLOWED",
        error_detail="blocked two",
    )
    _create_failure(
        route_db,
        task_uuid="task-other",
        failed_at=datetime(2026, 3, 28, 3, 2, 0),
        email="other@ok.test",
        email_suffix="ok.test",
        error_code="proxy_error",
        error_detail="network timeout",
    )

    response = client.get(
        "/api/registration/failures?email_suffix=blocked&error_keyword=registration_disallowed&page=1&page_size=1",
        cookies=auth_cookie,
    )
    body = response.json()

    assert response.status_code == 200
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["email_suffix"] == "semi-blocked.test"


def test_registration_failures_list_filters_by_proxy_ip_and_email_service_id(client, auth_cookie, route_db):
    _create_failure(
        route_db,
        task_uuid="task-ip-email-service-hit",
        failed_at=datetime(2026, 3, 28, 3, 0, 0),
        email="one@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="8.8.8.8",
        email_service_id=42,
    )
    _create_failure(
        route_db,
        task_uuid="task-ip-miss",
        failed_at=datetime(2026, 3, 28, 3, 1, 0),
        email="two@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="9.9.9.9",
        email_service_id=42,
    )
    _create_failure(
        route_db,
        task_uuid="task-service-miss",
        failed_at=datetime(2026, 3, 28, 3, 2, 0),
        email="three@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="8.8.8.8",
        email_service_id=7,
    )

    response = client.get(
        "/api/registration/failures?proxy_ip=8.8.8.8&email_service_id=42",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["task_uuid"] == "task-ip-email-service-hit"
    assert body["items"][0]["email_service_id"] == 42


def test_registration_failures_summary_filters_by_proxy_ip_and_email_service_id(client, auth_cookie, route_db):
    _create_failure(
        route_db,
        task_uuid="task-summary-hit-1",
        failed_at=datetime(2026, 3, 28, 3, 0, 0),
        email="one@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="8.8.4.4",
        email_service_id=99,
        error_code="proxy_error",
    )
    _create_failure(
        route_db,
        task_uuid="task-summary-hit-2",
        failed_at=datetime(2026, 3, 28, 3, 1, 0),
        email="two@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="8.8.4.4",
        email_service_id=99,
        error_code="registration_disallowed",
    )
    _create_failure(
        route_db,
        task_uuid="task-summary-miss",
        failed_at=datetime(2026, 3, 28, 3, 2, 0),
        email="other@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.1",
        email_service_id=99,
        error_code="registration_disallowed",
    )

    response = client.get(
        "/api/registration/failures/summary?proxy_ip=8.8.4.4&email_service_id=99",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_failed_attempts"] == 2
    assert body["top_proxy_ips"][0] == {"value": "8.8.4.4", "count": 2}


def test_registration_failures_summary_supports_structured_filters_and_fields(client, auth_cookie, route_db):
    _create_failure(
        route_db,
        task_uuid="task-structured-hit",
        failed_at=datetime(2026, 3, 28, 3, 0, 0),
        email="one@blocked.test",
        email_suffix="blocked.test",
        failure_stage="submit_login_password",
        step_key="submit_login_password",
        retryable=True,
    )
    _create_failure(
        route_db,
        task_uuid="task-structured-miss",
        failed_at=datetime(2026, 3, 28, 3, 1, 0),
        email="two@blocked.test",
        email_suffix="blocked.test",
        failure_stage="exchange_oauth_token",
        step_key="exchange_oauth_token",
        retryable=False,
    )

    response = client.get(
        "/api/registration/failures/summary"
        "?failure_stage=submit_login_password"
        "&step_key=submit_login_password"
        "&retryable=true",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_failed_attempts"] == 1
    assert body["top_failure_stages"] == [{"value": "submit_login_password", "count": 1}]
    assert body["top_step_keys"] == [{"value": "submit_login_password", "count": 1}]
    assert body["retryable_breakdown"] == [{"value": "retryable", "count": 1}]


def test_registration_failures_summary_route_delegates_to_facade(client, auth_cookie, monkeypatch):
    captured: dict[str, object] = {}

    class _FakeFacade:
        def build_failure_summary(self, **kwargs):
            captured.update(kwargs)
            return RegistrationFailureSummaryView(
                total_failed_attempts=3,
                today_failed_attempts=2,
                top_email_suffixes=[{"value": "blocked.test", "count": 3}],
                top_error_codes=[{"value": "registration_disallowed", "count": 3}],
                top_proxy_ips=[{"value": "8.8.8.8", "count": 3}],
                top_failure_stages=[{"value": "submit_login_password", "count": 2}],
                top_step_keys=[{"value": "submit_login_password", "count": 2}],
                retryable_breakdown=[{"value": "retryable", "count": 2}],
            )

    def _boom_get_db():
        raise AssertionError("route 不应直接调用 get_db")

    monkeypatch.setattr(registration_routes, "get_db", _boom_get_db)
    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: _FakeFacade())

    response = client.get(
        "/api/registration/failures/summary"
        "?pipeline_key=current_pipeline"
        "&failure_stage=submit_login_password"
        "&step_key=submit_login_password"
        "&retryable=true"
        "&failed_from=2026-03-28T00:00:00"
        "&failed_to=2026-03-28T10:00:00",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    assert response.json()["today_failed_attempts"] == 2
    assert captured["pipeline_key"] == "current_pipeline"
    assert captured["failure_stage"] == "submit_login_password"
    assert captured["step_key"] == "submit_login_password"
    assert captured["retryable"] is True
    assert captured["failed_from"] == "2026-03-28T00:00:00"
    assert captured["failed_to"] == "2026-03-28T10:00:00"


def test_registration_failures_list_route_delegates_to_facade_without_page_normalization(
    client, auth_cookie, monkeypatch
):
    captured: dict[str, object] = {}

    class _FakeFacade:
        def list_failures(self, **kwargs):
            captured.update(kwargs)
            return RegistrationFailureListView(
                total=7,
                items=[{"id": 1, "task_uuid": "task-1", "attempt_no": 1, "pipeline_key": "current_pipeline", "registration_mode": "batch", "error_code": "proxy_error", "error_detail": "timeout"}],
            )

    def _boom_get_db():
        raise AssertionError("route 不应直接调用 get_db")

    monkeypatch.setattr(registration_routes, "get_db", _boom_get_db)
    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: _FakeFacade())

    response = client.get(
        "/api/registration/failures?page=0&page_size=999&failed_from=2026-03-28T00:00:00",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 7
    assert captured["page"] == 0
    assert captured["page_size"] == 999
    assert captured["failed_from"] == "2026-03-28T00:00:00"


def test_registration_failures_list_supports_structured_filters_and_response_fields(
    client, auth_cookie, route_db
):
    _create_failure(
        route_db,
        task_uuid="task-structured-hit",
        failed_at=datetime(2026, 3, 28, 3, 0, 0),
        email="one@blocked.test",
        email_suffix="blocked.test",
        failure_stage="submit_login_password",
        step_key="submit_login_password",
        retryable=True,
    )
    _create_failure(
        route_db,
        task_uuid="task-structured-miss",
        failed_at=datetime(2026, 3, 28, 3, 1, 0),
        email="two@blocked.test",
        email_suffix="blocked.test",
        failure_stage="exchange_oauth_token",
        step_key="exchange_oauth_token",
        retryable=False,
    )

    response = client.get(
        "/api/registration/failures"
        "?failure_stage=submit_login_password"
        "&step_key=submit_login_password"
        "&retryable=true",
        cookies=auth_cookie,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["task_uuid"] == "task-structured-hit"
    assert body["items"][0]["failure_stage"] == "submit_login_password"
    assert body["items"][0]["step_key"] == "submit_login_password"
    assert body["items"][0]["retryable"] is True


def test_registration_failures_routes_convert_facade_value_error_to_http_400(
    client, auth_cookie, monkeypatch
):
    class _FakeFacade:
        def build_failure_summary(self, **kwargs):
            raise ValueError("bad summary window")

        def list_failures(self, **kwargs):
            raise ValueError("bad list window")

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: _FakeFacade())

    summary_resp = client.get("/api/registration/failures/summary", cookies=auth_cookie)
    list_resp = client.get("/api/registration/failures", cookies=auth_cookie)

    assert summary_resp.status_code == 400
    assert summary_resp.json()["detail"] == "bad summary window"
    assert list_resp.status_code == 400
    assert list_resp.json()["detail"] == "bad list window"
