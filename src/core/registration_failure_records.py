from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class RegistrationFailureQuery:
    pipeline_key: str | None = None
    registration_mode: str | None = None
    email_service_type: str | None = None
    email_suffix: str | None = None
    error_keyword: str | None = None
    failed_from: datetime | None = None
    failed_to: datetime | None = None
