from fastapi.testclient import TestClient
import pytest

from src.web.app import create_app
from src.web.task_manager import task_manager
import src.web.task_manager as task_manager_module


@pytest.fixture(autouse=True)
def clean_realtime_stream_state():
    _clear_state_for_tests()
    yield
    _clear_state_for_tests()


def _clear_state_for_tests():
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
        task_manager_module._run_status,
        task_manager_module._run_progress,
        task_manager_module._run_logs,
        task_manager_module._run_locks,
        task_manager_module._stream_seq,
        task_manager_module._stream_events,
        task_manager_module._stream_locks,
        task_manager_module._ws_connections,
        task_manager_module._ws_sent_index,
        task_manager_module._task_cancelled,
    ):
        container.clear()


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


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
    assert events.status_code == 200
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
    assert (
        batch_events.json()["events"][-1]["payload"]["entry"]["seq"]
        == batch_events.json()["events"][-1]["seq"]
    )

    with client.websocket_connect("/api/ws/task/task-new-1?after_seq=0") as task_ws:
        task_payload = task_ws.receive_json()
    with client.websocket_connect("/api/ws/batch/batch-new-1?after_seq=0") as batch_ws:
        batch_payload = batch_ws.receive_json()

    assert task_payload["stream"] == "task:task-new-1"
    assert batch_payload["stream"] == "batch:batch-new-1"
