from __future__ import annotations

from sqlalchemy import asc, func
from sqlalchemy.orm import Session

from ..models import RegistrationRun, RegistrationRunEvent


class RegistrationRepository:
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

    def __init__(self, session: Session):
        self.session = session

    def create_run(self, **kwargs) -> RegistrationRun:
        row = RegistrationRun(**kwargs)
        self.session.add(row)
        self.session.flush()
        self.session.refresh(row)
        return row

    def get_run(self, run_id: int) -> RegistrationRun | None:
        return self.session.query(RegistrationRun).filter(RegistrationRun.id == run_id).first()

    def get_run_by_task_uuid(self, task_uuid: str) -> RegistrationRun | None:
        return self.session.query(RegistrationRun).filter(RegistrationRun.task_uuid == task_uuid).first()

    def list_latest_runs_by_task_uuids(self, task_uuids: list[str]) -> list[RegistrationRun]:
        ordered_task_uuids = list(dict.fromkeys(task_uuids))
        if not ordered_task_uuids:
            return []

        latest_ids_subquery = (
            self.session.query(func.max(RegistrationRun.id).label("latest_id"))
            .filter(RegistrationRun.task_uuid.in_(ordered_task_uuids))
            .group_by(RegistrationRun.task_uuid)
            .subquery()
        )
        rows = (
            self.session.query(RegistrationRun)
            .join(latest_ids_subquery, RegistrationRun.id == latest_ids_subquery.c.latest_id)
            .all()
        )
        position = {task_uuid: index for index, task_uuid in enumerate(ordered_task_uuids)}
        rows.sort(key=lambda row: position.get(row.task_uuid, len(position)))
        return rows

    def update_run(self, run_id: int, **kwargs) -> RegistrationRun | None:
        row = self.get_run(run_id)
        if row is None:
            return None
        for key, value in kwargs.items():
            if hasattr(row, key):
                setattr(row, key, value)
        self.session.flush()
        self.session.refresh(row)
        return row

    def update_status_if_not_terminal(self, run_id: int, *, status: str, **kwargs) -> RegistrationRun | None:
        row = self.get_run(run_id)
        if row is None or row.status in self.TERMINAL_STATUSES:
            return row
        return self.update_run(run_id, status=status, **kwargs)

    def append_event(
        self,
        *,
        run_id: int,
        level: str,
        message: str,
        created_at=None,
    ) -> RegistrationRunEvent:
        if self.get_run(run_id) is None:
            raise ValueError(f"registration run not found: run_id={run_id}")

        row_payload = {"run_id": run_id, "level": level, "message": message}
        if created_at is not None:
            row_payload["created_at"] = created_at

        row = RegistrationRunEvent(**row_payload)
        self.session.add(row)
        self.session.flush()
        self.session.refresh(row)
        return row

    def list_events(self, run_id: int) -> list[RegistrationRunEvent]:
        return (
            self.session.query(RegistrationRunEvent)
            .filter(RegistrationRunEvent.run_id == run_id)
            .order_by(asc(RegistrationRunEvent.id))
            .all()
        )


def _repository(session: Session) -> RegistrationRepository:
    return RegistrationRepository(session)


def create_registration_run(session: Session, **kwargs) -> RegistrationRun:
    return _repository(session).create_run(**kwargs)


def get_registration_run_by_id(session: Session, run_id: int) -> RegistrationRun | None:
    return _repository(session).get_run(run_id)


def get_registration_run_by_task_uuid(session: Session, task_uuid: str) -> RegistrationRun | None:
    return _repository(session).get_run_by_task_uuid(task_uuid)


def list_latest_runs_by_task_uuids(session: Session, task_uuids: list[str]) -> list[RegistrationRun]:
    return _repository(session).list_latest_runs_by_task_uuids(task_uuids)


def update_status_if_not_terminal(
    session: Session,
    run_id: int,
    *,
    status: str,
    **kwargs,
) -> RegistrationRun | None:
    return _repository(session).update_status_if_not_terminal(run_id, status=status, **kwargs)


def append_registration_run_event(
    session: Session,
    *,
    run_id: int,
    level: str,
    message: str,
    created_at=None,
) -> RegistrationRunEvent:
    return _repository(session).append_event(
        run_id=run_id,
        level=level,
        message=message,
        created_at=created_at,
    )


def list_registration_run_events(session: Session, run_id: int) -> list[RegistrationRunEvent]:
    return _repository(session).list_events(run_id)


def update_registration_run(session: Session, run_id: int, **kwargs) -> RegistrationRun | None:
    return _repository(session).update_run(run_id, **kwargs)
