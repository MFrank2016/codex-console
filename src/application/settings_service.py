from __future__ import annotations

import os
from typing import Any

from ..config import settings as settings_module
from ..database.repositories.settings_repository import load_runtime_values, set_many


class SettingsService:
    def __init__(self, session):
        self.session = session

    def get_runtime_settings(self) -> settings_module.Settings:
        definitions = settings_module.get_all_setting_definitions()
        raw_values = load_runtime_values(self.session)
        settings_data = {
            attr_name: definition.default_value
            for attr_name, definition in definitions.items()
        }

        for attr_name, definition in definitions.items():
            stored_value = raw_values.get(definition.db_key)
            if stored_value is not None:
                settings_data[attr_name] = settings_module._convert_value(attr_name, stored_value)

        env_url = os.environ.get("APP_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if env_url:
            settings_data["database_url"] = settings_module._normalize_database_url(env_url)

        settings = settings_module.Settings(**settings_data)
        settings_module._settings = settings
        return settings

    def update_runtime_settings(self, payload: dict[str, Any]) -> settings_module.Settings:
        if not payload:
            return self.get_runtime_settings()

        current = self.get_runtime_settings()
        updated_data = current.model_dump()
        updated_data.update(payload)
        updated_settings = settings_module.Settings(**updated_data)
        self._validate_runtime_settings(payload, updated_settings)

        definitions = settings_module.get_all_setting_definitions()
        items: dict[str, dict[str, str | None]] = {}
        for attr_name, value in payload.items():
            definition = definitions.get(attr_name)
            if definition is None:
                raise ValueError(f"unknown setting: {attr_name}")
            items[definition.db_key] = {
                "value": settings_module._value_to_string(value),
                "category": definition.category.value,
                "description": definition.description,
            }

        set_many(self.session, items)
        self.session.commit()
        settings_module._settings = updated_settings
        return updated_settings

    def update_dynamic_proxy_settings(self, payload: dict[str, Any]) -> settings_module.Settings:
        update_dict = {
            "proxy_dynamic_enabled": payload.get("enabled", False),
            "proxy_dynamic_api_url": payload.get("api_url", ""),
            "proxy_dynamic_api_key_header": payload.get("api_key_header", "X-API-Key"),
            "proxy_dynamic_result_field": payload.get("result_field", ""),
        }
        if payload.get("api_key") is not None:
            update_dict["proxy_dynamic_api_key"] = payload.get("api_key")
        return self.update_runtime_settings(update_dict)

    def update_registration_settings(self, payload: dict[str, Any]) -> settings_module.Settings:
        return self.update_runtime_settings(
            {
                "registration_max_retries": payload["max_retries"],
                "registration_timeout": payload["timeout"],
                "registration_default_password_length": payload["default_password_length"],
                "registration_sleep_min": payload["sleep_min"],
                "registration_sleep_max": payload["sleep_max"],
            }
        )

    def update_webui_settings(self, payload: dict[str, Any]) -> settings_module.Settings:
        update_dict = {}
        if payload.get("host") is not None:
            update_dict["webui_host"] = payload["host"]
        if payload.get("port") is not None:
            update_dict["webui_port"] = payload["port"]
        if payload.get("debug") is not None:
            update_dict["debug"] = payload["debug"]
        if payload.get("access_password"):
            update_dict["webui_access_password"] = payload["access_password"]
        return self.update_runtime_settings(update_dict)

    def update_tempmail_settings(self, payload: dict[str, Any]) -> settings_module.Settings:
        update_dict = {}
        if payload.get("api_url"):
            update_dict["tempmail_base_url"] = payload["api_url"]
        return self.update_runtime_settings(update_dict)

    def update_email_code_settings(self, payload: dict[str, Any]) -> settings_module.Settings:
        return self.update_runtime_settings(
            {
                "email_code_timeout": payload["timeout"],
                "email_code_poll_interval": payload["poll_interval"],
            }
        )

    def _validate_runtime_settings(
        self,
        payload: dict[str, Any],
        updated_settings: settings_module.Settings,
    ) -> None:
        if "email_code_timeout" in payload:
            timeout = int(updated_settings.email_code_timeout)
            if timeout < 30 or timeout > 600:
                raise ValueError("timeout must be between 30 and 600 seconds")

        if "email_code_poll_interval" in payload:
            poll_interval = int(updated_settings.email_code_poll_interval)
            if poll_interval < 1 or poll_interval > 30:
                raise ValueError("poll interval must be between 1 and 30 seconds")

        if updated_settings.registration_sleep_max < updated_settings.registration_sleep_min:
            raise ValueError("registration sleep range is invalid")

        if not 1 <= int(updated_settings.proxy_port) <= 65535:
            raise ValueError("proxy port is invalid")

        if not 1 <= int(updated_settings.webui_port) <= 65535:
            raise ValueError("webui port is invalid")
