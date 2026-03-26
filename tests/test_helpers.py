import queue
import threading


def receive_json_with_timeout(ws, *, timeout_s: float = 1.0):
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
