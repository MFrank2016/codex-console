"""Registration read-side view objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class RegistrationTaskView:
    id: int
    task_uuid: str
    status: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    result: Dict[str, Any] | None = None
    logs: str | None = None


@dataclass(frozen=True)
class RegistrationTaskListView:
    total: int
    tasks: List[RegistrationTaskView]


@dataclass(frozen=True)
class RegistrationFailureSummaryView:
    total_failed_attempts: int
    top_email_suffixes: List[Dict[str, Any]]
    top_error_codes: List[Dict[str, Any]]
    top_proxy_ips: List[Dict[str, Any]]
    today_failed_attempts: int


@dataclass(frozen=True)
class RegistrationFailureListView:
    total: int
    items: List[Dict[str, Any]]


@dataclass(frozen=True)
class RegistrationBatchStatusView:
    batch_id: str
    payload: Dict[str, Any]


@dataclass(frozen=True)
class RegistrationStatsView:
    by_status: Dict[str, int]
    today_count: int


__all__ = [
    "RegistrationTaskView",
    "RegistrationTaskListView",
    "RegistrationFailureSummaryView",
    "RegistrationFailureListView",
    "RegistrationBatchStatusView",
    "RegistrationStatsView",
]
