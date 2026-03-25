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
        field_map = {
            "enabled": "proxy_dynamic_enabled",
            "api_url": "proxy_dynamic_api_url",
            "api_key_header": "proxy_dynamic_api_key_header",
            "result_field": "proxy_dynamic_result_field",
            "request_method": "proxy_dynamic_request_method",
            "request_url": "proxy_dynamic_request_url",
            "request_headers_template": "proxy_dynamic_request_headers_template",
            "request_body_mode": "proxy_dynamic_request_body_mode",
            "request_body_template": "proxy_dynamic_request_body_template",
            "request_timeout_seconds": "proxy_dynamic_request_timeout_seconds",
            "request_count_param_name": "proxy_dynamic_request_count_param_name",
            "request_count_default": "proxy_dynamic_request_count_default",
            "response_root_field": "proxy_dynamic_response_root_field",
            "response_item_mode": "proxy_dynamic_response_item_mode",
            "response_field_mapping": "proxy_dynamic_response_field_mapping",
            "task_defaults": "proxy_dynamic_task_defaults",
        }
        update_dict = {
            target_key: payload[source_key]
            for source_key, target_key in field_map.items()
            if source_key in payload
        }
        api_key = payload.get("api_key")
        if api_key not in (None, ""):
            update_dict["proxy_dynamic_api_key"] = api_key
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

    def update_outlook_settings(self, payload: dict[str, Any]) -> settings_module.Settings:
        update_dict = {}
        if payload.get("default_client_id") is not None:
            update_dict["outlook_default_client_id"] = payload["default_client_id"]
        return self.update_runtime_settings(update_dict)

    def update_team_manager_settings(self, payload: dict[str, Any]) -> settings_module.Settings:
        update_dict = {
            "tm_enabled": payload.get("enabled", False),
            "tm_api_url": payload.get("api_url", ""),
        }
        if payload.get("api_key"):
            update_dict["tm_api_key"] = payload["api_key"]
        return self.update_runtime_settings(update_dict)

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

        if "proxy_dynamic_request_method" in payload:
            request_method = str(updated_settings.proxy_dynamic_request_method)
            if request_method not in {"GET", "POST"}:
                raise ValueError("request method must be GET or POST")

        if "proxy_dynamic_request_body_mode" in payload:
            request_body_mode = str(updated_settings.proxy_dynamic_request_body_mode)
            if request_body_mode not in {"auto", "json", "form", "raw"}:
                raise ValueError("request body mode must be auto, json, form or raw")

        if "proxy_dynamic_response_item_mode" in payload:
            response_item_mode = str(updated_settings.proxy_dynamic_response_item_mode)
            if response_item_mode not in {"string_list", "object_list"}:
                raise ValueError("response item mode must be string_list or object_list")

        if "proxy_dynamic_request_timeout_seconds" in payload:
            request_timeout = int(updated_settings.proxy_dynamic_request_timeout_seconds)
            if request_timeout <= 0:
                raise ValueError("request timeout must be greater than 0")

        if "proxy_dynamic_request_count_default" in payload:
            request_count_default = int(updated_settings.proxy_dynamic_request_count_default)
            if request_count_default <= 0:
                raise ValueError("request count must be greater than 0")

        if updated_settings.registration_sleep_max < updated_settings.registration_sleep_min:
            raise ValueError("registration sleep range is invalid")

        if not 1 <= int(updated_settings.proxy_port) <= 65535:
            raise ValueError("proxy port is invalid")

        if not 1 <= int(updated_settings.webui_port) <= 65535:
            raise ValueError("webui port is invalid")
