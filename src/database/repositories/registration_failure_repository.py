from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Query, Session

from ...core.registration_failure_records import RegistrationFailureQuery
from ..models import RegistrationFailureRecord


def _apply_filters(query: Query, *, filters: RegistrationFailureQuery | None) -> Query:
    if filters is None:
        return query

    if filters.pipeline_key:
        query = query.filter(RegistrationFailureRecord.pipeline_key == filters.pipeline_key)
    if filters.registration_mode:
        query = query.filter(RegistrationFailureRecord.registration_mode == filters.registration_mode)
    if filters.email_service_type:
        query = query.filter(RegistrationFailureRecord.email_service_type == filters.email_service_type)
    if filters.email_suffix:
        query = query.filter(RegistrationFailureRecord.email_suffix.ilike(f"%{filters.email_suffix}%"))
    if filters.error_keyword:
        keyword = f"%{str(filters.error_keyword).strip().lower()}%"
        haystack = func.lower(
            func.coalesce(RegistrationFailureRecord.error_code, "")
            + " "
            + func.coalesce(RegistrationFailureRecord.error_detail, "")
        )
        query = query.filter(haystack.like(keyword))
    if filters.failed_from is not None:
        query = query.filter(RegistrationFailureRecord.failed_at >= filters.failed_from)
    if filters.failed_to is not None:
        query = query.filter(RegistrationFailureRecord.failed_at <= filters.failed_to)
    return query


def upsert_registration_failure_record(session: Session, **kwargs) -> RegistrationFailureRecord:
    bind = session.get_bind(mapper=RegistrationFailureRecord)
    dialect_name = bind.dialect.name if bind is not None else ""
    update_fields = {
        key: value
        for key, value in kwargs.items()
        if key not in {"task_uuid", "attempt_no"}
    }

    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        statement = sqlite_insert(RegistrationFailureRecord).values(**kwargs)
        if update_fields:
            statement = statement.on_conflict_do_update(
                index_elements=["task_uuid", "attempt_no"],
                set_=update_fields,
            )
        else:
            statement = statement.on_conflict_do_nothing(
                index_elements=["task_uuid", "attempt_no"],
            )
        session.execute(statement)
    elif dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        statement = postgresql_insert(RegistrationFailureRecord).values(**kwargs)
        if update_fields:
            statement = statement.on_conflict_do_update(
                index_elements=["task_uuid", "attempt_no"],
                set_=update_fields,
            )
        else:
            statement = statement.on_conflict_do_nothing(
                index_elements=["task_uuid", "attempt_no"],
            )
        session.execute(statement)
    else:
        row = (
            session.query(RegistrationFailureRecord)
            .filter(
                RegistrationFailureRecord.task_uuid == kwargs["task_uuid"],
                RegistrationFailureRecord.attempt_no == kwargs["attempt_no"],
            )
            .first()
        )
        if row is None:
            row = RegistrationFailureRecord(**kwargs)
            session.add(row)
        else:
            for key, value in kwargs.items():
                if hasattr(row, key):
                    setattr(row, key, value)

    session.flush()
    row = (
        session.query(RegistrationFailureRecord)
        .execution_options(populate_existing=True)
        .filter(
            RegistrationFailureRecord.task_uuid == kwargs["task_uuid"],
            RegistrationFailureRecord.attempt_no == kwargs["attempt_no"],
        )
        .first()
    )
    if row is None:
        raise RuntimeError("registration failure record upsert failed")
    session.refresh(row)
    return row


def list_registration_failure_records(
    session: Session,
    *,
    filters: RegistrationFailureQuery | None = None,
    page: int = 1,
    page_size: int = 20,
) -> list[RegistrationFailureRecord]:
    safe_page = max(1, int(page))
    safe_page_size = max(1, int(page_size))
    query = _apply_filters(session.query(RegistrationFailureRecord), filters=filters)
    return (
        query.order_by(desc(RegistrationFailureRecord.failed_at), desc(RegistrationFailureRecord.id))
        .offset((safe_page - 1) * safe_page_size)
        .limit(safe_page_size)
        .all()
    )


def count_registration_failure_records(
    session: Session,
    *,
    filters: RegistrationFailureQuery | None = None,
) -> int:
    query = _apply_filters(session.query(RegistrationFailureRecord), filters=filters)
    return int(query.count())


def _top_counts(values: list[str | None]) -> list[dict[str, Any]]:
    normalized = [str(value).strip() if value is not None and str(value).strip() else "unknown" for value in values]
    counter = Counter(normalized)
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:5]
    return [{"value": value, "count": count} for value, count in ranked]


def build_registration_failure_summary(
    session: Session,
    *,
    filters: RegistrationFailureQuery | None = None,
) -> dict[str, Any]:
    rows = _apply_filters(session.query(RegistrationFailureRecord), filters=filters).all()
    return {
        "total_failed_attempts": len(rows),
        "top_email_suffixes": _top_counts([row.email_suffix for row in rows]),
        "top_error_codes": _top_counts([row.error_code for row in rows]),
        "top_proxy_ips": _top_counts([row.proxy_ip for row in rows]),
    }
