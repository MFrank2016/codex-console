from __future__ import annotations

from pathlib import Path

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
