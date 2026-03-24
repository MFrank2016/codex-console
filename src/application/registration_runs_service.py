from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.time import utc_now_naive
from ..database.repositories.registration_repository import (
    append_registration_run_event,
    create_registration_run,
    get_registration_run_by_id,
    get_registration_run_by_task_uuid,
    list_registration_run_events,
    update_registration_run,
)


class RegistrationRunsService:
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

    def __init__(self, session: Session):
        self.session = session

    def create_run(self, *, task_uuid: str, batch_id: str | None, trigger_source: str):
        existing = get_registration_run_by_task_uuid(self.session, task_uuid)
        if existing is not None:
            return existing
        run = create_registration_run(
            self.session,
            task_uuid=task_uuid,
            batch_id=batch_id,
            trigger_source=trigger_source,
            status="pending",
        )
        self.session.commit()
        return run

    def append_event(self, run_id: int, *, level: str, message: str):
        event = append_registration_run_event(
            self.session,
            run_id=run_id,
            level=level,
            message=message,
            created_at=utc_now_naive(),
        )
        self.session.commit()
        return event

    def mark_running(self, run_id: int):
        run = self.get_run(run_id)
        if run is None or run.status in self.TERMINAL_STATUSES:
            return run
        started_at = run.started_at or utc_now_naive()
        run = update_registration_run(self.session, run_id, status="running", started_at=started_at)
        self.session.commit()
        return run

    def mark_completed(self, run_id: int):
        run = self.get_run(run_id)
        if run is None or run.status in self.TERMINAL_STATUSES:
            return run
        run = update_registration_run(
            self.session,
            run_id,
            status="completed",
            started_at=run.started_at or utc_now_naive(),
            completed_at=utc_now_naive(),
            error_message=None,
        )
        self.session.commit()
        return run

    def mark_failed(self, run_id: int, *, error_message: str | None = None):
        run = self.get_run(run_id)
        if run is None or run.status in self.TERMINAL_STATUSES:
            return run
        run = update_registration_run(
            self.session,
            run_id,
            status="failed",
            started_at=run.started_at or utc_now_naive(),
            completed_at=utc_now_naive(),
            error_message=error_message,
        )
        self.session.commit()
        return run

    def mark_cancelled(self, run_id: int, *, error_message: str | None = None):
        run = self.get_run(run_id)
        if run is None or run.status in self.TERMINAL_STATUSES:
            return run
        run = update_registration_run(
            self.session,
            run_id,
            status="cancelled",
            started_at=run.started_at or utc_now_naive(),
            completed_at=utc_now_naive(),
            error_message=error_message,
        )
        self.session.commit()
        return run

    def get_run(self, run_id: int):
        return get_registration_run_by_id(self.session, run_id)

    def get_run_by_task_uuid(self, task_uuid: str):
        return get_registration_run_by_task_uuid(self.session, task_uuid)

    def get_events(self, run_id: int):
        return list_registration_run_events(self.session, run_id)
