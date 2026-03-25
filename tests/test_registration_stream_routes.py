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
        task_events_after_one = client.get(
            "/api/registration/streams/task/task-route-1/events?after_seq=1"
        )
        batch_snapshot = client.get("/api/registration/streams/batch/batch-route-1/snapshot")
        batch_events = client.get("/api/registration/streams/batch/batch-route-1/events?after_seq=0")
        batch_events_after_one = client.get(
            "/api/registration/streams/batch/batch-route-1/events?after_seq=1"
        )

    assert task_snapshot.status_code == 200
    task_snapshot_json = task_snapshot.json()
    assert task_snapshot_json["stream"] == "task:task-route-1"
    assert task_snapshot_json["kind"] == "snapshot"
    assert isinstance(task_snapshot_json["seq"], int)
    assert task_snapshot_json["timestamp"]
    assert isinstance(task_snapshot_json["payload"], dict)
    assert "task" in task_snapshot_json["payload"]
    assert task_events.status_code == 200
    task_events_json = task_events.json()
    assert task_events_json["stream"] == "task:task-route-1"
    assert isinstance(task_events_json["events"], list)
    assert task_events_json["events"], "after_seq=0 should return at least one event"
    for event in task_events_json["events"]:
        assert event["stream"] == "task:task-route-1"
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
    assert batch_snapshot_json["stream"] == "batch:batch-route-1"
    assert batch_snapshot_json["kind"] == "snapshot"
    assert isinstance(batch_snapshot_json["seq"], int)
    assert batch_snapshot_json["timestamp"]
    assert isinstance(batch_snapshot_json["payload"], dict)
    assert "batch" in batch_snapshot_json["payload"]
    assert batch_events.status_code == 200
    batch_events_json = batch_events.json()
    assert batch_events_json["stream"] == "batch:batch-route-1"
    assert isinstance(batch_events_json["events"], list)
    assert batch_events_json["events"]
    for event in batch_events_json["events"]:
        assert event["stream"] == "batch:batch-route-1"
        assert isinstance(event["seq"], int)
        assert event["kind"]
        assert "payload" in event
    assert batch_events_after_one.status_code == 200
    assert batch_events_after_one.json()["events"]
    filtered = batch_events_after_one.json()["events"]
    assert all(event["seq"] > 1 for event in filtered)
    assert len(filtered) < len(batch_events_json["events"])
