from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.time import utc_now_naive
from ..database.repositories.registration_repository import RegistrationRepository


class RegistrationRunsService:
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
    # 迁移兼容：调用方尚未全量显式声明 commit ownership 前，默认保持 commit=True。
    DEFAULT_COMMIT = True

    def __init__(self, session: Session):
        self.session = session
        self.repository = RegistrationRepository(session)

    def _persist(self, row, *, commit: bool = True):
        if row is None:
            return None
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        self.session.refresh(row)
        return row

    def create_run(
        self,
        *,
        task_uuid: str,
        batch_id: str | None,
        trigger_source: str,
        commit: bool = DEFAULT_COMMIT,
    ):
        existing = self.repository.get_run_by_task_uuid(task_uuid)
        if existing is not None:
            return self._persist(existing, commit=commit)
        run = self.repository.create_run(
            task_uuid=task_uuid,
            batch_id=batch_id,
            trigger_source=trigger_source,
            status="pending",
        )
        return self._persist(run, commit=commit)

    def append_event(self, run_id: int, *, level: str, message: str, commit: bool = DEFAULT_COMMIT):
        event = self.repository.append_event(
            run_id=run_id,
            level=level,
            message=message,
            created_at=utc_now_naive(),
        )
        return self._persist(event, commit=commit)

    def mark_started(self, run_id: int, *, commit: bool = DEFAULT_COMMIT):
        run = self.get_run(run_id)
        if run is None:
            return None
        if run.status in self.TERMINAL_STATUSES:
            return self._persist(run, commit=commit)
        if run.started_at is not None:
            return self._persist(run, commit=commit)
        run = self.repository.update_run(run_id, started_at=utc_now_naive())
        return self._persist(run, commit=commit)

    def mark_running(self, run_id: int, *, commit: bool = DEFAULT_COMMIT):
        run = self.get_run(run_id)
        if run is None:
            return None
        if run.status in self.TERMINAL_STATUSES:
            return self._persist(run, commit=commit)
        if run.status == "running" and run.started_at is not None:
            return self._persist(run, commit=commit)
        started_at = run.started_at or utc_now_naive()
        run = self.repository.update_status_if_not_terminal(
            run_id,
            status="running",
            started_at=started_at,
        )
        return self._persist(run, commit=commit)

    def mark_completed(self, run_id: int, *, commit: bool = DEFAULT_COMMIT):
        run = self.get_run(run_id)
        if run is None:
            return None
        if run.status in self.TERMINAL_STATUSES:
            return self._persist(run, commit=commit)
        run = self.repository.update_status_if_not_terminal(
            run_id,
            status="completed",
            started_at=run.started_at or utc_now_naive(),
            completed_at=utc_now_naive(),
            error_message=None,
        )
        return self._persist(run, commit=commit)

    def mark_failed(self, run_id: int, *, error_message: str | None = None, commit: bool = DEFAULT_COMMIT):
        run = self.get_run(run_id)
        if run is None:
            return None
        if run.status in self.TERMINAL_STATUSES:
            return self._persist(run, commit=commit)
        run = self.repository.update_status_if_not_terminal(
            run_id,
            status="failed",
            started_at=run.started_at or utc_now_naive(),
            completed_at=utc_now_naive(),
            error_message=error_message,
        )
        return self._persist(run, commit=commit)

    def mark_cancelled(self, run_id: int, *, error_message: str | None = None, commit: bool = DEFAULT_COMMIT):
        run = self.get_run(run_id)
        if run is None:
            return None
        if run.status in self.TERMINAL_STATUSES:
            return self._persist(run, commit=commit)
        run = self.repository.update_status_if_not_terminal(
            run_id,
            status="cancelled",
            started_at=run.started_at or utc_now_naive(),
            completed_at=utc_now_naive(),
            error_message=error_message,
        )
        return self._persist(run, commit=commit)

    def get_run(self, run_id: int):
        return self.repository.get_run(run_id)

    def get_run_by_task_uuid(self, task_uuid: str):
        return self.repository.get_run_by_task_uuid(task_uuid)

    def get_events(self, run_id: int):
        return self.repository.list_events(run_id)
