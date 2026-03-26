from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from src.core.time import utc_now_naive
from src.database import crud
from src.database.models import Base
from src.database.session import DatabaseSessionManager
from src.database import session as session_module
from src.web.routes import payment as payment_routes


def _build_temp_session_manager(tmp_path: Path) -> DatabaseSessionManager:
    db_path = tmp_path / "payment-routes.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)
    return manager


def test_mark_subscription_sets_naive_subscription_time_for_paid_account(tmp_path, monkeypatch):
    manager = _build_temp_session_manager(tmp_path)
    monkeypatch.setattr(session_module, "_db_manager", manager)

    session = manager.SessionLocal()
    try:
        account = crud.create_account(
            session,
            email="paid@example.com",
            email_service="tempmail",
        )
    finally:
        session.close()

    response = payment_routes.mark_subscription(
        account.id,
        payment_routes.MarkSubscriptionRequest(subscription_type="plus"),
    )

    assert response == {"success": True, "subscription_type": "plus"}

    verify_session = manager.SessionLocal()
    try:
        persisted = crud.get_account_by_id(verify_session, account.id)
        assert persisted is not None
        assert persisted.subscription_type == "plus"
        assert persisted.subscription_at is not None
        assert persisted.subscription_at.tzinfo is None
    finally:
        verify_session.close()


def test_batch_check_subscription_sets_naive_subscription_time_for_successful_check(tmp_path, monkeypatch):
    manager = _build_temp_session_manager(tmp_path)
    monkeypatch.setattr(session_module, "_db_manager", manager)

    session = manager.SessionLocal()
    try:
        account = crud.create_account(
            session,
            email="batch@example.com",
            email_service="tempmail",
        )
    finally:
        session.close()

    monkeypatch.setattr(payment_routes, "resolve_account_ids", lambda *args, **kwargs: [account.id])
    monkeypatch.setattr(payment_routes, "check_subscription_status", lambda *args, **kwargs: "team")

    response = payment_routes.batch_check_subscription(
        payment_routes.BatchCheckSubscriptionRequest(
            ids=[account.id],
            proxy="http://proxy.local:8000",
        )
    )

    assert response["success_count"] == 1
    assert response["failed_count"] == 0
    assert response["details"][0]["subscription_type"] == "team"

    verify_session = manager.SessionLocal()
    try:
        persisted = crud.get_account_by_id(verify_session, account.id)
        assert persisted is not None
        assert persisted.subscription_type == "team"
        assert persisted.subscription_at is not None
        assert persisted.subscription_at.tzinfo is None
    finally:
        verify_session.close()


def test_generate_payment_link_rejects_invalid_plan_type(tmp_path, monkeypatch):
    manager = _build_temp_session_manager(tmp_path)
    monkeypatch.setattr(session_module, "_db_manager", manager)

    session = manager.SessionLocal()
    try:
        account = crud.create_account(
            session,
            email="invalid-plan@example.com",
            email_service="tempmail",
        )
    finally:
        session.close()

    with pytest.raises(HTTPException) as exc_info:
        payment_routes.generate_payment_link(
            payment_routes.GenerateLinkRequest(
                account_id=account.id,
                plan_type="enterprise",
            )
        )

    assert exc_info.value.status_code == 400
    assert "plan_type" in str(exc_info.value.detail)


def test_batch_check_subscription_reports_missing_account(tmp_path, monkeypatch):
    manager = _build_temp_session_manager(tmp_path)
    monkeypatch.setattr(session_module, "_db_manager", manager)
    monkeypatch.setattr(payment_routes, "resolve_account_ids", lambda *args, **kwargs: [999999])

    response = payment_routes.batch_check_subscription(
        payment_routes.BatchCheckSubscriptionRequest(
            ids=[999999],
            proxy="http://proxy.local:8000",
        )
    )

    assert response["success_count"] == 0
    assert response["failed_count"] == 1
    assert response["details"] == [
        {"id": 999999, "email": None, "success": False, "error": "账号不存在"}
    ]


def test_batch_check_subscription_clears_subscription_time_when_result_is_free(tmp_path, monkeypatch):
    manager = _build_temp_session_manager(tmp_path)
    monkeypatch.setattr(session_module, "_db_manager", manager)

    session = manager.SessionLocal()
    try:
        account = crud.create_account(
            session,
            email="free-now@example.com",
            email_service="tempmail",
        )
        account_id = account.id
        account.subscription_type = "plus"
        account.subscription_at = utc_now_naive()
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr(payment_routes, "resolve_account_ids", lambda *args, **kwargs: [account_id])
    monkeypatch.setattr(payment_routes, "check_subscription_status", lambda *args, **kwargs: "free")

    response = payment_routes.batch_check_subscription(
        payment_routes.BatchCheckSubscriptionRequest(
            ids=[account_id],
            proxy="http://proxy.local:8000",
        )
    )

    assert response["success_count"] == 1
    assert response["details"][0]["subscription_type"] == "free"

    verify_session = manager.SessionLocal()
    try:
        persisted = crud.get_account_by_id(verify_session, account_id)
        assert persisted is not None
        assert persisted.subscription_type is None
        assert persisted.subscription_at is None
    finally:
        verify_session.close()


def test_open_browser_incognito_rejects_blank_url_after_trim():
    with pytest.raises(HTTPException) as exc_info:
        payment_routes.open_browser_incognito(
            payment_routes.OpenIncognitoRequest(url="   ")
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "URL 不能为空"
