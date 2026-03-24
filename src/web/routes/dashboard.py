from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import desc, func

from ...database import crud
from ...database.models import Account, RegistrationTask, ScheduledPlan, ScheduledRun
from ...database.session import get_db
from ...scheduler.time_utils import SCHEDULER_TZ

router = APIRouter()


def _count_rows_by_status(db, model, status_column) -> dict[str, int]:
    rows = (
        db.query(status_column, func.count(model.id))
        .group_by(status_column)
        .all()
    )
    return {str(status or "unknown"): int(total or 0) for status, total in rows}


def _build_registration_summary(db) -> dict[str, int | float | None]:
    status_counts = _count_rows_by_status(db, RegistrationTask, RegistrationTask.status)

    pending = int(status_counts.get("pending", 0))
    running = int(status_counts.get("running", 0))
    completed = int(status_counts.get("completed", 0))
    failed = int(status_counts.get("failed", 0))
    cancelled = int(status_counts.get("cancelled", 0))
    total = int(sum(status_counts.values()))

    finished = completed + failed + cancelled
    success_rate = round((completed / finished) * 100, 1) if finished else None

    return {
        "total_tasks": total,
        "total": total,
        "pending": pending,
        "running": running,
        "completed": completed,
        "failed": failed,
        "cancelled": cancelled,
        "success_rate": success_rate,
    }


def _build_accounts_summary(db) -> dict[str, int]:
    status_counts = _count_rows_by_status(db, Account, Account.status)
    total = int(sum(status_counts.values()))

    return {
        "total": total,
        "active": int(status_counts.get("active", 0)),
        "expired": int(status_counts.get("expired", 0)),
        "banned": int(status_counts.get("banned", 0)),
        "failed": int(status_counts.get("failed", 0)),
    }


def _build_scheduled_summary(db) -> dict[str, int]:
    plans_total = int(db.query(func.count(ScheduledPlan.id)).scalar() or 0)
    plans_enabled = int(
        db.query(func.count(ScheduledPlan.id))
        .filter(ScheduledPlan.enabled.is_(True))
        .scalar()
        or 0
    )
    start_of_day = _scheduler_day_start_utc_naive()

    return {
        "plans_total": plans_total,
        "plans_enabled": plans_enabled,
        "runs_total": crud.count_scheduled_runs(db),
        "runs_today": crud.count_scheduled_runs(db, started_after=start_of_day),
        "runs_running": crud.count_scheduled_runs(db, status="running"),
        "runs_failed": crud.count_scheduled_runs(db, status="failed"),
    }


def _build_recent_activity(db, limit: int = 6) -> list[dict[str, str | None]]:
    registration_rows = (
        db.query(
            RegistrationTask.task_uuid,
            RegistrationTask.pipeline_key,
            RegistrationTask.status,
            RegistrationTask.created_at,
        )
        .order_by(desc(RegistrationTask.created_at), desc(RegistrationTask.id))
        .limit(limit)
        .all()
    )
    scheduled_rows = (
        db.query(
            ScheduledRun.id,
            ScheduledRun.plan_id,
            ScheduledRun.status,
            ScheduledRun.started_at,
            ScheduledRun.created_at,
            ScheduledPlan.name.label("plan_name"),
        )
        .outerjoin(ScheduledPlan, ScheduledPlan.id == ScheduledRun.plan_id)
        .order_by(desc(ScheduledRun.started_at), desc(ScheduledRun.id))
        .limit(limit)
        .all()
    )

    items: list[dict[str, str | datetime | None]] = []

    for task in registration_rows:
        timestamp = task.created_at
        items.append(
            {
                "kind": "registration",
                "title": f"注册任务 {task.task_uuid[:8]}",
                "description": f"流水线：{task.pipeline_key or 'default'}",
                "status": task.status or "unknown",
                "href": "/registration-workbench",
                "timestamp": timestamp.isoformat() if timestamp else None,
                "_sort_ts": timestamp,
            }
        )

    for run in scheduled_rows:
        timestamp = run.started_at or run.created_at
        items.append(
            {
                "kind": "scheduled",
                "title": f"定时运行 #{run.id}",
                "description": run.plan_name or f"计划 #{run.plan_id}",
                "status": run.status,
                "href": "/scheduled-tasks",
                "timestamp": timestamp.isoformat() if timestamp else None,
                "_sort_ts": timestamp,
            }
        )

    items.sort(key=lambda item: item.get("_sort_ts") or datetime.min, reverse=True)
    compact_items = []
    for item in items[:limit]:
        compact_items.append(
            {
                "kind": item.get("kind"),
                "title": item.get("title"),
                "description": item.get("description"),
                "status": item.get("status"),
                "href": item.get("href"),
                "timestamp": item.get("timestamp"),
            }
        )
    return compact_items


def _scheduler_day_start_utc_naive(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    scheduler_now = current.astimezone(SCHEDULER_TZ)
    scheduler_day_start = scheduler_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return scheduler_day_start.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/summary")
async def get_dashboard_summary():
    with get_db() as db:
        return {
            "registration": _build_registration_summary(db),
            "accounts": _build_accounts_summary(db),
            "scheduled": _build_scheduled_summary(db),
            "quick_links": [
                {
                    "label": "注册工作台",
                    "href": "/registration-workbench",
                    "description": "启动和追踪批量注册任务。",
                },
                {
                    "label": "账号管理",
                    "href": "/accounts",
                    "description": "查看账号状态并执行维护操作。",
                },
                {
                    "label": "定时任务",
                    "href": "/scheduled-tasks",
                    "description": "配置自动补号、清理和刷新任务。",
                },
                {
                    "label": "系统设置",
                    "href": "/settings",
                    "description": "调整代理、OpenAI 与全局参数。",
                },
            ],
            "recent_activity": _build_recent_activity(db),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
