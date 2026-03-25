from fastapi.testclient import TestClient
import pytest
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


def test_task_and_batch_stream_routes_return_expected_contract():
    app = create_app()
    task_uuid = f"task-route-{uuid4().hex}"
    batch_id = f"batch-route-{uuid4().hex}"
    task_manager.update_status(task_uuid, "running")
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
    last_event = task_events_json["events"][-1]
    assert last_event["kind"] == "log_appended"
    assert last_event["payload"].get("message") == "line-1"
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
