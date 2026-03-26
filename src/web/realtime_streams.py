from datetime import datetime
from typing import Any, Dict

from ..core.time import utc_now


STREAM_BUFFER_SIZE = 1000
LOG_TAIL_SIZE = 10
LOG_ENTRY_RESERVED_FIELDS = {
    "timestamp",
    "display_time",
    "level",
    "message",
    "raw",
    "source",
    "stream",
    "seq",
}


def task_stream_id(task_uuid: str) -> str:
    return f"task:{task_uuid}"


def batch_stream_id(batch_id: str) -> str:
    return f"batch:{batch_id}"


def run_stream_id(run_id: int) -> str:
    return f"run:{run_id}"


def _derive_display_time(timestamp: str | None) -> str | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.strftime("%H:%M:%S")


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
    resolved_timestamp = timestamp or now.isoformat()
    resolved_display_time = display_time or _derive_display_time(resolved_timestamp) or now.strftime("%H:%M:%S")
    entry: Dict[str, Any] = {
        "timestamp": resolved_timestamp,
        "display_time": resolved_display_time,
        "level": level,
        "message": message,
        "raw": raw or message,
        "source": source or "system",
        "stream": stream,
        "seq": seq,
    }
    if extra:
        for key, value in extra.items():
            if key not in LOG_ENTRY_RESERVED_FIELDS:
                entry[key] = value
    return entry
