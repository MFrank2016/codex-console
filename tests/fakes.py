"""
Shared fake helpers for registration-related test suites.

Houses lightweight Registration/Batch task managers so tests don't cross-import
from large test modules and keep only the methods currently relied on.
"""


class RegistrationFakeTaskManager:
    """Minimal fake task manager covering registration-service expectations."""

    def __init__(self):
        self._task_status = {}
        self._task_steps = {}
        self._task_progress = {}
        self._task_cancelled = {}
        self._logs = {}
        self._stream_events = {}
        self._closed_streams = []
        self._loop = None

    def set_loop(self, loop):
        self._loop = loop

    def get_loop(self):
        return self._loop

    def is_cancelled(self, task_uuid):
        return self._task_cancelled.get(task_uuid, False)

    def update_status(self, task_uuid, status, **kwargs):
        self._task_status.setdefault(task_uuid, {}).update({"status": status, **kwargs})

    def get_status(self, task_uuid):
        return self._task_status.get(task_uuid)

    def close_task_stream(self, task_uuid, final_status):
        self._closed_streams.append((task_uuid, final_status))

    def add_log(self, task_uuid, message):
        self._logs.setdefault(task_uuid, []).append(message)
        self._stream_events.setdefault(task_uuid, []).append(
            {
                "kind": "log_appended",
                "payload": {
                    "entry": {
                        "message": message,
                        "stream": f"task:{task_uuid}",
                        "seq": None,
                    }
                },
            }
        )

    def get_logs(self, task_uuid):
        return list(self._logs.get(task_uuid, []))

    def get_stream_events(self, task_uuid):
        return list(self._stream_events.get(task_uuid, []))

    def create_log_callback(self, task_uuid, prefix="", batch_id=""):
        def _callback(message: str):
            full = f"{prefix} {message}" if prefix else message
            self.add_log(task_uuid, full)

        return _callback

    def clear_task_steps(self, task_uuid):
        self._task_steps.pop(task_uuid, None)
        self._task_progress.pop(task_uuid, None)

    def set_task_steps(self, task_uuid, steps, *, task_progress=None):
        self._task_steps[task_uuid] = list(steps or [])
        if task_progress is None:
            self._task_progress.pop(task_uuid, None)
        else:
            self._task_progress[task_uuid] = dict(task_progress)

    @property
    def executor(self):
        return None


class BatchFakeTaskManager:
    """Shared stub used by batch registration tests to track batch state/logs."""

    def __init__(self):
        self._batch_status = {}
        self._batch_logs = {}
        self._task_status = {}
        self._task_logs = {}
        self._cancelled = set()
        self._closed_streams = []
        self._loop = None

    def set_loop(self, loop):
        self._loop = loop

    def get_loop(self):
        return self._loop

    def init_batch(self, batch_id, total, **kwargs):
        self._batch_status[batch_id] = {
            "status": "running",
            "total": total,
            "completed": 0,
            "success": 0,
            "failed": 0,
            "current_index": 0,
            "finished": False,
            **kwargs,
        }

    def update_batch_status(self, batch_id, **kwargs):
        self._batch_status.setdefault(batch_id, {}).update(kwargs)

    def get_batch_status(self, batch_id):
        return self._batch_status.get(batch_id)

    def add_batch_log(self, batch_id, message):
        self._batch_logs.setdefault(batch_id, []).append(message)

    def get_batch_logs(self, batch_id):
        return list(self._batch_logs.get(batch_id, []))

    def update_status(self, task_uuid, status, **kwargs):
        self._task_status.setdefault(task_uuid, {}).update({"status": status, **kwargs})

    def add_log(self, task_uuid, message):
        self._task_logs.setdefault(task_uuid, []).append(message)

    def get_logs(self, task_uuid):
        return list(self._task_logs.get(task_uuid, []))

    def clear_task_steps(self, task_uuid):
        return None

    def close_task_stream(self, task_uuid, final_status):
        return None

    def is_batch_cancelled(self, batch_id):
        return (
            batch_id in self._cancelled
            or self._batch_status.get(batch_id, {}).get("cancelled", False)
        )

    def cancel_batch(self, batch_id):
        self._cancelled.add(batch_id)
        self._batch_status.setdefault(batch_id, {})["cancelled"] = True

    def close_batch_stream(self, batch_id, final_status):
        self._closed_streams.append((batch_id, final_status))
