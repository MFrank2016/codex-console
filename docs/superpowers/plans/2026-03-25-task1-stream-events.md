# Task 1 Stream Event Primitives Implementation Plan

I'm using the writing-plans skill to create the implementation plan.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 TaskManager 中建立 stream 事件原语，提供 snapshot 与序列增量事件的基础契约，供首页与注册工作台实时流消费。

**Architecture:** 新增 `realtime_streams` 辅助模块定义 stream id 与缓冲参数，TaskManager 维护 seq/事件队列并提供 snapshot 构建、增量查询；测试夹具通过 `TaskManager` API 验证 snapshot payload 与 seq 顺序；后续 REST/WebSocket 路由可直接复用 helper。

**Tech Stack:** Python 3.12、FastAPI、pytest

---

### Task 1: 建立 stream 事件原语与 TaskManager 缓冲层

**Files:**
- Create: `src/web/realtime_streams.py`
- Modify: `src/web/task_manager.py`
- Test: `tests/test_task_manager.py`

- [ ] **Step 1: 写失败测试，锁定 task stream 的 seq / snapshot / 增量回放契约**

```python
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
    assert snapshot["payload"]["logs_tail"] == ["[12:00:00] create email"]
    assert [item["seq"] for item in events] == [1, 2, 3]
    assert events[-1]["payload"]["message"] == "[12:00:00] create email"
```

- [ ] **Step 2: 运行测试，确认当前实现确实缺少 stream API**

Run: `timeout 60s pytest tests/test_task_manager.py::test_task_manager_builds_snapshot_and_incremental_events -q`
Expected: FAIL，提示 `AttributeError`（`build_task_stream_snapshot` / `get_stream_events_after` 未实现）。

- [ ] **Step 3: 用最小实现补齐 stream helper 与 TaskManager 内存结构**

```python
# src/web/realtime_streams.py
from collections import deque

STREAM_BUFFER_SIZE = 1000
LOG_TAIL_SIZE = 10


def task_stream_id(task_uuid: str) -> str:
    return f"task:{task_uuid}"


def batch_stream_id(batch_id: str) -> str:
    return f"batch:{batch_id}"
```

```python
# src/web/task_manager.py
from collections import defaultdict, deque
from src.web.realtime_streams import (
    STREAM_BUFFER_SIZE,
    LOG_TAIL_SIZE,
    task_stream_id,
)

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

    def build_task_stream_snapshot(self, task_uuid: str) -> dict:
        stream_id = task_stream_id(task_uuid)
        task = self._task_status.get(task_uuid, {})
        current_step = self._task_steps.get(task_uuid, [None])[-1] or {}
        logs_tail = self.get_logs(task_uuid)[-LOG_TAIL_SIZE:]
        steps = self.get_task_steps(task_uuid)
        return {
            "seq": self._stream_seq.get(stream_id, 0) + 1,
            "stream": stream_id,
            "kind": "snapshot",
            "timestamp": utc_now().isoformat(),
            "payload": {
                "task": task,
                "current_step": current_step,
                "steps": steps,
                "logs_tail": logs_tail,
            },
        }

    def get_stream_events_after(self, stream_id: str, after_seq: int) -> list[dict]:
        return [event for event in self._stream_events.get(stream_id, []) if event["seq"] > after_seq]
```

- [ ] **Step 4: 再跑同一条测试，确认 seq、snapshot、事件缓冲契约成立**

Run: `timeout 60s pytest tests/test_task_manager.py::test_task_manager_builds_snapshot_and_incremental_events -q`
Expected: PASS。

- [ ] **Step 5: 提交 Task 1**

```bash
git add tests/test_task_manager.py src/web/realtime_streams.py src/web/task_manager.py
git commit -m "feat: add registration stream event primitives"
```
