# Unified Realtime Log Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为注册工作台和定时任务运行日志落地统一的 WebSocket 实时日志同步链路、共享日志 store / console 组件，并彻底移除“日志事件直写 DOM + 轮询主链路”造成的不实时问题。

**Architecture:** 后端继续复用现有 `TaskManager + realtime_streams + websocket replay` 机制，但补齐 `run:{run_id}` 第三类 stream、结构化日志条目 contract、统一 `/api/realtime-streams/*` 路由与 run WebSocket。前端新增共享 `realtime_log_store.js + realtime_log_client.js + realtime_log_console.js + realtime_log_console.css`，定时任务与注册工作台都改为“snapshot/history -> store -> console render”的单向数据流，同时保留历史 chunk 接口与旧 registration stream alias 作为兼容层。

**Tech Stack:** FastAPI、SQLAlchemy、vanilla JS、WebSocket、Jinja2、pytest、FastAPI TestClient、Node VM harness、CSS 自定义属性。

---

## Spec Reference

- 设计文档：`docs/superpowers/specs/2026-03-26-unified-realtime-log-sync-design.md`

## Implementation Guardrails

- 执行每个任务时，都遵守 @superpowers:test-driven-development、@superpowers:verification-before-completion。
- 每个测试命令都使用 `timeout 60s`，避免后台卡死。
- 页面脚本不得再新增“收到事件直接 append DOM”的路径；所有日志必须先进入共享 store。
- 定时任务历史日志仍使用 `/api/scheduled-runs/{run_id}/logs`，但它只负责历史，不再是实时主链路。

## File Map

### Backend realtime contracts

- Modify: `src/web/realtime_streams.py`
  - 新增 `run_stream_id(...)`、结构化日志条目 helper、通用 snapshot / event envelope helper、统一常量（`STREAM_BUFFER_SIZE=1000`、`LOG_TAIL_SIZE=10`）。
- Modify: `src/web/task_manager.py`
  - 增加 run stream 状态、结构化 `logs_tail`、`snapshot.seq` contract、run websocket 注册 / replay / broadcast / stream close。
- Create: `src/web/routes/realtime_streams.py`
  - 提供 `task/batch/run` 的通用 snapshot / events REST 接口。
- Modify: `src/web/routes/registration_streams.py`
  - 旧 `/api/registration/streams/*` 变为兼容层，内部委托给通用 realtime-streams 实现。
- Modify: `src/web/routes/websocket.py`
  - 统一 task / batch / run WebSocket 入口，补 run replay、`snapshot_required` 重同步语义与解析注释。
- Modify: `src/web/routes/__init__.py`
  - 注册新的 `/api/realtime-streams` router。

### Scheduler emitters

- Modify: `src/scheduler/run_logger.py`
  - `append_run_log(...)` 构造结构化日志条目并广播到 `run:{run_id}` stream。
- Modify: `src/scheduler/engine.py`
  - 运行开始 / stopping / success / failed / cancelled 时发 `run_status_changed` / `stream_closed`。
- Modify: `src/scheduler/runners/cleanup.py`
- Modify: `src/scheduler/runners/refill.py`
- Modify: `src/scheduler/runners/refresh.py`
  - 仅在必要处补显式 `level=` 或进度摘要，不做无关重构。

### Shared frontend realtime console

- Create: `static/js/realtime_log_store.js`
  - 通用 reducer、cursor 去重、history/live window 合并、搜索 / 过滤 / wrap / auto-scroll 视图状态。
- Create: `static/js/realtime_log_client.js`
  - WebSocket 连接、`after_seq` 重连、`snapshot_required` 重同步队列、HTTP events fallback。
- Create: `static/js/realtime_log_console.js`
  - 紧凑列式 console 渲染、复制 / 清空视图 / 空态 / 错误态 / 连接态。
- Modify: `static/js/registration_stream.js`
  - 改成注册页兼容 shim，复用共享 store contract，避免旧测试和旧调用点彻底失联。
- Create: `static/css/realtime_log_console.css`
  - 语义化主题变量、亮 / 暗主题日志级别文字色、共享 console shell / toolbar / dense rows。

### Registration integration

- Modify: `templates/index.html`
  - 加载共享 realtime console CSS / JS；把当前 `#console-log` 区域改成共享 console 挂点与共享 toolbar hook。
- Modify: `static/js/app.js`
  - 用 shared client/store/console 取代 `addLog(...)` 主路径，保留必要兼容包装；单任务 / 批量任务状态栏继续存在。
- Modify: `static/css/registration_workbench.css`
  - 让共享 console 填满右侧反馈区，维持更高日志面板高度。
- Modify: `tests_runtime/app_js_harness.py`
  - 先加载 shared JS，再加载 `registration_stream.js` 与 `app.js`。
- Modify: `tests/test_registration_page_assets.py`
  - 覆盖共享 console 接入、即时日志追加、不再依赖 legacy DOM append 的回归断言。

### Scheduled tasks integration

- Modify: `templates/scheduled_tasks.html`
  - 加载共享 realtime console CSS / JS；日志 modal 切换为共享 console markup。
- Modify: `static/js/scheduled_tasks.js`
  - 以 run snapshot + history chunk + run WebSocket 替换当前 offset polling 主链路，保留 chunk 仅用于历史加载。
- Modify: `tests/test_scheduled_tasks_routes.py`
  - 增加 run snapshot / events HTTP contract 覆盖。
- Modify: `tests/test_scheduled_tasks_page_assets.py`
  - 增加 run WebSocket / shared console / dense row / theme class / modal cleanup 回归。

### Shared tests and harnesses

- Modify: `tests/test_task_manager.py`
  - run stream snapshot / broadcast / replay / structured logs coverage。
- Create: `tests/test_realtime_stream_routes.py`
  - `/api/realtime-streams/task|batch|run` snapshot / events / WebSocket contract coverage。
- Modify: `tests/test_registration_stream_routes.py`
  - 旧 alias 路由的兼容 contract 覆盖。
- Modify: `tests/test_scheduler_engine.py`
  - run logger 结构化 entry、status/stream_closed 生命周期覆盖。
- Create: `tests/test_realtime_log_console_assets.py`
  - 通过 shared harness 固定共享 console 的搜索、过滤、wrap、auto-scroll、copy、clear、connection/empty/error state 行为。
- Modify: `tests/test_static_asset_versioning.py`
  - 共享 realtime console CSS / JS 在 registration 与 scheduled tasks 页面都必须带版本号。
- Create: `tests_runtime/realtime_log_harness.py`
  - 共享 JS store / client / console 的 Node harness，供 registration / scheduled assets 测试复用。

## Parallelization Notes

- **Track A（后端 contract）**：Task 1 → Task 3 必须串行，因为 run stream contract、API、scheduler emitters 共享同一个协议边界。
- **Track B（shared frontend runtime）**：Task 4 依赖 Task 1~2 的稳定 contract；Task 5 与 Task 6 都依赖 Task 4。
- **Track C（页面集成）**：Task 5（scheduled tasks）和 Task 6（registration）可并行，因为它们只共享 Task 4 产出的 shared JS/CSS，写集不同。
- 推荐执行顺序：一个 agent 负责 Task 1~3，另一个 agent 在 Task 4 完成后并行实现 Task 5 与 Task 6，再由主 agent 完成 Task 7 总验收。

### Task 1: 固化 task / batch / run 三类 stream 的结构化日志条目 contract

**Files:**
- Modify: `src/web/realtime_streams.py`
- Modify: `src/web/task_manager.py`
- Test: `tests/test_task_manager.py`

- [ ] **Step 1: 先写失败测试，锁定 run stream snapshot / log entry / stream_closed contract**

```python
# tests/test_task_manager.py

def test_run_stream_snapshot_uses_structured_log_entries():
    manager = TaskManager()
    run_id = 321

    manager.update_run_status(
        run_id,
        status="running",
        id=run_id,
        plan_id=12,
        plan_name="cleanup",
        task_type="cpa_cleanup",
        is_running=True,
        can_stop=True,
        log_version=4,
        last_log_at="2026-03-26T10:00:00+08:00",
    )
    manager.add_run_log(
        run_id,
        {
            "timestamp": "2026-03-26T10:00:00+08:00",
            "display_time": "10:00:00",
            "level": "INFO",
            "message": "cleanup runner start",
            "raw": "2026-03-26 10:00:00.123 [INFO] cleanup runner start",
            "source": "scheduler",
        },
    )

    snapshot = manager.build_run_stream_snapshot(run_id)
    assert snapshot["stream"] == "run:321"
    assert snapshot["kind"] == "snapshot"
    assert isinstance(snapshot["seq"], int)
    assert snapshot["payload"]["run"]["status"] == "running"
    assert snapshot["payload"]["run"]["id"] == 321
    assert snapshot["payload"]["run"]["plan_id"] == 12
    assert snapshot["payload"]["run"]["plan_name"] == "cleanup"
    assert snapshot["payload"]["run"]["task_type"] == "cpa_cleanup"
    assert snapshot["payload"]["run"]["is_running"] is True
    assert snapshot["payload"]["run"]["can_stop"] is True
    assert snapshot["payload"]["run"]["log_version"] == 4
    assert snapshot["payload"]["logs_tail"][0]["level"] == "INFO"
    assert snapshot["payload"]["logs_tail"][0]["message"] == "cleanup runner start"


def test_task_and_batch_stream_snapshots_also_use_structured_logs_tail():
    manager = TaskManager()
    manager.update_status("task-structured-1", "running")
    manager.add_log("task-structured-1", "proxy bootstrap ok")
    manager.init_batch("batch-structured-1", total=2)
    manager.add_batch_log("batch-structured-1", "batch proxy warmup")

    task_snapshot = manager.build_task_stream_snapshot("task-structured-1")
    batch_snapshot = manager.build_batch_stream_snapshot("batch-structured-1")
    task_events = manager.get_stream_events_after("task:task-structured-1", after_seq=0)
    batch_events = manager.get_stream_events_after("batch:batch-structured-1", after_seq=0)

    assert task_snapshot["payload"]["logs_tail"][0]["message"] == "proxy bootstrap ok"
    assert task_snapshot["payload"]["logs_tail"][0]["level"] == "INFO"
    assert task_events[-1]["payload"]["entry"]["message"] == "proxy bootstrap ok"
    assert task_events[-1]["payload"]["entry"]["seq"] == task_events[-1]["seq"]
    assert batch_snapshot["payload"]["logs_tail"][0]["message"] == "batch proxy warmup"
    assert batch_events[-1]["payload"]["entry"]["stream"] == batch_events[-1]["stream"]


def test_run_stream_close_appends_terminal_event():
    manager = TaskManager()
    run_id = 654

    manager.update_run_status(run_id, status="running")
    manager.close_run_stream(run_id, final_status="failed")

    events = manager.get_stream_events_after("run:654", after_seq=0)
    assert events[-1]["kind"] == "stream_closed"
    assert events[-1]["payload"]["final_status"] == "failed"
```

- [ ] **Step 2: 运行聚焦测试，确认当前实现缺少 run stream API**

Run: `timeout 60s pytest tests/test_task_manager.py::test_run_stream_snapshot_uses_structured_log_entries tests/test_task_manager.py::test_task_and_batch_stream_snapshots_also_use_structured_logs_tail tests/test_task_manager.py::test_run_stream_close_appends_terminal_event -q`
Expected: FAIL，提示 `TaskManager` 不存在 `update_run_status` / `build_run_stream_snapshot` / `close_run_stream`，或 task/batch 仍返回字符串 `logs_tail` / `payload.message` 而非结构化 `payload.entry`。

- [ ] **Step 3: 在 `realtime_streams.py` 和 `task_manager.py` 实现最小 run contract**

```python
# src/web/realtime_streams.py
STREAM_BUFFER_SIZE = 1000
LOG_TAIL_SIZE = 10


def run_stream_id(run_id: int) -> str:
    return f"run:{run_id}"


def build_log_entry(*, seq: int, stream: str, timestamp: str, level: str, message: str, raw: str, source: str) -> dict:
    return {
        "seq": seq,
        "stream": stream,
        "timestamp": timestamp,
        "display_time": timestamp[11:19],
        "level": level,
        "message": message,
        "raw": raw,
        "source": source,
    }

# src/web/task_manager.py
_run_status = {}
_run_progress = {}
_run_logs = defaultdict(list)


def update_run_status(self, run_id: int, *, status: str, **kwargs):
    ...


def add_run_log(self, run_id: int, entry: dict):
    ...


def add_log(self, task_uuid: str, log_message: str):
    # 统一构造成 structured entry，再由 event.payload = {"entry": ...}
    ...


def add_batch_log(self, batch_id: str, log_message: str):
    # 与 task 保持相同 contract
    ...


def build_run_stream_snapshot(self, run_id: int) -> dict:
    return {
        "stream": run_stream_id(run_id),
        "seq": self._stream_seq.get(run_stream_id(run_id), 0),
        "kind": "snapshot",
        "timestamp": utc_now().isoformat(),
        "payload": {"run": ..., "run_progress": ..., "logs_tail": ...},
    }
```

- [ ] **Step 4: 重新运行 TaskManager 聚焦测试，确认 structured snapshot / close event 通过**

Run: `timeout 60s pytest tests/test_task_manager.py::test_run_stream_snapshot_uses_structured_log_entries tests/test_task_manager.py::test_task_and_batch_stream_snapshots_also_use_structured_logs_tail tests/test_task_manager.py::test_run_stream_close_appends_terminal_event -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 1**

```bash
git add tests/test_task_manager.py src/web/realtime_streams.py src/web/task_manager.py
git commit -m "feat: add run stream contract to task manager"
```

### Task 2: 提供通用 realtime-streams REST / WebSocket 契约并保留 registration alias

**Files:**
- Create: `src/web/routes/realtime_streams.py`
- Modify: `src/web/routes/registration_streams.py`
- Modify: `src/web/routes/websocket.py`
- Modify: `src/web/routes/__init__.py`
- Test: `tests/test_realtime_stream_routes.py`
- Test: `tests/test_registration_stream_routes.py`

- [ ] **Step 1: 先写失败测试，固定 task/batch/run 的 snapshot/events/ws contract 与旧 alias 兼容行为**

```python
# tests/test_realtime_stream_routes.py

def test_run_realtime_stream_routes_and_websocket_contract(client):
    task_manager.update_run_status(777, status="running", plan_name="cleanup")
    task_manager.add_run_log(777, {
        "timestamp": "2026-03-26T10:00:00+08:00",
        "display_time": "10:00:00",
        "level": "INFO",
        "message": "hello",
        "raw": "2026-03-26 10:00:00.123 [INFO] hello",
        "source": "scheduler",
    })

    snapshot = client.get("/api/realtime-streams/run/777/snapshot")
    events = client.get("/api/realtime-streams/run/777/events?after_seq=0")
    assert snapshot.status_code == 200
    assert snapshot.json()["stream"] == "run:777"
    assert snapshot.json()["kind"] == "snapshot"
    assert events.json()["events"][-1]["kind"] == "log_appended"

    with client.websocket_connect("/api/ws/run/777?after_seq=0") as ws:
        payload = ws.receive_json()
    assert payload["stream"] == "run:777"


def test_task_and_batch_realtime_stream_routes_also_use_new_contract(client):
    task_manager.update_status("task-new-1", "running", email="demo@example.com")
    task_manager.add_log("task-new-1", "task-line-1")
    task_manager.init_batch("batch-new-1", total=3)
    task_manager.update_batch_status("batch-new-1", completed=1, success=1, failed=0)
    task_manager.add_batch_log("batch-new-1", "batch-line-1")

    task_snapshot = client.get("/api/realtime-streams/task/task-new-1/snapshot")
    task_events = client.get("/api/realtime-streams/task/task-new-1/events?after_seq=0")
    batch_snapshot = client.get("/api/realtime-streams/batch/batch-new-1/snapshot")
    batch_events = client.get("/api/realtime-streams/batch/batch-new-1/events?after_seq=0")

    assert task_snapshot.status_code == 200
    assert task_snapshot.json()["kind"] == "snapshot"
    assert task_snapshot.json()["stream"] == "task:task-new-1"
    assert task_events.json()["events"][-1]["kind"] == "log_appended"
    assert task_events.json()["events"][-1]["payload"]["entry"]["message"] == "task-line-1"
    assert task_snapshot.json()["payload"]["logs_tail"][0]["level"] == "INFO"
    assert batch_snapshot.status_code == 200
    assert batch_snapshot.json()["stream"] == "batch:batch-new-1"
    assert batch_snapshot.json()["payload"]["logs_tail"][0]["message"] == "batch-line-1"
    assert batch_events.json()["events"][-1]["stream"] == "batch:batch-new-1"
    assert batch_events.json()["events"][-1]["payload"]["entry"]["seq"] == batch_events.json()["events"][-1]["seq"]

    with client.websocket_connect("/api/ws/task/task-new-1?after_seq=0") as task_ws:
        task_payload = task_ws.receive_json()
    with client.websocket_connect("/api/ws/batch/batch-new-1?after_seq=0") as batch_ws:
        batch_payload = batch_ws.receive_json()

    assert task_payload["stream"] == "task:task-new-1"
    assert batch_payload["stream"] == "batch:batch-new-1"


def test_registration_stream_alias_routes_delegate_to_realtime_streams(client):
    task_manager.update_status("task-alias-1", "running")
    response = client.get("/api/registration/streams/task/task-alias-1/snapshot")
    assert response.status_code == 200
    assert response.json()["stream"] == "task:task-alias-1"
```

- [ ] **Step 2: 运行聚焦路由测试，确认当前缺少 `/api/realtime-streams/*` 和 run WebSocket**

Run: `timeout 60s pytest tests/test_realtime_stream_routes.py::test_run_realtime_stream_routes_and_websocket_contract tests/test_realtime_stream_routes.py::test_task_and_batch_realtime_stream_routes_also_use_new_contract tests/test_registration_stream_routes.py::test_registration_stream_routes_return_404_for_missing_streams -q`
Expected: FAIL，`/api/realtime-streams/run/777/snapshot` 返回 404，或 `/api/ws/run/777` 不存在，或 `task/batch` 仍返回旧 `payload.message + string logs_tail` 契约。

- [ ] **Step 3: 最小实现通用 router、legacy alias 委托和 run websocket replay**

```python
# src/web/routes/realtime_streams.py
router = APIRouter()

@router.get("/run/{run_id}/snapshot")
async def get_run_stream_snapshot(run_id: int):
    if not task_manager.run_stream_exists(run_id):
        raise HTTPException(status_code=404, detail="Run stream not found")
    return task_manager.build_run_stream_snapshot(run_id)

@router.get("/run/{run_id}/events")
async def get_run_stream_events(run_id: int, after_seq: int = Query(0, ge=0)):
    return {"stream": run_stream_id(run_id), "events": task_manager.get_stream_events_after(run_stream_id(run_id), after_seq)}

# src/web/routes/registration_streams.py
@router.get("/task/{task_uuid}/snapshot")
async def get_task_stream_snapshot(task_uuid: str):
    return await realtime_streams_routes.get_task_stream_snapshot(task_uuid)

# src/web/routes/websocket.py
@router.websocket("/ws/run/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: int):
    after_seq = int(websocket.query_params.get("after_seq", "0"))
    task_manager.register_run_websocket(run_id, websocket, mode="replaying", after_seq=after_seq)
    ...
```

- [ ] **Step 4: 重新运行 route / websocket 聚焦测试，确认新 contract 与旧 alias 同时成立**

Run: `timeout 60s pytest tests/test_realtime_stream_routes.py tests/test_registration_stream_routes.py -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 2**

```bash
git add tests/test_realtime_stream_routes.py tests/test_registration_stream_routes.py src/web/routes/realtime_streams.py src/web/routes/registration_streams.py src/web/routes/websocket.py src/web/routes/__init__.py
git commit -m "feat: add generic realtime stream routes and run websocket"
```

### Task 3: 让 scheduler run 写库时同步发实时事件，并补齐 run 生命周期状态

**Files:**
- Modify: `src/scheduler/run_logger.py`
- Modify: `src/scheduler/engine.py`
- Modify: `src/scheduler/runners/cleanup.py`
- Modify: `src/scheduler/runners/refill.py`
- Modify: `src/scheduler/runners/refresh.py`
- Test: `tests/test_scheduler_engine.py`
- Test: `tests/test_scheduled_tasks_routes.py`

- [ ] **Step 1: 先写失败测试，锁定 `append_run_log(...)` 的结构化实时 payload 与 run 终态事件**

```python
# tests/test_scheduler_engine.py

def test_append_run_log_emits_structured_realtime_entry(monkeypatch):
    emitted = {}

    def _fake_add_run_log(run_id, entry):
        emitted["run_id"] = run_id
        emitted["entry"] = entry
        return {
            "seq": 7,
            "stream": "run:9",
            "payload": {
                "entry": {
                    **entry,
                    "seq": 7,
                    "stream": "run:9",
                }
            },
        }

    monkeypatch.setattr(task_manager, "add_run_log", _fake_add_run_log)

    logged_at = datetime(2026, 3, 26, 10, 0, 0, 123000)
    assert run_logger.append_run_log(9, "hello", level="WARN", logged_at=logged_at) is True

    assert emitted["run_id"] == 9
    assert emitted["entry"]["level"] == "WARN"
    assert emitted["entry"]["display_time"] == "10:00:00"
    assert emitted["entry"]["raw"].endswith("[WARN] hello")
    returned = _fake_add_run_log(9, emitted["entry"])
    assert returned["payload"]["entry"]["seq"] == returned["seq"]
    assert returned["payload"]["entry"]["stream"] == returned["stream"]


def test_scheduler_engine_marks_stream_closed_on_failed_run(monkeypatch):
    closed = []
    monkeypatch.setattr(task_manager, "close_run_stream", lambda run_id, final_status: closed.append((run_id, final_status)))
    ...
    assert closed == [(run_id, "failed")]


def test_scheduler_engine_emits_stopping_and_success_statuses(monkeypatch):
    statuses = []
    monkeypatch.setattr(task_manager, "update_run_status", lambda run_id, **payload: statuses.append((run_id, payload["status"])))
    ...
    assert ("stopping" in [status for _, status in statuses])
    assert ("success" in [status for _, status in statuses])


def test_scheduler_engine_marks_cancelled_run_as_terminal_stream(monkeypatch):
    closed = []
    monkeypatch.setattr(task_manager, "close_run_stream", lambda run_id, final_status: closed.append(final_status))
    ...
    assert closed[-1] == "cancelled"
```

- [ ] **Step 2: 运行聚焦 scheduler 测试，确认当前不会发 realtime entry / stream_closed**

Run: `timeout 60s pytest tests/test_scheduler_engine.py::test_append_run_log_emits_structured_realtime_entry tests/test_scheduler_engine.py::test_scheduler_engine_marks_stream_closed_on_failed_run tests/test_scheduler_engine.py::test_scheduler_engine_emits_stopping_and_success_statuses tests/test_scheduler_engine.py::test_scheduler_engine_marks_cancelled_run_as_terminal_stream -q`
Expected: FAIL，`task_manager.add_run_log` / `update_run_status` / `close_run_stream` 未被调用，或 `stopping/success/cancelled` 分支未覆盖。

- [ ] **Step 3: 在 logger / engine 中补最小生命周期发射器**

```python
# src/scheduler/run_logger.py
from src.web.task_manager import task_manager
from src.web.realtime_streams import build_log_entry, run_stream_id


def append_run_log(...):
    actual_logged_at = logged_at or utc_now_naive()
    normalized_level = _normalize_run_log_level(level)
    raw = _format_run_log_line(message, level=normalized_level, logged_at=actual_logged_at)
    persisted = crud.append_scheduled_run_log(..., raw, logged_at=actual_logged_at)
    if persisted:
        event = task_manager.add_run_log(
            run_id,
            build_log_entry(
                seq=-1,  # 仅占位，真实 seq/stream 必须由 task_manager.add_run_log 覆盖
                stream=run_stream_id(run_id),
                timestamp=actual_logged_at.isoformat(),
                level=normalized_level,
                message=message,
                raw=raw,
                source="scheduler",
            ),
        )
        assert event["payload"]["entry"]["seq"] == event["seq"]
        assert event["payload"]["entry"]["stream"] == event["stream"]
    return persisted

# src/scheduler/engine.py

task_manager.update_run_status(run_id, status="running", plan_name=plan.name, ...)
...
task_manager.update_run_status(run_id, status="stopping", stop_requested_at=requested_at)
...
task_manager.update_run_status(run_id, status="success", summary=summary)
task_manager.close_run_stream(run_id, final_status="success")
...
task_manager.update_run_status(run_id, status="failed", error_message=str(exc))
task_manager.close_run_stream(run_id, final_status="failed")
...
task_manager.update_run_status(run_id, status="cancelled", error_message=USER_REQUESTED_STOP_ERROR_MESSAGE)
task_manager.close_run_stream(run_id, final_status="cancelled")
```

- [ ] **Step 4: 重新运行 scheduler 聚焦测试，确认 run logger 和终态事件通过**

Run: `timeout 60s pytest tests/test_scheduler_engine.py -q`
Expected: PASS，既有 logger 测试与新 realtime tests 同时通过。

- [ ] **Step 5: 提交 Task 3**

```bash
git add tests/test_scheduler_engine.py tests/test_scheduled_tasks_routes.py src/scheduler/run_logger.py src/scheduler/engine.py src/scheduler/runners/cleanup.py src/scheduler/runners/refill.py src/scheduler/runners/refresh.py
git commit -m "feat: emit realtime run events from scheduler"
```

### Task 4: 抽共享 realtime log store / client / console 与主题化高密度样式

**Files:**
- Create: `static/js/realtime_log_store.js`
- Create: `static/js/realtime_log_client.js`
- Create: `static/js/realtime_log_console.js`
- Modify: `static/js/registration_stream.js`
- Create: `static/css/realtime_log_console.css`
- Create: `tests/test_realtime_log_console_assets.py`
- Create: `tests_runtime/realtime_log_harness.py`
- Modify: `tests/test_static_asset_versioning.py`

- [ ] **Step 1: 先写失败 harness 测试，锁定 shared store / client / console contract**

```python
# tests/test_realtime_log_console_assets.py
from tests_runtime.realtime_log_harness import run_realtime_log_scenario

result = run_realtime_log_scenario("snapshot_required_resync")
assert result["cursor_after_snapshot"] == 9
assert result["visible_levels"] == ["INFO", "ERROR"]
assert result["last_rendered_text"].startswith("10:00:00")
assert result["theme_error_class"] == "realtime-log-level-error"
assert result["live_window_size"] == 500
assert result["resync_pending_replayed_in_order"] is True

search_result = run_realtime_log_scenario("search_and_level_filter")
assert search_result["visible_messages"] == ["proxy fallback failed"]

wrap_result = run_realtime_log_scenario("wrap_and_auto_scroll_toggle")
assert wrap_result["has_nowrap_class"] is True
assert wrap_result["auto_scroll_preserved_manual_position"] is True

copy_result = run_realtime_log_scenario("copy_and_clear_view")
assert copy_result["copied_text"].endswith("proxy fallback failed")
assert copy_result["clear_keeps_store_entries"] is True

state_result = run_realtime_log_scenario("connection_empty_error_states")
assert state_result["connection_text"] == "重连中"
assert state_result["empty_state_visible"] is True
assert state_result["error_state_visible"] is True

# tests/test_static_asset_versioning.py
_assert_versioned_asset(response.text, "/static/css/realtime_log_console.css")
_assert_versioned_asset(response.text, "/static/js/realtime_log_store.js")
_assert_versioned_asset(response.text, "/static/js/realtime_log_client.js")
_assert_versioned_asset(response.text, "/static/js/realtime_log_console.js")
```

- [ ] **Step 2: 运行聚焦 harness / versioning 测试，确认 shared assets 尚不存在**

Run: `timeout 60s pytest tests/test_static_asset_versioning.py -q`
Expected: FAIL，缺少 versioned asset 引用；`tests/test_realtime_log_console_assets.py` 也会因 shared JS/CSS/harness 尚不存在而失败。

- [ ] **Step 3: 实现共享 JS/CSS 模块与 registration shim**

```javascript
// static/js/realtime_log_store.js
(function () {
  function createState() {
    return {
      connection: { status: 'disconnected' },
      cursors: {},
      historyPrefix: [],
      liveWindow: [],
      filters: { search: '', level: '', wrap: true, autoScroll: true },
      context: { task: null, batch: null, run: null, taskProgress: null, runProgress: null },
    };
  }

  function reduceHistoryChunk(state, chunkText) {
    // 解析 chunk -> history_entries -> 与 live_window 去重拼接
  }

  function reduceEvent(state, event) {
    // 处理 snapshot / log_appended / *_status_changed / *_progress_updated / stream_closed
  }

  window.realtimeLogStore = { createState, reduceEvent, reduceHistoryChunk };
})();

// static/js/realtime_log_client.js
window.realtimeLogClient = { createStreamClient };

// static/js/realtime_log_console.js
window.realtimeLogConsole = { mountRealtimeLogConsole, renderRealtimeLogConsole };

// static/js/registration_stream.js
window.registrationStream = {
  reduce(state, event) {
    return window.realtimeLogStore.reduceEvent(state, event);
  },
};
```

```css
/* static/css/realtime_log_console.css */
:root {
  --log-console-bg: #f8fafc;
  --log-console-border: rgba(148, 163, 184, 0.25);
  --log-info-fg: #0f3d91;
  --log-warn-fg: #9a5b00;
  --log-error-fg: #a11d2d;
}
[data-theme="dark"] {
  --log-console-bg: #0f172a;
  --log-info-fg: #7dd3fc;
  --log-warn-fg: #fbbf24;
  --log-error-fg: #fca5a5;
}
.realtime-log-line { display: grid; grid-template-columns: 72px 56px minmax(0, 1fr); }
```

- [ ] **Step 4: 重新运行 shared asset / harness 测试，确认 shared runtime contract 成立**

Run: `timeout 60s pytest tests/test_realtime_log_console_assets.py tests/test_static_asset_versioning.py -q`
Expected: PASS（若 harness 已单列测试，也一并 PASS，并验证搜索 / 级别过滤 / wrap / auto-scroll / copy / clear-view / connection/empty/error state / 500 条 ring buffer / `resync_pending_queue` 有序合并）。

- [ ] **Step 5: 提交 Task 4**

```bash
git add tests/test_realtime_log_console_assets.py tests/test_static_asset_versioning.py tests_runtime/realtime_log_harness.py static/js/realtime_log_store.js static/js/realtime_log_client.js static/js/realtime_log_console.js static/js/registration_stream.js static/css/realtime_log_console.css
git commit -m "feat: add shared realtime log runtime and console styles"
```

### Task 5: 让 scheduled tasks 日志 modal 切到 shared console + run WebSocket 主链路

**Files:**
- Modify: `templates/scheduled_tasks.html`
- Modify: `static/js/scheduled_tasks.js`
- Modify: `tests/test_scheduled_tasks_routes.py`
- Modify: `tests/test_scheduled_tasks_page_assets.py`

- [ ] **Step 1: 先写失败页面测试，锁定 scheduled tasks 的 shared console / run ws / history merge 行为**

```python
# tests/test_scheduled_tasks_page_assets.py
result = run_scheduled_tasks_log_console_scenario("run_ws_live_append")
assert result["ws_url"] == "ws://localhost/api/ws/run/123?after_seq=0"
assert result["console_has_shared_class"] is True
assert result["last_line_level_class"] == "realtime-log-level-error"
assert result["history_tail_deduped"] is True
assert result["teardown_closed_ws"] is True
assert result["teardown_stopped_fallback"] is True

# tests/test_scheduled_tasks_routes.py
response = client.get("/api/realtime-streams/run/123/snapshot")
assert response.status_code in {200, 404}
```

- [ ] **Step 2: 运行 scheduled tasks 聚焦测试，确认当前仍使用 offset polling 主链路**

Run: `timeout 60s pytest tests/test_scheduled_tasks_page_assets.py::test_scheduled_tasks_run_log_loading_drains_chunks_even_when_run_is_finished tests/test_scheduled_tasks_page_assets.py::test_scheduled_tasks_run_log_polling_is_single_flight -q`
Expected: FAIL（或需要更新断言），因为页面仍以 polling 为主、shared console class 不存在。

- [ ] **Step 3: 最小改造 scheduled tasks 页面为 history chunk + snapshot + run ws**

```html
<!-- templates/scheduled_tasks.html -->
{% block head_extra %}
<link rel="stylesheet" href="/static/css/realtime_log_console.css?v={{ static_version }}">
{% endblock %}
{% block page_scripts %}
<script src="{{ '/static/js/realtime_log_store.js?v=' ~ static_version }}"></script>
<script src="{{ '/static/js/realtime_log_client.js?v=' ~ static_version }}"></script>
<script src="{{ '/static/js/realtime_log_console.js?v=' ~ static_version }}"></script>
<script src="{{ '/static/js/scheduled_tasks.js?v=' ~ static_version }}"></script>
{% endblock %}
```

```javascript
// static/js/scheduled_tasks.js
let runLogStore = window.realtimeLogStore.createState();
const runLogConsole = window.realtimeLogConsole.mountRealtimeLogConsole({...});
const runLogClient = window.realtimeLogClient.createStreamClient({
  streamType: 'run',
  streamId: runId,
  snapshotUrl: `/api/realtime-streams/run/${runId}/snapshot`,
  eventsUrl: `/api/realtime-streams/run/${runId}/events`,
  wsUrl: `${protocol}//${location.host}/api/ws/run/${runId}`,
});

async function openScheduledRunLog(runId) {
  const historyChunk = await api.get(`/scheduled-runs/${runId}/logs?offset=${Math.max(0, latestOffset - 65536)}`);
  const nextStateFromHistory = window.realtimeLogStore.reduceHistoryChunk(runLogStore, historyChunk.chunk);
  runLogStore = nextStateFromHistory;
  runLogConsole.render(runLogStore);
  await runLogClient.bootstrap();
}
```

- [ ] **Step 4: 重新运行 scheduled tasks 聚焦测试，确认 run WebSocket、dense console、历史去重均成立**

Run: `timeout 60s pytest tests/test_scheduled_tasks_page_assets.py tests/test_scheduled_tasks_routes.py -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 5**

```bash
git add templates/scheduled_tasks.html static/js/scheduled_tasks.js tests/test_scheduled_tasks_routes.py tests/test_scheduled_tasks_page_assets.py
git commit -m "feat: migrate scheduled run logs to shared realtime console"
```

### Task 6: 让 registration workbench 日志彻底切到 shared console，并移除日志直写 DOM 主链路

**Files:**
- Modify: `templates/index.html`
- Modify: `static/js/app.js`
- Modify: `static/css/registration_workbench.css`
- Modify: `tests_runtime/app_js_harness.py`
- Modify: `tests/test_registration_page_assets.py`

- [ ] **Step 1: 先写失败测试，固定 registration 页 shared console 接入与“live 事件立即显示”行为**

```python
# tests/test_registration_page_assets.py
result = run_app_js_scenario("shared_console_single_task_live_append")
assert result["console_has_shared_class"] is True
assert result["rendered_log_count"] == 2
assert result["last_line_level_class"] == "realtime-log-level-info"
assert result["legacy_direct_append_path_used"] is False
assert result["teardown_closed_ws"] is True
assert result["teardown_stopped_fallback"] is True

script = Path("static/js/app.js").read_text(encoding="utf-8")
assert "window.realtimeLogClient.createStreamClient" in script
assert "appendLogLine(getLogType(message)" not in script
```

- [ ] **Step 2: 运行 registration 聚焦测试，确认当前仍依赖 legacy `addLog` / `appendLogLine`**

Run: `timeout 60s pytest tests/test_registration_page_assets.py::test_realtime_log_appended_event_updates_console_without_waiting_for_task_detail_refresh tests/test_registration_page_assets.py::test_app_js_task_realtime_fallback_prefers_stream_events_over_legacy_logs_endpoint -q`
Expected: FAIL（或断言需要更新），因为脚本还没有 shared client / shared console。

- [ ] **Step 3: 最小改造 registration 页面使用 shared console，同时保留状态卡逻辑**

```html
<!-- templates/index.html -->
{% block head_extra %}
<link rel="stylesheet" href="/static/css/registration_workbench.css?v={{ static_version }}">
<link rel="stylesheet" href="/static/css/realtime_log_console.css?v={{ static_version }}">
{% endblock %}
{% block page_scripts %}
<script src="{{ '/static/js/utils.js?v=' ~ static_version }}"></script>
<script src="{{ '/static/js/realtime_log_store.js?v=' ~ static_version }}"></script>
<script src="{{ '/static/js/realtime_log_client.js?v=' ~ static_version }}"></script>
<script src="{{ '/static/js/realtime_log_console.js?v=' ~ static_version }}"></script>
<script src="{{ '/static/js/registration_stream.js?v=' ~ static_version }}"></script>
<script src="{{ '/static/js/app.js?v=' ~ static_version }}"></script>
{% endblock %}
```

```javascript
// static/js/app.js
const registrationLogStore = window.realtimeLogStore.createState();
const registrationConsole = window.realtimeLogConsole.mountRealtimeLogConsole({
  root: document.getElementById('console-log'),
  toolbar: {...},
});

function reduceRegistrationStream(event) {
  registrationStreamState = window.realtimeLogStore.reduceEvent(registrationStreamState, event);
  registrationConsole.render(registrationStreamState);
  syncRegistrationStatusPanels(registrationStreamState, event);
}

function addLog(type, message) {
  return reduceRegistrationStream({
    kind: 'log_appended',
    stream: activeTaskUuid ? `task:${activeTaskUuid}` : 'task:local',
    seq: Date.now(),
    payload: { entry: buildLocalFallbackEntry(type, message) },
    meta: { local: true },
  });
}
```

- [ ] **Step 4: 重新运行 registration 聚焦测试，确认 live 日志即时显示、共享 console 生效、legacy 直写退居兼容层**

Run: `timeout 60s pytest tests/test_registration_page_assets.py -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 6**

```bash
git add templates/index.html static/js/app.js static/css/registration_workbench.css tests_runtime/app_js_harness.py tests/test_registration_page_assets.py
git commit -m "feat: migrate registration workbench to shared realtime console"
```

### Task 7: 兼容层清理、全链路回归与最终验收

**Files:**
- Modify: `src/web/routes/registration_streams.py`
- Modify: `static/js/scheduled_tasks.js`
- Modify: `static/js/app.js`
- Modify: `tests/test_realtime_stream_routes.py`
- Modify: `tests/test_registration_stream_routes.py`
- Modify: `tests/test_static_asset_versioning.py`

- [ ] **Step 1: 写最后一批失败回归测试，锁定兼容 alias、版本化资产和重同步边界**

```python
# tests/test_realtime_stream_routes.py

def test_snapshot_required_keeps_connection_and_replays_pending_after_snapshot():
    ...
    assert payload["kind"] == "snapshot_required"
    assert follow_up["seq"] > snapshot_seq

# tests/test_static_asset_versioning.py
_assert_versioned_asset(response.text, "/static/js/realtime_log_store.js")
_assert_versioned_asset(response.text, "/static/js/realtime_log_client.js")
_assert_versioned_asset(response.text, "/static/js/realtime_log_console.js")
_assert_versioned_asset(response.text, "/static/css/realtime_log_console.css")
```

- [ ] **Step 2: 运行最终聚焦回归矩阵，确认仍有待清理的兼容分支**

Run: `timeout 60s pytest tests/test_realtime_stream_routes.py tests/test_registration_stream_routes.py tests/test_static_asset_versioning.py -q`
Expected: FAIL（如果还有旧 alias / 版本化 / 重同步边界未对齐）。

- [ ] **Step 3: 清理废弃主路径，只保留必要兼容层，并补最终注释 / 文档说明**

```python
# src/web/routes/registration_streams.py
# 保留 alias，但所有实现委托到 realtime_streams router helper，避免重复维护。

# static/js/scheduled_tasks.js / static/js/app.js
// 删除以 offset polling / addLog DOM append 作为主链路的分支。
// 保留历史 chunk 加载和 store 未初始化时的最小兜底，不再默认走 legacy polling。
```

- [ ] **Step 4: 运行最终验收矩阵并记录结果**

Run:
- `timeout 60s pytest tests/test_task_manager.py tests/test_realtime_stream_routes.py tests/test_registration_stream_routes.py -q`
- `timeout 60s pytest tests/test_scheduler_engine.py tests/test_scheduled_tasks_routes.py -q`
- `timeout 60s pytest tests/test_registration_page_assets.py tests/test_scheduled_tasks_page_assets.py tests/test_static_asset_versioning.py -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交 Task 7**

```bash
git add src/web/routes/registration_streams.py static/js/app.js static/js/scheduled_tasks.js tests/test_realtime_stream_routes.py tests/test_registration_stream_routes.py tests/test_static_asset_versioning.py
git commit -m "refactor: finalize unified realtime log sync rollout"
```
