# codex-console 架构治理与渐进式重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不打断现有功能交付的前提下，拆分启动配置与运行时配置、统一注册运行态、引入 application/repository 分层，并收敛事务与日志边界。

**Architecture:** 采用低风险、渐进式纵切方案，按 6 个可独立回归的 PR 推进。先收口平台基线与启动边界，再引入持久化运行态，随后把注册单任务/批量主链路迁入应用服务层，最后完成 settings 分层与事务/日志治理，避免继续放大 route/crud 巨石文件。

**Tech Stack:** FastAPI、SQLAlchemy ORM、Pydantic v2、SQLite/PostgreSQL 兼容层、Jinja2、vanilla JS、pytest、现有 route/task-manager/scheduler/pipeline 模式。

---

## Spec Reference

- `docs/superpowers/specs/2026-03-24-architecture-refactor-roadmap-design.md`

## Review Note

- 当前会话未获得用户对 reviewer/subagent 的显式授权，因此本计划先按现有上下文本地自审并落盘；如后续用户授权，再补 reviewer 循环。

## Execution Prerequisite

在进入 Task 1 之前，先恢复可执行的本地测试基线；否则后续所有“红/绿”步骤都会被环境错误污染。

1. 安装依赖：

```bash
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
```

2. 记录当前基线：

```bash
timeout 60s python -m pytest -q
```

3. 若仍出现环境级错误（如 `jinja2` / `croniter` 缺失），先解决环境问题，再进入下面任务。

---

## File Map

### Create

- `src/boot/__init__.py` — Boot 层导出。
- `src/boot/settings.py` — 进程级启动配置模型、CLI/env 解析与 override 存取。
- `src/boot/lifespan.py` — FastAPI lifespan 启停装配。
- `src/core/time.py` — UTC aware 时间工具入口。
- `src/application/__init__.py` — 应用服务层导出。
- `src/application/settings_service.py` — Runtime settings 读取/更新编排与校验。
- `src/application/registration_runs_service.py` — 注册 run/event 创建、事件追加、状态流转。
- `src/application/registration_service.py` — 单任务注册 orchestration。
- `src/application/batch_registration_service.py` — 普通批量 / 无限批量 orchestration。
- `src/database/repositories/__init__.py` — repository 包导出。
- `src/database/repositories/settings_repository.py` — settings 持久化访问层。
- `src/database/repositories/registration_repository.py` — registration run/event 持久化访问层。
- `tests/test_boot_settings.py` — Boot/runtime 配置拆分测试。
- `tests/test_app_lifespan.py` — 生命周期与时间 helper 测试。
- `tests/test_registration_runs_service.py` — run/event service 测试。
- `tests/test_registration_service.py` — 单任务应用服务测试。
- `tests/test_batch_registration_service.py` — 批量应用服务测试。
- `tests/test_settings_service.py` — settings service 行为测试。
- `tests/test_registration_engine_logging.py` — 注册日志缓冲/flush/事务边界测试。

### Modify

- `webui.py` — 停止把 CLI/env 启动覆盖写回 DB，改为使用 BootSettings。
- `src/config/settings.py` — 收敛为 runtime settings 读取入口，支持 force reload。
- `src/web/app.py` — 使用 app factory + lifespan，认证逻辑支持 boot override。
- `src/web/task_manager.py` — 从主状态存储降级为 WebSocket/广播适配器。
- `src/web/routes/registration.py` — 委托给 application services，移除主编排职责。
- `src/web/routes/settings.py` — 委托给 settings service。
- `src/web/routes/accounts.py` — 触达范围内切换时间 helper / ConfigDict。
- `src/web/routes/email.py` — 触达范围内切换 ConfigDict / 时间 helper。
- `src/database/models.py` — 新增 registration run/event 表并清理 ORM 基础定义。
- `src/database/crud.py` — 保留兼容 wrapper，同时为 session-owned helper 做收口。
- `src/database/session.py` — 确保新表可建并为 repository/service 提供稳定 session 入口。
- `src/core/register.py` — 改造日志写入策略，从逐条 commit 改为缓冲 flush。
- `src/core/registration_job.py` — 如测试驱动需要，补齐与新 service/logging 边界的配合。
- `README.md` — 对齐启动优先级、配置持久化语义、数据库部署建议与后续硬化说明。
- `tests/test_database_session.py` — 新表创建与迁移 guardrail。
- `tests/test_registration_batch_routes.py` — 注册路由回归与批量汇总回归。
- `tests/test_task_manager.py` — TaskManager 降级后的行为回归。
- `tests/test_proxy_settings_routes.py` — settings route 回归。
- `tests/test_settings_proxy_assets.py` — settings 页面/接口资源回归。
- `tests/test_scheduled_tasks_routes.py` — 配置与调度链路回归。

---

## Task 1: 收口平台基线（lifespan、aware UTC、弃用项清理）

**Files:**
- Create: `src/core/time.py`
- Create: `src/boot/lifespan.py`
- Create: `tests/test_app_lifespan.py`
- Modify: `src/web/app.py`
- Modify: `src/database/models.py`
- Modify: `src/web/routes/accounts.py`
- Modify: `src/web/routes/email.py`
- Modify: `src/web/routes/registration.py`

- [ ] **Step 1: 写失败测试，锁定时间 helper 与生命周期行为**

```python
from datetime import timedelta

from src.core.time import utc_now


def test_utc_now_returns_timezone_aware_utc_datetime():
    value = utc_now()
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)
```

```python
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.task_manager import task_manager


def test_create_app_uses_lifespan_startup_and_shutdown_hooks():
    app = create_app()
    engine = app.state.scheduler_engine

    assert engine._started is False

    with TestClient(app):
        assert engine._started is True
        assert task_manager.get_loop() is not None
        assert app.state.account_survival_dispatcher is not None

    assert engine._started is False
```

- [ ] **Step 2: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s python -m pytest tests/test_app_lifespan.py -q
```

Expected: FAIL，因为 `src/core/time.py` 与 lifespan wiring 尚不存在。

- [ ] **Step 3: 实现最小 UTC aware 时间入口**

```python
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
```

- [ ] **Step 4: 把启动/关闭逻辑从 `on_event` 迁到 `src/boot/lifespan.py`**

```python
from contextlib import asynccontextmanager
import asyncio


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    initialize_database()
    task_manager.set_loop(asyncio.get_running_loop())
    app.state.scheduler_engine.start()
    try:
        yield
    finally:
        app.state.scheduler_engine.stop()
```

然后让 `create_app()` 使用：

```python
app = FastAPI(..., lifespan=app_lifespan)
```

- [ ] **Step 5: 清理本任务触达范围内的明显弃用项**

```python
from sqlalchemy.orm import declarative_base
from pydantic import ConfigDict
```

优先处理：

- `src/database/models.py` 的 `declarative_base`
- 触达的响应模型上的 `ConfigDict(from_attributes=True)`
- 触达文件中的 `datetime.utcnow()`，改为复用 `utc_now()` 或集中 helper

- [ ] **Step 6: 回归生命周期与调度基线**

Run:

```bash
timeout 60s python -m pytest tests/test_app_lifespan.py tests/test_scheduler_engine.py -q
```

Expected: PASS。

- [ ] **Step 7: 运行一轮更宽的 smoke 回归**

Run:

```bash
timeout 60s python -m pytest tests/test_dashboard_page_assets.py tests/test_static_asset_versioning.py -q
```

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add src/core/time.py src/boot/lifespan.py src/web/app.py src/database/models.py src/web/routes/accounts.py src/web/routes/email.py src/web/routes/registration.py tests/test_app_lifespan.py
git commit -m "refactor: adopt lifespan and shared utc helpers"
```

---

## Task 2: 拆分 Boot Settings 与 Runtime Settings

**Files:**
- Create: `src/boot/__init__.py`
- Create: `src/boot/settings.py`
- Create: `tests/test_boot_settings.py`
- Modify: `webui.py`
- Modify: `src/config/settings.py`
- Modify: `src/web/app.py`
- Modify: `README.md`

- [ ] **Step 1: 写失败测试，锁定启动优先级与“不落库”语义**

```python
from src.boot.settings import BootSettings


def test_boot_settings_cli_overrides_env():
    settings = BootSettings.from_sources(
        env={"WEBUI_HOST": "127.0.0.1", "WEBUI_PORT": "9001", "WEBUI_ACCESS_PASSWORD": "env-secret"},
        cli={"host": "0.0.0.0", "port": 8010, "access_password": "cli-secret", "debug": False, "reload": False},
    )
    assert settings.host == "0.0.0.0"
    assert settings.port == 8010
    assert settings.access_password_override == "cli-secret"
```

```python
def test_webui_cli_overrides_do_not_call_update_settings(monkeypatch):
    called = {"value": False}

    def fake_update_settings(**kwargs):
        called["value"] = True
        raise AssertionError("boot override must not persist to DB")

    monkeypatch.setattr("src.config.settings.update_settings", fake_update_settings)
    ...
    assert called["value"] is False
```

- [ ] **Step 2: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s python -m pytest tests/test_boot_settings.py -q
```

Expected: FAIL，因为 `BootSettings` 与进程级 override 尚不存在。

- [ ] **Step 3: 引入 `BootSettings` 与进程级 boot override 存取**

```python
@dataclass(frozen=True)
class BootSettings:
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    reload: bool = False
    log_level: str | None = None
    access_password_override: str | None = None
    database_url_override: str | None = None
```

同时提供：

```python
def set_boot_settings(settings: BootSettings) -> None: ...
def get_boot_settings() -> BootSettings: ...
```

- [ ] **Step 4: 改造 `webui.py`，让 CLI/env 覆盖只作用当前进程**

```python
boot_settings = BootSettings.from_sources(env=os.environ, cli=vars(args))
set_boot_settings(boot_settings)
start_webui(boot_settings)
```

删除/替换当前：

```python
update_settings(**updates)
```

- [ ] **Step 5: 收紧 `src/config/settings.py`，只保留 runtime settings 入口**

```python
def get_settings(*, force_reload: bool = False) -> Settings:
    ...
```

并移除明显属于 boot 层的 env override：

- `APP_HOST`
- `APP_PORT`
- `APP_ACCESS_PASSWORD`

- [ ] **Step 6: 让 `src/web/app.py` 登录逻辑优先读取 boot access password override**

```python
def _effective_access_password() -> str:
    boot = get_boot_settings()
    if boot.access_password_override:
        return boot.access_password_override
    return get_settings().webui_access_password.get_secret_value()
```

- [ ] **Step 7: 更新 README，写清启动优先级与持久化行为**

```text
CLI 和环境变量启动覆盖仅作用于当前进程，不会写回设置数据库。
如需持久化修改，请通过 Web UI 设置页面或明确的管理入口修改。
```

- [ ] **Step 8: 回归配置与页面入口链路**

Run:

```bash
timeout 60s python -m pytest tests/test_boot_settings.py tests/test_scheduler_engine.py tests/test_dashboard_page_assets.py tests/test_registration_page_assets.py -q
```

Expected: PASS。

- [ ] **Step 9: Commit**

```bash
git add src/boot/__init__.py src/boot/settings.py webui.py src/config/settings.py src/web/app.py README.md tests/test_boot_settings.py
git commit -m "refactor: split boot settings from runtime settings"
```

---

## Task 3: 新增持久化注册运行态（registration_runs / registration_run_events）

**Files:**
- Create: `src/application/__init__.py`
- Create: `src/application/registration_runs_service.py`
- Create: `src/database/repositories/__init__.py`
- Create: `src/database/repositories/registration_repository.py`
- Create: `tests/test_registration_runs_service.py`
- Modify: `src/database/models.py`
- Modify: `src/database/session.py`
- Modify: `tests/test_database_session.py`

- [ ] **Step 1: 写失败测试，锁定 run/event 的创建与终态规则**

```python
from src.application.registration_runs_service import RegistrationRunsService


def test_registration_runs_service_creates_run_and_appends_events(temp_db):
    service = RegistrationRunsService(temp_db)
    run = service.create_run(task_uuid="task-1", batch_id="batch-1", trigger_source="manual")
    service.append_event(run.id, level="info", message="queued")

    events = service.get_events(run.id)
    assert run.id is not None
    assert events[0].message == "queued"
```

```python
def test_registration_runs_service_terminal_status_is_immutable(temp_db):
    service = RegistrationRunsService(temp_db)
    run = service.create_run(task_uuid="task-2", batch_id=None, trigger_source="manual")
    service.mark_completed(run.id)
    updated = service.mark_failed(run.id, error_message="ignored")

    assert updated.status == "completed"
```

- [ ] **Step 2: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s python -m pytest tests/test_registration_runs_service.py -q
```

Expected: FAIL，因为 run/event 模型与 service 尚不存在。

- [ ] **Step 3: 在 ORM 中新增 `registration_runs` 与 `registration_run_events`**

```python
class RegistrationRun(Base):
    __tablename__ = "registration_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_uuid = Column(String(36), nullable=False, unique=True, index=True)
    batch_id = Column(String(36), index=True)
    trigger_source = Column(String(32), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
```

```python
class RegistrationRunEvent(Base):
    __tablename__ = "registration_run_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("registration_runs.id"), nullable=False, index=True)
    level = Column(String(16), nullable=False)
    message = Column(Text, nullable=False)
```

- [ ] **Step 4: 建立 repository，保证新持久化逻辑不再继续堆进 `crud.py`**

```python
def create_registration_run(session, **kwargs) -> RegistrationRun: ...
def get_registration_run_by_task_uuid(session, task_uuid: str) -> RegistrationRun | None: ...
def append_registration_run_event(session, *, run_id: int, level: str, message: str, created_at=None) -> RegistrationRunEvent: ...
```

规则：repository 负责持久化，不负责状态机语义；优先 `flush()/refresh()`，尽量不内置 `commit()`。

- [ ] **Step 5: 建立 `RegistrationRunsService`，负责状态流转与终态只写一次**

```python
class RegistrationRunsService:
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

    def mark_failed(self, run_id: int, *, error_message: str | None = None):
        ...
```

- [ ] **Step 6: 补数据库层 guardrail，确保新表可建**

```python
from sqlalchemy import inspect
from src.database.session import DatabaseSessionManager


def test_create_tables_includes_registration_run_tables(tmp_path):
    manager = DatabaseSessionManager(f"sqlite:///{tmp_path / 'test.db'}")
    manager.create_tables()
    table_names = set(inspect(manager.engine).get_table_names())
    assert "registration_runs" in table_names
    assert "registration_run_events" in table_names
```

- [ ] **Step 7: 回归新 service 与 DB 层**

Run:

```bash
timeout 60s python -m pytest tests/test_registration_runs_service.py tests/test_database_session.py -q
```

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add src/application/__init__.py src/application/registration_runs_service.py src/database/repositories/__init__.py src/database/repositories/registration_repository.py src/database/models.py src/database/session.py tests/test_registration_runs_service.py tests/test_database_session.py
git commit -m "feat: add persistent registration run state"
```

---

## Task 4: 把注册单任务 / 批量主链路迁入 application services

**Files:**
- Create: `src/application/registration_service.py`
- Create: `src/application/batch_registration_service.py`
- Create: `tests/test_registration_service.py`
- Create: `tests/test_batch_registration_service.py`
- Modify: `src/web/routes/registration.py`
- Modify: `src/web/task_manager.py`
- Modify: `src/core/register.py`
- Modify: `tests/test_registration_batch_routes.py`
- Modify: `tests/test_task_manager.py`

- [ ] **Step 1: 写失败测试，锁定单任务 service 的 run 状态与 legacy task 同步**

```python
def test_registration_service_creates_run_records_and_terminal_status(temp_db, monkeypatch):
    service = RegistrationService(...)
    result = service.run_single_task_sync(task_uuid="task-1", ...)
    assert result.run.status == "completed"
```

```python
def test_registration_service_keeps_legacy_registration_task_in_sync(temp_db, monkeypatch):
    service = RegistrationService(...)
    result = service.run_single_task_sync(task_uuid="task-2", ...)
    assert result.task.status == "completed"
```

- [ ] **Step 2: 写失败测试，锁定批量 service 的汇总、取消与 finalize 行为**

```python
def test_batch_registration_service_updates_batch_progress_from_run_records(temp_db, monkeypatch):
    service = BatchRegistrationService(...)
    summary = service.run_parallel_batch(...)
    assert summary.completed == 2
```

```python
def test_batch_registration_service_finalizes_ordinary_batch_stats(temp_db, monkeypatch):
    ...
```

- [ ] **Step 3: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s python -m pytest tests/test_registration_service.py tests/test_batch_registration_service.py -q
```

Expected: FAIL，因为 application orchestration 层尚不存在。

- [ ] **Step 4: 把 `_run_sync_registration_task()` / `run_registration_task()` 迁到 `RegistrationService`**

服务层负责：

- 创建或获取 `registration_runs`
- 状态流转（pending → running → terminal）
- 更新 legacy `registration_tasks`
- 调用 `run_registration_job(...)`
- 保留自动上传 CPA/Sub2API/TM 逻辑

- [ ] **Step 5: 把普通批量 / 无限批量逻辑迁到 `BatchRegistrationService`**

从 route 中迁出：

- `_init_batch_state(...)`
- `_make_batch_helpers(...)`
- `_finalize_batch_domain_stats(...)`
- `_build_batch_statistics_context(...)`
- `_finalize_ordinary_batch_statistics(...)`
- `run_batch_parallel(...)`
- `run_batch_pipeline(...)`
- `run_unlimited_batch_registration(...)`

- [ ] **Step 6: 把 `TaskManager` 降级成广播适配器，而不是主真相源**

规则：

- 允许短期保留 `_task_status / _batch_status / _log_queues` 作为镜像缓存
- 新主状态来自 `registration_runs` + service 汇总
- route 查询优先从 DB/service 取值，TaskManager 只补实时广播态

- [ ] **Step 7: 让 `registration.py` route 只做 request/response 与 service 调用**

例如：

```python
@router.post("/start")
async def start_registration(request: RegistrationRequest):
    return await registration_service.start_from_request(request)
```

- [ ] **Step 8: 回归 application service 与现有 route 兼容性**

Run:

```bash
timeout 60s python -m pytest tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_batch_routes.py tests/test_task_manager.py -q
```

Expected: PASS。

- [ ] **Step 9: Commit**

```bash
git add src/application/registration_service.py src/application/batch_registration_service.py src/web/routes/registration.py src/web/task_manager.py src/core/register.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_batch_routes.py tests/test_task_manager.py
git commit -m "refactor: move registration orchestration into services"
```

---

## Task 5: 抽出 settings service / repository 边界

**Files:**
- Create: `src/application/settings_service.py`
- Create: `src/database/repositories/settings_repository.py`
- Create: `tests/test_settings_service.py`
- Modify: `src/web/routes/settings.py`
- Modify: `src/config/settings.py`
- Modify: `src/database/crud.py`
- Modify: `tests/test_proxy_settings_routes.py`
- Modify: `tests/test_settings_proxy_assets.py`
- Modify: `tests/test_scheduled_tasks_routes.py`

- [ ] **Step 1: 写失败测试，锁定 settings service 的统一更新语义**

```python
from src.application.settings_service import SettingsService


def test_settings_service_updates_proxy_settings(temp_db):
    service = SettingsService(...)
    settings = service.update_runtime_settings({
        "proxy_enabled": True,
        "proxy_host": "127.0.0.1",
        "proxy_port": 7890,
    })
    assert settings.proxy_enabled is True
```

```python
def test_settings_service_rejects_invalid_email_code_timeout(temp_db):
    service = SettingsService(...)
    with pytest.raises(ValueError, match="timeout"):
        service.update_runtime_settings({"email_code_timeout": 10})
```

- [ ] **Step 2: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s python -m pytest tests/test_settings_service.py -q
```

Expected: FAIL，因为 settings service/repository 尚不存在。

- [ ] **Step 3: 新建 `SettingsRepository`，只负责 DB 访问，不负责业务语义**

```python
def get_by_key(session, key: str): ...
def set_by_key(session, key: str, value: str, *, category: str, description: str): ...
def set_many(session, items: dict[str, str]): ...
def load_runtime_values(session) -> dict[str, Any]: ...
```

- [ ] **Step 4: 新建 `SettingsService`，集中参数校验、批量更新与错误映射**

```python
class SettingsService:
    def get_runtime_settings(self) -> Settings: ...
    def update_runtime_settings(self, payload: dict[str, Any]) -> Settings: ...
    def update_dynamic_proxy_settings(self, request) -> Settings: ...
```

- [ ] **Step 5: 把 `src/web/routes/settings.py` 改成只调 service**

例如：

```python
@router.post("/registration")
async def update_registration_settings(request: RegistrationSettings):
    settings_service.update_registration_settings(request)
    return {"success": True, "message": "注册设置已更新"}
```

- [ ] **Step 6: 保持 `src/config/settings.py` 为 runtime settings 入口，停止继续堆业务逻辑**

新规则：

- `Settings` 模型与 `get_settings(force_reload=True)` 保留
- 新增 settings 业务逻辑进入 service/repository
- `crud.py` 只保留兼容 wrapper，不再新增 settings 顶层 helper

- [ ] **Step 7: 回归 settings route 与现有页面资源**

Run:

```bash
timeout 60s python -m pytest tests/test_settings_service.py tests/test_proxy_settings_routes.py tests/test_settings_proxy_assets.py tests/test_scheduled_tasks_routes.py -q
```

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add src/application/settings_service.py src/database/repositories/settings_repository.py src/web/routes/settings.py src/config/settings.py src/database/crud.py tests/test_settings_service.py tests/test_proxy_settings_routes.py tests/test_settings_proxy_assets.py tests/test_scheduled_tasks_routes.py
git commit -m "refactor: introduce settings service and repository"
```

---

## Task 6: 收口事务边界与注册日志写入策略

**Files:**
- Create: `tests/test_registration_engine_logging.py`
- Modify: `src/core/register.py`
- Modify: `src/core/registration_job.py`
- Modify: `src/database/crud.py`
- Modify: `src/database/models.py`
- Modify: `README.md`
- Modify: `tests/test_database_session.py`
- Modify: `tests/test_registration_batch_routes.py`
- Modify: `tests/test_task_manager.py`

- [ ] **Step 1: 写失败测试，锁定“日志不再逐条 commit”**

```python
def test_registration_logging_does_not_commit_per_message(monkeypatch, temp_db):
    commits = []
    ...
    assert len(commits) <= 1
```

```python
def test_registration_log_buffer_flushes_all_lines(temp_db):
    ...
    assert "line 1" in persisted.logs
    assert "line 2" in persisted.logs
```

- [ ] **Step 2: 运行聚焦测试，确认先红灯**

Run:

```bash
timeout 60s python -m pytest tests/test_registration_engine_logging.py -q
```

Expected: FAIL，因为当前 `_log()` 仍会逐条 `with get_db()` + `crud.append_task_log()` + `commit()`。

- [ ] **Step 3: 在 `src/database/crud.py` 新增 session-owned helper，避免 helper 内部抢事务所有权**

```python
def update_registration_task_fields(session, task_uuid: str, **kwargs): ...
def append_task_logs(session, task_uuid: str, log_messages: list[str]) -> bool: ...
```

规则：优先 `flush()`，不在 helper 里 `commit()`。

- [ ] **Step 4: 改造 `RegistrationEngine._log()`，变成“实时广播 + 延迟持久化”**

```python
self._pending_task_logs.append(log_message)
self.callback_logger(log_message)
```

保留 callback 实时性，但把 DB 持久化延后到：

- 关键阶段结束
- 成功出口
- 失败出口
- 异常出口
- 或积累到阈值时

- [ ] **Step 5: 在 service/orchestration 层统一 flush 日志与任务状态**

目标：

- 让状态更新、日志 flush、终态写入尽量落在同一事务边界
- 避免“一条日志一次会话 + 一次提交”的高频碎事务模式

- [ ] **Step 6: 保证实时日志行为不回归**

继续通过 `TaskManager` / callback_logger 提供：

- 前端实时日志
- WebSocket 推送
- 短时日志缓存

DB 持久化延迟，不代表前端实时体验延迟。

- [ ] **Step 7: 更新 README，补齐 PostgreSQL-first 与敏感字段后续硬化说明**

```text
SQLite 适合本地/单用户使用；需要持续并发注册负载时，推荐 PostgreSQL 作为默认部署目标。
账号密码、第三方服务密钥等敏感字段后续将进入字段级保护与硬化阶段。
```

- [ ] **Step 8: 回归日志/事务/批量主链路**

Run:

```bash
timeout 60s python -m pytest tests/test_registration_engine_logging.py tests/test_database_session.py tests/test_registration_batch_routes.py tests/test_task_manager.py -q
```

Expected: PASS。

- [ ] **Step 9: 跑全量回归**

Run:

```bash
timeout 60s python -m pytest -q
```

Expected: PASS。

- [ ] **Step 10: Commit**

```bash
git add src/core/register.py src/core/registration_job.py src/database/crud.py src/database/models.py README.md tests/test_registration_engine_logging.py tests/test_database_session.py tests/test_registration_batch_routes.py tests/test_task_manager.py
git commit -m "refactor: tighten transaction and logging boundaries"
```

---

## Suggested PR Sequence

按依赖关系，推荐严格按下面顺序推进：

1. `PR-1` 平台基线治理
2. `PR-2` Boot / Runtime 配置拆分
3. `PR-3` 注册运行态持久化
4. `PR-4` 注册主流程服务化
5. `PR-5` Settings / Repository 分层
6. `PR-6` 事务与日志边界治理

说明：

- `PR-1 → PR-4` 属于强依赖链，不能随意并行。
- `PR-5` 与 `PR-6` 理论上可部分并行写测试，但实现阶段都会碰到边界收口与 `crud.py`，仍建议串行执行。

---

## Exit Criteria

整条架构路线完成时，必须同时满足以下条件：

1. CLI/env 启动覆盖是进程级的，不再静默写回数据库。
2. 应用启动/关闭使用 `lifespan`，并有统一 UTC aware 时间入口。
3. 注册运行态落在 `registration_runs / registration_run_events`，成为单一权威来源。
4. `TaskManager` 只承担广播/适配职责，不再是主状态存储。
5. 注册与 settings 路由主要只负责 request/response，不再直接编排复杂业务。
6. 新的持久化逻辑默认进入 repository / service，而不是继续扩张 `src/database/crud.py`。
7. 相关聚焦测试与最终全量 `pytest` 均通过。
