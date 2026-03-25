# Dashboard and Registration Realtime Event Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为首页和注册工作台落地现代数据看板样式，并用统一实时事件流替换当前分裂的任务状态 / 步骤 / 日志 / 批量统计更新链路。

**Architecture:** 在现有 FastAPI + Jinja2 + vanilla JS 架构上扩展 `TaskManager` 为 stream snapshot + seq 增量事件中枢，新增注册 stream REST 接口和支持 `after_seq` 的 WebSocket 补发协议。前端注册页切换为 reducer 驱动的单状态树，Dashboard 与 Registration Workbench 分别使用独立页面样式文件完成视觉升级，同时保留数据库作为历史持久化来源而非实时显示来源。

**Tech Stack:** FastAPI、Jinja2、vanilla JS、WebSocket、pytest、FastAPI TestClient、Node JS harness、SQLite/SQLAlchemy。

---

## Spec Reference

- 设计文档：`docs/superpowers/specs/2026-03-25-dashboard-and-registration-realtime-event-stream-design.md`

## File Structure

### Realtime backend core

- Create: `src/web/realtime_streams.py`
  - 统一定义 stream id、event envelope、snapshot/error payload 辅助函数。
- Modify: `src/web/task_manager.py`
  - 维护 `seq`、事件缓冲、snapshot 构建、增量查询、stream close 逻辑。
- Create: `src/web/routes/registration_streams.py`
  - 暴露 task/batch snapshot 与增量 events REST 接口。
- Modify: `src/web/routes/websocket.py`
  - 为 task/batch WebSocket 增加 `after_seq` 回放、snapshot-required 分支、统一事件格式。
- Modify: `src/web/routes/__init__.py`
  - 注册新的 registration stream router。

### Registration runtime emitters

- Modify: `src/application/registration_service.py`
  - 在任务生命周期边界发出 `task_status_changed` 与 `stream_closed`。
- Modify: `src/application/batch_registration_service.py`
  - 在批量进度更新时发出 `batch_progress_updated` 与 `stream_closed`。
- Modify: `src/core/pipeline/context.py`
  - 为 pipeline 传递轻量 step progress hook 留出上下文字段或 metadata 约定。
- Modify: `src/core/pipeline/runner.py`
  - 在 step 开始 / 结束 / 失败时同步刷新 task step snapshot 与当前步骤事件。

### Registration frontend

- Create: `static/js/registration_stream.js`
  - reducer、snapshot 初始化、seq 去重、WebSocket / REST fallback 管理。
- Modify: `static/js/app.js`
  - 从“多通道直改 DOM”改为“订阅 store + render panels”。
- Modify: `templates/index.html`
  - 重组为 1/3 配置区 + 2/3 反馈区，并接入新的 panel hook id。
- Create: `static/css/registration_workbench.css`
  - 工作台专属布局、panel、log console、空态与连接态样式。

### Dashboard frontend

- Modify: `templates/dashboard.html`
  - 输出新的 hero / metrics / activity / quick actions 骨架。
- Modify: `static/js/dashboard.js`
  - 渲染 Hero、指标卡、活动列表、健康概览的新版组件结构。
- Create: `static/css/dashboard_page.css`
  - Dashboard 专属视觉层，避免把所有页面样式继续塞进 `style.css`。

### Tests and harnesses

- Modify: `tests/test_task_manager.py`
- Create: `tests/test_registration_stream_routes.py`
- Modify: `tests/test_pipeline_runner.py`
- Modify: `tests/test_registration_service.py`
- Modify: `tests/test_batch_registration_service.py`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests/test_dashboard_page_assets.py`
- Modify: `tests/test_static_asset_versioning.py`
- Modify: `tests_runtime/app_js_harness.py`
- Create: `tests_runtime/dashboard_js_harness.py`

## Parallelization Notes

- **Track A（后端实时流）**：Task 1 → Task 4 必须串行。
- **Track B（Registration 前端）**：Task 5 依赖 Task 1~4 完成。
- **Track C（Dashboard 视觉）**：Task 7 只依赖共享样式入口约定，可在 Task 5 开始后并行执行，因为它使用独立 `dashboard_page.css`，不与 `registration_workbench.css` 产生写冲突。
- 如果使用 subagent-driven-development，优先让一个 agent 负责 Track A，另一个 agent 在 Task 5 开始后并行处理 Task 7。

### Task 1: 建立 stream 事件原语与 TaskManager 缓冲层

**Files:**
- Create: `src/web/realtime_streams.py`
- Modify: `src/web/task_manager.py`
- Test: `tests/test_task_manager.py`

- [ ] **Step 1: 写失败测试，锁定 task stream 的 seq / snapshot / 增量回放契约**

```python
# tests/test_task_manager.py
@pytest.mark.anyio
async def test_task_manager_builds_snapshot_and_incremental_events():
    manager = TaskManager()
    manager.set_loop(asyncio.get_running_loop())

    manager.update_status("task-live-1", "running", email="demo@example.com")
    manager.set_task_steps(
        "task-live-1",
        [{"step_key": "create_email", "status": "running", "duration_ms": 12}],
    )
    manager.add_log("task-live-1", "[12:00:00] create email")

    snapshot = manager.build_task_stream_snapshot("task-live-1")
    events = manager.get_stream_events_after("task:task-live-1", after_seq=0)

    assert snapshot["kind"] == "snapshot"
    assert snapshot["payload"]["task"]["status"] == "running"
    assert snapshot["payload"]["current_step"]["step_key"] == "create_email"
    assert [item["seq"] for item in events] == [1, 2, 3]
    assert events[-1]["payload"]["message"] == "[12:00:00] create email"
```

- [ ] **Step 2: 运行测试，确认当前实现确实缺少 stream API**

Run: `timeout 60s pytest tests/test_task_manager.py::test_task_manager_builds_snapshot_and_incremental_events -q`
Expected: FAIL，报 `AttributeError`（如 `build_task_stream_snapshot` / `get_stream_events_after` 不存在）。

- [ ] **Step 3: 用最小实现补齐 stream helper 与 TaskManager 内存结构**

```python
# src/web/realtime_streams.py
from collections import deque

STREAM_BUFFER_SIZE = 1000

def task_stream_id(task_uuid: str) -> str:
    return f"task:{task_uuid}"

def batch_stream_id(batch_id: str) -> str:
    return f"batch:{batch_id}"

# src/web/task_manager.py
self._stream_seq = defaultdict(int)
self._stream_events = defaultdict(lambda: deque(maxlen=STREAM_BUFFER_SIZE))

def append_stream_event(self, stream_id: str, kind: str, payload: dict) -> dict:
    self._stream_seq[stream_id] += 1
    event = {
        "seq": self._stream_seq[stream_id],
        "stream": stream_id,
        "kind": kind,
        "timestamp": utc_now().isoformat(),
        "payload": payload,
    }
    self._stream_events[stream_id].append(event)
    return event
```

- [ ] **Step 4: 再跑同一条测试，确认 seq、snapshot、事件缓冲契约成立**

Run: `timeout 60s pytest tests/test_task_manager.py::test_task_manager_builds_snapshot_and_incremental_events -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 1**

```bash
git add tests/test_task_manager.py src/web/realtime_streams.py src/web/task_manager.py
git commit -m "feat: add registration stream event primitives"
```

### Task 2: 提供 task/batch snapshot 与增量 events REST 接口

**Files:**
- Create: `src/web/routes/registration_streams.py`
- Modify: `src/web/routes/__init__.py`
- Modify: `src/web/task_manager.py`
- Test: `tests/test_registration_stream_routes.py`

- [ ] **Step 1: 写失败测试，固定 task/batch snapshot/events 路由 contract**

```python
# tests/test_registration_stream_routes.py
from fastapi.testclient import TestClient
from src.web.app import create_app
from src.web.task_manager import task_manager


def test_task_and_batch_stream_routes_return_expected_contract():
    app = create_app()
    task_manager.update_status("task-route-1", "running")
    task_manager.add_log("task-route-1", "line-1")
    task_manager.init_batch("batch-route-1", total=5)
    task_manager.update_batch_status("batch-route-1", completed=2, success=1, failed=1)
    task_manager.add_batch_log("batch-route-1", "batch-line-1")

    with TestClient(app) as client:
        task_snapshot = client.get("/api/registration/streams/task/task-route-1/snapshot")
        task_events = client.get("/api/registration/streams/task/task-route-1/events?after_seq=0")
        batch_snapshot = client.get("/api/registration/streams/batch/batch-route-1/snapshot")
        batch_events = client.get("/api/registration/streams/batch/batch-route-1/events?after_seq=0")

    assert task_snapshot.status_code == 200
    assert task_snapshot.json()["stream"] == "task:task-route-1"
    assert task_events.status_code == 200
    assert batch_snapshot.status_code == 200
    assert batch_snapshot.json()["stream"] == "batch:batch-route-1"
    assert batch_events.status_code == 200
    assert batch_events.json()["events"][-1]["kind"] in {"batch_progress_updated", "log_appended"}
```

- [ ] **Step 2: 运行测试，确认当前返回 404**

Run: `timeout 60s pytest tests/test_registration_stream_routes.py::test_task_and_batch_stream_routes_return_expected_contract -q`
Expected: FAIL，`404 != 200`。

- [ ] **Step 3: 新增 router 并接入 API 总路由**

```python
# src/web/routes/registration_streams.py
router = APIRouter()

@router.get("/task/{task_uuid}/snapshot")
async def get_task_stream_snapshot(task_uuid: str):
    return task_manager.build_task_stream_snapshot(task_uuid)

@router.get("/task/{task_uuid}/events")
async def get_task_stream_events(task_uuid: str, after_seq: int = Query(0, ge=0)):
    return {
        "stream": f"task:{task_uuid}",
        "events": task_manager.get_stream_events_after(f"task:{task_uuid}", after_seq=after_seq),
    }

@router.get("/batch/{batch_id}/snapshot")
async def get_batch_stream_snapshot(batch_id: str):
    return task_manager.build_batch_stream_snapshot(batch_id)

@router.get("/batch/{batch_id}/events")
async def get_batch_stream_events(batch_id: str, after_seq: int = Query(0, ge=0)):
    return {
        "stream": f"batch:{batch_id}",
        "events": task_manager.get_stream_events_after(f"batch:{batch_id}", after_seq=after_seq),
    }
```

- [ ] **Step 4: 再跑 route 测试，确认 snapshot / events 接口可用**

Run: `timeout 60s pytest tests/test_registration_stream_routes.py::test_task_and_batch_stream_routes_return_expected_contract -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 2**

```bash
git add tests/test_registration_stream_routes.py src/web/routes/registration_streams.py src/web/routes/__init__.py src/web/task_manager.py
git commit -m "feat: add registration stream snapshot routes"
```

### Task 3: 升级 WebSocket，支持 after_seq 回放与 snapshot-required 恢复分支

**Files:**
- Modify: `src/web/routes/websocket.py`
- Modify: `src/web/task_manager.py`
- Test: `tests/test_registration_stream_routes.py`

- [ ] **Step 1: 写失败测试，固定 task/batch WebSocket replay 语义**

```python
# tests/test_registration_stream_routes.py
from fastapi.testclient import TestClient
from src.web.app import create_app
from src.web.task_manager import task_manager


def test_task_and_batch_websocket_replay_missing_events_after_after_seq():
    app = create_app()
    task_manager.update_status("task-ws-1", "running")
    task_manager.add_log("task-ws-1", "line-1")
    task_manager.add_log("task-ws-1", "line-2")
    task_manager.init_batch("batch-ws-1", total=3)
    task_manager.add_batch_log("batch-ws-1", "batch-line-1")
    task_manager.add_batch_log("batch-ws-1", "batch-line-2")

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws/task/task-ws-1?after_seq=1") as task_ws:
            task_replay = task_ws.receive_json()
        with client.websocket_connect("/api/ws/batch/batch-ws-1?after_seq=1") as batch_ws:
            batch_replay = batch_ws.receive_json()

    assert task_replay["seq"] == 2
    assert task_replay["kind"] == "log_appended"
    assert batch_replay["seq"] == 2
    assert batch_replay["stream"] == "batch:batch-ws-1"
```

- [ ] **Step 2: 运行测试，确认当前 WebSocket 仍是旧的 log/status 协议**

Run: `timeout 60s pytest tests/test_registration_stream_routes.py::test_task_and_batch_websocket_replay_missing_events_after_after_seq -q`
Expected: FAIL，收到旧格式消息或连接报错。

- [ ] **Step 3: 改造 WebSocket 路由与 TaskManager 增量读取逻辑**

```python
# src/web/routes/websocket.py
after_seq = int(websocket.query_params.get("after_seq", "0"))
replay = task_manager.get_stream_events_after(task_stream_id(task_uuid), after_seq=after_seq)
for event in replay:
    await websocket.send_json(event)

batch_after_seq = int(websocket.query_params.get("after_seq", "0"))
batch_replay = task_manager.get_stream_events_after(batch_stream_id(batch_id), after_seq=batch_after_seq)
for event in batch_replay:
    await websocket.send_json(event)

# 若 after_seq 已过期（task / batch 都要走这个分支）
await websocket.send_json({
    "stream": task_stream_id(task_uuid),
    "kind": "snapshot_required",
    "payload": {"reason": "after_seq_expired"},
})
```

- [ ] **Step 4: 再跑 WebSocket replay 测试，并补一条 snapshot-required 测试**

Run: `timeout 60s pytest tests/test_registration_stream_routes.py -k 'task_and_batch_websocket_replay or snapshot_required' -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 3**

```bash
git add tests/test_registration_stream_routes.py src/web/routes/websocket.py src/web/task_manager.py
git commit -m "feat: support websocket stream replay"
```

### Task 4: 让 registration runtime 发出当前步骤与批量进度事件

**Files:**
- Modify: `src/application/registration_service.py`
- Modify: `src/application/batch_registration_service.py`
- Modify: `src/core/pipeline/context.py`
- Modify: `src/core/pipeline/runner.py`
- Modify: `tests/test_pipeline_runner.py`
- Modify: `tests/test_registration_service.py`
- Modify: `tests/test_batch_registration_service.py`

- [ ] **Step 1: 写失败测试，固定 pipeline step hook 会同步刷新 current_step**

```python
# tests/test_pipeline_runner.py
def test_runner_emits_current_step_snapshot(fake_db):
    emitted = []

    pipeline = PipelineDefinition(
        pipeline_key="demo",
        steps=[StepDefinition("create_email", lambda ctx: {"email": "a@example.com"})],
    )
    task_uuid = "task-step-live"
    crud.create_registration_task(fake_db, task_uuid=task_uuid)
    ctx = PipelineContext(
        task_uuid=task_uuid,
        pipeline_key="demo",
        metadata={"task_step_callback": lambda payload: emitted.append(payload)},
    )

    PipelineRunner(fake_db).run(pipeline, ctx)

    assert emitted[0]["current_step"]["step_key"] == "create_email"
    assert emitted[-1]["steps"][-1]["status"] == "completed"
```

- [ ] **Step 2: 运行测试，确认当前 runner 不会发任何 step snapshot**

Run: `timeout 60s pytest tests/test_pipeline_runner.py::test_runner_emits_current_step_snapshot -q`
Expected: FAIL，`emitted` 为空。

- [ ] **Step 3: 最小实现 pipeline / service / batch emitter**

```python
# src/core/pipeline/runner.py
callback = ctx.metadata.get("task_step_callback")
if callback:
    callback({
        "current_step": {"step_key": step.step_key, "status": "running"},
        "steps": [...],
    })

# src/application/registration_service.py
self.task_manager.set_task_steps(task_uuid, payload["steps"])
self.task_manager.update_status(task_uuid, "running", current_step_key=payload["current_step"]["step_key"])
# completed / failed / cancelled 分支都要显式 close stream
self.task_manager.close_task_stream(task_uuid, final_status=result.task.status)

# src/application/batch_registration_service.py
self.task_manager.update_batch_status(
    batch_id,
    total=state["total"],
    completed=state["completed"],
    success=state["success"],
    failed=state["failed"],
    finished=state["finished"],
)
if state["finished"]:
    self.task_manager.close_batch_stream(batch_id, final_status=state.get("status", "completed"))
```

- [ ] **Step 4: 运行 pipeline / registration / batch 三组测试，确认事件发射器接通**

Run: `timeout 60s pytest tests/test_pipeline_runner.py tests/test_registration_service.py tests/test_batch_registration_service.py -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 4**

```bash
git add tests/test_pipeline_runner.py tests/test_registration_service.py tests/test_batch_registration_service.py src/core/pipeline/context.py src/core/pipeline/runner.py src/application/registration_service.py src/application/batch_registration_service.py
git commit -m "feat: emit registration step and batch progress streams"
```

### Task 5: 引入 registration realtime store，并让前端按 seq reducer 驱动渲染

**Files:**
- Create: `static/js/registration_stream.js`
- Modify: `static/js/app.js`
- Modify: `tests_runtime/app_js_harness.py`
- Modify: `tests/test_registration_page_assets.py`

- [ ] **Step 1: 写失败测试，固定 snapshot 初始化、seq 去重、batch progress 更新 contract**

```python
# tests/test_registration_page_assets.py
def test_registration_realtime_store_reduces_snapshot_and_tracks_connection_state():
    result = run_app_js_scenario("realtime_store_seq_dedup")
    assert result["current_step_key"] == "submit_login_email"
    assert result["batch_success"] == "3"
    assert result["log_count"] == 2
    assert result["connection_status"] == "polling"
```

- [ ] **Step 2: 运行测试，确认当前 harness 场景不存在**

Run: `timeout 60s pytest tests/test_registration_page_assets.py::test_registration_realtime_store_reduces_snapshot_and_tracks_connection_state -q`
Expected: FAIL，提示 scenario unknown 或 reducer hook 缺失。

- [ ] **Step 3: 新建 realtime store 模块，扩展 JS harness 场景，并让 app.js 改为消费 store**

```javascript
// static/js/registration_stream.js
(function () {
  function reduce(state, event) {
    if (!event || typeof event.seq !== 'number' || event.seq <= state.lastSeq) {
      return state;
    }
    switch (event.kind) {
      case 'snapshot':
        return { ...state, ...event.payload, connection: { status: 'connected' }, lastSeq: event.seq };
      case 'task_step_updated':
        return { ...state, currentStep: event.payload.current_step, steps: event.payload.steps, lastSeq: event.seq };
      case 'batch_progress_updated':
        return { ...state, batch: { ...state.batch, ...event.payload.batch }, lastSeq: event.seq };
      case 'log_appended':
        return { ...state, logs: [...state.logs, event.payload], lastSeq: event.seq };
      case 'connection_state_changed':
        return { ...state, connection: { status: event.payload.status }, lastSeq: event.seq };
      default:
        return { ...state, lastSeq: event.seq };
    }
  }

  window.registrationStream = { reduce };
})();

// tests_runtime/app_js_harness.py
case 'realtime_store_seq_dedup': {
  const events = [
    { seq: 1, kind: 'snapshot', payload: { currentStep: { step_key: 'submit_login_email' }, batch: { success: 1 }, logs: [] } },
    { seq: 2, kind: 'log_appended', payload: { message: 'line-1' } },
    { seq: 2, kind: 'log_appended', payload: { message: 'line-1-duplicate' } },
    { seq: 3, kind: 'batch_progress_updated', payload: { batch: { success: 3 } } },
    { seq: 4, kind: 'connection_state_changed', payload: { status: 'polling' } },
    { seq: 5, kind: 'log_appended', payload: { message: 'line-2' } },
  ];
  // 逐条喂给 window.registrationStream.reduce，并返回 current_step_key / batch_success / log_count / connection_status
}
```

同时在 `static/js/app.js` 里把 WebSocket 断开、重连、fallback 轮询切换统一转成 `connection_state_changed` 事件，再由 `registration-stream-status` 面板渲染 `connected / reconnecting / polling` 文案。

- [ ] **Step 4: 运行 JS harness 测试，确认 reducer / 去重 / batch 渲染全绿**

Run: `timeout 60s pytest tests/test_registration_page_assets.py -k 'realtime_store or single_task_step_refresh or unlimited_progress' -q`
Expected: PASS，并且日志区连接态文案会随着 `connected / reconnecting / polling` 切换。

- [ ] **Step 5: 提交 Task 5**

```bash
git add tests/test_registration_page_assets.py tests_runtime/app_js_harness.py static/js/registration_stream.js static/js/app.js
git commit -m "feat: add registration realtime store"
```

### Task 6: 重做注册工作台布局与反馈面板（1/3 配置 + 2/3 反馈）

**Files:**
- Modify: `templates/index.html`
- Create: `static/css/registration_workbench.css`
- Modify: `static/js/app.js`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests/test_static_asset_versioning.py`

- [ ] **Step 1: 写失败测试，固定新布局 hook 与新静态资源引用**

```python
# tests/test_registration_page_assets.py
def test_registration_template_contains_realtime_feedback_panels():
    template = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'id="registration-config-panel"' in template
    assert 'id="registration-single-progress"' in template
    assert 'id="registration-batch-summary"' in template
    assert 'id="registration-stream-status"' in template
    assert '/static/css/registration_workbench.css' in template
```

- [ ] **Step 2: 运行测试，确认当前模板仍是旧布局**

Run: `timeout 60s pytest tests/test_registration_page_assets.py::test_registration_template_contains_realtime_feedback_panels -q`
Expected: FAIL，缺少新 panel id / 新 CSS 引用。

- [ ] **Step 3: 以最小重排实现 1/3:2/3 布局和反馈区三层面板**

```html
<!-- templates/index.html -->
<section id="registration-config-panel" class="registration-layout-config">...</section>
<section class="registration-layout-feedback">
  <article id="registration-single-progress" class="feedback-panel"></article>
  <article id="registration-batch-summary" class="feedback-panel"></article>
  <article id="registration-log-console" class="feedback-panel feedback-panel-log"></article>
</section>
```

```css
/* static/css/registration_workbench.css */
.registration-layout {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(0, 2fr);
  gap: 24px;
}
.feedback-panel-log {
  min-height: 320px;
  background: #0f172a;
  color: #e2e8f0;
}
```

- [ ] **Step 4: 跑 registration 页面资产与 versioning 测试，确认 hook、样式、版本号都正确**

Run: `timeout 60s pytest tests/test_registration_page_assets.py tests/test_static_asset_versioning.py -k 'registration' -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 6**

```bash
git add templates/index.html static/css/registration_workbench.css static/js/app.js tests/test_registration_page_assets.py tests/test_static_asset_versioning.py
git commit -m "feat: redesign registration workbench panels"
```

### Task 7: 重做 Dashboard 为现代数据看板，并使用独立页面样式

**Files:**
- Modify: `templates/dashboard.html`
- Modify: `static/js/dashboard.js`
- Create: `static/css/dashboard_page.css`
- Create: `tests_runtime/dashboard_js_harness.py`
- Modify: `tests/test_dashboard_page_assets.py`
- Modify: `tests/test_static_asset_versioning.py`

- [ ] **Step 1: 写失败测试，固定新版 Dashboard 骨架与渲染 helper**

```python
# tests/test_dashboard_page_assets.py
def test_dashboard_template_contains_new_hero_and_activity_sections():
    template = Path("templates/dashboard.html").read_text(encoding="utf-8")
    assert 'id="dashboard-hero-primary"' in template
    assert 'id="dashboard-metric-grid"' in template
    assert 'id="dashboard-activity-feed"' in template
    assert 'id="dashboard-quick-actions"' in template
    assert '/static/css/dashboard_page.css' in template
```

- [ ] **Step 2: 运行测试，确认当前模板 / 脚本仍是旧版**

Run: `timeout 60s pytest tests/test_dashboard_page_assets.py::test_dashboard_template_contains_new_hero_and_activity_sections -q`
Expected: FAIL。

- [ ] **Step 3: 以最小实现重做 template、page css 与 dashboard render 函数**

```javascript
// static/js/dashboard.js
function renderDashboardHero(summary) {
  return `
    <div class="dashboard-hero-copy">...</div>
    <div id="dashboard-metric-grid" class="dashboard-metric-grid">...</div>
  `;
}

function renderRecentActivity(items) {
  return items.map((item) => `
    <li class="dashboard-activity-item">
      <a href="${escapeHtml(item.href)}">${escapeHtml(item.title)}</a>
      <span>${escapeHtml(item.status)}</span>
    </li>
  `).join('');
}
```

- [ ] **Step 4: 跑 dashboard 资产 / harness / versioning 测试，确认新版结构和 JS 契约都成立**

Run: `timeout 60s pytest tests/test_dashboard_page_assets.py tests/test_static_asset_versioning.py -k 'dashboard' -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 7**

```bash
git add templates/dashboard.html static/css/dashboard_page.css static/js/dashboard.js tests_runtime/dashboard_js_harness.py tests/test_dashboard_page_assets.py tests/test_static_asset_versioning.py
git commit -m "feat: redesign dashboard overview page"
```

### Task 8: 回归验证、旧链路清理与最终交付检查

**Files:**
- Modify: `static/js/app.js`
- Modify: `src/web/routes/websocket.py`
- Modify: `src/web/routes/registration.py`
- Modify: `tests/test_registration_page_assets.py`
- Modify: `tests/test_dashboard_page_assets.py`
- Modify: `tests/test_registration_stream_routes.py`
- Modify: `tests/test_task_manager.py`

- [ ] **Step 1: 写最后一组失败测试，锁定 fallback 不再依赖 DB flush 的行为**

```python
# tests/test_registration_stream_routes.py
def test_task_events_route_returns_live_log_before_database_flush(monkeypatch):
    task_manager.update_status("task-live-fallback", "running")
    task_manager.add_log("task-live-fallback", "live-line")

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/registration/streams/task/task-live-fallback/events?after_seq=0")

    assert response.status_code == 200
    assert response.json()["events"][-1]["payload"]["message"] == "live-line"
```

- [ ] **Step 2: 运行失败测试，确认它在清理旧 fallback 之前会暴露问题**

Run: `timeout 60s pytest tests/test_registration_stream_routes.py::test_task_events_route_returns_live_log_before_database_flush -q`
Expected: FAIL（如果事件路由仍走旧落库链路）或暴露兼容问题。

- [ ] **Step 3: 删除 / 收敛旧的 registration-workbench 多源拼接分支，保留兼容接口但不再作为 UI 主链路**

```javascript
// static/js/app.js
// 删除：轮询 /registration/tasks/{task_uuid}/logs 作为主实时来源
// 保留：仅在 snapshot-required 且 store 未建立时作为兼容兜底
```

```python
# src/web/routes/registration.py
# 保留旧详情/日志接口供其他页面使用；新工作台只消费 /streams/*
```

- [ ] **Step 4: 运行完整相关回归套件，确认前后端主路径均通过**

Run: `timeout 60s pytest tests/test_task_manager.py tests/test_registration_stream_routes.py tests/test_pipeline_runner.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_page_assets.py tests/test_dashboard_page_assets.py tests/test_static_asset_versioning.py -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 8**

```bash
git add src/web/routes/registration.py src/web/routes/websocket.py static/js/app.js tests/test_task_manager.py tests/test_registration_stream_routes.py tests/test_pipeline_runner.py tests/test_registration_service.py tests/test_batch_registration_service.py tests/test_registration_page_assets.py tests/test_dashboard_page_assets.py tests/test_static_asset_versioning.py
git commit -m "refactor: finalize realtime registration dashboard flow"
```
