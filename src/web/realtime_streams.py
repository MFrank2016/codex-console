from typing import Any, Dict

from ..core.time import utc_now


STREAM_BUFFER_SIZE = 1000
LOG_TAIL_SIZE = 10


def task_stream_id(task_uuid: str) -> str:
    return f"task:{task_uuid}"


def batch_stream_id(batch_id: str) -> str:
    return f"batch:{batch_id}"


def run_stream_id(run_id: int) -> str:
    return f"run:{run_id}"


def build_log_entry(
    *,
    stream: str,
    message: str,
    timestamp: str | None = None,
    display_time: str | None = None,
    level: str = "INFO",
    raw: str | None = None,
    source: str | None = None,
    seq: int | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    now = utc_now()
    entry: Dict[str, Any] = {
        "timestamp": timestamp or now.isoformat(),
        "display_time": display_time or now.strftime("%H:%M:%S"),
        "level": level,
        "message": message,
        "raw": raw or message,
        "source": source or "system",
        "stream": stream,
        "seq": seq,
    }
    if extra:
        entry.update(extra)
    return entry
