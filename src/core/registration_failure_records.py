from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .email_suffix_blacklist import RegistrationDisallowedSuffixError, extract_email_suffix

SENSITIVE_RESULT_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "session_token",
}


@dataclass(slots=True)
class RegistrationFailureQuery:
    pipeline_key: str | None = None
    registration_mode: str | None = None
    email_service_type: str | None = None
    email_suffix: str | None = None
    error_keyword: str | None = None
    failed_from: datetime | None = None
    failed_to: datetime | None = None


@dataclass(slots=True)
class RegistrationFailureWritePayload:
    task_uuid: str
    attempt_no: int
    batch_id: str | None
    pipeline_key: str
    registration_mode: str
    email: str | None
    email_service_type: str | None
    display_name: str | None
    birthdate: str | None
    proxy: str | None
    proxy_ip: str | None
    error_code: str
    error_detail: str
    failed_at: datetime
    extra_json: dict[str, Any]


def truncate_error_detail(value: str | None, *, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if not text:
        return "(empty)"
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def redact_result_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in SENSITIVE_RESULT_KEYS:
                redacted[key] = truncate_secret(str(item or ""))
            else:
                redacted[key] = redact_result_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_result_payload(item) for item in value]
    return value


def truncate_secret(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:20] + "..."


def classify_failure_error(
    *,
    result_payload: dict[str, Any] | None,
    error_message: str | None,
    exc: Exception | None = None,
) -> str:
    if isinstance(exc, RegistrationDisallowedSuffixError):
        return "registration_disallowed"

    message = str(error_message or "").lower()
    detail = str(((result_payload or {}).get("error_message") or "")).lower()
    combined = f"{message} {detail}"
    if "registration disallowed" in combined or "registration_disallowed" in combined:
        return "registration_disallowed"
    if "create_email" in combined or "创建邮箱失败" in combined:
        return "create_email_failed"
    if "proxy" in combined or "ip location" in combined:
        return "proxy_error"
    if "oauth" in combined:
        return "oauth_failed"
    return "unknown"


def extract_failure_profile(*, engine: Any | None = None, result_payload: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    source = getattr(engine, "_engine", engine) if engine is not None else None
    profile = None
    if source is not None:
        profile = getattr(source, "generated_user_profile", None)
    if not profile:
        profile = ((result_payload or {}).get("metadata") or {}).get("user_profile")
    if not isinstance(profile, dict):
        return None, None

    display_name = str(profile.get("name") or profile.get("display_name") or "").strip() or None
    birthdate = str(profile.get("birthdate") or profile.get("date_of_birth") or "").strip() or None
    return display_name, birthdate


def extract_failure_proxy_ip(*, engine: Any | None = None, result_payload: dict[str, Any] | None = None) -> str | None:
    source = getattr(engine, "_engine", engine) if engine is not None else None
    if source is not None:
        proxy_ip = str(getattr(source, "proxy_ip", "") or "").strip()
        if proxy_ip:
            return proxy_ip
    metadata = (result_payload or {}).get("metadata") or {}
    proxy_ip = str(metadata.get("proxy_ip") or "").strip()
    return proxy_ip or None


def build_failure_write_payload(
    *,
    task_uuid: str | None,
    attempt_no: int,
    batch_id: str | None,
    pipeline_key: str,
    registration_mode: str,
    email_service_type: str | None,
    email: str | None,
    proxy: str | None,
    error_message: str | None,
    result_payload: dict[str, Any] | None,
    engine: Any | None,
    exc: Exception | None = None,
    failed_at: datetime,
) -> RegistrationFailureWritePayload | None:
    cleaned_task_uuid = str(task_uuid or "").strip()
    if not cleaned_task_uuid:
        return None

    known_email = str(email or (result_payload or {}).get("email") or getattr(engine, "email", "") or "").strip() or None
    display_name, birthdate = extract_failure_profile(engine=engine, result_payload=result_payload)
    proxy_ip = extract_failure_proxy_ip(engine=engine, result_payload=result_payload)
    detail = truncate_error_detail(error_message)
    error_code = classify_failure_error(result_payload=result_payload, error_message=error_message, exc=exc)

    extra_json: dict[str, Any] = {
        "result_payload": redact_result_payload(result_payload or {}),
    }
    if exc is not None:
        extra_json["exception_type"] = type(exc).__name__

    return RegistrationFailureWritePayload(
        task_uuid=cleaned_task_uuid,
        attempt_no=int(attempt_no),
        batch_id=str(batch_id or "").strip() or None,
        pipeline_key=str(pipeline_key or "current_pipeline").strip() or "current_pipeline",
        registration_mode=str(registration_mode or "single").strip() or "single",
        email=known_email,
        email_service_type=str(email_service_type or "").strip() or None,
        display_name=display_name,
        birthdate=birthdate,
        proxy=str(proxy or "").strip() or None,
        proxy_ip=proxy_ip,
        error_code=error_code,
        error_detail=detail,
        failed_at=failed_at,
        extra_json=extra_json,
    )


def write_registration_failure_record(session, payload: RegistrationFailureWritePayload | None):
    if payload is None:
        return None
    from ..database.repositories import registration_failure_repository as failure_repo

    return failure_repo.upsert_registration_failure_record(
        session,
        task_uuid=payload.task_uuid,
        attempt_no=payload.attempt_no,
        batch_id=payload.batch_id,
        pipeline_key=payload.pipeline_key,
        registration_mode=payload.registration_mode,
        email=payload.email,
        email_suffix=extract_email_suffix(payload.email or ""),
        email_service_type=payload.email_service_type,
        display_name=payload.display_name,
        birthdate=payload.birthdate,
        proxy=payload.proxy,
        proxy_ip=payload.proxy_ip,
        error_code=payload.error_code,
        error_detail=payload.error_detail,
        failed_at=payload.failed_at,
        extra_json=payload.extra_json,
    )
