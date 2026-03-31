from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import inspect as sa_inspect

from src.core.registration_failure_records import RegistrationFailureQuery
from src.database.models import Base, RegistrationTask
from src.database.repositories import registration_failure_repository as repo
from src.database.session import DatabaseSessionManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "registration-failure-repository.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _upsert(
    temp_db,
    *,
    task_uuid: str,
    attempt_no: int,
    failed_at: datetime,
    email: str,
    email_suffix: str,
    proxy_ip: str | None,
    error_code: str,
    error_detail: str,
    failure_stage: str | None = None,
    step_key: str | None = None,
    retryable: bool = False,
):
    return repo.upsert_registration_failure_record(
        temp_db,
        task_uuid=task_uuid,
        attempt_no=attempt_no,
        batch_id="batch-1",
        pipeline_key="current_pipeline",
        registration_mode="batch",
        email=email,
        email_suffix=email_suffix,
        email_service_type="tempmail",
        display_name="Alice Smith",
        birthdate="1994-02-03",
        proxy="http://proxy-a",
        proxy_ip=proxy_ip,
        error_code=error_code,
        error_detail=error_detail,
        failure_stage=failure_stage,
        step_key=step_key,
        retryable=retryable,
        failed_at=failed_at,
        extra_json={"step": "create_account_profile"},
    )


def test_upsert_registration_failure_record_overwrites_same_attempt(temp_db):
    first = _upsert(
        temp_db,
        task_uuid="task-1",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 1, 0, 0),
        email="first@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.1",
        error_code="registration_disallowed",
        error_detail="first error",
    )

    second = _upsert(
        temp_db,
        task_uuid="task-1",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 1, 5, 0),
        email="retry@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="2.2.2.2",
        error_code="registration_disallowed",
        error_detail="second error",
    )

    rows = repo.list_registration_failure_records(temp_db)

    assert len(rows) == 1
    assert second.id == first.id
    assert rows[0].email == "retry@blocked.test"
    assert rows[0].proxy_ip == "2.2.2.2"


def test_upsert_registration_failure_record_persists_structured_failure_fields(temp_db):
    row = _upsert(
        temp_db,
        task_uuid="task-structured",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 2, 0, 0),
        email="user@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="3.3.3.3",
        error_code="registration_disallowed",
        error_detail="structured error",
        failure_stage="submit_login_password",
        step_key="submit_login_password",
        retryable=True,
    )

    assert row.failure_stage == "submit_login_password"
    assert row.step_key == "submit_login_password"
    assert row.retryable is True


def test_list_registration_failure_records_filters_structured_failure_fields(temp_db):
    _upsert(
        temp_db,
        task_uuid="task-structured-1",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 2, 1, 0),
        email="one@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="3.3.3.1",
        error_code="registration_disallowed",
        error_detail="structured error 1",
        failure_stage="submit_login_password",
        step_key="submit_login_password",
        retryable=True,
    )
    _upsert(
        temp_db,
        task_uuid="task-structured-2",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 2, 2, 0),
        email="two@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="3.3.3.2",
        error_code="oauth_failed",
        error_detail="structured error 2",
        failure_stage="exchange_oauth_token",
        step_key="exchange_oauth_token",
        retryable=False,
    )

    rows = repo.list_registration_failure_records(
        temp_db,
        filters=RegistrationFailureQuery(
            failure_stage="submit_login_password",
            step_key="submit_login_password",
            retryable=True,
        ),
    )

    assert [row.task_uuid for row in rows] == ["task-structured-1"]


def test_list_registration_failure_records_orders_failed_at_desc_then_id_desc(temp_db):
    _upsert(
        temp_db,
        task_uuid="task-old",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 0, 0, 0),
        email="old@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.1",
        error_code="registration_disallowed",
        error_detail="old error",
    )
    _upsert(
        temp_db,
        task_uuid="task-new",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 0, 1, 0),
        email="new@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.2",
        error_code="registration_disallowed",
        error_detail="new error",
    )

    rows = repo.list_registration_failure_records(temp_db)

    assert [row.task_uuid for row in rows] == ["task-new", "task-old"]


def test_build_registration_failure_summary_groups_unknown_proxy_and_sorts_stably(temp_db):
    rows = [
        ("task-1", "a.test", None, "registration_disallowed"),
        ("task-2", "b.test", None, "registration_disallowed"),
        ("task-3", "c.test", "1.1.1.1", "proxy_error"),
        ("task-4", "d.test", "1.1.1.2", "proxy_error"),
        ("task-5", "e.test", "1.1.1.3", "oauth_failed"),
        ("task-6", "f.test", "1.1.1.4", "unknown"),
        ("task-7", "g.test", "1.1.1.5", "create_email_failed"),
        ("task-8", "h.test", "1.1.1.6", "blocked_other"),
    ]
    for index, (task_uuid, suffix, proxy_ip, error_code) in enumerate(rows, start=1):
        _upsert(
            temp_db,
            task_uuid=task_uuid,
            attempt_no=1,
            failed_at=datetime(2026, 3, 28, 1, index, 0),
            email=f"user{index}@{suffix}",
            email_suffix=suffix,
            proxy_ip=proxy_ip,
            error_code=error_code,
            error_detail=f"{error_code} detail {index}",
        )

    summary = repo.build_registration_failure_summary(temp_db, filters=None)

    assert summary["total_failed_attempts"] == 8
    assert summary["top_proxy_ips"][0] == {"value": "unknown", "count": 2}
    assert len(summary["top_email_suffixes"]) == 5
    assert len(summary["top_error_codes"]) == 5
    assert len(summary["top_proxy_ips"]) == 5


def test_build_registration_failure_summary_includes_structured_dimensions(temp_db):
    _upsert(
        temp_db,
        task_uuid="task-structured-a",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 4, 0, 0),
        email="a@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="8.8.8.8",
        error_code="oauth_failed",
        error_detail="oauth timeout",
        failure_stage="submit_login_password",
        step_key="submit_login_password",
        retryable=True,
    )
    _upsert(
        temp_db,
        task_uuid="task-structured-b",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 4, 1, 0),
        email="b@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="8.8.4.4",
        error_code="oauth_failed",
        error_detail="oauth timeout",
        failure_stage="submit_login_password",
        step_key="submit_login_password",
        retryable=True,
    )
    _upsert(
        temp_db,
        task_uuid="task-structured-c",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 4, 2, 0),
        email="c@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.1",
        error_code="proxy_error",
        error_detail="network timeout",
        failure_stage="exchange_oauth_token",
        step_key="exchange_oauth_token",
        retryable=False,
    )

    summary = repo.build_registration_failure_summary(temp_db, filters=None)

    assert summary["top_failure_stages"][0] == {"value": "submit_login_password", "count": 2}
    assert summary["top_step_keys"][0] == {"value": "submit_login_password", "count": 2}
    assert summary["retryable_breakdown"] == [
        {"value": "retryable", "count": 2},
        {"value": "non_retryable", "count": 1},
    ]


def test_list_registration_failure_records_applies_suffix_contains_and_error_keyword_case_insensitive(temp_db):
    _upsert(
        temp_db,
        task_uuid="task-blocked-1",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 3, 0, 0),
        email="one@blocked.test",
        email_suffix="blocked.test",
        proxy_ip="1.1.1.1",
        error_code="registration_disallowed",
        error_detail="Sorry, blocked by policy",
    )
    _upsert(
        temp_db,
        task_uuid="task-blocked-2",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 3, 1, 0),
        email="two@semi-blocked.test",
        email_suffix="semi-blocked.test",
        proxy_ip="1.1.1.2",
        error_code="REGISTRATION_DISALLOWED",
        error_detail="another blocked case",
    )
    _upsert(
        temp_db,
        task_uuid="task-other",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 3, 2, 0),
        email="three@ok.test",
        email_suffix="ok.test",
        proxy_ip="1.1.1.3",
        error_code="proxy_error",
        error_detail="network timeout",
    )

    rows = repo.list_registration_failure_records(
        temp_db,
        filters=RegistrationFailureQuery(
            email_suffix="blocked",
            error_keyword="REGISTRATION_DISALLOWED",
        ),
    )

    assert [row.task_uuid for row in rows] == ["task-blocked-2", "task-blocked-1"]


def test_count_registration_failure_records_uses_same_filters_as_list(temp_db):
    _upsert(
        temp_db,
        task_uuid="task-proxy-1",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 4, 0, 0),
        email="one@a.test",
        email_suffix="a.test",
        proxy_ip="1.1.1.1",
        error_code="proxy_error",
        error_detail="proxy failed one",
    )
    _upsert(
        temp_db,
        task_uuid="task-proxy-2",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 4, 1, 0),
        email="two@b.test",
        email_suffix="b.test",
        proxy_ip="1.1.1.2",
        error_code="proxy_error",
        error_detail="proxy failed two",
    )
    _upsert(
        temp_db,
        task_uuid="task-proxy-3",
        attempt_no=1,
        failed_at=datetime(2026, 3, 28, 4, 2, 0),
        email="three@c.test",
        email_suffix="c.test",
        proxy_ip="1.1.1.3",
        error_code="other_error",
        error_detail="contains proxy_error in detail",
    )

    filters = RegistrationFailureQuery(error_keyword="proxy_error")

    assert repo.count_registration_failure_records(temp_db, filters=filters) == 3


def test_upsert_registration_failure_record_supports_non_committed_atomic_flow(temp_db):
    repo.upsert_registration_failure_record(
        temp_db,
        task_uuid="task-atomic",
        attempt_no=1,
        batch_id="batch-atomic",
        pipeline_key="current_pipeline",
        registration_mode="batch",
        email="atomic@blocked.test",
        email_suffix="blocked.test",
        email_service_type="tempmail",
        display_name="Atomic User",
        birthdate="1994-02-03",
        proxy="http://proxy-a",
        proxy_ip="1.1.1.1",
        error_code="registration_disallowed",
        error_detail="atomic error",
        failed_at=datetime(2026, 3, 28, 5, 0, 0),
        extra_json={"step": "create_account_profile"},
    )

    temp_db.rollback()

    assert repo.count_registration_failure_records(temp_db) == 0


def test_upsert_registration_failure_record_does_not_expire_unrelated_loaded_objects(temp_db):
    task = RegistrationTask(task_uuid="task-keep-loaded", status="pending")
    temp_db.add(task)
    temp_db.commit()
    temp_db.refresh(task)

    repo.upsert_registration_failure_record(
        temp_db,
        task_uuid="task-failure",
        attempt_no=1,
        batch_id="batch-keep-loaded",
        pipeline_key="current_pipeline",
        registration_mode="batch",
        email="loaded@blocked.test",
        email_suffix="blocked.test",
        email_service_type="tempmail",
        display_name="Loaded User",
        birthdate="1994-02-03",
        proxy="http://proxy-a",
        proxy_ip="1.1.1.1",
        error_code="registration_disallowed",
        error_detail="loaded error",
        failed_at=datetime(2026, 3, 28, 6, 0, 0),
        extra_json={"step": "create_account_profile"},
    )

    assert sa_inspect(task).expired is False
