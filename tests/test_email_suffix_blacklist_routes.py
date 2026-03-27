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


def test_email_suffix_blacklist_rejects_multi_at_value(client):
    response = client.post(
        "/api/settings/email-suffix-blacklist",
        json={"suffix": "@foo@bar.com"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"suffix": None},
        {"suffix": ""},
        {"suffix": "   "},
    ],
)
def test_email_suffix_blacklist_rejects_empty_suffix_as_400(client, payload):
    response = client.post(
        "/api/settings/email-suffix-blacklist",
        json=payload,
    )
    assert response.status_code == 400


def test_email_suffix_blacklist_duplicate_create_returns_409(client):
    first = client.post(
        "/api/settings/email-suffix-blacklist",
        json={"suffix": "badmail.com"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/settings/email-suffix-blacklist",
        json={"suffix": "@BadMail.COM"},
    )
    assert second.status_code == 409


def test_email_suffix_blacklist_patch_duplicate_suffix_returns_409(client):
    first = client.post(
        "/api/settings/email-suffix-blacklist",
        json={"suffix": "first.com"},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/settings/email-suffix-blacklist",
        json={"suffix": "second.com"},
    )
    assert second.status_code == 200

    second_id = second.json()["item"]["id"]
    response = client.patch(
        f"/api/settings/email-suffix-blacklist/{second_id}",
        json={"suffix": "FIRST.com"},
    )
    assert response.status_code == 409


def test_email_suffix_blacklist_patch_missing_row_returns_404(client):
    response = client.patch(
        "/api/settings/email-suffix-blacklist/999999",
        json={"reason": "missing"},
    )
    assert response.status_code == 404


def test_email_suffix_blacklist_delete_missing_row_returns_404(client):
    response = client.delete("/api/settings/email-suffix-blacklist/999999")
    assert response.status_code == 404


def test_email_suffix_blacklist_patch_suffix_none_returns_400(client):
    created = client.post(
        "/api/settings/email-suffix-blacklist",
        json={"suffix": "seed.com"},
    )
    assert created.status_code == 200
    row_id = created.json()["item"]["id"]

    response = client.patch(
        f"/api/settings/email-suffix-blacklist/{row_id}",
        json={"suffix": None},
    )
    assert response.status_code == 400


def test_email_suffix_blacklist_patch_enabled_none_returns_400(client):
    created = client.post(
        "/api/settings/email-suffix-blacklist",
        json={"suffix": "seed-enabled.com"},
    )
    assert created.status_code == 200
    row_id = created.json()["item"]["id"]

    response = client.patch(
        f"/api/settings/email-suffix-blacklist/{row_id}",
        json={"enabled": None},
    )
    assert response.status_code == 400
