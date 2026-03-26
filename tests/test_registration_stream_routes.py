from fastapi.testclient import TestClient
import pytest
import queue
import threading
from src.web.app import create_app
from src.web.realtime_streams import STREAM_BUFFER_SIZE
from src.web.task_manager import task_manager
import src.web.task_manager as task_manager_module
from uuid import uuid4


@pytest.fixture(autouse=True)
def clean_registration_stream_state():
    _clear_state_for_tests()
    yield
    _clear_state_for_tests()


def _clear_state_for_tests():
    """测试专用：清理 task_manager 全局状态"""
    for container in (
        task_manager_module._task_status,
        task_manager_module._task_steps,
        task_manager_module._task_progress,
        task_manager_module._experiment_status,
        task_manager_module._log_queues,
        task_manager_module._log_locks,
        task_manager_module._batch_status,
        task_manager_module._batch_logs,
        task_manager_module._batch_locks,
        task_manager_module._stream_seq,
        task_manager_module._stream_events,
        task_manager_module._stream_locks,
        task_manager_module._ws_connections,
        task_manager_module._ws_sent_index,
        task_manager_module._task_cancelled,
    ):
        container.clear()


def _receive_json_with_timeout(ws, *, timeout_s: float = 1.0):
    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def _target():
        try:
            result_queue.put(ws.receive_json())
        except Exception as exc:  # pragma: no cover - 测试辅助兜底
            result_queue.put(exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    try:
        result = result_queue.get(timeout=timeout_s)
    except queue.Empty as exc:
        raise AssertionError(f"WebSocket receive_json 超时({timeout_s}s)，可能存在丢消息/卡死") from exc
    if isinstance(result, Exception):
        raise result
    return result


def test_task_and_batch_stream_routes_return_expected_contract():
    app = create_app()
    task_uuid = f"task-route-{uuid4().hex}"
    batch_id = f"batch-route-{uuid4().hex}"
    task_manager.update_status(task_uuid, "running")
    task_manager.set_task_steps(
        task_uuid,
        [{"step_key": "create_email", "status": "running"}],
        task_progress={"step_index": 2, "total_steps": 5, "progress_percent": 40},
    )
    task_manager.add_log(task_uuid, "line-1")
    task_manager.init_batch(batch_id, total=5)
    task_manager.update_batch_status(batch_id, completed=2, success=1, failed=1)
    task_manager.add_batch_log(batch_id, "batch-line-1")

    with TestClient(app) as client:
        task_snapshot = client.get(f"/api/registration/streams/task/{task_uuid}/snapshot")
        task_events = client.get(f"/api/registration/streams/task/{task_uuid}/events?after_seq=0")
        task_events_after_one = client.get(
            f"/api/registration/streams/task/{task_uuid}/events?after_seq=1"
        )
        batch_snapshot = client.get(f"/api/registration/streams/batch/{batch_id}/snapshot")
        batch_events = client.get(f"/api/registration/streams/batch/{batch_id}/events?after_seq=0")
        batch_events_after_one = client.get(
            f"/api/registration/streams/batch/{batch_id}/events?after_seq=1"
        )

    assert task_snapshot.status_code == 200
    task_snapshot_json = task_snapshot.json()
    assert task_snapshot_json["stream"] == f"task:{task_uuid}"
    assert task_snapshot_json["kind"] == "snapshot"
    assert isinstance(task_snapshot_json["seq"], int)
    assert task_snapshot_json["timestamp"]
    assert isinstance(task_snapshot_json["payload"], dict)
    assert "task" in task_snapshot_json["payload"]
    assert task_snapshot_json["payload"]["task_progress"] == {
        "step_index": 2,
        "total_steps": 5,
        "progress_percent": 40,
    }
    assert task_events.status_code == 200
    task_events_json = task_events.json()
    assert task_events_json["stream"] == f"task:{task_uuid}"
    assert isinstance(task_events_json["events"], list)
    assert task_events_json["events"], "after_seq=0 should return at least one event"
    for event in task_events_json["events"]:
        assert event["stream"] == f"task:{task_uuid}"
        assert isinstance(event["seq"], int)
        assert event["kind"]
        assert "payload" in event
    assert task_events_json["events"][1]["kind"] == "task_step_updated"
    assert task_events_json["events"][1]["payload"]["task_progress"] == {
        "step_index": 2,
        "total_steps": 5,
        "progress_percent": 40,
    }
    last_event = task_events_json["events"][-1]
    assert last_event["kind"] == "log_appended"
    assert last_event["payload"].get("message") == "line-1"
    assert task_snapshot_json["seq"] == last_event["seq"]
    assert task_events_after_one.status_code == 200
    assert task_events_after_one.json()["events"]
    assert all(event["seq"] > 1 for event in task_events_after_one.json()["events"])

    assert batch_snapshot.status_code == 200
    batch_snapshot_json = batch_snapshot.json()
    assert batch_snapshot_json["stream"] == f"batch:{batch_id}"
    assert batch_snapshot_json["kind"] == "snapshot"
    assert isinstance(batch_snapshot_json["seq"], int)
    assert batch_snapshot_json["timestamp"]
    assert isinstance(batch_snapshot_json["payload"], dict)
    assert "batch" in batch_snapshot_json["payload"]
    assert batch_events.status_code == 200
    batch_events_json = batch_events.json()
    assert batch_events_json["stream"] == f"batch:{batch_id}"
    assert isinstance(batch_events_json["events"], list)
    assert batch_events_json["events"]
    for event in batch_events_json["events"]:
        assert event["stream"] == f"batch:{batch_id}"
        assert isinstance(event["seq"], int)
        assert event["kind"]
        assert "payload" in event
    assert batch_events_after_one.status_code == 200
    assert batch_events_after_one.json()["events"]
    filtered = batch_events_after_one.json()["events"]
    assert all(event["seq"] > 1 for event in filtered)
    assert len(filtered) < len(batch_events_json["events"])
    assert batch_snapshot_json["seq"] == batch_events_json["events"][-1]["seq"]


def test_registration_stream_routes_return_404_for_missing_streams():
    app = create_app()
    missing_task_uuid = f"task-route-{uuid4().hex}"
    missing_batch_id = f"batch-route-{uuid4().hex}"

    with TestClient(app) as client:
        task_snapshot = client.get(f"/api/registration/streams/task/{missing_task_uuid}/snapshot")
        task_events = client.get(f"/api/registration/streams/task/{missing_task_uuid}/events?after_seq=0")
        batch_snapshot = client.get(f"/api/registration/streams/batch/{missing_batch_id}/snapshot")
        batch_events = client.get(f"/api/registration/streams/batch/{missing_batch_id}/events?after_seq=0")

    assert task_snapshot.status_code == 404
    assert task_events.status_code == 404
    assert batch_snapshot.status_code == 404
    assert batch_events.status_code == 404


def test_task_and_batch_websocket_replay_missing_events_after_after_seq():
    app = create_app()
    task_manager.update_status("task-ws-1", "running")
    task_manager.add_log("task-ws-1", "line-1")
    task_manager.add_log("task-ws-1", "line-2")
    task_manager.init_batch("batch-ws-1", total=3)
    task_manager.update_batch_status("batch-ws-1", completed=1, success=1, failed=0)
    task_manager.add_batch_log("batch-ws-1", "batch-line-1")
    task_manager.add_batch_log("batch-ws-1", "batch-line-2")

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws/task/task-ws-1?after_seq=1") as task_ws:
            task_first = task_ws.receive_json()
            task_second = task_ws.receive_json()
        with client.websocket_connect("/api/ws/batch/batch-ws-1?after_seq=1") as batch_ws:
            batch_first = batch_ws.receive_json()
            batch_second = batch_ws.receive_json()

    task_seqs = [task_first["seq"], task_second["seq"]]
    assert task_seqs == sorted(task_seqs)
    assert len(set(task_seqs)) == len(task_seqs)
    assert task_first["seq"] == 2
    assert task_second["seq"] == 3
    assert task_first["kind"] == "log_appended"
    assert task_second["kind"] == "log_appended"

    batch_seqs = [batch_first["seq"], batch_second["seq"]]
    assert batch_seqs == sorted(batch_seqs)
    assert len(set(batch_seqs)) == len(batch_seqs)
    assert batch_first["stream"] == "batch:batch-ws-1"
    assert batch_first["seq"] == 2
    assert batch_second["seq"] == 3


def test_task_websocket_replies_snapshot_required_when_after_seq_expired():
    app = create_app()
    task_uuid = "task-ws-expired"
    task_manager.update_status(task_uuid, "running")
    for i in range(STREAM_BUFFER_SIZE + 5):
        task_manager.add_log(task_uuid, f"line-{i}")

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/ws/task/{task_uuid}?after_seq=1") as ws:
            payload = ws.receive_json()

    assert payload["stream"] == f"task:{task_uuid}"
    assert payload["kind"] == "snapshot_required"
    assert payload["payload"]["reason"] == "after_seq_expired"


def test_batch_websocket_replies_snapshot_required_when_after_seq_expired():
    app = create_app()
    batch_id = "batch-ws-expired"
    task_manager.init_batch(batch_id, total=1)
    for i in range(STREAM_BUFFER_SIZE + 5):
        task_manager.add_batch_log(batch_id, f"line-{i}")

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/ws/batch/{batch_id}?after_seq=1") as ws:
            payload = ws.receive_json()

    assert payload["stream"] == f"batch:{batch_id}"
    assert payload["kind"] == "snapshot_required"
    assert payload["payload"]["reason"] == "after_seq_expired"


def test_task_websocket_snapshot_required_connection_keeps_receiving_live_events():
    app = create_app()
    task_uuid = "task-ws-expired-live"
    task_manager.update_status(task_uuid, "running")
    for i in range(STREAM_BUFFER_SIZE + 5):
        task_manager.add_log(task_uuid, f"line-{i}")

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/ws/task/{task_uuid}?after_seq=1") as ws:
            payload = ws.receive_json()
            assert payload["kind"] == "snapshot_required"

            task_manager.add_log(task_uuid, "after-snapshot-required")
            event = _receive_json_with_timeout(ws, timeout_s=1.5)

    assert event["stream"] == f"task:{task_uuid}"
    assert event["kind"] == "log_appended"
    assert event["payload"]["message"] == "after-snapshot-required"


def test_batch_websocket_snapshot_required_connection_keeps_receiving_live_events():
    app = create_app()
    batch_id = "batch-ws-expired-live"
    task_manager.init_batch(batch_id, total=1)
    for i in range(STREAM_BUFFER_SIZE + 5):
        task_manager.add_batch_log(batch_id, f"line-{i}")

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/ws/batch/{batch_id}?after_seq=1") as ws:
            payload = ws.receive_json()
            assert payload["kind"] == "snapshot_required"

            task_manager.add_batch_log(batch_id, "after-snapshot-required")
            event = _receive_json_with_timeout(ws, timeout_s=1.5)

    assert event["stream"] == f"batch:{batch_id}"
    assert event["kind"] == "log_appended"
    assert event["payload"]["message"] == "after-snapshot-required"


def test_task_websocket_keeps_ping_pong_and_cancel_as_control_messages():
    app = create_app()
    task_uuid = "task-ws-control"
    task_manager.update_status(task_uuid, "running")

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/ws/task/{task_uuid}?after_seq=9999") as ws:
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong == {"type": "pong"}

            ws.send_json({"type": "cancel"})
            event = _receive_json_with_timeout(ws, timeout_s=1.5)
            assert event["stream"] == f"task:{task_uuid}"
            assert event["kind"] == "task_status_changed"
            assert event["payload"]["status"] == "cancelling"


def test_task_websocket_does_not_lose_events_emitted_during_replay_handshake():
    app = create_app()
    task_uuid = "task-ws-race"
    task_manager.update_status(task_uuid, "running")
    task_manager.add_log(task_uuid, "line-1")

    original = task_manager.get_stream_events_after
    call_count = {"n": 0}

    def _patched(stream_id: str, after_seq: int):
        call_count["n"] += 1
        result = original(stream_id, after_seq=after_seq)
        # 模拟：replay 已经读取完（replay 列表已确定），恰好有新事件产生
        if call_count["n"] == 1 and stream_id == f"task:{task_uuid}":
            task_manager.add_log(task_uuid, "late-line")
        return result

    task_manager.get_stream_events_after = _patched  # monkeypatch（避免引入 pytest monkeypatch 依赖）
    try:
        with TestClient(app) as client:
            with client.websocket_connect(f"/api/ws/task/{task_uuid}?after_seq=0") as ws:
                first = ws.receive_json()
                second = ws.receive_json()
                third = _receive_json_with_timeout(ws, timeout_s=1.5)

        seqs = [first["seq"], second["seq"], third["seq"]]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
        assert third["kind"] == "log_appended"
        assert third["payload"]["message"] == "late-line"
    finally:
        task_manager.get_stream_events_after = original


def test_batch_websocket_cancel_emits_stream_event_confirmation():
    app = create_app()
    batch_id = "batch-ws-control"
    task_manager.init_batch(batch_id, total=2)

    with TestClient(app) as client:
        with client.websocket_connect(f"/api/ws/batch/{batch_id}?after_seq=9999") as ws:
            ws.send_json({"type": "cancel"})
            event = _receive_json_with_timeout(ws, timeout_s=1.5)

    assert event["stream"] == f"batch:{batch_id}"
    assert event["kind"] == "batch_progress_updated"
    assert event["payload"]["status"] == "cancelling"


def test_task_events_route_returns_live_log_before_database_flush(monkeypatch):
    task_manager.update_status("task-live-fallback", "running")
    task_manager.add_log("task-live-fallback", "live-line")

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/registration/streams/task/task-live-fallback/events?after_seq=0")

    assert response.status_code == 200
    assert response.json()["events"][-1]["payload"]["message"] == "live-line"
