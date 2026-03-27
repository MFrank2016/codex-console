from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database.models import Base
from src.database.session import DatabaseSessionManager
from src.web.routes import settings as settings_routes


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "email-suffix-blacklist-routes.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(monkeypatch, temp_db):
    @contextmanager
    def _get_db():
        yield temp_db

    monkeypatch.setattr(settings_routes, "get_db", _get_db)

    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api/settings")

    with TestClient(app) as test_client:
        yield test_client


def test_email_suffix_blacklist_crud_and_filters(client):
    create_response = client.post(
        "/api/settings/email-suffix-blacklist",
        json={"suffix": "@BadMail.COM", "reason": "manual"},
    )
    assert create_response.status_code == 200
    created = create_response.json()["item"]
    row_id = created["id"]
    assert created["suffix"] == "badmail.com"
    assert created["enabled"] is True

    list_response = client.get("/api/settings/email-suffix-blacklist")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    patch_response = client.patch(
        f"/api/settings/email-suffix-blacklist/{row_id}",
        json={"enabled": False, "reason": "disabled for verify"},
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()["item"]
    assert patched["enabled"] is False
    assert patched["reason"] == "disabled for verify"

    filter_by_keyword = client.get(
        "/api/settings/email-suffix-blacklist",
        params={"keyword": "badmail", "enabled": "false"},
    )
    assert filter_by_keyword.status_code == 200
    filter_payload = filter_by_keyword.json()
    assert filter_payload["total"] == 1
    assert filter_payload["items"][0]["id"] == row_id

    delete_response = client.delete(f"/api/settings/email-suffix-blacklist/{row_id}")
    assert delete_response.status_code == 200

    after_delete = client.get("/api/settings/email-suffix-blacklist")
    assert after_delete.status_code == 200
    assert after_delete.json()["total"] == 0


def test_email_suffix_blacklist_rejects_full_email_value(client):
    response = client.post(
        "/api/settings/email-suffix-blacklist",
        json={"suffix": "foo@bar.com"},
    )
    assert response.status_code == 400
