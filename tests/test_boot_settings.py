from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

import webui
from src.boot.settings import BootSettings, get_boot_settings, set_boot_settings
from src.web.app import create_app


@dataclass
class _Args:
    host: str | None = None
    port: int | None = None
    debug: bool = False
    reload: bool = False
    log_level: str | None = None
    access_password: str | None = None


def test_boot_settings_cli_overrides_env():
    settings = BootSettings.from_sources(
        env={
            "WEBUI_HOST": "127.0.0.1",
            "WEBUI_PORT": "9001",
            "WEBUI_ACCESS_PASSWORD": "env-secret",
        },
        cli={
            "host": "0.0.0.0",
            "port": 8010,
            "access_password": "cli-secret",
            "debug": False,
            "reload": False,
            "log_level": None,
        },
    )

    assert settings.host == "0.0.0.0"
    assert settings.port == 8010
    assert settings.access_password_override == "cli-secret"


def test_boot_settings_falls_back_to_env():
    settings = BootSettings.from_sources(
        env={
            "WEBUI_HOST": "127.0.0.1",
            "WEBUI_PORT": "9001",
            "WEBUI_ACCESS_PASSWORD": "env-secret",
        },
        cli={},
    )

    assert settings.host == "127.0.0.1"
    assert settings.port == 9001
    assert settings.access_password_override == "env-secret"


def test_main_uses_process_local_boot_settings_without_update_settings(monkeypatch):
    monkeypatch.setattr("argparse.ArgumentParser.parse_args", lambda self: _Args(host="127.0.0.1", port=8011, access_password="cli-secret"))

    captured: dict[str, object] = {}

    def fake_update_settings(**kwargs):
        raise AssertionError("boot override must not persist to DB")

    def fake_start_webui(boot_settings):
        captured["boot"] = boot_settings

    monkeypatch.setattr("src.config.settings.update_settings", fake_update_settings)
    monkeypatch.setattr(webui, "start_webui", fake_start_webui)

    webui.main()

    boot = captured["boot"]
    assert isinstance(boot, BootSettings)
    assert boot.host == "127.0.0.1"
    assert boot.port == 8011
    assert boot.access_password_override == "cli-secret"


def test_main_loads_dotenv_before_building_boot_settings(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("APP_HOST=0.0.0.0\nAPP_PORT=8123\n", encoding="utf-8")

    monkeypatch.delenv("APP_HOST", raising=False)
    monkeypatch.delenv("APP_PORT", raising=False)
    monkeypatch.delenv("WEBUI_HOST", raising=False)
    monkeypatch.delenv("WEBUI_PORT", raising=False)
    monkeypatch.setattr(webui, "project_root", tmp_path)
    monkeypatch.setattr("argparse.ArgumentParser.parse_args", lambda self: _Args())

    captured: dict[str, object] = {}

    def fake_start_webui(boot_settings):
        captured["boot"] = boot_settings

    monkeypatch.setattr(webui, "start_webui", fake_start_webui)

    webui.main()

    boot = captured["boot"]
    assert isinstance(boot, BootSettings)
    assert boot.host == "0.0.0.0"
    assert boot.port == 8123


def test_login_accepts_boot_access_password_override():
    set_boot_settings(BootSettings(access_password_override="override-secret"))
    try:
        app = create_app()
        with TestClient(app) as client:
            response = client.post(
                "/login",
                data={"password": "override-secret", "next": "/"},
                follow_redirects=False,
            )
        assert response.status_code == 302
    finally:
        set_boot_settings(BootSettings())


def test_get_boot_settings_returns_process_local_override():
    override = BootSettings(host="127.0.0.1", port=9009)
    set_boot_settings(override)
    try:
        current = get_boot_settings()
        assert current.host == "127.0.0.1"
        assert current.port == 9009
    finally:
        set_boot_settings(BootSettings())
