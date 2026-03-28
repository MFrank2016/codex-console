# Registration Runs Boundary Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前 `main` 基线上回迁 `registration run` 的持久化边界，让 run 生命周期由 application service 主导、repository 负责持久化、事务 ownership 不再散落在 route / helper / task_manager 中。

**Architecture:** 采用 repository-first 的兼容式迁移方案。第一批不新增表、不整体替换旧分支代码、不改动 UI / realtime 协议；保留当前 `RegistrationRun` schema 与现有对外接口，把 `created / started` 语义先落到 `create_run + started_at checkpoint + 语义化 service API` 上，持久化状态值仍兼容当前主线的 `pending / running / completed / failed / cancelled`，避免把 blast radius 扩散到历史数据、页面筛选与 run-center 之外。`RegistrationService` 先成为单任务 run owner，`BatchRegistrationService` 同步改为消费新的 repository / service 契约，但本批不引入新的“批次聚合 run”数据模型。

**Tech Stack:** Python、FastAPI、SQLAlchemy ORM、pytest、DatabaseSessionManager、现有 task_manager / registration job runner

---

## File Structure Map

### Existing files to modify

- `src/database/repositories/registration_repository.py` — 把当前函数集合收口成 `RegistrationRepository`，提供 run 查询、创建、批量查询、终态保护更新与事件追加接口，同时保留兼容 wrapper，避免一次性改爆所有 import。
- `src/database/repositories/__init__.py` — 导出新的 repository class / helper，保持旧调用点可平滑迁移。
- `src/application/registration_runs_service.py` — 改成语义化 facade：`create_run`、`mark_started`、`mark_running`、`mark_completed`、`mark_failed`、`mark_cancelled`、`append_event`、bulk query；默认不隐式 commit，由调用它的 application service 决定事务边界。
- `src/application/registration_service.py` — 单任务注册正式成为 run owner；把 queued / started / running / terminal checkpoint 变成显式的 service-owned 事务边界。
- `src/application/batch_registration_service.py` — 复用新的 run service / repository 契约，收口代理池失败路径、批量结果汇总查询与 run summary 读取。
- `tests/test_registration_runs_service.py` — run repository / service 边界测试、终态保护测试、commit ownership 测试。
- `tests/test_registration_service.py` — 单任务 owner 语义测试、checkpoint 顺序测试、异常路径测试。
- `tests/test_batch_registration_service.py` — 批量读取 bulk run 查询、代理池失败路径、兼容 summary 行为测试。

### Files expected to stay unchanged in this batch

- `src/database/models.py` — 本批不改 `RegistrationRun` 表结构，不做 schema migration。
- `src/database/session.py` — 本批不增加 migration 语句。
- `src/web/routes/registration.py` — route 保持 HTTP adapter 角色，不直接承担 run 语义迁移。

### Regression-only files to run but not modify unless smoke tests暴露问题

- `tests/test_registration_batch_routes.py`
- `tests/test_registration_page_assets.py`
- `tests/test_run_center_page_assets.py`

---

### Task 1: 冻结 registration repository 边界契约

**Files:**
- Modify: `src/database/repositories/registration_repository.py`
- Modify: `src/database/repositories/__init__.py`
- Test: `tests/test_registration_runs_service.py`

- [ ] **Step 1: 先写 repository 边界的失败测试**

```python
from src.database.repositories.registration_repository import RegistrationRepository


def test_registration_repository_create_run_does_not_commit_implicitly(temp_db):
    repo = RegistrationRepository(temp_db)

    run = repo.create_run(
        task_uuid="task-rollback",
        batch_id=None,
        trigger_source="manual",
        status="pending",
    )
    run_id = run.id

    temp_db.rollback()

    assert repo.get_run(run_id) is None


def test_registration_repository_bulk_lookup_returns_latest_rows_by_task_uuid(temp_db):
    repo = RegistrationRepository(temp_db)

    first = repo.create_run(task_uuid="task-a", batch_id="batch-1", trigger_source="manual", status="pending")
    temp_db.commit()
    repo.update_run(first.id, status="failed", error_message="old")
    temp_db.commit()

    second = repo.create_run(task_uuid="task-b", batch_id="batch-1", trigger_source="manual", status="pending")
    temp_db.commit()

    latest = repo.list_latest_runs_by_task_uuids(["task-a", "task-b"])

    assert set(latest.keys()) == {"task-a", "task-b"}
    assert latest["task-a"].status == "failed"
    assert latest["task-b"].id == second.id


def test_registration_repository_refuses_to_override_terminal_status(temp_db):
    repo = RegistrationRepository(temp_db)

    run = repo.create_run(task_uuid="task-terminal", batch_id=None, trigger_source="manual", status="pending")
    temp_db.commit()
    repo.update_run(run.id, status="completed")
    temp_db.commit()

    persisted = repo.update_status_if_not_terminal(run.id, status="failed", error_message="ignored")
    temp_db.commit()

    assert persisted.status == "completed"
    assert persisted.error_message in (None, "")
```

- [ ] **Step 2: 运行 repository 测试，确认先失败**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest tests/test_registration_runs_service.py -q
```

Expected: FAIL，提示 `RegistrationRepository`、`list_latest_runs_by_task_uuids()` 或 `update_status_if_not_terminal()` 尚不存在，或现有实现存在隐式 commit / 无终态保护。

- [ ] **Step 3: 实现最小 repository 边界**

```python
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
        return (
            self.session.query(RegistrationRun)
            .filter(RegistrationRun.task_uuid == task_uuid)
            .order_by(desc(RegistrationRun.id))
            .first()
        )

    def list_latest_runs_by_task_uuids(self, task_uuids: list[str]) -> dict[str, RegistrationRun]:
        rows = (...)  # 一次查询 + 逐 task_uuid 保留最后一条
        return {row.task_uuid: row for row in rows}

    def update_status_if_not_terminal(self, run_id: int, **kwargs) -> RegistrationRun:
        row = self.require_run(run_id)
        if row.status in self.TERMINAL_STATUSES:
            self.session.refresh(row)
            return row
        return self.update_run(run_id, **kwargs)
```

兼容要求：
- 保留当前模块级函数 wrapper，内部直接转调 `RegistrationRepository`。
- repository 只 `flush` / `refresh`，**不 `commit`**。
- orphan event 仍抛 `ValueError`，不要静默吞掉。

- [ ] **Step 4: 重新运行 repository 测试并确认通过**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest tests/test_registration_runs_service.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 1**

```bash
git add src/database/repositories/registration_repository.py \
  src/database/repositories/__init__.py \
  tests/test_registration_runs_service.py
git commit -m "refactor: add registration run repository boundary"
```

---

### Task 2: 收口 RegistrationRunsService 的生命周期语义

**Files:**
- Modify: `src/application/registration_runs_service.py`
- Test: `tests/test_registration_runs_service.py`

- [ ] **Step 1: 先写 run service 事务 ownership 与语义测试**

```python
from src.application.registration_runs_service import RegistrationRunsService


def test_registration_runs_service_supports_service_owned_commit_boundaries(temp_db):
    service = RegistrationRunsService(temp_db)

    run = service.create_run(
        task_uuid="task-boundary",
        batch_id=None,
        trigger_source="manual",
        commit=False,
    )
    service.append_event(run.id, level="info", message="queued", commit=False)

    temp_db.rollback()

    assert service.get_run_by_task_uuid("task-boundary") is None


def test_registration_runs_service_mark_started_is_idempotent(temp_db):
    service = RegistrationRunsService(temp_db)

    run = service.create_run(task_uuid="task-started", batch_id=None, trigger_source="manual", commit=True)
    first = service.mark_started(run.id, commit=True)
    second = service.mark_started(run.id, commit=True)

    assert first.started_at is not None
    assert second.started_at == first.started_at
    assert second.status in {"pending", "running"}


def test_registration_runs_service_terminal_status_is_immutable(temp_db):
    service = RegistrationRunsService(temp_db)

    run = service.create_run(task_uuid="task-terminal", batch_id=None, trigger_source="manual", commit=True)
    service.mark_completed(run.id, commit=True)
    updated = service.mark_failed(run.id, error_message="ignored", commit=True)

    assert updated.status == "completed"
    assert updated.error_message in (None, "")
```

- [ ] **Step 2: 运行 run service 测试，确认先失败**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest tests/test_registration_runs_service.py -q
```

Expected: FAIL，提示 `commit=False`/`mark_started()` 等新契约尚未实现，或现有 service 仍在每个方法里隐式 commit。

- [ ] **Step 3: 实现语义化 run service**

```python
class RegistrationRunsService:
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

    def __init__(self, session: Session):
        self.session = session
        self.repo = RegistrationRepository(session)

    def create_run(..., commit: bool = False):
        existing = self.repo.get_run_by_task_uuid(task_uuid)
        if existing is not None:
            return existing
        row = self.repo.create_run(..., status="pending")
        return self._persist(row, commit=commit)

    def mark_started(self, run_id: int, *, commit: bool = False):
        run = self._require_run(run_id)
        if run.started_at is None:
            run.started_at = utc_now_naive()
        return self._persist(self.repo.save_run(run), commit=commit)

    def mark_running(self, run_id: int, *, commit: bool = False):
        run = self.mark_started(run_id, commit=False)
        if run.status not in self.TERMINAL_STATUSES and run.status != "running":
            run = self.repo.update_status_if_not_terminal(run_id, status="running", started_at=run.started_at)
        return self._persist(run, commit=commit)
```

实现要求：
- `create_run`、`append_event`、`mark_*` 默认 **不 commit**。
- `_persist(..., commit=True)` 只在调用方明确要求时提交。
- `mark_started()` 只负责 started checkpoint，不让晚到调用改坏终态。
- `append_event()` 允许终态后补日志，但不允许 orphan run。

- [ ] **Step 4: 重新运行 run service 测试并确认通过**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest tests/test_registration_runs_service.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 2**

```bash
git add src/application/registration_runs_service.py tests/test_registration_runs_service.py
git commit -m "refactor: move registration run semantics into service boundary"
```

---

### Task 3: 让 RegistrationService 成为单任务 run owner

**Files:**
- Modify: `src/application/registration_service.py`
- Test: `tests/test_registration_service.py`

- [ ] **Step 1: 先写单任务 owner 语义的失败测试**

```python
from src.application.registration_service import RegistrationService
from src.core.registration_job import RegistrationJobResult


def test_registration_service_commits_queued_checkpoint_before_job_runner(db_factory, temp_db, monkeypatch):
    crud.create_registration_task(temp_db, task_uuid="task-checkpoint")

    commits: list[str] = []
    original_commit = temp_db.commit

    def counting_commit():
        commits.append("commit")
        return original_commit()

    monkeypatch.setattr(temp_db, "commit", counting_commit)

    seen_by_job: list[int] = []

    def fake_job_runner(**kwargs):
        seen_by_job.append(len(commits))
        return RegistrationJobResult(success=True, email="ok@example.com", result_payload={"success": True})

    service = RegistrationService(db_factory=db_factory, task_manager=FakeTaskManager(), job_runner=fake_job_runner)
    service.run_single_task_sync(
        task_uuid="task-checkpoint",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
    )

    assert seen_by_job == [1]


def test_registration_service_persists_run_events_in_owner_defined_order(db_factory, temp_db):
    crud.create_registration_task(temp_db, task_uuid="task-events", pipeline_key="current_pipeline")

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        job_runner=lambda **_: RegistrationJobResult(success=True, email="ok@example.com", result_payload={"success": True}),
    )
    result = service.run_single_task_sync(
        task_uuid="task-events",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
    )

    assert [event.message for event in result.events[:4]] == ["queued", "started", "running", "completed"]


def test_registration_service_marks_failed_once_when_job_runner_raises(db_factory, temp_db):
    crud.create_registration_task(temp_db, task_uuid="task-boom")

    service = RegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        job_runner=lambda **_: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = service.run_single_task_sync(
        task_uuid="task-boom",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
    )

    assert result.run.status == "failed"
    assert [event.message for event in result.events][-1] == "failed"
```

- [ ] **Step 2: 运行单任务 service 测试，确认先失败**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest tests/test_registration_service.py -q
```

Expected: FAIL，提示 queued/start checkpoint 未持久化、事件顺序不对，或 job runner 看到的 commit 次数不满足 service-owned transaction 边界。

- [ ] **Step 3: 实现单任务 owner 迁移**

```python
with service.db_factory() as db:
    runs_service = RegistrationRunsService(db)
    run = runs_service.create_run(..., commit=False)
    runs_service.append_event(run.id, level="info", message="queued", commit=False)
    db.commit()  # checkpoint 1: queued

    task = crud.update_registration_task(..., started_at=now(), status="running", pipeline_status="running")
    runs_service.mark_started(run.id, commit=False)
    runs_service.append_event(run.id, level="info", message="started", commit=False)
    runs_service.mark_running(run.id, commit=False)
    runs_service.append_event(run.id, level="info", message="running", commit=False)
    db.commit()  # checkpoint 2: execution start

    job_result = service.job_runner(...)

    if job_result.success:
        crud.update_registration_task(..., status="completed", pipeline_status="completed", completed_at=now())
        runs_service.mark_completed(run.id, commit=False)
        runs_service.append_event(run.id, level="info", message="completed", commit=False)
    else:
        crud.update_registration_task(..., status="failed", pipeline_status="failed", completed_at=now())
        runs_service.mark_failed(run.id, error_message=job_result.error_message, commit=False)
        runs_service.append_event(run.id, level="error", message="failed", commit=False)
    db.commit()  # checkpoint 3: terminal
```

实现要求：
- 仍保留 executor / proxy dispatch / task_manager 实时事件逻辑，不做 unrelated refactor。
- `task_manager` 继续负责 runtime stream；run 持久化只能通过 `RegistrationRunsService`。
- 异常 fallback 分支也必须使用同一套 run service API，不允许再直接散写 run row。

- [ ] **Step 4: 重新运行单任务 service 测试并确认通过**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest tests/test_registration_service.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 3**

```bash
git add src/application/registration_service.py tests/test_registration_service.py
git commit -m "refactor: make registration service own run lifecycle"
```

---

### Task 4: 让 BatchRegistrationService 复用新的 run 查询与失败路径边界

**Files:**
- Modify: `src/application/batch_registration_service.py`
- Test: `tests/test_batch_registration_service.py`

- [ ] **Step 1: 先写批量侧 bulk query / failure path 的失败测试**

```python
import pytest


@pytest.mark.anyio
async def test_batch_registration_service_build_summary_uses_bulk_run_lookup(db_factory, temp_db, monkeypatch):
    from src.application.batch_registration_service import BatchRegistrationService
    import src.application.batch_registration_service as batch_module

    calls: list[list[str]] = []

    class FakeRunsService:
        def __init__(self, db):
            self.db = db

        def list_latest_runs_by_task_uuids(self, task_uuids):
            calls.append(list(task_uuids))
            return {}

    monkeypatch.setattr(batch_module, "RegistrationRunsService", FakeRunsService)

    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={"batch-1": {"task_uuids": ["a", "b"], "completed": 0, "success": 0, "failed": 0}},
        registration_task_runner=lambda *args, **kwargs: None,
    )

    summary = service.build_summary("batch-1", task_uuids=["a", "b"])

    assert summary.runs == []
    assert calls == [["a", "b"]]


@pytest.mark.anyio
async def test_batch_registration_service_proxy_pool_failure_persists_failed_run_and_event(db_factory, temp_db):
    from src.application.batch_registration_service import BatchRegistrationService

    crud.create_registration_task(temp_db, task_uuid="proxy-fail-task")
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        batch_tasks_store={},
        registration_task_runner=lambda *args, **kwargs: None,
    )

    service._mark_proxy_pool_failure("batch-proxy", "proxy-fail-task", "batch proxy pool exhausted")

    runs = RegistrationRunsService(temp_db)
    run = runs.get_run_by_task_uuid("proxy-fail-task")
    events = runs.get_events(run.id)

    assert run.status == "failed"
    assert run.error_message == "batch proxy pool exhausted"
    assert events[-1].message == "failed"
```

- [ ] **Step 2: 运行批量 service 测试，确认先失败**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest tests/test_batch_registration_service.py -q
```

Expected: FAIL，提示 `list_latest_runs_by_task_uuids()` 尚未被 batch service 采用，或批量失败路径仍依赖旧式零散 run 更新。

- [ ] **Step 3: 实现批量侧兼容迁移**

```python
with self.db_factory() as db:
    runs_service = RegistrationRunsService(db)
    latest_runs = runs_service.list_latest_runs_by_task_uuids(effective_task_uuids)
    runs = [latest_runs[task_uuid] for task_uuid in effective_task_uuids if task_uuid in latest_runs]
```

```python
with self.db_factory() as db:
    runs_service = RegistrationRunsService(db)
    run = runs_service.get_run_by_task_uuid(task_uuid)
    if run is None:
        run = runs_service.create_run(task_uuid=task_uuid, batch_id=batch_id, trigger_source="batch", commit=False)
    crud.update_registration_task(..., status="failed", pipeline_status="failed", completed_at=self.utc_now_provider())
    runs_service.mark_failed(run.id, error_message=error_message, commit=False)
    runs_service.append_event(run.id, level="error", message="failed", commit=False)
    db.commit()
```

实现要求：
- 本批只让 batch service 成为**子任务 run 触发 / 汇总的 owner**，不新增批次聚合 run 模型。
- `build_summary()`、`_load_outcome_status()` 优先复用 bulk query helper，避免继续 N+1 拉 run。
- `registration_task_runner` 调用协议不改，避免影响现有 batch 并发逻辑。

- [ ] **Step 4: 重新运行批量 service 测试并确认通过**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest tests/test_batch_registration_service.py -q
```

Expected: PASS

- [ ] **Step 5: 提交 Task 4**

```bash
git add src/application/batch_registration_service.py tests/test_batch_registration_service.py
git commit -m "refactor: reuse registration run boundary in batch service"
```

---

### Task 5: 主流程与页面 smoke 回归

**Files:**
- Test: `tests/test_registration_runs_service.py`
- Test: `tests/test_registration_service.py`
- Test: `tests/test_batch_registration_service.py`
- Test: `tests/test_registration_batch_routes.py`
- Test: `tests/test_registration_page_assets.py`
- Test: `tests/test_run_center_page_assets.py`

- [ ] **Step 1: 运行 run / service / batch 回归集合**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest \
  tests/test_registration_runs_service.py \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py -q
```

Expected: PASS

- [ ] **Step 2: 运行页面 smoke tests，确认 run 持久化边界改动没有把前端契约打坏**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest \
  tests/test_registration_page_assets.py \
  tests/test_run_center_page_assets.py -q
```

Expected: PASS

- [ ] **Step 3: 检查 git 状态，确认没有误带当前 main 的无关页面改动**

Run:

```bash
git status --short
```

Expected: 只包含本计划涉及文件；不得把 `main` 工作区中未提交的 `run_center / scheduled_tasks` 页面改动带入该 worktree。

- [ ] **Step 4: 提交最终回归结果**

```bash
git add src/database/repositories/registration_repository.py \
  src/database/repositories/__init__.py \
  src/application/registration_runs_service.py \
  src/application/registration_service.py \
  src/application/batch_registration_service.py \
  tests/test_registration_runs_service.py \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py
git commit -m "refactor: migrate registration run ownership boundaries"
```

---

## Execution Notes

- 先执行 Task 1 → Task 2 → Task 3 → Task 4 → Task 5，不能跳序，因为 repository / run service 是后续 owner 迁移的前置依赖。
- 本批**不允许**顺手改 UI、boot、scheduler scheduled runs、workspace shell 或静态资源版本逻辑。
- 如果实现过程中发现必须新增 schema 或改变外部状态词汇，请先停下，回到 spec 讨论，而不是在本计划中静默扩大范围。
