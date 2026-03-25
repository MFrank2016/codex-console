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


@pytest.fixture(autouse=True)
def clean_task_manager_globals():
    names = [
        "_log_queues",
        "_log_locks",
        "_ws_connections",
        "_ws_sent_index",
        "_task_status",
        "_task_steps",
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
        store = getattr(task_manager_module, name)
        snapshots[name] = store.copy()
        store.clear()

    yield

    for name in names:
        store = getattr(task_manager_module, name)
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
