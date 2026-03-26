from __future__ import annotations

import re
from typing import Any

from ...database import crud
from ...database.models import ScheduledPlan
from ...database.session import get_db
from ..cpa_client import count_valid_accounts, delete_invalid_accounts, probe_invalid_accounts
from ..engine import ScheduledRunCancelledError, is_run_stop_requested
from ..run_logger import append_run_log, finalize_cancelled_run, finalize_run, raise_if_stop_requested


_PROBE_PROGRESS_PATTERN = re.compile(r"scanned=(\d+)(?:/\d+)?, invalid=(\d+)")
_PROBE_CANDIDATES_PATTERN = re.compile(r"total=(\d+), selected=(\d+)")
_PROGRESS_EVERY = 100
_DEFAULT_PROBE_WORKERS = 10
_DEFAULT_DELETE_WORKERS = 20


def _resolve_max_cleanup_count(config: dict[str, Any]) -> int:
    raw_value = config.get("max_cleanup_count", 0)
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _resolve_max_probe_count(config: dict[str, Any]) -> int:
    raw_value = config.get("max_probe_count", 0)
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _resolve_worker_count(config: dict[str, Any], key: str, *, default: int) -> int:
    raw_value = config.get(key, 0)
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def run_cleanup_plan(*, plan_id: int, run_id: int) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "probe_items_selected": 0,
        "probe_items_scanned": 0,
        "invalid_items_found": 0,
        "invalid_items_considered": 0,
        "local_marked_expired": 0,
        "remote_deleted": 0,
        "remote_delete_failed": 0,
        "remaining_valid_count": None,
    }

    try:
        with get_db() as db:
            plan = db.query(ScheduledPlan).filter(ScheduledPlan.id == plan_id).first()
            if plan is None:
                raise ValueError(f"scheduled plan {plan_id} does not exist")
            if plan.task_type != "cpa_cleanup":
                raise ValueError(f"plan {plan_id} is not cpa_cleanup")

            service = crud.get_cpa_service_by_id(db, plan.cpa_service_id)
            if service is None:
                raise ValueError(f"cpa service {plan.cpa_service_id} does not exist")

            service_payload = {
                "id": service.id,
                "api_url": service.api_url,
                "api_token": service.api_token,
            }
            cpa_service_id = plan.cpa_service_id
            max_cleanup_count = _resolve_max_cleanup_count(plan.config or {})
            max_probe_count = _resolve_max_probe_count(plan.config or {})
            probe_workers = _resolve_worker_count(plan.config or {}, "probe_workers", default=_DEFAULT_PROBE_WORKERS)
            delete_workers = _resolve_worker_count(plan.config or {}, "delete_workers", default=_DEFAULT_DELETE_WORKERS)

        append_run_log(run_id, f"cleanup runner start (plan_id={plan_id})")
        append_run_log(
            run_id,
            (
                "cleanup probe config "
                f"(max_probe_count={max_probe_count or 'unlimited'}, "
                f"max_cleanup_count={max_cleanup_count or 'unlimited'}, "
                f"probe_workers={probe_workers}, delete_workers={delete_workers})"
            ),
        )

        next_probe_progress = _PROGRESS_EVERY

        def _on_probe_progress(message: str) -> None:
            nonlocal next_probe_progress
            append_run_log(run_id, message)

            candidates_match = _PROBE_CANDIDATES_PATTERN.search(message)
            if candidates_match:
                summary["probe_items_selected"] = int(candidates_match.group(2))

            match = _PROBE_PROGRESS_PATTERN.search(message)
            if match:
                scanned = int(match.group(1))
                invalid = int(match.group(2))
                summary["probe_items_scanned"] = max(int(summary["probe_items_scanned"]), scanned)
                summary["invalid_items_found"] = max(int(summary["invalid_items_found"]), invalid)
                while scanned >= next_probe_progress:
                    append_run_log(
                        run_id,
                        f"cleanup probe progress (scanned={next_probe_progress}, invalid={invalid})",
                    )
                    next_probe_progress += _PROGRESS_EVERY

            raise_if_stop_requested(run_id, stage="cleanup probe")

        invalid_items = probe_invalid_accounts(
            service=service_payload,
            # 这里不能再用 cleanup 上限截断 probe 结果，否则“失效数”会被误记成“本次清理数”。
            limit=None,
            max_probe_count=max_probe_count if max_probe_count > 0 else None,
            progress_callback=_on_probe_progress,
            workers=probe_workers,
        )
        summary["invalid_items_found"] = max(int(summary["invalid_items_found"]), len(invalid_items))

        selected_items = invalid_items[:max_cleanup_count] if max_cleanup_count > 0 else invalid_items
        summary["invalid_items_considered"] = len(selected_items)

        remote_names: list[str] = []
        local_processed = 0

        with get_db() as db:
            email_batch: list[str] = []
            for item in selected_items:
                raise_if_stop_requested(run_id, stage="cleanup expire")
                email = str(item.get("email") or "").strip()
                if not email:
                    continue

                email_batch.append(email)
                local_processed += 1
                if len(email_batch) >= _PROGRESS_EVERY:
                    summary["local_marked_expired"] += crud.mark_accounts_expired_by_emails_and_cpa(
                        db,
                        emails=email_batch,
                        cpa_service_id=cpa_service_id,
                        reason="cpa_cleanup",
                    )
                    append_run_log(
                        run_id,
                        (
                            "cleanup expire progress "
                            f"(processed={local_processed}, local_expired={summary['local_marked_expired']})"
                        ),
                    )
                    email_batch = []

                name = str(item.get("name") or "").strip()
                if not name:
                    name = f"{email}.json"
                remote_names.append(name)

            if email_batch:
                summary["local_marked_expired"] += crud.mark_accounts_expired_by_emails_and_cpa(
                    db,
                    emails=email_batch,
                    cpa_service_id=cpa_service_id,
                    reason="cpa_cleanup",
                )

        if remote_names:
            remote_processed = 0
            for start in range(0, len(remote_names), _PROGRESS_EVERY):
                raise_if_stop_requested(run_id, stage="cleanup delete")
                batch = remote_names[start:start + _PROGRESS_EVERY]
                delete_result = delete_invalid_accounts(
                    service=service_payload,
                    names=batch,
                    workers=delete_workers,
                )
                summary["remote_deleted"] += int(delete_result.get("deleted", 0) or 0)
                summary["remote_delete_failed"] += int(delete_result.get("failed", 0) or 0)
                remote_processed += len(batch)
                if remote_processed % _PROGRESS_EVERY == 0:
                    append_run_log(
                        run_id,
                        (
                            "cleanup delete progress "
                            f"(processed={remote_processed}, remote_deleted={summary['remote_deleted']}, "
                            f"remote_delete_failed={summary['remote_delete_failed']})"
                        ),
                    )

        raise_if_stop_requested(run_id, stage="cleanup delete")

        try:
            summary["remaining_valid_count"] = max(0, int(count_valid_accounts(service_payload)))
            append_run_log(
                run_id,
                f"cleanup remaining valid count (remaining={summary['remaining_valid_count']})",
            )
        except Exception as exc:
            append_run_log(
                run_id,
                f"cleanup remaining valid count unavailable: {exc}",
                level="WARN",
            )

        append_run_log(
            run_id,
            (
                "cleanup runner complete "
                f"(invalid={summary['invalid_items_found']}, "
                f"local_expired={summary['local_marked_expired']}, "
                f"remote_deleted={summary['remote_deleted']})"
            ),
        )
        finalize_run(run_id, status="success", summary=summary)
        return summary

    except ScheduledRunCancelledError:
        if is_run_stop_requested(run_id):
            finalize_cancelled_run(run_id, summary=summary)
            return summary
        raise
    except Exception as exc:
        append_run_log(run_id, f"cleanup runner failed: {exc}", level="ERROR")
        finalize_run(run_id, status="failed", summary=summary, error_message=str(exc))
        raise
