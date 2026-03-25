from contextlib import contextmanager

import pytest

from src.database.models import Base, Setting
from src.database.session import DatabaseSessionManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "settings-service.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clear_settings_cache():
    import src.config.settings as settings_module

    previous = settings_module._settings
    settings_module._settings = None
    try:
        yield
    finally:
        settings_module._settings = previous


def test_settings_service_updates_proxy_settings(temp_db):
    from src.application.settings_service import SettingsService

    service = SettingsService(temp_db)
    settings = service.update_runtime_settings(
        {
            "proxy_enabled": True,
            "proxy_host": "127.0.0.1",
            "proxy_port": 7890,
        }
    )

    persisted = {row.key: row.value for row in temp_db.query(Setting).all()}
    assert settings.proxy_enabled is True
    assert settings.proxy_host == "127.0.0.1"
    assert settings.proxy_port == 7890
    assert persisted["proxy.enabled"] == "true"
    assert persisted["proxy.host"] == "127.0.0.1"
    assert persisted["proxy.port"] == "7890"


def test_settings_service_rejects_invalid_email_code_timeout(temp_db):
    from src.application.settings_service import SettingsService

    service = SettingsService(temp_db)

    with pytest.raises(ValueError, match="timeout"):
        service.update_runtime_settings({"email_code_timeout": 10})


def test_settings_service_keeps_existing_dynamic_proxy_api_key_when_omitted(temp_db):
    from src.application.settings_service import SettingsService

    service = SettingsService(temp_db)
    service.update_dynamic_proxy_settings(
        {
            "enabled": True,
            "api_url": "https://proxy.example.com",
            "api_key": "secret-token",
            "api_key_header": "X-Token",
            "result_field": "data.proxy",
        }
    )

    updated = service.update_dynamic_proxy_settings(
        {
            "enabled": False,
            "api_url": "https://proxy-2.example.com",
            "api_key": None,
            "api_key_header": "Authorization",
            "result_field": "payload.url",
        }
    )

    persisted = {row.key: row.value for row in temp_db.query(Setting).all()}
    assert updated.proxy_dynamic_enabled is False
    assert updated.proxy_dynamic_api_url == "https://proxy-2.example.com"
    assert updated.proxy_dynamic_api_key.get_secret_value() == "secret-token"
    assert persisted["proxy.dynamic_api_key"] == "secret-token"


def test_settings_service_persists_dynamic_proxy_advanced_contract_fields(temp_db):
    from src.application.settings_service import SettingsService

    service = SettingsService(temp_db)
    payload = {
        "enabled": True,
        "api_url": "https://proxy.example.com/basic",
        "api_key": "secret-token",
        "api_key_header": "X-Token",
        "result_field": "legacy.proxy",
        "request_method": "POST",
        "request_url": "https://proxy.example.com/pool",
        "request_headers_template": {"Authorization": "Bearer abc"},
        "request_body_template": {"region": "us-west"},
        "request_timeout_seconds": 18,
        "request_count_param_name": "limit",
        "request_count_default": 5,
        "response_root_field": "data.items",
        "response_item_mode": "object_list",
        "response_field_mapping": {"proxy_url": "endpoint"},
        "task_defaults": {
            "batch_registration": {
                "allocation_strategy": "exclusive",
                "lease_seconds": 240,
            }
        },
    }

    updated = service.update_dynamic_proxy_settings(payload)
    reloaded = service.get_runtime_settings()
    persisted = {row.key: row.value for row in temp_db.query(Setting).all()}

    assert updated.proxy_dynamic_request_method == "POST"
    assert updated.proxy_dynamic_request_url == "https://proxy.example.com/pool"
    assert updated.proxy_dynamic_request_headers_template == {"Authorization": "Bearer abc"}
    assert updated.proxy_dynamic_request_body_template == {"region": "us-west"}
    assert updated.proxy_dynamic_request_timeout_seconds == 18
    assert updated.proxy_dynamic_request_count_param_name == "limit"
    assert updated.proxy_dynamic_request_count_default == 5
    assert updated.proxy_dynamic_response_root_field == "data.items"
    assert updated.proxy_dynamic_response_item_mode == "object_list"
    assert updated.proxy_dynamic_response_field_mapping == {"proxy_url": "endpoint"}
    assert updated.proxy_dynamic_task_defaults["batch_registration"]["allocation_strategy"] == "exclusive"
    assert reloaded.proxy_dynamic_request_method == "POST"
    assert reloaded.proxy_dynamic_response_item_mode == "object_list"
    assert reloaded.proxy_dynamic_task_defaults["batch_registration"]["lease_seconds"] == 240
    assert persisted["proxy.dynamic_request_method"] == "POST"
    assert persisted["proxy.dynamic_request_timeout_seconds"] == "18"
    assert "batch_registration" in persisted["proxy.dynamic_task_defaults"]


def test_settings_service_keeps_existing_dynamic_proxy_api_key_when_empty_string(temp_db):
    from src.application.settings_service import SettingsService

    service = SettingsService(temp_db)
    service.update_dynamic_proxy_settings(
        {
            "enabled": True,
            "api_url": "https://proxy.example.com",
            "api_key": "secret-token",
            "api_key_header": "X-Token",
            "result_field": "data.proxy",
        }
    )

    updated = service.update_dynamic_proxy_settings(
        {
            "enabled": True,
            "api_url": "https://proxy.example.com/v2",
            "api_key": "",
            "api_key_header": "Authorization",
            "result_field": "payload.url",
        }
    )

    persisted = {row.key: row.value for row in temp_db.query(Setting).all()}
    assert updated.proxy_dynamic_api_key.get_secret_value() == "secret-token"
    assert persisted["proxy.dynamic_api_key"] == "secret-token"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("proxy_dynamic_request_method", "PUT", "request method"),
        ("proxy_dynamic_response_item_mode", "flat", "response item mode"),
        ("proxy_dynamic_request_timeout_seconds", 0, "request timeout"),
        ("proxy_dynamic_request_count_default", 0, "request count"),
    ],
)
def test_settings_service_rejects_invalid_dynamic_proxy_advanced_fields(temp_db, field, value, error):
    from src.application.settings_service import SettingsService

    service = SettingsService(temp_db)

    with pytest.raises(ValueError, match=error):
        service.update_runtime_settings({field: value})


def test_dynamic_proxy_request_count_default_default_is_three(temp_db):
    import src.config.settings as settings_module
    from src.application.settings_service import SettingsService

    service = SettingsService(temp_db)
    settings = service.get_runtime_settings()
    definitions = settings_module.get_all_setting_definitions()

    assert settings.proxy_dynamic_request_count_default == 3
    assert definitions["proxy_dynamic_request_count_default"].default_value == 3
    assert settings.proxy_dynamic_request_body_mode == "auto"
    assert definitions["proxy_dynamic_request_body_mode"].default_value == "auto"


def test_settings_service_partial_dynamic_proxy_update_keeps_existing_advanced_fields(temp_db):
    from src.application.settings_service import SettingsService

    service = SettingsService(temp_db)
    service.update_dynamic_proxy_settings(
        {
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
    )

    updated = service.update_dynamic_proxy_settings(
        {
            "enabled": False,
            "api_url": "https://basic2.example.com",
        }
    )

    assert updated.proxy_dynamic_enabled is False
    assert updated.proxy_dynamic_api_url == "https://basic2.example.com"
    assert updated.proxy_dynamic_request_method == "POST"
    assert updated.proxy_dynamic_request_url == "https://proxy.example.com/pool"
    assert updated.proxy_dynamic_request_headers_template == {"Authorization": "Bearer abc"}
    assert updated.proxy_dynamic_request_body_template == {"region": "us-west"}
    assert updated.proxy_dynamic_request_timeout_seconds == 20
    assert updated.proxy_dynamic_request_count_default == 7
    assert updated.proxy_dynamic_response_item_mode == "object_list"
    assert updated.proxy_dynamic_task_defaults["batch_registration"]["allocation_strategy"] == "exclusive"
