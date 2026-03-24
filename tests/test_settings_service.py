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
