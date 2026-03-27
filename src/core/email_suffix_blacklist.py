"""邮箱后缀黑名单核心工具。"""
from typing import Any

TEMPORARY_EMAIL_BLACKLIST_SERVICE_TYPES = {
    "tempmail",
    "temp_mail",
    "duck_mail",
    "freemail",
    "moe_mail",
}


class RegistrationDisallowedSuffixError(RuntimeError):
    def __init__(self, *, email: str | None, suffix: str | None, detail: str):
        self.email = email
        self.suffix = suffix
        self.detail = detail
        super().__init__(detail)


def normalize_email_suffix(value: str) -> str:
    return str(value or "").strip().lstrip("@").lower()


def extract_email_suffix(email: str) -> str | None:
    text = str(email or "").strip()
    if "@" not in text:
        return None
    _, suffix = text.rsplit("@", 1)
    normalized = normalize_email_suffix(suffix)
    return normalized or None


def should_apply_email_suffix_blacklist(service_type: str | Any | None) -> bool:
    raw_service_type = getattr(service_type, "value", service_type)
    normalized = str(raw_service_type or "").strip().lower()
    return normalized in TEMPORARY_EMAIL_BLACKLIST_SERVICE_TYPES
