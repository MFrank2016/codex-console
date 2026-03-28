# Backend Architecture Remediation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不更换现有技术栈的前提下，先把注册启动链路里的 owner 边界收口：由 application service 拥有 single/batch/outlook batch 的 bootstrap 语义，route 退回 HTTP adapter，避免继续把 run / batch 启动逻辑写散在 route 和兼容 store 中。

**Architecture:** 这份 roadmap spec 覆盖多个独立整改阶段，不适合用一份实现计划同时落完。本计划只覆盖第一批可执行切片：Phase 0 的护栏测试、Phase 1 的事务 / bootstrap owner 收口，以及少量 Phase 2 的 route 瘦身（仅限 start path，不碰 query facade 与大规模 read-side 拆分）。实现上采用“DTO 快照 + service bootstrap API + route 只负责 background task 调度”的兼容式迁移方案，不改 DB schema、不改 realtime 协议、不提前拆 `crud.py` / `register.py`。

**Tech Stack:** Python、FastAPI、SQLAlchemy ORM、pytest、现有 `RegistrationService` / `BatchRegistrationService`、`task_manager`、BackgroundTasks

---

## Spec Reference

- `docs/superpowers/specs/2026-03-28-backend-architecture-remediation-roadmap-design.md`

## Scope Split Note

这份 spec 是总路线图，不应一次性实现到 Phase 4。本计划只实现“foundation”切片；完成后再分别编写后续计划：

1. route/query boundary plan（`get_available_email_services`、status/detail query facade）
2. repository split plan（拆 `crud.py`）
3. runtime split plan（拆 `task_manager`）
4. core purification plan（`registration_job.py` / `register.py` / dynamic proxy）

## Execution Notes

1. 所有测试命令统一带 `timeout 60s`。
2. 每个任务严格按 TDD 执行：先写失败测试，再实现最小代码，再跑绿，再 commit。
3. 第一批只处理 **start path** 的 owner 边界：`/registration/start`、`/registration/batch`、`/registration/outlook-batch`。
4. 第一批保持响应 JSON 兼容；route 返回结构不能破坏现有页面和 JS harness。
5. 第一批不改 `RegistrationRun` schema、不改 realtime stream payload、不改前端模板。
6. service 对 route 的返回值统一改成 DTO / snapshot，禁止把 live ORM 生命周期继续暴露给 route。

---

## File Structure Map

### Create

- `src/application/registration_bootstrap_dtos.py` — 定义 single/batch/outlook bootstrap 阶段使用的不可变 DTO 快照，隔离 route 与 ORM 生命周期。
- `tests/test_registration_bootstrap_contracts.py` — 锁定 owner 边界的聚焦合同测试：route 委托、service 返回 DTO、bootstrap 由 service 持有。

### Modify

- `src/application/__init__.py` — 导出新的 bootstrap DTO，保持 application 层入口一致。
- `src/application/registration_service.py` — 新增 single registration bootstrap API，返回 `RegistrationTaskSnapshot`，不再要求 route 直接消费 ORM。
- `src/application/batch_registration_service.py` — 新增 ordinary batch / outlook batch bootstrap API，把 batch_id、task records、proxy pool warmup、batch state init 收口到 service。
- `src/web/routes/registration.py` — start 路由改为：校验 request → 调 service bootstrap → 安排 background task → 返回 DTO；删除 route 内直接写 batch state 的逻辑。
- `tests/test_registration_service.py` — 单任务 bootstrap、DTO 契约、背景执行参数透传测试。
- `tests/test_batch_registration_service.py` — ordinary/outlook batch bootstrap、proxy pool warmup、跳过已注册邮箱、DTO 返回测试。
- `tests/test_registration_batch_routes.py` — route 代理 service bootstrap、响应兼容、background task 调度测试。

### Regression-only files to run but not modify unless tests expose drift

- `tests/test_registration_runs_service.py`
- `tests/test_task_manager.py`
- `tests/test_realtime_stream_routes.py`
- `tests/test_registration_page_assets.py`
- `tests/test_run_center_page_assets.py`

---

### Task 1: 先锁定 bootstrap owner 边界合同测试

**Files:**
- Create: `tests/test_registration_bootstrap_contracts.py`
- Modify: `tests/test_registration_service.py`
- Modify: `tests/test_batch_registration_service.py`
- Modify: `tests/test_registration_batch_routes.py`

- [ ] **Step 1: 在新测试文件中先写 single / batch / outlook bootstrap 的失败合同测试**

```python
from dataclasses import is_dataclass

from src.application.registration_bootstrap_dtos import (
    BatchBootstrapResult,
    OutlookBatchBootstrapResult,
    RegistrationTaskSnapshot,
)


def test_registration_service_start_task_returns_snapshot_not_live_orm(db_factory, temp_db):
    service = RegistrationService(db_factory=db_factory, task_manager=FakeTaskManager())

    snapshot = service.start_task(
        task_uuid="task-bootstrap",
        proxy=None,
        pipeline_key="current_pipeline",
        email_service_id=7,
    )

    assert isinstance(snapshot, RegistrationTaskSnapshot)
    assert is_dataclass(snapshot)
    assert snapshot.task_uuid == "task-bootstrap"
    assert not hasattr(snapshot, "_sa_instance_state")
```

```python
def test_batch_registration_service_start_batch_owns_batch_state_and_proxy_warmup(db_factory, fake_task_manager):
    dispatcher = FakeProxyDispatcher()
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=fake_task_manager,
        proxy_dispatcher=dispatcher,
        uuid_factory=lambda: "batch-001",
    )

    result = service.start_batch(
        count=2,
        proxy=None,
        pipeline_key="current_pipeline",
        concurrency=3,
        use_proxy=True,
        proxy_task_group="batch_registration",
        proxy_overrides={"dynamic_proxy_strategy": "exclusive"},
    )

    assert isinstance(result, BatchBootstrapResult)
    assert result.batch_id == "batch-001"
    assert len(result.task_snapshots) == 2
    assert service.batch_tasks["batch-001"]["status"] == "running"
    assert dispatcher.prepare_calls == [
        ("batch-001", "batch_registration", 3, {"dynamic_proxy_strategy": "exclusive"})
    ]
```

```python
def test_outlook_batch_bootstrap_filters_registered_accounts_and_returns_dto(db_factory, fake_task_manager):
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=fake_task_manager,
        uuid_factory=lambda: "outlook-batch-001",
    )

    result = service.start_outlook_batch(
        service_ids=[101, 102, 103],
        skip_registered=True,
        proxy=None,
        concurrency=2,
        use_proxy=False,
        proxy_task_group="outlook_batch",
        proxy_overrides={},
    )

    assert isinstance(result, OutlookBatchBootstrapResult)
    assert result.batch_id == "outlook-batch-001"
    assert result.skipped == 1
    assert result.service_ids == [101, 103]
```

- [ ] **Step 2: 在 route 测试里先锁定“route 只委托，不自管 batch state”**

```python
def test_start_batch_registration_delegates_bootstrap_to_service(route_db, batch_state, monkeypatch):
    bootstrap_result = BatchBootstrapResult(
        batch_id="batch-from-service",
        task_snapshots=[RegistrationTaskSnapshot(id=1, task_uuid="task-1", status="pending")],
        is_unlimited=False,
    )

    class FakeBatchService:
        def __init__(self):
            self.calls = []

        def start_batch(self, **kwargs):
            self.calls.append(kwargs)
            return bootstrap_result

    fake_service = FakeBatchService()
    monkeypatch.setattr(registration_routes, "_build_batch_registration_service", lambda: fake_service)

    response = client.post("/api/registration/batch", json={"count": 1, "concurrency": 1, "mode": "pipeline"})

    assert response.status_code == 200
    assert response.json()["batch_id"] == "batch-from-service"
    assert fake_service.calls[0]["count"] == 1
    assert "batch-from-service" not in registration_routes.batch_tasks
```

- [ ] **Step 3: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest \
  tests/test_registration_bootstrap_contracts.py \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py -q
```

Expected: FAIL，提示 DTO / bootstrap API 尚不存在，route 仍直接操作 batch state。

- [ ] **Step 4: Commit failing-test baseline**

```bash
git add tests/test_registration_bootstrap_contracts.py \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py
git commit -m "test: lock registration bootstrap boundary contracts"
```

---

### Task 2: 引入 bootstrap DTO，并收口 single registration start path

**Files:**
- Create: `src/application/registration_bootstrap_dtos.py`
- Modify: `src/application/__init__.py`
- Modify: `src/application/registration_service.py`
- Modify: `src/web/routes/registration.py`
- Test: `tests/test_registration_bootstrap_contracts.py`
- Test: `tests/test_registration_service.py`
- Test: `tests/test_registration_batch_routes.py`

- [ ] **Step 1: 在 DTO 文件中写最小不可变快照类型**

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegistrationTaskSnapshot:
    id: int | None
    task_uuid: str
    status: str
    proxy: str | None = None
    pipeline_key: str | None = None
    email_service_id: int | None = None


@dataclass(frozen=True)
class BatchBootstrapResult:
    batch_id: str
    task_snapshots: list[RegistrationTaskSnapshot] = field(default_factory=list)
    is_unlimited: bool = False


@dataclass(frozen=True)
class OutlookBatchBootstrapResult:
    batch_id: str
    total: int
    skipped: int
    service_ids: list[int] = field(default_factory=list)
```

- [ ] **Step 2: 先让 `RegistrationService` 暴露 `start_task()`，内部完成创建 + snapshot 映射**

```python
def start_task(
    self,
    *,
    task_uuid: str,
    proxy: str | None,
    pipeline_key: str | None,
    email_service_id: int | None,
) -> RegistrationTaskSnapshot:
    with self.db_factory() as db:
        task = crud.create_registration_task(
            db,
            task_uuid=task_uuid,
            proxy=proxy,
            pipeline_key=pipeline_key,
            email_service_id=email_service_id,
        )
        return RegistrationTaskSnapshot(
            id=task.id,
            task_uuid=task.task_uuid,
            status=task.status,
            proxy=task.proxy,
            pipeline_key=task.pipeline_key,
            email_service_id=task.email_service_id,
        )
```

不要让 route 再直接拿 ORM task；保留 `create_task()` 作为兼容 wrapper，但在新 start path 中只使用 `start_task()`。

- [ ] **Step 3: 让 `start_registration` 路由改为消费 snapshot，而不是 ORM**

```python
snapshot = _build_registration_service().start_task(
    task_uuid=task_uuid,
    proxy=request.proxy if request.use_proxy else None,
    pipeline_key=request.pipeline_key,
    email_service_id=request.email_service_id,
)

return RegistrationTaskResponse(
    id=snapshot.id,
    task_uuid=snapshot.task_uuid,
    status=snapshot.status,
    proxy=snapshot.proxy,
    pipeline_key=snapshot.pipeline_key,
    email_service_id=snapshot.email_service_id,
)
```

`background_tasks.add_task(...)` 仍留在 route；这是 HTTP adapter 责任。

- [ ] **Step 4: 运行 single-start 聚焦测试并确认转绿**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest \
  tests/test_registration_bootstrap_contracts.py \
  tests/test_registration_service.py \
  tests/test_registration_batch_routes.py -q
```

Expected: PASS，single start 相关测试转绿；batch/outlook 相关测试仍可能失败。

- [ ] **Step 5: Commit single-start bootstrap boundary**

```bash
git add src/application/registration_bootstrap_dtos.py \
  src/application/__init__.py \
  src/application/registration_service.py \
  src/web/routes/registration.py \
  tests/test_registration_bootstrap_contracts.py \
  tests/test_registration_service.py \
  tests/test_registration_batch_routes.py
git commit -m "refactor: move single registration bootstrap into service"
```

---

### Task 3: 把 ordinary batch bootstrap 收口到 `BatchRegistrationService`

**Files:**
- Modify: `src/application/batch_registration_service.py`
- Modify: `src/web/routes/registration.py`
- Test: `tests/test_registration_bootstrap_contracts.py`
- Test: `tests/test_batch_registration_service.py`
- Test: `tests/test_registration_batch_routes.py`

- [ ] **Step 1: 先给 `BatchRegistrationService` 增加 `uuid_factory` 注入点，避免测试里 monkeypatch `uuid.uuid4`**

```python
def __init__(..., uuid_factory: Callable[[], str] | None = None):
    ...
    self.uuid_factory = uuid_factory or (lambda: str(uuid.uuid4()))
```

- [ ] **Step 2: 实现 `start_batch()`，把 batch_id、task creation、proxy warmup、state init 收口到 service**

```python
def start_batch(
    self,
    *,
    count: int,
    proxy: str | None,
    pipeline_key: str | None,
    concurrency: int,
    use_proxy: bool,
    proxy_task_group: str,
    proxy_overrides: dict[str, Any],
) -> BatchBootstrapResult:
    batch_id = self.uuid_factory()

    if count == 0:
        if use_proxy:
            self._prepare_proxy_pool_with_fallback(...)
        self.init_batch_state(batch_id, [], is_unlimited=True, total=0)
        return BatchBootstrapResult(batch_id=batch_id, task_snapshots=[], is_unlimited=True)

    if use_proxy:
        self._prepare_proxy_pool_with_fallback(...)

    tasks = self.create_batch_tasks(count=count, proxy=proxy, pipeline_key=pipeline_key)
    self.init_batch_state(batch_id, [task.task_uuid for task in tasks])
    return BatchBootstrapResult(
        batch_id=batch_id,
        task_snapshots=[self._task_to_snapshot(task) for task in tasks],
        is_unlimited=False,
    )
```

保留原有 `create_batch_tasks()`、`init_batch_state()` 供内部复用，但 route 不再直接调它们。

- [ ] **Step 3: 改造 `/registration/batch` route，只保留 request 校验与 background task 调度**

```python
bootstrap = batch_service.start_batch(
    count=request.count,
    proxy=request.proxy if request.use_proxy else None,
    pipeline_key=request.pipeline_key,
    concurrency=request.concurrency,
    use_proxy=request.use_proxy,
    proxy_task_group="batch_registration" if request.count else "unlimited_registration",
    proxy_overrides=batch_proxy_overrides,
)
```

然后根据 `bootstrap.is_unlimited` 决定 background task 调度哪个 runner；route 不再写 `_init_batch_state()`，也不再直接调用 `prepare_batch_proxy_pool()`。

- [ ] **Step 4: 运行 ordinary batch 聚焦测试并确认转绿**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest \
  tests/test_registration_bootstrap_contracts.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py -q
```

Expected: PASS，ordinary batch start / unlimited bootstrap 相关测试转绿。

- [ ] **Step 5: Commit ordinary batch bootstrap boundary**

```bash
git add src/application/batch_registration_service.py \
  src/web/routes/registration.py \
  tests/test_registration_bootstrap_contracts.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py
git commit -m "refactor: move batch bootstrap into service"
```

---

### Task 4: 把 Outlook batch bootstrap 与跳过逻辑收口到 service

**Files:**
- Modify: `src/application/batch_registration_service.py`
- Modify: `src/web/routes/registration.py`
- Test: `tests/test_registration_bootstrap_contracts.py`
- Test: `tests/test_batch_registration_service.py`
- Test: `tests/test_registration_batch_routes.py`

- [ ] **Step 1: 先把“过滤已注册邮箱 + skipped 计数”写成 service 失败测试**

```python
def test_batch_registration_service_start_outlook_batch_filters_registered_accounts(db_factory, fake_task_manager):
    seed_outlook_services_and_accounts(...)
    service = BatchRegistrationService(
        db_factory=db_factory,
        task_manager=fake_task_manager,
        uuid_factory=lambda: "outlook-batch-001",
    )

    result = service.start_outlook_batch(
        service_ids=[1, 2, 3],
        skip_registered=True,
        proxy=None,
        concurrency=2,
        use_proxy=False,
        proxy_task_group="outlook_batch",
        proxy_overrides={},
    )

    assert result.batch_id == "outlook-batch-001"
    assert result.total == 3
    assert result.skipped == 1
    assert result.service_ids == [1, 3]
```

- [ ] **Step 2: 实现 `start_outlook_batch()`，由 service 统一负责过滤、batch init、proxy warmup**

```python
def start_outlook_batch(... ) -> OutlookBatchBootstrapResult:
    batch_id = self.uuid_factory()
    actual_service_ids, skipped = self._filter_outlook_service_ids(...)
    if not actual_service_ids:
        return OutlookBatchBootstrapResult(
            batch_id="",
            total=len(service_ids),
            skipped=skipped,
            service_ids=[],
        )

    self.batch_tasks[batch_id] = {...}
    if use_proxy:
        self._prepare_proxy_pool_with_fallback(...)

    return OutlookBatchBootstrapResult(
        batch_id=batch_id,
        total=len(service_ids),
        skipped=skipped,
        service_ids=actual_service_ids,
    )
```

第一批可以接受 `batch_tasks` 初始化仍在 service 内部，后续 runtime split 计划再处理与 `task_manager` 的进一步分层。

- [ ] **Step 3: 改造 `/registration/outlook-batch` route，只保留 request 校验与 background task 调度**

```python
bootstrap = batch_service.start_outlook_batch(
    service_ids=request.service_ids,
    skip_registered=request.skip_registered,
    proxy=request.proxy if request.use_proxy else None,
    concurrency=request.concurrency,
    use_proxy=request.use_proxy,
    proxy_task_group="outlook_batch",
    proxy_overrides=batch_proxy_overrides,
)

if not bootstrap.service_ids:
    return OutlookBatchRegistrationResponse(
        batch_id="",
        total=bootstrap.total,
        skipped=bootstrap.skipped,
        to_register=0,
        service_ids=[],
    )
```

- [ ] **Step 4: 运行 Outlook batch 聚焦测试并确认转绿**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest \
  tests/test_registration_bootstrap_contracts.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py -q
```

Expected: PASS，Outlook batch bootstrap、skip_registered、响应兼容测试转绿。

- [ ] **Step 5: Commit Outlook bootstrap boundary**

```bash
git add src/application/batch_registration_service.py \
  src/web/routes/registration.py \
  tests/test_registration_bootstrap_contracts.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py
git commit -m "refactor: move outlook batch bootstrap into service"
```

---

### Task 5: 清理 start path 遗留逻辑并跑回归套件

**Files:**
- Modify: `src/web/routes/registration.py`
- Test: `tests/test_registration_bootstrap_contracts.py`
- Test: `tests/test_registration_service.py`
- Test: `tests/test_batch_registration_service.py`
- Test: `tests/test_registration_batch_routes.py`
- Regression: `tests/test_registration_runs_service.py`
- Regression: `tests/test_task_manager.py`
- Regression: `tests/test_realtime_stream_routes.py`

- [ ] **Step 1: 删除 route 中已失效的 batch bootstrap helper，只保留兼容读路径别名**

至少检查并清理：

```python
# 删除或内联为 service 调用后的冗余 helper
_init_batch_state
_build_batch_proxy_overrides  # 若仍只承担 request -> dict 映射，可以保留
batch_tasks[...] = {...}      # route 中不应再直接出现
prepare_batch_proxy_pool(...) # route 中不应再直接出现
```

允许 `batch_tasks = DEFAULT_BATCH_TASKS_STORE` 继续存在，作为兼容读路径；等后续 runtime split plan 再处理读接口的彻底下沉。

- [ ] **Step 2: 运行 foundation 聚焦回归套件**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest \
  tests/test_registration_bootstrap_contracts.py \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py \
  tests/test_registration_runs_service.py \
  tests/test_task_manager.py -q
```

Expected: PASS

- [ ] **Step 3: 运行 start-path 相关 smoke tests，确认未打坏页面与 realtime 合约**

Run:

```bash
timeout 60s env PYTHONPATH="$PWD/.venv/lib/python3.14/site-packages" \
  python -m pytest \
  tests/test_realtime_stream_routes.py \
  tests/test_registration_page_assets.py \
  tests/test_run_center_page_assets.py -q
```

Expected: PASS

- [ ] **Step 4: 检查 diff 只覆盖 foundation 范围，不把后续 phase 的想法顺手混进来**

Run:

```bash
git diff --stat
git diff -- src/application src/web/routes tests | sed -n '1,220p'
```

Expected: 只出现 DTO / service bootstrap / route start path / tests 相关变更；没有顺手拆 `crud.py`、`task_manager` 大重构、`register.py` 清债等超范围内容。

- [ ] **Step 5: Commit foundation slice**

```bash
git add src/application/__init__.py \
  src/application/registration_bootstrap_dtos.py \
  src/application/registration_service.py \
  src/application/batch_registration_service.py \
  src/web/routes/registration.py \
  tests/test_registration_bootstrap_contracts.py \
  tests/test_registration_service.py \
  tests/test_batch_registration_service.py \
  tests/test_registration_batch_routes.py
git commit -m "refactor: move registration bootstrap ownership into services"
```

---

## Handoff Notes

1. 这个 foundation 计划完成后，应用层会正式拥有 start path 的 bootstrap 语义，但 **query/status path 仍未完全下沉**；不要误判为整个 Phase 2 已完成。
2. 完成本计划后，优先进入下一份 route/query boundary plan，而不是直接去拆 `crud.py` 或 `register.py`。
3. 如果在执行过程中发现 `task_manager` 镜像与 service bootstrap 契约冲突，不要临时在 route 层打补丁，应记录为下一份 runtime split plan 的显式输入。
