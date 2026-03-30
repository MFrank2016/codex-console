# Registration Route/Query Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 registration read-side 从 `src/web/routes/registration.py` 中抽离到 query facade / DTO，令 route 退回 HTTP adapter，同时保持现有 JSON 契约兼容。

**Architecture:** 这一轮只处理 registration 的 read-side，不碰 repository split、runtime split 与 core purification。实现方式采用“query facade + read DTO + route 委托”的兼容迁移方案：facade 当前阶段允许内部继续依赖 `crud`、`failure_repo`、`task_manager` 和 `get_settings`，但这些读取细节必须从 route 中移除。最终 `registration.py` 仅保留 request parsing、鉴权、错误映射和 response_model 适配。

**Tech Stack:** Python、FastAPI、Pydantic、SQLAlchemy ORM、pytest、现有 `RegistrationService` / `BatchRegistrationService` / `failure_repo` / `task_manager`

---

## Spec Reference

- `docs/superpowers/specs/2026-03-30-registration-route-query-boundary-design.md`

## Scope Guardrails

1. 本计划只做 **registration read-side boundary**。
2. 不改 `/registration/start`、`/registration/batch`、`/registration/outlook-batch` 的 bootstrap / command owner。
3. 不拆 `src/database/crud.py`。
4. 不重写 `src/web/task_manager.py`。
5. 不修改 `src/core/register.py`、`src/core/registration_job.py` 的 DB ownership。
6. 保持现有页面与 JS harness 消费的 JSON 字段兼容。

## File Structure Map

### Create

- `src/application/registration_query_dtos.py` — 定义 registration read-side DTO / view，承接 task / failure / service availability / batch 状态只读结构。
- `src/application/registration_query_facade.py` — 统一承接 registration read-side 用例，内部集中读取 DB / runtime mirror / settings。
- `tests/test_registration_query_facade.py` — 聚焦合同测试，锁定 facade 输出与 read-side fallback 语义。

### Modify

- `src/application/__init__.py` — 导出 query facade / DTO。
- `src/web/routes/registration.py` — 删掉 read-side helper 与查询编排，改为委托 facade。
- `tests/test_registration_batch_routes.py` — 增加 task/batch/outlook-batch status route 委托 facade 的测试。
- `tests/test_registration_failure_routes.py` — 增加 failure summary / list route 委托 facade 的测试。

### Regression-only files to run but not modify unless tests expose drift

- `tests/test_registration_stream_routes.py`
- `tests/test_realtime_stream_routes.py`
- `tests/test_registration_page_assets.py`
- `tests/test_run_center_page_assets.py`
- `tests/test_task_manager.py`

---

### Task 1: 建立最小测试支撑并锁第一个 facade 场景

**Files:**
- Create: `tests/test_registration_query_facade.py`

- [ ] **Step 1: 在新测试文件中写最小 fixture / helper 支撑**

```python
from contextlib import contextmanager

import pytest

from src.database.models import Base
from src.database.session import DatabaseSessionManager
from tests.fakes import RegistrationFakeTaskManager as FakeTaskManager


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "registration-query-facade.db"
    manager = DatabaseSessionManager(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=manager.engine)

    session = manager.SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.expunge_all()
        session.close()


@pytest.fixture
def db_factory(temp_db):
    @contextmanager
    def _factory():
        yield temp_db

    return _factory


class _FakeSettings:
    custom_domain_base_url = "https://mail.example.com"
    custom_domain_api_key = "secret"


def _settings_reader():
    return _FakeSettings()
```

- [ ] **Step 2: 只为一个最小 read-side 场景写失败测试**

```python
from src.application.registration_query_facade import RegistrationQueryFacade
from src.database import crud


def test_registration_query_facade_list_tasks_prefers_runtime_steps_when_db_steps_missing(db_factory, temp_db):
    crud.create_registration_task(temp_db, task_uuid="task-facade-1", pipeline_key="current_pipeline")
    task_manager = FakeTaskManager()
    task_manager.set_task_steps(
        "task-facade-1",
        [{"step_key": "runtime-only", "status": "running"}],
        task_progress={"step_index": 1, "total_steps": 2, "progress_percent": 50},
    )

    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=task_manager,
    )

    view = facade.list_tasks(page=1, page_size=20, status=None)

    assert view.total == 1
    assert view.tasks[0].task_uuid == "task-facade-1"
    assert view.tasks[0].steps == [{"step_key": "runtime-only", "status": "running"}]
```

- [ ] **Step 3: 跑单个测试，确认先红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_registration_query_facade.py::test_registration_query_facade_list_tasks_prefers_runtime_steps_when_db_steps_missing -q
```

Expected:

- FAIL，提示 `RegistrationQueryFacade` 尚不存在，或 `list_tasks()` 未实现。

- [ ] **Step 4: Commit failing-test baseline**

```bash
git add tests/test_registration_query_facade.py
git commit -m "test: lock initial registration query facade contract"
```

---

### Task 2: 搭建 read DTO、facade 骨架与 route builder stub

**Files:**
- Create: `src/application/registration_query_dtos.py`
- Create: `src/application/registration_query_facade.py`
- Modify: `src/application/__init__.py`
- Modify: `src/web/routes/registration.py`
- Test: `tests/test_registration_query_facade.py`

- [ ] **Step 1: 在 DTO 文件中写最小只读结构**

```python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RegistrationTaskView:
    id: int
    task_uuid: str
    status: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    logs: str | None = None


@dataclass(frozen=True)
class RegistrationTaskListView:
    total: int
    tasks: list[RegistrationTaskView]
```

同文件补齐：

- `RegistrationFailureSummaryView`
- `RegistrationFailureListView`
- `RegistrationBatchStatusView`
- `RegistrationStatsView`

第一版允许 DTO 继续包 `dict`，不要提前过度抽象。

- [ ] **Step 2: 在 facade 文件中写最小骨架**

```python
class RegistrationQueryFacade:
    def __init__(
        self,
        *,
        db_factory,
        task_manager,
        failure_repository=failure_repo,
        utc_now_provider=utc_now,
        settings_reader=get_settings,
        batch_tasks_store=None,
    ):
        self.db_factory = db_factory
        self.task_manager = task_manager
        self.failure_repository = failure_repository
        self.utc_now_provider = utc_now_provider
        self.settings_reader = settings_reader
        self.batch_tasks = batch_tasks_store if batch_tasks_store is not None else DEFAULT_BATCH_TASKS_STORE
```

并先补空方法：

- `list_tasks(...)`
- `get_task_detail(task_uuid)`
- `get_task_logs(task_uuid)`
- `get_registration_stats()`
- `build_failure_summary(...)`
- `list_failures(...)`
- `get_batch_status(batch_id)`
- `get_outlook_batch_status(batch_id)`
- `get_available_email_services()`
- `get_outlook_accounts_for_registration()`

- [ ] **Step 3: 在 route 中补最小 builder stub，给后续 route delegation 测试提供 patch 点**

在 `src/web/routes/registration.py` 增加：

```python
def _build_registration_query_facade() -> RegistrationQueryFacade:
    return RegistrationQueryFacade(
        db_factory=get_db,
        task_manager=task_manager,
        batch_tasks_store=batch_tasks,  # 测试中如需隔离，调用方应传入独立 dict 副本
    )
```

这一步先只建立构造入口，不要求 route 立刻全部委托。

- [ ] **Step 4: 在 `src/application/__init__.py` 导出 facade / DTO**

加入：

```python
from .registration_query_facade import RegistrationQueryFacade
from .registration_query_dtos import (
    RegistrationTaskView,
    RegistrationTaskListView,
    RegistrationFailureSummaryView,
    RegistrationFailureListView,
    RegistrationBatchStatusView,
    RegistrationStatsView,
)
```

- [ ] **Step 5: 跑 Task 1 单测，确认 import 链已打通但实现仍未完成**

Run same command as Task 1 Step 3.

Expected:

- 不再报 import / class not found；
- 仍会因 facade 方法未实现而失败。

- [ ] **Step 6: Commit scaffold**

```bash
git add src/application/registration_query_dtos.py \
  src/application/registration_query_facade.py \
  src/application/__init__.py \
  src/web/routes/registration.py
git commit -m "refactor: add registration query facade scaffold"
```

---

### Task 3: 迁出 task list/detail/logs/stats read-side

**Files:**
- Modify: `src/application/registration_query_facade.py`
- Modify: `src/web/routes/registration.py`
- Modify: `tests/test_registration_query_facade.py`
- Modify: `tests/test_registration_batch_routes.py`
- Regression: `tests/test_registration_stream_routes.py`

- [ ] **Step 1: 先补 task detail / logs 的增量失败测试**

在 `tests/test_registration_query_facade.py` 增加：

```python
def test_registration_query_facade_get_task_detail_returns_none_for_missing_task(db_factory):
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
    )

    assert facade.get_task_detail("missing-task") is None
```

```python
def test_registration_query_facade_task_logs_keeps_legacy_split_lines(db_factory, temp_db):
    task = crud.create_registration_task(temp_db, task_uuid="task-log-1")
    crud.update_registration_task(temp_db, task.task_uuid, logs="line-1\nline-2")

    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
    )

    payload = facade.get_task_logs("task-log-1")
    assert payload["task_uuid"] == "task-log-1"
    assert payload["logs"] == ["line-1", "line-2"]
```

```python
def test_registration_query_facade_list_tasks_prefers_db_steps_over_runtime_when_rows_exist(db_factory, temp_db):
    task = crud.create_registration_task(temp_db, task_uuid="task-db-steps-1")
    crud.create_pipeline_step_run(
        temp_db,
        task_uuid=task.task_uuid,
        step_key="db-step",
        step_order=1,
        step_impl="demo",
        status="completed",
    )
    task_manager = FakeTaskManager()
    task_manager.set_task_steps(task.task_uuid, [{"step_key": "runtime-step", "status": "running"}])

    facade = RegistrationQueryFacade(db_factory=db_factory, task_manager=task_manager)

    view = facade.list_tasks(page=1, page_size=20, status=None)

    assert view.tasks[0].steps[0]["step_key"] == "db-step"
```

- [ ] **Step 2: 在 route 测试里锁定 task read-side route 委托 facade**

在 `tests/test_registration_batch_routes.py` 增加：

```python
def test_list_tasks_route_delegates_to_query_facade(client, monkeypatch):
    class FakeFacade:
        def list_tasks(self, **kwargs):
            return type(
                "TaskListView",
                (),
                {
                    "total": 1,
                    "tasks": [
                        type(
                            "TaskView",
                            (),
                            {
                                "id": 1,
                                "task_uuid": "task-via-facade",
                                "status": "pending",
                                "steps": [],
                                "result": None,
                                "logs": None,
                            },
                        )()
                    ],
                },
            )()

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    response = client.get("/api/registration/tasks")

    assert response.status_code == 200
    assert response.json()["tasks"][0]["task_uuid"] == "task-via-facade"
```

- [ ] **Step 3: 在 facade 中实现 task read-side**

把以下 route helper 迁入 facade：

- `_step_run_to_dict`
- `_collect_task_steps`
- `task_to_response` 的只读部分

建议在 facade 内实现：

```python
def _collect_task_steps(self, db, task_uuid: str) -> list[dict]:
    step_rows = crud.get_pipeline_step_runs_by_task_uuid(db, task_uuid)
    if step_rows:
        return [self._step_run_to_dict(row) for row in step_rows]
    if hasattr(self.task_manager, "get_task_steps"):
        return self.task_manager.get_task_steps(task_uuid)
    return []
```

并实现：

- `list_tasks(...)`
- `get_task_detail(...)`
- `get_task_logs(...)`
- `get_registration_stats()`

- [ ] **Step 4: 改 route 只委托 facade**

把：

- `list_tasks`
- `get_task`
- `get_task_logs`
- `get_registration_stats`

改成：

```python
view = _build_registration_query_facade().list_tasks(...)
return TaskListResponse(total=view.total, tasks=[...])
```

其中 route 仍负责把 facade view 映射到现有 `RegistrationTaskResponse` / `TaskListResponse`。

- [ ] **Step 5: 跑聚焦测试验证通过**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_registration_query_facade.py \
  tests/test_registration_batch_routes.py \
  tests/test_registration_stream_routes.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit task read-side migration**

```bash
git add src/application/registration_query_facade.py \
  src/web/routes/registration.py \
  tests/test_registration_query_facade.py \
  tests/test_registration_batch_routes.py
git commit -m "refactor: move registration task queries into facade"
```

---

### Task 4: 迁出 failure summary/list read-side

**Files:**
- Modify: `src/application/registration_query_facade.py`
- Modify: `src/web/routes/registration.py`
- Modify: `tests/test_registration_query_facade.py`
- Modify: `tests/test_registration_failure_routes.py`

- [ ] **Step 1: 先写 failure facade 聚焦测试**

在 `tests/test_registration_query_facade.py` 增加：

```python
def test_registration_query_facade_build_failure_summary_keeps_today_intersection_semantics(db_factory):
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
    )

    summary = facade.build_failure_summary(
        pipeline_key=None,
        registration_mode=None,
        email_service_type=None,
        email_suffix=None,
        email_service_id=None,
        proxy_ip=None,
        error_keyword=None,
        failed_from=None,
        failed_to=None,
    )

    assert "today_failed_attempts" in summary
```

- [ ] **Step 2: 先锁 failure route delegation**

在 `tests/test_registration_failure_routes.py` 增加：

```python
def test_registration_failures_summary_route_delegates_to_query_facade(client, monkeypatch):
    class FakeFacade:
        def build_failure_summary(self, **kwargs):
            return {
                "total_failed_attempts": 3,
                "today_failed_attempts": 1,
                "top_email_suffixes": [],
                "top_error_codes": [],
                "top_proxy_ips": [],
            }

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    response = client.get("/api/registration/failures/summary")

    assert response.status_code == 200
    assert response.json()["total_failed_attempts"] == 3
```

- [ ] **Step 3: 在 facade 中迁入 failure 规则**

迁入并封装：

- `_build_failure_filters`
- `_current_day_intersection_count`
- summary/list 中的 `resolve_failure_window(...)`

建议 facade API：

```python
def build_failure_summary(...): ...
def list_failures(..., page: int, page_size: int): ...
```

route 不再自己组装 `RegistrationFailureQuery`。

- [ ] **Step 4: 改 failure routes 只委托 facade**

把：

- `get_registration_failures_summary`
- `get_registration_failures`

改成：

```python
facade = _build_registration_query_facade()
summary = facade.build_failure_summary(...)
return summary
```

route 只保留：

- `require_authenticated`
- 参数接收
- `ValueError -> HTTP 400`

- [ ] **Step 5: 跑失败分析聚焦回归**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_registration_query_facade.py \
  tests/test_registration_failure_routes.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit failure query migration**

```bash
git add src/application/registration_query_facade.py \
  src/web/routes/registration.py \
  tests/test_registration_query_facade.py \
  tests/test_registration_failure_routes.py
git commit -m "refactor: move registration failure queries into facade"
```

---

### Task 5: 迁出 available services / outlook accounts read-side

**Files:**
- Modify: `src/application/registration_query_facade.py`
- Modify: `src/web/routes/registration.py`
- Modify: `tests/test_registration_query_facade.py`

- [ ] **Step 1: 先写 settings fallback 的最小失败测试**

在 `tests/test_registration_query_facade.py` 增加：

```python
def test_registration_query_facade_available_services_keeps_settings_fallback(db_factory):
    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
        settings_reader=_settings_reader,
    )

    view = facade.get_available_email_services()

    assert view["tempmail"]["available"] is True
    assert view["moe_mail"]["available"] is True
    assert view["moe_mail"]["services"][0]["from_settings"] is True
```

- [ ] **Step 2: 再补 outlook accounts 注册态测试**

```python
def test_registration_query_facade_outlook_accounts_marks_registered_rows(db_factory, temp_db):
    service = crud.create_email_service(
        temp_db,
        service_type="outlook",
        name="registered-outlook",
        config={"email": "registered@example.com"},
        enabled=True,
    )
    crud.create_account(temp_db, email="registered@example.com", email_service="outlook")

    facade = RegistrationQueryFacade(
        db_factory=db_factory,
        task_manager=FakeTaskManager(),
    )

    result = facade.get_outlook_accounts_for_registration()

    assert result.accounts[0].id == service.id
    assert result.accounts[0].is_registered is True
```

- [ ] **Step 3: 在 facade 中实现 service availability 读模型**

把 route 中这些查询与拼装迁入 facade：

- `get_available_email_services`
- `get_outlook_accounts_for_registration`

要求保留：

1. `tempmail` 默认可用语义；
2. `moe_mail` 的 settings fallback；
3. Outlook 的 `has_oauth` 计算；
4. Outlook `is_registered` 的 account 查重语义。

- [ ] **Step 4: 改 route 委托 facade**

route 仅保留：

- endpoint 声明；
- response_model 映射（如需要）；
- facade 调用。

- [ ] **Step 5: 跑聚焦测试**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_registration_query_facade.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit service availability migration**

```bash
git add src/application/registration_query_facade.py \
  src/web/routes/registration.py \
  tests/test_registration_query_facade.py
git commit -m "refactor: move registration availability queries into facade"
```

---

### Task 6: 迁出 batch / outlook-batch status read-side，并清理 route helper 残留

**Files:**
- Modify: `src/application/registration_query_facade.py`
- Modify: `src/web/routes/registration.py`
- Modify: `tests/test_registration_query_facade.py`
- Modify: `tests/test_registration_batch_routes.py`
- Regression: `tests/test_realtime_stream_routes.py`

- [ ] **Step 1: 先写 batch status 的最小失败测试**

在 `tests/test_registration_query_facade.py` 增加：

```python
def test_registration_query_facade_batch_status_reads_application_owned_store():
    facade = RegistrationQueryFacade(
        db_factory=lambda: (_ for _ in ()).throw(AssertionError("db should not be used")),
        task_manager=FakeTaskManager(),
        batch_tasks_store={
            "batch-owned-1": {
                "total": 3,
                "completed": 1,
                "success": 1,
                "failed": 0,
                "current_index": 1,
                "cancelled": False,
                "finished": False,
                "domain_stats": [],
            }
        },
    )

    view = facade.get_batch_status("batch-owned-1")

    assert view["batch_id"] == "batch-owned-1"
    assert view["progress"] == "1/3"
```

- [ ] **Step 2: 再补 batch route delegation 测试**

在 `tests/test_registration_batch_routes.py` 增加：

```python
def test_get_batch_status_route_delegates_to_query_facade(client, monkeypatch):
    class FakeFacade:
        def get_batch_status(self, batch_id):
            assert batch_id == "batch-xyz"
            return {
                "batch_id": "batch-xyz",
                "total": 2,
                "completed": 1,
                "success": 1,
                "failed": 0,
                "current_index": 1,
                "cancelled": False,
                "finished": False,
                "progress": "1/2",
                "is_unlimited": False,
                "consecutive_failures": 0,
                "max_consecutive_failures": 10,
                "stop_reason": None,
                "domain_stats": [],
            }

    monkeypatch.setattr(registration_routes, "_build_registration_query_facade", lambda: FakeFacade())
    response = client.get("/api/registration/batch/batch-xyz")

    assert response.status_code == 200
    assert response.json()["batch_id"] == "batch-xyz"
```

- [ ] **Step 3: 在 facade 中实现 batch / outlook-batch status 读取**

要求：

1. 当前阶段继续从 `batch_tasks_store` 读取；
2. route 不再直接依赖 `batch_tasks` 兼容别名；
3. 保持普通 batch 和 outlook batch 响应 JSON 字段兼容；
4. `progress` 字段仍保留字符串格式。

- [ ] **Step 4: route 委托 facade，并删掉 route 中已无用的 read-side helper**

处理：

- `get_batch_status`
- `get_outlook_batch_status`

并清理 route 中已不再需要的 read-side helper 与 import。

- [ ] **Step 5: 跑整组 registration read-side 回归**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
python -m pytest \
  tests/test_registration_query_facade.py \
  tests/test_registration_batch_routes.py \
  tests/test_registration_failure_routes.py \
  tests/test_registration_stream_routes.py \
  tests/test_realtime_stream_routes.py \
  tests/test_registration_page_assets.py \
  tests/test_run_center_page_assets.py \
  tests/test_task_manager.py -q
```

Expected: PASS。

- [ ] **Step 6: Commit final boundary cleanup**

```bash
git add src/application/registration_query_facade.py \
  src/web/routes/registration.py \
  tests/test_registration_query_facade.py \
  tests/test_registration_batch_routes.py \
  tests/test_registration_failure_routes.py
git commit -m "refactor: complete registration route query boundary"
```

---

## Done Criteria

完成本计划后，应满足：

1. `src/web/routes/registration.py` 中的 read-side endpoint 不再直接查询 DB / `failure_repo` / `batch_tasks`。
2. task/failure/service availability/batch status 的 read-side 逻辑集中到 `RegistrationQueryFacade`。
3. route 文件只保留 adapter 职责与 response_model 映射。
4. 现有 JSON 契约与页面 harness 保持兼容。
5. 后续 `registration repository split` 可以直接以 facade / command 边界为输入继续推进。

## Out of Scope Reminder

若执行过程中出现以下诱惑，必须拒绝并记录到后续计划，而不是顺手实现：

1. 顺手拆 `crud.py`
2. 顺手重写 `task_manager`
3. 顺手把 batch 状态持久化
4. 顺手清理 `register.py` / `registration_job.py`
5. 顺手把 command route 全部 service 化
