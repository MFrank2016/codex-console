from __future__ import annotations

from sqlalchemy import asc
from sqlalchemy.orm import Session

from ..models import RegistrationRun, RegistrationRunEvent


def create_registration_run(session: Session, **kwargs) -> RegistrationRun:
    row = RegistrationRun(**kwargs)
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def get_registration_run_by_id(session: Session, run_id: int) -> RegistrationRun | None:
    return session.query(RegistrationRun).filter(RegistrationRun.id == run_id).first()


def get_registration_run_by_task_uuid(session: Session, task_uuid: str) -> RegistrationRun | None:
    return session.query(RegistrationRun).filter(RegistrationRun.task_uuid == task_uuid).first()


def append_registration_run_event(
    session: Session,
    *,
    run_id: int,
    level: str,
    message: str,
    created_at=None,
) -> RegistrationRunEvent:
    row = RegistrationRunEvent(run_id=run_id, level=level, message=message, created_at=created_at)
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def list_registration_run_events(session: Session, run_id: int) -> list[RegistrationRunEvent]:
    return (
        session.query(RegistrationRunEvent)
        .filter(RegistrationRunEvent.run_id == run_id)
        .order_by(asc(RegistrationRunEvent.id))
        .all()
    )


def update_registration_run(session: Session, run_id: int, **kwargs) -> RegistrationRun | None:
    row = get_registration_run_by_id(session, run_id)
    if row is None:
        return None
    for key, value in kwargs.items():
        if hasattr(row, key):
            setattr(row, key, value)
    session.flush()
    session.refresh(row)
    return row
