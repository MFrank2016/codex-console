from collections import deque

STREAM_BUFFER_SIZE = 1000
LOG_TAIL_SIZE = 10


def task_stream_id(task_uuid: str) -> str:
    return f"task:{task_uuid}"


def batch_stream_id(batch_id: str) -> str:
    return f"batch:{batch_id}"
