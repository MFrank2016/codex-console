import asyncio
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.core.ip_location import IPLocation
from src.database import crud
from src.database.models import Base
from src.database.session import DatabaseSessionManager
from src.web.routes import settings as settings_routes


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "proxy-settings.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

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

    monkeypatch.setattr(settings_routes, "get_db", _get_db)
    return temp_db


def test_get_proxies_supports_keyword_status_default_and_location_filters(temp_db):
    db = temp_db

    first = crud.create_proxy(
        db,
        name="美国-西雅图-001",
        type="http",
        host="1.1.1.1",
        port=8080,
        country="美国",
        city="西雅图",
    )
    crud.create_proxy(
        db,
        name="代理-001",
        type="socks5",
        host="2.2.2.2",
        port=1080,
        enabled=False,
    )
    crud.set_proxy_default(db, proxy_id=first.id)

    rows = crud.get_proxies(
        db,
        keyword="美国",
        type="http",
        enabled=True,
        is_default=True,
        location="西雅图",
    )

    assert [row.host for row in rows] == ["1.1.1.1"]


def test_create_proxy_keeps_backward_compatible_positional_args(temp_db):
    db = temp_db

    proxy = crud.create_proxy(
        db,
        "老调用",
        "http",
        "7.7.7.7",
        8081,
        "legacy-user",
        "legacy-pass",
        False,
        7,
    )

    assert proxy.username == "legacy-user"
    assert proxy.password == "legacy-pass"
    assert proxy.enabled is False
    assert proxy.priority == 7
    assert proxy.country is None
    assert proxy.city is None


def test_get_proxies_keeps_backward_compatible_positional_args(temp_db):
    db = temp_db
    crud.create_proxy(db, "启用-1", "http", "8.8.8.1", 8080, enabled=True)
    crud.create_proxy(db, "启用-2", "http", "8.8.8.2", 8080, enabled=True)
    crud.create_proxy(db, "禁用-1", "http", "8.8.8.3", 8080, enabled=False)

    rows = crud.get_proxies(db, True, 0, 1)

    assert len(rows) == 1
    assert rows[0].enabled is True


def test_find_proxy_by_host_port_crud_helper_matches_exact_proxy(temp_db):
    db = temp_db

    created = crud.create_proxy(
        db,
        name="代理-精确匹配",
        type="http",
        host="5.5.5.5",
        port=3128,
    )

    matched = crud.find_proxy_by_host_port(db, host="5.5.5.5", port=3128)

    assert matched is not None
    assert matched.id == created.id


def test_delete_proxies_batch_ignores_missing_ids(temp_db):
    db = temp_db

    created = crud.create_proxy(
        db,
        name="代理-待删除",
        type="http",
        host="3.3.3.3",
        port=8080,
    )

    deleted = crud.delete_proxies(db, [created.id, 999])

    assert deleted == 1


def test_proxy_to_dict_exposes_country_and_city(temp_db):
    db = temp_db

    proxy = crud.create_proxy(
        db,
        name="美国-纽约-001",
        type="http",
        host="9.9.9.9",
        port=8080,
        country="美国",
        city="纽约",
    )

    payload = proxy.to_dict()

    assert payload["country"] == "美国"
    assert payload["city"] == "纽约"


def test_sqlite_migrate_tables_adds_proxy_country_and_city_columns(tmp_path):
    db_path = tmp_path / "legacy-proxy-schema.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE proxies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                type VARCHAR(20) NOT NULL DEFAULT 'http',
                host VARCHAR(255) NOT NULL,
                port INTEGER NOT NULL,
                username VARCHAR(100),
                password VARCHAR(255),
                enabled BOOLEAN,
                is_default BOOLEAN DEFAULT 0,
                priority INTEGER,
                last_used DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        conn.commit()

    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    manager.migrate_tables()

    with manager.engine.connect() as conn:
        columns = {
            row["name"]
            for row in conn.execute(text("PRAGMA table_info('proxies')")).mappings().all()
        }

    assert "country" in columns
    assert "city" in columns


def test_batch_import_proxies_creates_rows_and_skips_duplicates(monkeypatch, route_db):
    monkeypatch.setattr(settings_routes, "lookup_locations", lambda hosts, **_: {
        "1.1.1.1": IPLocation(ip="1.1.1.1", country="美国", city="西雅图"),
        "2.2.2.2": IPLocation(ip="2.2.2.2", country="", city=""),
    })

    result = asyncio.run(settings_routes.batch_import_proxies(
        settings_routes.ProxyBatchImportRequest(
            data="1.1.1.1:8080\nuser:pass@2.2.2.2:1080\n1.1.1.1:8080",
            default_type="http",
        )
    ))

    rows = crud.get_proxies(route_db)

    assert result["success"] == 2
    assert result["skipped"] == 1
    assert result["failed"] == 0
    assert {row.host for row in rows} == {"1.1.1.1", "2.2.2.2"}


def test_get_proxies_list_accepts_filter_query_params(route_db):
    first = crud.create_proxy(
        route_db,
        name="美国-西雅图-001",
        type="http",
        host="1.1.1.1",
        port=8080,
        country="美国",
        city="西雅图",
    )
    crud.create_proxy(
        route_db,
        name="代理-001",
        type="socks5",
        host="2.2.2.2",
        port=1080,
        enabled=False,
    )
    crud.set_proxy_default(route_db, proxy_id=first.id)

    result = asyncio.run(settings_routes.get_proxies_list(
        enabled=True,
        keyword="美国",
        type="http",
        is_default=True,
        location="西雅图",
    ))

    assert result["total"] == 1
    assert [proxy["host"] for proxy in result["proxies"]] == ["1.1.1.1"]


def test_batch_delete_route_returns_requested_deleted_and_missing(route_db):
    first = crud.create_proxy(
        route_db,
        name="代理-001",
        type="http",
        host="3.3.3.3",
        port=8080,
    )
    second = crud.create_proxy(
        route_db,
        name="代理-002",
        type="http",
        host="4.4.4.4",
        port=8081,
    )

    result = asyncio.run(settings_routes.batch_delete_proxies(
        settings_routes.ProxyBatchDeleteRequest(ids=[first.id, second.id, 404])
    ))

    assert result == {"success": True, "requested": 3, "deleted": 2, "missing": [404]}
    assert crud.get_proxies(route_db) == []


def test_batch_import_proxies_skips_blank_and_comment_lines_and_reports_invalid(route_db, monkeypatch):
    monkeypatch.setattr(settings_routes, "lookup_locations", lambda hosts, **_: {
        "1.1.1.1": IPLocation(ip="1.1.1.1", country="美国", city="西雅图"),
    })

    result = asyncio.run(settings_routes.batch_import_proxies(
        settings_routes.ProxyBatchImportRequest(
            data="\n# comment\n  \n1.1.1.1:8080\nbad-input\n# trailing",
            default_type="http",
        )
    ))

    rows = crud.get_proxies(route_db)

    assert result["success"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 1
    assert [entry["status"] for entry in result["results"]] == ["failed", "success"]
    assert result["results"][0]["line_no"] == 5
    assert result["results"][0]["reason"] == "unsupported proxy line format"
    assert [row.host for row in rows] == ["1.1.1.1"]


def test_batch_import_proxies_falls_back_when_geolocation_lookup_fails(route_db, monkeypatch):
    crud.create_proxy(
        route_db,
        name="代理-009",
        type="http",
        host="9.9.9.9",
        port=9000,
    )

    def broken_lookup(hosts, **_):
        raise RuntimeError("geo lookup failed")

    monkeypatch.setattr(settings_routes, "lookup_locations", broken_lookup)

    result = asyncio.run(settings_routes.batch_import_proxies(
        settings_routes.ProxyBatchImportRequest(
            data="proxy.example.com:8080",
            default_type="http",
        )
    ))

    rows = crud.get_proxies(route_db)
    imported = next(row for row in rows if row.host == "proxy.example.com")

    assert result["success"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert imported.name == "代理-010"
    assert imported.country is None
    assert imported.city is None


def test_batch_import_proxies_dedupes_domain_hosts_case_insensitively(route_db, monkeypatch):
    crud.create_proxy(
        route_db,
        name="现有域名代理",
        type="http",
        host="Example.COM",
        port=8080,
    )
    monkeypatch.setattr(settings_routes, "lookup_locations", lambda hosts, **_: {})

    result = asyncio.run(settings_routes.batch_import_proxies(
        settings_routes.ProxyBatchImportRequest(
            data="example.com:8080\nEXAMPLE.com:8080\nunique.example.com:8080",
            default_type="http",
        )
    ))

    rows = crud.get_proxies(route_db)

    assert result["success"] == 1
    assert result["skipped"] == 2
    assert result["failed"] == 0
    assert sorted((row.host, row.port) for row in rows) == [
        ("Example.COM", 8080),
        ("unique.example.com", 8080),
    ]


def test_batch_import_proxies_allows_same_host_port_with_different_credentials(route_db, monkeypatch):
    monkeypatch.setattr(settings_routes, "lookup_locations", lambda hosts, **_: {})

    result = asyncio.run(settings_routes.batch_import_proxies(
        settings_routes.ProxyBatchImportRequest(
            data=(
                "socks5://change4.owlproxy.com:7778:user_a:2539361\n"
                "socks5://change4.owlproxy.com:7778:user_b:2539361\n"
                "socks5://change4.owlproxy.com:7778:user_c:2539361"
            ),
            default_type="http",
        )
    ))

    rows = crud.get_proxies(route_db)
    credentials = sorted((row.username, row.password) for row in rows)

    assert result["success"] == 3
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert credentials == [
        ("user_a", "2539361"),
        ("user_b", "2539361"),
        ("user_c", "2539361"),
    ]


def test_batch_import_proxies_uses_asyncio_to_thread_for_geolocation(route_db, monkeypatch):
    tracker = {"called": False}

    async def fake_to_thread(func, *args, **kwargs):
        tracker["called"] = True
        return func(*args, **kwargs)

    monkeypatch.setattr(settings_routes, "asyncio", SimpleNamespace(to_thread=fake_to_thread))
    monkeypatch.setattr(settings_routes, "lookup_locations", lambda hosts, **_: {})

    result = asyncio.run(settings_routes.batch_import_proxies(
        settings_routes.ProxyBatchImportRequest(
            data="thread-check.example.com:8080",
            default_type="http",
        )
    ))

    assert result["success"] == 1
    assert tracker["called"] is True


def test_update_proxy_item_recomputes_location_when_host_changes(route_db, monkeypatch):
    proxy = crud.create_proxy(
        route_db,
        name="旧位置代理",
        type="http",
        host="1.1.1.1",
        port=8080,
        country="美国",
        city="西雅图",
    )
    tracker = {"called": False}

    async def fake_to_thread(func, *args, **kwargs):
        tracker["called"] = True
        return func(*args, **kwargs)

    monkeypatch.setattr(settings_routes, "asyncio", SimpleNamespace(to_thread=fake_to_thread))
    monkeypatch.setattr(settings_routes, "lookup_locations", lambda hosts, **_: {
        "2.2.2.2": IPLocation(ip="2.2.2.2", country="日本", city="东京"),
    })

    result = asyncio.run(settings_routes.update_proxy_item(
        proxy.id,
        settings_routes.ProxyUpdateRequest(host="2.2.2.2"),
    ))

    route_db.expire_all()
    updated = crud.get_proxy_by_id(route_db, proxy.id)

    assert tracker["called"] is True
    assert result["proxy"]["host"] == "2.2.2.2"
    assert result["proxy"]["country"] == "日本"
    assert result["proxy"]["city"] == "东京"
    assert updated.country == "日本"
    assert updated.city == "东京"


def test_update_proxy_item_clears_stale_location_when_lookup_fails(route_db, monkeypatch):
    proxy = crud.create_proxy(
        route_db,
        name="旧位置代理",
        type="http",
        host="1.1.1.1",
        port=8080,
        country="美国",
        city="西雅图",
    )

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    def broken_lookup(hosts, **_):
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(settings_routes, "asyncio", SimpleNamespace(to_thread=fake_to_thread))
    monkeypatch.setattr(settings_routes, "lookup_locations", broken_lookup)

    result = asyncio.run(settings_routes.update_proxy_item(
        proxy.id,
        settings_routes.ProxyUpdateRequest(host="3.3.3.3"),
    ))

    route_db.expire_all()
    updated = crud.get_proxy_by_id(route_db, proxy.id)

    assert result["proxy"]["host"] == "3.3.3.3"
    assert result["proxy"]["country"] is None
    assert result["proxy"]["city"] is None
    assert updated.country is None
    assert updated.city is None


def test_dynamic_proxy_settings_route_round_trip_for_advanced_contract(route_db, monkeypatch):
    from src.application.settings_service import SettingsService

    monkeypatch.setattr(
        settings_routes,
        "get_settings",
        lambda: SettingsService(route_db).get_runtime_settings(),
    )

    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api/settings")

    payload = {
        "enabled": True,
        "api_url": "https://proxy.example.com/basic",
        "api_key": "secret-token",
        "api_key_header": "X-Proxy-Token",
        "result_field": "legacy.path",
        "request_method": "POST",
        "request_url": "https://proxy.example.com/pool",
        "request_headers_template": {"Authorization": "Bearer abc"},
        "request_body_template": {"region": "us-east"},
        "request_timeout_seconds": 15,
        "request_count_param_name": "count",
        "request_count_default": 6,
        "response_root_field": "data.proxies",
        "response_item_mode": "object_list",
        "response_field_mapping": {"proxy_url": "endpoint"},
        "task_defaults": {
            "batch_registration": {
                "allocation_strategy": "exclusive",
                "lease_seconds": 180,
            }
        },
    }

    with TestClient(app) as client:
        post_response = client.post("/api/settings/proxy/dynamic", json=payload)
        assert post_response.status_code == 200

        get_response = client.get("/api/settings/proxy/dynamic")
        assert get_response.status_code == 200
        body = get_response.json()

    assert body["enabled"] is True
    assert body["api_url"] == "https://proxy.example.com/basic"
    assert body["api_key_header"] == "X-Proxy-Token"
    assert body["result_field"] == "legacy.path"
    assert body["request_method"] == "POST"
    assert body["request_url"] == "https://proxy.example.com/pool"
    assert body["request_headers_template"]["Authorization"] == "Bearer abc"
    assert body["request_body_template"]["region"] == "us-east"
    assert body["request_timeout_seconds"] == 15
    assert body["request_count_param_name"] == "count"
    assert body["request_count_default"] == 6
    assert body["response_root_field"] == "data.proxies"
    assert body["response_item_mode"] == "object_list"
    assert body["response_field_mapping"]["proxy_url"] == "endpoint"
    assert body["task_defaults"]["batch_registration"]["allocation_strategy"] == "exclusive"
    assert body["task_defaults"]["batch_registration"]["lease_seconds"] == 180
    assert body["has_api_key"] is True


def test_dynamic_proxy_settings_route_uses_request_count_default_three_when_omitted(route_db, monkeypatch):
    from src.application.settings_service import SettingsService

    monkeypatch.setattr(
        settings_routes,
        "get_settings",
        lambda: SettingsService(route_db).get_runtime_settings(),
    )

    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api/settings")

    payload = {
        "enabled": True,
        "api_url": "https://proxy.example.com/basic",
        "api_key": "secret-token",
        "request_method": "GET",
        "request_url": "https://proxy.example.com/pool",
    }

    with TestClient(app) as client:
        post_response = client.post("/api/settings/proxy/dynamic", json=payload)
        assert post_response.status_code == 200

        get_response = client.get("/api/settings/proxy/dynamic")
        assert get_response.status_code == 200
        body = get_response.json()

    assert body["request_count_default"] == 3
    assert body["request_body_mode"] == "auto"


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"request_method": "PUT"}, "request_method"),
        ({"response_item_mode": "flat"}, "response_item_mode"),
        ({"request_timeout_seconds": 0}, "request_timeout_seconds"),
        ({"request_count_default": 0}, "request_count_default"),
    ],
)
def test_dynamic_proxy_settings_route_rejects_invalid_advanced_values(route_db, monkeypatch, payload, field):
    from src.application.settings_service import SettingsService

    monkeypatch.setattr(
        settings_routes,
        "get_settings",
        lambda: SettingsService(route_db).get_runtime_settings(),
    )

    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api/settings")

    base_payload = {
        "enabled": True,
        "api_url": "https://proxy.example.com/basic",
        "request_method": "GET",
        "request_url": "https://proxy.example.com/pool",
        "response_item_mode": "string_list",
        "request_timeout_seconds": 10,
        "request_count_default": 3,
    }
    base_payload.update(payload)

    with TestClient(app) as client:
        response = client.post("/api/settings/proxy/dynamic", json=base_payload)

    assert response.status_code == 422
    assert field in response.text


def test_dynamic_proxy_settings_route_partial_update_keeps_existing_advanced_fields(route_db, monkeypatch):
    from src.application.settings_service import SettingsService

    monkeypatch.setattr(
        settings_routes,
        "get_settings",
        lambda: SettingsService(route_db).get_runtime_settings(),
    )

    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api/settings")

    full_payload = {
        "enabled": True,
        "api_url": "https://proxy.example.com/full",
        "api_key": "secret-token",
        "request_method": "POST",
        "request_url": "https://proxy.example.com/pool",
        "request_headers_template": {"Authorization": "Bearer abc"},
        "request_body_template": {"region": "us-west"},
        "request_timeout_seconds": 20,
        "request_count_default": 7,
        "response_item_mode": "object_list",
        "task_defaults": {"batch_registration": {"allocation_strategy": "exclusive"}},
    }
    partial_payload = {
        "enabled": False,
        "api_url": "https://basic2.example.com",
    }

    with TestClient(app) as client:
        first = client.post("/api/settings/proxy/dynamic", json=full_payload)
        assert first.status_code == 200

        second = client.post("/api/settings/proxy/dynamic", json=partial_payload)
        assert second.status_code == 200

        get_response = client.get("/api/settings/proxy/dynamic")
        assert get_response.status_code == 200
        body = get_response.json()

    assert body["enabled"] is False
    assert body["api_url"] == "https://basic2.example.com"
    assert body["request_method"] == "POST"
    assert body["request_url"] == "https://proxy.example.com/pool"
    assert body["request_headers_template"] == {"Authorization": "Bearer abc"}
    assert body["request_body_template"] == {"region": "us-west"}
    assert body["request_timeout_seconds"] == 20
    assert body["request_count_default"] == 7
    assert body["response_item_mode"] == "object_list"
    assert body["task_defaults"]["batch_registration"]["allocation_strategy"] == "exclusive"


def test_dynamic_proxy_test_route_reuses_new_dynamic_request_and_probe_helpers(route_db, monkeypatch):
    from src.core import dynamic_proxy as dynamic_proxy_module
    from src.application.settings_service import SettingsService
    from src.core.dynamic_proxy import (
        DynamicProxyCandidate,
        DynamicProxyProbeResult,
        DynamicProxyRequest,
    )

    monkeypatch.setattr(
        settings_routes,
        "get_settings",
        lambda: SettingsService(route_db).get_runtime_settings(),
    )

    called: dict[str, object] = {}

    def _fake_build_dynamic_proxy_request(**kwargs):
        called["build"] = kwargs
        return DynamicProxyRequest(
            method="POST",
            url="https://proxy.example.com/pool",
            headers={"Authorization": "Bearer abc"},
            body={"count": 3, "region": "us-east"},
        )

    def _fake_fetch_dynamic_proxy_candidates(request, **kwargs):
        called["fetch"] = {
            "request": request,
            **kwargs,
        }
        return [
            DynamicProxyCandidate(
                proxy_url="http://10.0.0.1:8080",
                scheme="http",
                host="10.0.0.1",
                port=8080,
            )
        ]

    def _fake_probe_proxy_candidate(candidate, **kwargs):
        called["probe"] = {
            "candidate": candidate,
            **kwargs,
        }
        return DynamicProxyProbeResult(
            ok=True,
            proxy_url=candidate.proxy_url,
            egress_ip=None,
            response_time_ms=18,
        )

    monkeypatch.setattr(settings_routes, "build_dynamic_proxy_request", _fake_build_dynamic_proxy_request, raising=False)
    monkeypatch.setattr(settings_routes, "fetch_dynamic_proxy_candidates", _fake_fetch_dynamic_proxy_candidates, raising=False)
    monkeypatch.setattr(settings_routes, "probe_proxy_candidate", _fake_probe_proxy_candidate, raising=False)

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"ip": "8.8.8.8"}

    monkeypatch.setattr(dynamic_proxy_module, "fetch_dynamic_proxy", lambda **_: "http://10.0.0.1:8080")
    monkeypatch.setattr(dynamic_proxy_module, "cffi_requests", SimpleNamespace(get=lambda *args, **kwargs: _FakeResponse()), raising=False)

    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api/settings")

    payload = {
        "enabled": True,
        "api_url": "https://proxy.example.com/basic",
        "request_method": "POST",
        "request_url": "https://proxy.example.com/pool",
        "request_headers_template": {"Authorization": "Bearer abc"},
        "request_body_template": {"region": "us-east"},
        "request_count_param_name": "count",
        "request_count_default": 3,
        "response_root_field": "data.items",
        "response_item_mode": "object_list",
        "response_field_mapping": {"proxy_url": "endpoint"},
    }

    with TestClient(app) as client:
        response = client.post("/api/settings/proxy/dynamic/test", json=payload)

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["proxy_url"] == "http://10.0.0.1:8080"
    assert called["build"]["request_url"] == "https://proxy.example.com/pool"
    assert called["fetch"]["response_root_field"] == "data.items"
    assert called["probe"]["candidate"].proxy_url == "http://10.0.0.1:8080"


def test_dynamic_proxy_test_route_probes_legacy_proxy_directly_when_new_helpers_return_empty(route_db, monkeypatch):
    from src.application.settings_service import SettingsService
    from src.core.dynamic_proxy import DynamicProxyProbeResult

    monkeypatch.setattr(
        settings_routes,
        "get_settings",
        lambda: SettingsService(route_db).get_runtime_settings(),
    )

    calls: dict[str, object] = {}

    def _fake_fetch_dynamic_proxy_candidates(*args, **kwargs):
        calls["fetch_candidates_called"] = True
        return []

    def _fake_fetch_dynamic_proxy(**kwargs):
        calls["legacy_fetch"] = kwargs
        return "socks5://legacy-user:legacy-pass@9.9.9.9:1080"

    def _fake_probe_proxy_candidate(candidate, **kwargs):
        calls["probe"] = {
            "candidate": candidate,
            **kwargs,
        }
        return DynamicProxyProbeResult(
            ok=True,
            proxy_url=candidate.proxy_url,
            egress_ip="7.7.7.7",
            response_time_ms=23,
        )

    monkeypatch.setattr(settings_routes, "fetch_dynamic_proxy_candidates", _fake_fetch_dynamic_proxy_candidates, raising=False)
    monkeypatch.setattr(settings_routes, "fetch_dynamic_proxy", _fake_fetch_dynamic_proxy, raising=False)
    monkeypatch.setattr(settings_routes, "probe_proxy_candidate", _fake_probe_proxy_candidate, raising=False)

    app = FastAPI()
    app.include_router(settings_routes.router, prefix="/api/settings")

    payload = {
        "enabled": True,
        "api_url": "https://proxy.example.com/legacy",
        "api_key": "secret-token",
        "api_key_header": "X-Proxy-Token",
        "result_field": "data.proxy",
        "request_method": "POST",
        "request_url": "https://proxy.example.com/pool",
        "request_body_template": {"region": "us-east"},
        "request_count_default": 3,
        "response_root_field": "data.items",
        "response_item_mode": "object_list",
        "response_field_mapping": {"proxy_url": "endpoint"},
    }

    with TestClient(app) as client:
        response = client.post("/api/settings/proxy/dynamic/test", json=payload)

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["proxy_url"] == "socks5://legacy-user:legacy-pass@9.9.9.9:1080"
    assert body["ip"] == "7.7.7.7"
    assert calls["legacy_fetch"] == {
        "api_url": "https://proxy.example.com/legacy",
        "api_key": "secret-token",
        "api_key_header": "X-Proxy-Token",
        "result_field": "data.proxy",
    }
    assert calls["probe"]["candidate"].proxy_url == "socks5://legacy-user:legacy-pass@9.9.9.9:1080"
    assert calls["probe"]["candidate"].scheme == "socks5"
