import asyncio

import pytest

from src.web import task_manager as task_manager_module
from src.web.task_manager import TaskManager
from src.web.realtime_streams import task_stream_id, batch_stream_id


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


class _ModeFlipDict(dict):
    """测试专用：第一次读取 mode 时返回 replaying，但立刻把自身 mode 切到 active。

    用于稳定复现：broadcast 读取到旧 mode 后，状态已切换到 active 的临界区竞态。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mode_read_once = False

    def __getitem__(self, key):
        if key == "mode" and not self._mode_read_once:
            self._mode_read_once = True
            # 先返回 replaying，再切 active（模拟 replay -> active 切换窗口）
            value = "replaying"
            super().__setitem__("mode", "active")
            return value
        return super().__getitem__(key)


@pytest.fixture(autouse=True)
def clean_task_manager_globals():
    names = [
        "_log_queues",
        "_log_locks",
        "_ws_connections",
        "_ws_sent_index",
        "_task_status",
        "_task_steps",
        "_task_progress",
        "_task_cancelled",
        "_batch_status",
        "_batch_logs",
        "_batch_locks",
        "_stream_seq",
        "_stream_events",
        "_stream_locks",
    ]
    snapshots = {}
    for name in names:
        store = getattr(task_manager_module, name, None)
        if store is None:
            continue
        snapshots[name] = store.copy()
        store.clear()

    yield

    for name in names:
        store = getattr(task_manager_module, name, None)
        if store is None:
            continue
        store.clear()
        store.update(snapshots[name])


@pytest.mark.anyio
async def test_update_status_broadcasts_to_registered_task_websocket():
    manager = TaskManager()
    manager.set_loop(asyncio.get_running_loop())
    websocket = FakeWebSocket()
    task_uuid = "task-single-123"

    manager.register_websocket(task_uuid, websocket)
    manager.update_status(task_uuid, "completed", email="tester@example.com")
    await asyncio.sleep(0.05)

    assert manager.get_status(task_uuid)["status"] == "completed"
    assert len(websocket.messages) == 1
    message = websocket.messages[0]
    assert message["stream"] == f"task:{task_uuid}"
    assert message["kind"] == "task_status_changed"
    assert message["payload"]["task_uuid"] == task_uuid
    assert message["payload"]["status"] == "completed"
    assert message["payload"]["email"] == "tester@example.com"
    assert message["timestamp"]


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
    assert snapshot["seq"] == events[-1]["seq"]
    assert snapshot["payload"]["logs_tail"] == ["[12:00:00] create email"]
    assert [item["seq"] for item in events] == [1, 2, 3]
    assert events[-1]["payload"]["message"] == "[12:00:00] create email"


def test_task_stream_snapshot_includes_explicit_progress_contract():
    manager = TaskManager()
    task_uuid = "task-progress-snapshot"

    manager.update_status(task_uuid, "running")
    manager.set_task_steps(
        task_uuid,
        [
            {"step_key": "create_email", "status": "completed"},
            {"step_key": "submit_login_email", "status": "running"},
        ],
        task_progress={
            "step_index": 2,
            "total_steps": 5,
            "progress_percent": 40,
        },
    )

    snapshot = manager.build_task_stream_snapshot(task_uuid)

    assert snapshot["payload"]["task_progress"] == {
        "step_index": 2,
        "total_steps": 5,
        "progress_percent": 40,
    }


def test_task_step_updated_event_includes_explicit_progress_contract():
    manager = TaskManager()
    task_uuid = "task-progress-event"

    manager.set_task_steps(
        task_uuid,
        [
            {"step_key": "create_email", "status": "completed"},
            {"step_key": "submit_login_email", "status": "running"},
        ],
        task_progress={
            "step_index": 2,
            "total_steps": 5,
            "progress_percent": 40,
        },
    )

    events = manager.get_stream_events_after(task_stream_id(task_uuid), after_seq=0)

    assert events[-1]["kind"] == "task_step_updated"
    assert events[-1]["payload"]["task_progress"]["step_index"] == 2
    assert events[-1]["payload"]["task_progress"]["total_steps"] == 5


@pytest.mark.anyio
async def test_websocket_replay_state_buffers_pending_events_and_flushes_in_seq_order():
    manager = TaskManager()
    manager.set_loop(asyncio.get_running_loop())

    websocket = FakeWebSocket()
    task_uuid = "task-replay-buffer"
    stream_id = task_stream_id(task_uuid)

    # 预先存在的事件：由路由负责 replay 发送
    first = manager.append_stream_event(
        stream_id,
        "task_status_changed",
        {"task_uuid": task_uuid, "status": "running"},
    )
    second = manager.append_stream_event(
        stream_id,
        "log_appended",
        {"task_uuid": task_uuid, "message": "line-1"},
    )

    # 连接进入 replaying：期间新广播事件必须先进入 pending
    manager.register_websocket(task_uuid, websocket, mode="replaying", after_seq=0)
    await manager.send_task_stream_event(task_uuid, websocket, first)
    await manager.send_task_stream_event(task_uuid, websocket, second)

    third = manager.append_stream_event(
        stream_id,
        "log_appended",
        {"task_uuid": task_uuid, "message": "late-line"},
    )
    await manager.broadcast_task_stream_event(task_uuid, third)

    await manager.finish_task_websocket_replay(task_uuid, websocket)

    assert [item["seq"] for item in websocket.messages] == [1, 2, 3]
    assert websocket.messages[-1]["payload"]["message"] == "late-line"


@pytest.mark.anyio
async def test_batch_websocket_replay_state_buffers_pending_events_and_flushes_in_seq_order():
    manager = TaskManager()
    manager.set_loop(asyncio.get_running_loop())

    websocket = FakeWebSocket()
    batch_id = "batch-replay-buffer"
    stream_id = batch_stream_id(batch_id)

    first = manager.append_stream_event(
        stream_id,
        "batch_progress_updated",
        {"batch_id": batch_id, "status": "running"},
    )
    second = manager.append_stream_event(
        stream_id,
        "log_appended",
        {"batch_id": batch_id, "message": "line-1"},
    )

    manager.register_batch_websocket(batch_id, websocket, mode="replaying", after_seq=0)
    await manager.send_batch_stream_event(batch_id, websocket, first)
    await manager.send_batch_stream_event(batch_id, websocket, second)

    third = manager.append_stream_event(
        stream_id,
        "log_appended",
        {"batch_id": batch_id, "message": "late-line"},
    )
    await manager.broadcast_batch_stream_event(batch_id, third)

    await manager.finish_batch_websocket_replay(batch_id, websocket)

    assert [item["seq"] for item in websocket.messages] == [1, 2, 3]
    assert websocket.messages[-1]["payload"]["message"] == "late-line"


@pytest.mark.anyio
async def test_broadcast_task_stream_event_does_not_drop_event_when_mode_flips_to_active():
    manager = TaskManager()
    manager.set_loop(asyncio.get_running_loop())

    websocket = FakeWebSocket()
    task_uuid = "task-race-mode-flip"

    manager.register_websocket(task_uuid, websocket, mode="replaying", after_seq=0)

    # 将 ws state 替换为“读取 mode 时自动切 active”的 dict，稳定模拟竞态
    ws_id = id(websocket)
    original = task_manager_module._ws_connections[task_uuid][ws_id]
    task_manager_module._ws_connections[task_uuid][ws_id] = _ModeFlipDict(original)

    event = manager.append_stream_event(
        task_stream_id(task_uuid),
        "log_appended",
        {"task_uuid": task_uuid, "message": "line-1"},
    )
    await manager.broadcast_task_stream_event(task_uuid, event)

    state = task_manager_module._ws_connections[task_uuid][ws_id]
    delivered = any(item.get("payload", {}).get("message") == "line-1" for item in websocket.messages)
    queued = any(item.get("payload", {}).get("message") == "line-1" for item in state.get("pending", []))
    assert delivered or queued, "事件必须要么被发送，要么进入 pending，不能静默丢失"


@pytest.mark.anyio
async def test_broadcast_batch_stream_event_does_not_drop_event_when_mode_flips_to_active():
    manager = TaskManager()
    manager.set_loop(asyncio.get_running_loop())

    websocket = FakeWebSocket()
    batch_id = "batch-race-mode-flip"

    manager.register_batch_websocket(batch_id, websocket, mode="replaying", after_seq=0)

    ws_key = manager._stream_ws_key_for_batch(batch_id)
    ws_id = id(websocket)
    original = task_manager_module._ws_connections[ws_key][ws_id]
    task_manager_module._ws_connections[ws_key][ws_id] = _ModeFlipDict(original)

    event = manager.append_stream_event(
        batch_stream_id(batch_id),
        "log_appended",
        {"batch_id": batch_id, "message": "batch-line-1"},
    )
    await manager.broadcast_batch_stream_event(batch_id, event)

    state = task_manager_module._ws_connections[ws_key][ws_id]
    delivered = any(item.get("payload", {}).get("message") == "batch-line-1" for item in websocket.messages)
    queued = any(item.get("payload", {}).get("message") == "batch-line-1" for item in state.get("pending", []))
    assert delivered or queued, "事件必须要么被发送，要么进入 pending，不能静默丢失"
