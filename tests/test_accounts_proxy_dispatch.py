from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database import crud
from src.database import session as session_module
from src.database.models import Base
from src.database.session import DatabaseSessionManager
from src.web.routes import api_router
from src.web.routes import accounts as accounts_routes


def test_batch_request_models_include_primary_cpa_service_id_filter():
    model_classes = [
        accounts_routes.BatchDeleteRequest,
        accounts_routes.BatchExportRequest,
        accounts_routes.BatchRefreshRequest,
        accounts_routes.BatchValidateRequest,
        accounts_routes.BatchCPAUploadRequest,
        accounts_routes.BatchSub2ApiUploadRequest,
        accounts_routes.BatchUploadTMRequest,
    ]

    for model_cls in model_classes:
        assert "primary_cpa_service_id_filter" in model_cls.model_fields


def test_resolve_account_ids_filters_by_primary_cpa_service_id(route_db):
    first = crud.create_account(
        route_db,
        email="cpa-one@example.com",
        email_service="tempmail",
        status="active",
    )
    second = crud.create_account(
        route_db,
        email="cpa-two@example.com",
        email_service="tempmail",
        status="active",
    )
    crud.update_account(route_db, first.id, primary_cpa_service_id=7)
    crud.update_account(route_db, second.id, primary_cpa_service_id=8)

    ids = accounts_routes.resolve_account_ids(
        route_db,
        [],
        True,
        primary_cpa_service_id_filter=7,
    )

    assert ids == [first.id]


def test_get_proxy_uses_unified_proxy_dispatch_service_with_legacy_dispatcher(monkeypatch):
    class FakeDispatchService:
        def resolve_single_proxy(self, task_group, explicit_proxy, overrides):
            assert task_group == "generic_single"
            assert explicit_proxy is None
            assert overrides == {}
            return SimpleNamespace(proxy_url="http://dispatch-picked:8000")

    monkeypatch.setattr(accounts_routes, "_build_proxy_dispatch_service", lambda: FakeDispatchService())

    assert accounts_routes._get_proxy() == "http://dispatch-picked:8000"


def test_get_proxy_passes_use_proxy_when_dispatcher_supports_it(monkeypatch):
    captured = {}

    class FakeDispatchService:
        def resolve_single_proxy(self, task_group, explicit_proxy, overrides, *, use_proxy):
            captured["task_group"] = task_group
            captured["explicit_proxy"] = explicit_proxy
            captured["overrides"] = overrides
            captured["use_proxy"] = use_proxy
            return SimpleNamespace(proxy_url="http://dispatch-picked:8000")

    monkeypatch.setattr(accounts_routes, "_build_proxy_dispatch_service", lambda: FakeDispatchService())

    assert accounts_routes._get_proxy() == "http://dispatch-picked:8000"
    assert captured == {
        "task_group": "generic_single",
        "explicit_proxy": None,
        "overrides": {},
        "use_proxy": True,
    }


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "accounts-proxy-dispatch.db"
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

    monkeypatch.setattr(accounts_routes, "get_db", _get_db)
    return temp_db


@pytest.fixture
def client(route_db):
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded_account(route_db):
    return crud.create_account(
        route_db,
        email="proxy-check@example.com",
        email_service="tempmail",
        access_token="access-token",
        refresh_token="refresh-token",
        status="active",
    )


def test_refresh_endpoint_keeps_working_with_new_dispatcher_signature(monkeypatch, client, seeded_account):
    captured = {}

    class FakeDispatchService:
        def resolve_single_proxy(self, task_group, explicit_proxy, overrides, *, use_proxy):
            captured["task_group"] = task_group
            captured["explicit_proxy"] = explicit_proxy
            captured["overrides"] = overrides
            captured["use_proxy"] = use_proxy
            return SimpleNamespace(proxy_url="http://dispatch-picked:8000")

    monkeypatch.setattr(accounts_routes, "_build_proxy_dispatch_service", lambda: FakeDispatchService())

    def fake_refresh(account_id, proxy):
        assert account_id == seeded_account.id
        assert proxy == "http://dispatch-picked:8000"
        return SimpleNamespace(success=False, error_message="refresh failed", expires_at=None)

    monkeypatch.setattr(accounts_routes, "do_refresh", fake_refresh)

    response = client.post(f"/api/accounts/{seeded_account.id}/refresh", json={})

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "error": "refresh failed",
    }
    assert captured == {
        "task_group": "generic_single",
        "explicit_proxy": None,
        "overrides": {},
        "use_proxy": True,
    }


def test_batch_validate_endpoint_keeps_working_with_new_dispatcher_signature(monkeypatch, client, seeded_account):
    captured = {}

    class FakeDispatchService:
        def resolve_single_proxy(self, task_group, explicit_proxy, overrides, *, use_proxy):
            captured["task_group"] = task_group
            captured["explicit_proxy"] = explicit_proxy
            captured["overrides"] = overrides
            captured["use_proxy"] = use_proxy
            return SimpleNamespace(proxy_url="http://dispatch-picked:8000")

    monkeypatch.setattr(accounts_routes, "_build_proxy_dispatch_service", lambda: FakeDispatchService())

    def fake_validate(account_id, proxy):
        assert account_id == seeded_account.id
        assert proxy == "http://dispatch-picked:8000"
        return False, "token invalid"

    monkeypatch.setattr(accounts_routes, "do_validate", fake_validate)

    response = client.post("/api/accounts/batch-validate", json={"ids": [seeded_account.id]})

    assert response.status_code == 200
    assert response.json() == {
        "valid_count": 0,
        "invalid_count": 1,
        "details": [
            {
                "id": seeded_account.id,
                "valid": False,
                "error": "token invalid",
            }
        ],
    }
    assert captured == {
        "task_group": "generic_single",
        "explicit_proxy": None,
        "overrides": {},
        "use_proxy": True,
    }


def test_batch_validate_endpoint_forwards_primary_cpa_service_id_filter(monkeypatch, client):
    monkeypatch.setattr(accounts_routes, "_get_proxy", lambda *_args, **_kwargs: None)

    captured = {}

    def fake_resolve_account_ids(
        db,
        ids,
        select_all=False,
        status_filter=None,
        email_service_filter=None,
        search_filter=None,
        primary_cpa_service_id_filter=None,
    ):
        captured["ids"] = ids
        captured["select_all"] = select_all
        captured["status_filter"] = status_filter
        captured["email_service_filter"] = email_service_filter
        captured["search_filter"] = search_filter
        captured["primary_cpa_service_id_filter"] = primary_cpa_service_id_filter
        return []

    monkeypatch.setattr(accounts_routes, "resolve_account_ids", fake_resolve_account_ids)

    response = client.post(
        "/api/accounts/batch-validate",
        json={
            "ids": [],
            "select_all": True,
            "status_filter": "expired",
            "email_service_filter": "tempmail",
            "search_filter": "user",
            "primary_cpa_service_id_filter": 7,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "ids": [],
        "select_all": True,
        "status_filter": "expired",
        "email_service_filter": "tempmail",
        "search_filter": "user",
        "primary_cpa_service_id_filter": 7,
    }


@pytest.mark.parametrize(
    ("path", "extra_payload"),
    [
        ("/api/accounts/batch-delete", {}),
        ("/api/accounts/export/json", {}),
        ("/api/accounts/export/csv", {}),
        ("/api/accounts/export/sub2api", {}),
        ("/api/accounts/export/cpa", {}),
        ("/api/accounts/batch-upload-cpa", {}),
        ("/api/accounts/batch-upload-sub2api", {}),
        ("/api/accounts/batch-upload-tm", {}),
    ],
)
def test_account_batch_routes_forward_primary_cpa_service_id_filter(
    monkeypatch,
    client,
    path,
    extra_payload,
):
    captured = {}

    def fake_resolve_account_ids(
        db,
        ids,
        select_all=False,
        status_filter=None,
        email_service_filter=None,
        search_filter=None,
        primary_cpa_service_id_filter=None,
    ):
        captured["ids"] = ids
        captured["select_all"] = select_all
        captured["status_filter"] = status_filter
        captured["email_service_filter"] = email_service_filter
        captured["search_filter"] = search_filter
        captured["primary_cpa_service_id_filter"] = primary_cpa_service_id_filter
        return []

    monkeypatch.setattr(accounts_routes, "resolve_account_ids", fake_resolve_account_ids)
    monkeypatch.setattr(
        accounts_routes,
        "batch_upload_to_cpa",
        lambda ids, proxy, api_url=None, api_token=None: {"success_count": len(ids), "failed_count": 0, "skipped_count": 0},
    )
    monkeypatch.setattr(
        accounts_routes,
        "batch_upload_to_sub2api",
        lambda ids, api_url, api_key, concurrency=3, priority=50: {"success_count": len(ids), "failed_count": 0, "skipped_count": 0},
    )
    monkeypatch.setattr(
        accounts_routes,
        "batch_upload_to_team_manager",
        lambda ids, api_url, api_key: {"success_count": len(ids), "failed_count": 0, "skipped_count": 0},
    )
    monkeypatch.setattr(accounts_routes.crud, "get_sub2api_services", lambda db, enabled=True: [SimpleNamespace(api_url="https://sub2api.test", api_key="sub-key")])
    monkeypatch.setattr(accounts_routes.crud, "get_tm_services", lambda db, enabled=True: [SimpleNamespace(api_url="https://tm.test", api_key="tm-key")])

    response = client.post(
        path,
        json={
            "ids": [],
            "select_all": True,
            "status_filter": "active",
            "email_service_filter": "tempmail",
            "search_filter": "user",
            "primary_cpa_service_id_filter": 12,
            **extra_payload,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "ids": [],
        "select_all": True,
        "status_filter": "active",
        "email_service_filter": "tempmail",
        "search_filter": "user",
        "primary_cpa_service_id_filter": 12,
    }
