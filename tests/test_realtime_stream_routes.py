from fastapi.testclient import TestClient
import pytest

from src.web.app import create_app
from src.web.realtime_streams import STREAM_BUFFER_SIZE
from src.web.task_manager import reset_state_for_tests, task_manager
from tests.test_helpers import receive_json_with_timeout


@pytest.fixture(autouse=True)
def clean_realtime_stream_state():
    reset_state_for_tests()
    yield
    reset_state_for_tests()


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


def test_run_websocket_replay_missing_events_after_after_seq(client):
    task_manager.update_run_status(888, status="running", plan_name="sync")
    task_manager.add_run_log(888, {"message": "run-line-1", "source": "scheduler"})
    task_manager.add_run_log(888, {"message": "run-line-2", "source": "scheduler"})

    with client.websocket_connect("/api/ws/run/888?after_seq=1") as ws:
        first = ws.receive_json()
        second = ws.receive_json()

    assert first["stream"] == "run:888"
    assert first["seq"] == 2
    assert first["kind"] == "log_appended"
    assert first["payload"]["entry"]["message"] == "run-line-1"
    assert second["stream"] == "run:888"
    assert second["seq"] == 3
    assert second["kind"] == "log_appended"
    assert second["payload"]["entry"]["message"] == "run-line-2"


def test_run_websocket_replies_snapshot_required_when_after_seq_expired(client):
    task_manager.update_run_status(889, status="running")
    for i in range(STREAM_BUFFER_SIZE + 5):
        task_manager.add_run_log(889, {"message": f"line-{i}", "source": "scheduler"})

    with client.websocket_connect("/api/ws/run/889?after_seq=1") as ws:
        payload = ws.receive_json()

    assert payload["stream"] == "run:889"
    assert payload["kind"] == "snapshot_required"
    assert payload["payload"]["reason"] == "after_seq_expired"


def test_run_websocket_snapshot_required_connection_keeps_receiving_live_events(client):
    task_manager.update_run_status(890, status="running")
    for i in range(STREAM_BUFFER_SIZE + 5):
        task_manager.add_run_log(890, {"message": f"line-{i}", "source": "scheduler"})

    with client.websocket_connect("/api/ws/run/890?after_seq=1") as ws:
        payload = ws.receive_json()
        assert payload["kind"] == "snapshot_required"

        task_manager.add_run_log(890, {"message": "after-snapshot-required", "source": "scheduler"})
        event = receive_json_with_timeout(ws, timeout_s=1.5)

    assert event["stream"] == "run:890"
    assert event["kind"] == "log_appended"
    assert event["payload"]["entry"]["message"] == "after-snapshot-required"
