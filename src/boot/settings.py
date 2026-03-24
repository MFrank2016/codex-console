from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


@dataclass(frozen=True)
class BootSettings:
    host: str | None = None
    port: int | None = None
    debug: bool = False
    reload: bool = False
    log_level: str | None = None
    access_password_override: str | None = None
    database_url_override: str | None = None

    @classmethod
    def from_sources(cls, *, env: Mapping[str, str], cli: Mapping[str, Any]) -> "BootSettings":
        return cls(
            host=cli.get("host") or env.get("WEBUI_HOST") or env.get("APP_HOST"),
            port=_parse_int(cli.get("port")) if cli.get("port") is not None else _parse_int(env.get("WEBUI_PORT") or env.get("APP_PORT")),
            debug=bool(cli.get("debug")) or _parse_bool(env.get("DEBUG")),
            reload=bool(cli.get("reload")) or _parse_bool(env.get("RELOAD")),
            log_level=cli.get("log_level") or env.get("LOG_LEVEL"),
            access_password_override=cli.get("access_password") or env.get("WEBUI_ACCESS_PASSWORD") or env.get("APP_ACCESS_PASSWORD"),
            database_url_override=cli.get("database_url") or env.get("APP_DATABASE_URL") or env.get("DATABASE_URL"),
        )


_boot_settings: BootSettings | None = None


def set_boot_settings(settings: BootSettings) -> None:
    global _boot_settings
    _boot_settings = settings


def get_boot_settings() -> BootSettings:
    global _boot_settings
    if _boot_settings is None:
        _boot_settings = BootSettings.from_sources(env=os.environ, cli={})
    return _boot_settings
