import pytest

from src.core.email_suffix_blacklist import extract_email_suffix, normalize_email_suffix
from src.database.crud import (
    create_email_suffix_blacklist,
    is_email_suffix_blacklisted,
    upsert_auto_blacklist_suffix,
)
from src.database.models import Base
from src.database.session import DatabaseSessionManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "email-suffix-blacklist.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_normalize_email_suffix_strips_at_and_lowercase():
    assert normalize_email_suffix(" @BadMail.COM ") == "badmail.com"


def test_extract_email_suffix_invalid_email_returns_none():
    assert extract_email_suffix("not-an-email") is None


def test_upsert_auto_blacklist_suffix_reenables_and_accumulates_hit_count(temp_db):
    row = create_email_suffix_blacklist(
        temp_db,
        suffix="badmail.com",
        enabled=False,
        source="manual",
        reason="initial",
    )

    assert row.hit_count == 0

    updated = upsert_auto_blacklist_suffix(
        temp_db,
        "badmail.com",
        reason="disallowed by register",
    )

    assert updated.id == row.id
    assert updated.enabled is True
    assert updated.hit_count == 1
    assert updated.source == "auto_registration_disallowed"
    assert updated.last_hit_at is not None


def test_is_email_suffix_blacklisted_only_matches_enabled_record(temp_db):
    create_email_suffix_blacklist(temp_db, suffix="blocked.com", enabled=True)
    create_email_suffix_blacklist(temp_db, suffix="disabled.com", enabled=False)

    assert is_email_suffix_blacklisted(temp_db, "blocked.com") is True
    assert is_email_suffix_blacklisted(temp_db, "disabled.com") is False
