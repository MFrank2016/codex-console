"""
任务管理器
负责管理后台任务、日志队列和 WebSocket 推送
"""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, List, Callable, Any, Literal
from collections import defaultdict, deque

from ..core.time import utc_now
from src.web.realtime_streams import (
    STREAM_BUFFER_SIZE,
    LOG_TAIL_SIZE,
    task_stream_id,
    batch_stream_id,
    run_stream_id,
    build_log_entry,
)
logger = logging.getLogger(__name__)

# 全局线程池（支持最多 50 个并发注册任务）
_executor = ThreadPoolExecutor(max_workers=50, thread_name_prefix="reg_worker")

# 全局元锁：保护所有 defaultdict 的首次 key 创建（避免多线程竞态）
_meta_lock = threading.Lock()

# 任务日志队列 (task_uuid -> list of structured entries)
_log_queues: Dict[str, List[dict]] = defaultdict(list)
_log_locks: Dict[str, threading.Lock] = {}

# WebSocket 连接管理 (task_uuid -> list of websockets)
_ws_connections: Dict[str, Dict[int, dict]] = defaultdict(dict)
_ws_lock = threading.Lock()

# 旧协议遗留：用于“增量日志”那套逻辑（Task 3 迁移后不再使用，但测试清理会用到）
_ws_sent_index: Dict[str, Dict] = defaultdict(dict)

# 任务状态
_task_status: Dict[str, dict] = {}
_task_steps: Dict[str, List[dict]] = {}
_task_progress: Dict[str, dict] = {}
_experiment_status: Dict[int, dict] = {}

# 任务取消标志
_task_cancelled: Dict[str, bool] = {}

# 批量任务状态 (batch_id -> dict)
_batch_status: Dict[str, dict] = {}
_batch_logs: Dict[str, List[dict]] = defaultdict(list)
_batch_locks: Dict[str, threading.Lock] = {}

# run 任务状态 (run_id -> dict)
_run_status: Dict[int, dict] = {}
_run_progress: Dict[int, dict] = {}
_run_logs: Dict[int, List[dict]] = defaultdict(list)
_run_locks: Dict[int, threading.Lock] = {}

_stream_seq: Dict[str, int] = {}
_stream_events: Dict[str, deque] = {}
_stream_locks: Dict[str, threading.Lock] = {}


def _get_stream_lock(stream_id: str) -> threading.Lock:
    if stream_id not in _stream_locks:
        with _meta_lock:
            if stream_id not in _stream_locks:
                _stream_locks[stream_id] = threading.Lock()
    return _stream_locks[stream_id]


def _get_logs_tail(task_uuid: str, tail_size: int) -> List[dict]:
    with _get_log_lock(task_uuid):
        logs = _log_queues.get(task_uuid, [])
        if tail_size >= len(logs):
            return list(logs)
        return list(logs[-tail_size:])


def _get_batch_logs_tail(batch_id: str, tail_size: int) -> List[dict]:
    with _get_batch_lock(batch_id):
        logs = _batch_logs.get(batch_id, [])
        if tail_size >= len(logs):
            return list(logs)
        return list(logs[-tail_size:])


def _get_run_lock(run_id: int) -> threading.Lock:
    if run_id not in _run_locks:
        with _meta_lock:
            if run_id not in _run_locks:
                _run_locks[run_id] = threading.Lock()
    return _run_locks[run_id]


def _get_run_logs_tail(run_id: int, tail_size: int) -> List[dict]:
    with _get_run_lock(run_id):
        logs = _run_logs.get(run_id, [])
        if tail_size >= len(logs):
            return list(logs)
        return list(logs[-tail_size:])



def _get_log_lock(task_uuid: str) -> threading.Lock:
    """线程安全地获取或创建任务日志锁"""
    if task_uuid not in _log_locks:
        with _meta_lock:
            if task_uuid not in _log_locks:
                _log_locks[task_uuid] = threading.Lock()
    return _log_locks[task_uuid]


def _get_batch_lock(batch_id: str) -> threading.Lock:
    """线程安全地获取或创建批量任务日志锁"""
    if batch_id not in _batch_locks:
        with _meta_lock:
            if batch_id not in _batch_locks:
                _batch_locks[batch_id] = threading.Lock()
    return _batch_locks[batch_id]


class TaskManager:
    """任务管理器"""

    def __init__(self):
        self.executor = _executor
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """设置事件循环（在 FastAPI 启动时调用）"""
        self._loop = loop

    def append_stream_event(self, stream_id: str, kind: str, payload: dict) -> dict:
        """记录 stream 事件并维护递增 seq"""
        lock = _get_stream_lock(stream_id)
        with lock:
            seq = _stream_seq.get(stream_id, 0) + 1
            _stream_seq[stream_id] = seq
            payload_copy = payload.copy() if isinstance(payload, dict) else payload
            event = {
                "seq": seq,
                "stream": stream_id,
                "kind": kind,
                "timestamp": utc_now().isoformat(),
                "payload": payload_copy,
            }
            buffer = _stream_events.get(stream_id)
            if buffer is None:
                buffer = deque(maxlen=STREAM_BUFFER_SIZE)
                _stream_events[stream_id] = buffer
            buffer.append(event)
        return event

    def build_task_stream_snapshot(self, task_uuid: str) -> dict:
        stream_id = task_stream_id(task_uuid)
        task_snapshot = dict(self.get_status(task_uuid) or {})
        steps = self.get_task_steps(task_uuid)
        task_progress = self.get_task_progress(task_uuid)
        current_step = steps[-1] if steps else {}
        logs_tail = _get_logs_tail(task_uuid, LOG_TAIL_SIZE)
        lock = _get_stream_lock(stream_id)
        with lock:
            seq = _stream_seq.get(stream_id, 0)
        return {
            "seq": seq,
            "stream": stream_id,
            "kind": "snapshot",
            "timestamp": utc_now().isoformat(),
            "payload": {
                "task": task_snapshot,
                "current_step": current_step,
                "steps": steps,
                "task_progress": task_progress,
                "logs_tail": logs_tail,
            },
        }

    def build_batch_stream_snapshot(self, batch_id: str) -> dict:
        stream_id = batch_stream_id(batch_id)
        batch_snapshot = dict(self.get_batch_status(batch_id) or {})
        logs_tail = _get_batch_logs_tail(batch_id, LOG_TAIL_SIZE)
        lock = _get_stream_lock(stream_id)
        with lock:
            seq = _stream_seq.get(stream_id, 0)
        return {
            "seq": seq,
            "stream": stream_id,
            "kind": "snapshot",
            "timestamp": utc_now().isoformat(),
            "payload": {
                "batch": batch_snapshot,
                "logs_tail": logs_tail,
            },
        }

    def build_run_stream_snapshot(self, run_id: int) -> dict:
        stream_id = run_stream_id(run_id)
        run_snapshot = dict(_run_status.get(run_id) or {})
        run_progress = _run_progress.get(run_id)
        logs_tail = _get_run_logs_tail(run_id, LOG_TAIL_SIZE)
        lock = _get_stream_lock(stream_id)
        with lock:
            seq = _stream_seq.get(stream_id, 0)
        return {
            "seq": seq,
            "stream": stream_id,
            "kind": "snapshot",
            "timestamp": utc_now().isoformat(),
            "payload": {
                "run": run_snapshot,
                "run_progress": dict(run_progress) if isinstance(run_progress, dict) else None,
                "logs_tail": logs_tail,
            },
        }

    def get_stream_events_after(self, stream_id: str, after_seq: int) -> List[dict]:
        lock = _get_stream_lock(stream_id)
        with lock:
            events = list(_stream_events.get(stream_id, []))
        return [event for event in events if event["seq"] > after_seq]

    def is_stream_after_seq_expired(self, stream_id: str, after_seq: int) -> bool:
        """判断 after_seq 是否已过期（事件缓冲区无法覆盖缺失区间）。"""
        lock = _get_stream_lock(stream_id)
        with lock:
            buffer = _stream_events.get(stream_id)
            if not buffer:
                return False
            oldest_seq = buffer[0]["seq"]
        return after_seq < (oldest_seq - 1)

    def _stream_ws_key_for_batch(self, batch_id: str) -> str:
        return f"batch_{batch_id}"

    def _ensure_ws_state(
        self,
        ws_key: str,
        websocket: Any,
        *,
        mode: Literal["replaying", "active"],
        after_seq: int,
    ) -> None:
        ws_id = id(websocket)
        with _ws_lock:
            states = _ws_connections[ws_key]
            if ws_id in states:
                states[ws_id]["mode"] = mode
                states[ws_id]["last_sent_seq"] = min(states[ws_id]["last_sent_seq"], after_seq)
                return
            states[ws_id] = {
                "ws_id": ws_id,
                "websocket": websocket,
                "mode": mode,
                "pending": [],
                "last_sent_seq": after_seq,
                "send_lock": asyncio.Lock(),
            }

    def _get_ws_state(self, ws_key: str, websocket: Any) -> Optional[dict]:
        ws_id = id(websocket)
        with _ws_lock:
            return _ws_connections.get(ws_key, {}).get(ws_id)

    async def _send_stream_event(self, ws_key: str, websocket: Any, event: dict) -> None:
        state = self._get_ws_state(ws_key, websocket)
        if state is None:
            return
        send_lock = state["send_lock"]
        async with send_lock:
            await websocket.send_json(event)
        with _ws_lock:
            current = _ws_connections.get(ws_key, {}).get(state["ws_id"])
            if current is not None:
                current["last_sent_seq"] = max(current["last_sent_seq"], int(event.get("seq", 0)))

    async def _send_control_message(self, ws_key: str, websocket: Any, payload: dict) -> None:
        """发送控制消息（ping/pong 等），复用同一 websocket 的 send_lock，避免并发 send。"""
        state = self._get_ws_state(ws_key, websocket)
        if state is None:
            await websocket.send_json(payload)
            return
        send_lock = state["send_lock"]
        async with send_lock:
            await websocket.send_json(payload)

    async def broadcast_task_stream_event(self, task_uuid: str, event: dict) -> None:
        """向 task WebSocket 连接广播 stream 事件（replay 期间先入队，结束后按 seq flush）。"""
        ws_key = task_uuid
        # 关键点：不能使用 targets 快照里的 mode（replaying/active）来做决策，
        # 否则在 replay -> active 切换窗口可能发生“既不 append pending 也不发送”的静默丢事件。
        with _ws_lock:
            ws_ids = list(_ws_connections.get(ws_key, {}).keys())

        for ws_id in ws_ids:
            with _ws_lock:
                current = _ws_connections.get(ws_key, {}).get(ws_id)
                if current is None:
                    continue
                if current["mode"] == "replaying":
                    current["pending"].append(event)
                    continue
                websocket = current["websocket"]
            try:
                await self._send_stream_event(ws_key, websocket, event)
            except Exception as e:
                logger.warning(f"WebSocket 发送 task stream 事件失败: {e}")

    async def broadcast_batch_stream_event(self, batch_id: str, event: dict) -> None:
        """向 batch WebSocket 连接广播 stream 事件（replay 期间先入队，结束后按 seq flush）。"""
        ws_key = self._stream_ws_key_for_batch(batch_id)
        with _ws_lock:
            ws_ids = list(_ws_connections.get(ws_key, {}).keys())

        for ws_id in ws_ids:
            with _ws_lock:
                current = _ws_connections.get(ws_key, {}).get(ws_id)
                if current is None:
                    continue
                if current["mode"] == "replaying":
                    current["pending"].append(event)
                    continue
                websocket = current["websocket"]
            try:
                await self._send_stream_event(ws_key, websocket, event)
            except Exception as e:
                logger.warning(f"WebSocket 发送 batch stream 事件失败: {e}")

    async def send_task_stream_event(self, task_uuid: str, websocket: Any, event: dict) -> None:
        """replay 阶段：向指定 task websocket 发送事件并推进 last_sent_seq。"""
        await self._send_stream_event(task_uuid, websocket, event)

    async def send_batch_stream_event(self, batch_id: str, websocket: Any, event: dict) -> None:
        """replay 阶段：向指定 batch websocket 发送事件并推进 last_sent_seq。"""
        await self._send_stream_event(self._stream_ws_key_for_batch(batch_id), websocket, event)

    async def send_task_control_message(self, task_uuid: str, websocket: Any, payload: dict) -> None:
        await self._send_control_message(task_uuid, websocket, payload)

    async def send_batch_control_message(self, batch_id: str, websocket: Any, payload: dict) -> None:
        await self._send_control_message(self._stream_ws_key_for_batch(batch_id), websocket, payload)

    async def finish_task_websocket_replay(self, task_uuid: str, websocket: Any) -> None:
        """结束 replay：按 seq flush pending，再切换为 active。"""
        ws_key = task_uuid
        while True:
            state = self._get_ws_state(ws_key, websocket)
            if state is None:
                return
            with _ws_lock:
                current = _ws_connections.get(ws_key, {}).get(state["ws_id"])
                if current is None:
                    return
                last_sent_seq = current["last_sent_seq"]
                pending = list(current["pending"])
                current["pending"] = []

            to_send = [item for item in pending if int(item.get("seq", 0)) > last_sent_seq]
            to_send.sort(key=lambda item: int(item.get("seq", 0)))
            for item in to_send:
                try:
                    await self._send_stream_event(ws_key, websocket, item)
                except Exception as e:
                    logger.warning(f"WebSocket replay flush 发送失败: {e}")
                    return

            with _ws_lock:
                current = _ws_connections.get(ws_key, {}).get(state["ws_id"])
                if current is None:
                    return
                if current["pending"]:
                    continue
                current["mode"] = "active"
                return

    async def finish_batch_websocket_replay(self, batch_id: str, websocket: Any) -> None:
        ws_key = self._stream_ws_key_for_batch(batch_id)
        while True:
            state = self._get_ws_state(ws_key, websocket)
            if state is None:
                return
            with _ws_lock:
                current = _ws_connections.get(ws_key, {}).get(state["ws_id"])
                if current is None:
                    return
                last_sent_seq = current["last_sent_seq"]
                pending = list(current["pending"])
                current["pending"] = []

            to_send = [item for item in pending if int(item.get("seq", 0)) > last_sent_seq]
            to_send.sort(key=lambda item: int(item.get("seq", 0)))
            for item in to_send:
                try:
                    await self._send_stream_event(ws_key, websocket, item)
                except Exception as e:
                    logger.warning(f"WebSocket replay flush 发送失败: {e}")
                    return

            with _ws_lock:
                current = _ws_connections.get(ws_key, {}).get(state["ws_id"])
                if current is None:
                    return
                if current["pending"]:
                    continue
                current["mode"] = "active"
                return

    def get_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """获取事件循环"""
        return self._loop

    def is_cancelled(self, task_uuid: str) -> bool:
        """检查任务是否已取消"""
        return _task_cancelled.get(task_uuid, False)

    def cancel_task(self, task_uuid: str):
        """取消任务"""
        _task_cancelled[task_uuid] = True
        logger.info(f"任务 {task_uuid} 已标记为取消")

    def add_log(self, task_uuid: str, log_message: str):
        """添加日志并推送到 WebSocket（线程安全）"""
        with _get_log_lock(task_uuid):
            stream_id = task_stream_id(task_uuid)
            entry = build_log_entry(
                stream=stream_id,
                message=log_message,
                source="task",
            )
            _log_queues[task_uuid].append(entry)
            event = self.append_stream_event(
                stream_id,
                "log_appended",
                {"entry": entry},
            )
            event_entry = event["payload"]["entry"]
            event_entry["seq"] = event["seq"]
            event_entry["stream"] = event["stream"]
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_task_stream_event(task_uuid, event),
                    self._loop,
                )
            except Exception as e:
                logger.warning(f"推送 task stream 事件到 WebSocket 失败: {e}")

    def register_websocket(
        self,
        task_uuid: str,
        websocket: Any,
        *,
        mode: Literal["replaying", "active"] = "active",
        after_seq: int = 0,
    ):
        """注册 task WebSocket 连接。

        说明：
        - 业务事件：走 stream envelope（seq/stream/kind/payload）
        - 控制消息：依然走 {"type": "ping"/"pong"/"cancel"}
        """
        self._ensure_ws_state(task_uuid, websocket, mode=mode, after_seq=after_seq)
        logger.info(f"WebSocket 连接已注册(task): {task_uuid} mode={mode}")

    def unregister_websocket(self, task_uuid: str, websocket):
        """注销 WebSocket 连接"""
        ws_id = id(websocket)
        with _ws_lock:
            if task_uuid in _ws_connections:
                _ws_connections[task_uuid].pop(ws_id, None)
            if task_uuid in _ws_sent_index:
                _ws_sent_index[task_uuid].pop(ws_id, None)
        logger.info(f"WebSocket 连接已注销: {task_uuid}")

    def get_logs(self, task_uuid: str) -> List[str]:
        """获取任务的所有日志"""
        with _get_log_lock(task_uuid):
            return [str(item.get("message", "")) for item in _log_queues.get(task_uuid, [])]

    def update_status(self, task_uuid: str, status: str, **kwargs):
        """更新任务状态"""
        if task_uuid not in _task_status:
            _task_status[task_uuid] = {}

        _task_status[task_uuid]["status"] = status
        _task_status[task_uuid].update(kwargs)

        event = self.append_stream_event(
            task_stream_id(task_uuid),
            "task_status_changed",
            {"task_uuid": task_uuid, "status": status, **kwargs},
        )
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_task_stream_event(task_uuid, event),
                    self._loop,
                )
            except Exception as e:
                logger.warning(f"广播 task stream 状态事件失败: {e}")

    def get_status(self, task_uuid: str) -> Optional[dict]:
        """获取任务状态"""
        return _task_status.get(task_uuid)

    def task_stream_exists(self, task_uuid: str) -> bool:
        """判断任务 stream 是否存在（状态 / 步骤 / 日志 / 事件任一存在）"""
        stream_id = task_stream_id(task_uuid)
        return (
            task_uuid in _task_status
            or task_uuid in _task_steps
            or task_uuid in _task_progress
            or task_uuid in _log_queues
            or stream_id in _stream_events
        )

    def set_task_steps(
        self,
        task_uuid: str,
        steps: List[dict],
        *,
        task_progress: dict | None = None,
    ):
        """设置任务步骤快照（轻量内存态，供 API 快速读取）。"""
        _task_steps[task_uuid] = list(steps or [])
        if task_progress is None:
            _task_progress.pop(task_uuid, None)
        else:
            _task_progress[task_uuid] = dict(task_progress)
        event = self.append_stream_event(
            task_stream_id(task_uuid),
            "task_step_updated",
            {
                "task_uuid": task_uuid,
                "current_step": _task_steps[task_uuid][-1] if _task_steps[task_uuid] else {},
                "steps": list(_task_steps[task_uuid]),
                "task_progress": dict(_task_progress[task_uuid]) if task_uuid in _task_progress else None,
            },
        )
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_task_stream_event(task_uuid, event),
                    self._loop,
                )
            except Exception as e:
                logger.warning(f"广播 task stream 步骤事件失败: {e}")

    def get_task_steps(self, task_uuid: str) -> List[dict]:
        """获取任务步骤快照。"""
        return list(_task_steps.get(task_uuid, []))

    def get_task_progress(self, task_uuid: str) -> Optional[dict]:
        """获取任务进度快照。"""
        payload = _task_progress.get(task_uuid)
        return dict(payload) if isinstance(payload, dict) else None

    def clear_task_steps(self, task_uuid: str):
        """清理任务步骤快照。"""
        _task_steps.pop(task_uuid, None)
        _task_progress.pop(task_uuid, None)

    def close_task_stream(self, task_uuid: str, *, final_status: str):
        """显式关闭 task stream（用于前端 reducer 停止等待）。"""
        snapshot = _task_status.setdefault(task_uuid, {})
        if snapshot.get("stream_closed"):
            return
        snapshot["stream_closed"] = True
        snapshot["stream_final_status"] = final_status

        event = self.append_stream_event(
            task_stream_id(task_uuid),
            "stream_closed",
            {"task_uuid": task_uuid, "final_status": final_status},
        )
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_task_stream_event(task_uuid, event),
                    self._loop,
                )
            except Exception as e:
                logger.warning(f"广播 task stream 关闭事件失败: {e}")

    def update_run_status(self, run_id: int, status: str, **kwargs):
        """更新 run 状态快照，并写入 run stream 状态事件。"""
        snapshot = _run_status.setdefault(run_id, {})
        snapshot["status"] = status
        snapshot.update(kwargs)

        if "run_progress" in kwargs and kwargs["run_progress"] is not None:
            _run_progress[run_id] = dict(kwargs["run_progress"])

        self.append_stream_event(
            run_stream_id(run_id),
            "run_status_changed",
            {"run_id": run_id, "status": status, **kwargs},
        )

    def add_run_log(self, run_id: int, log_entry: dict):
        """追加 run 结构化日志，并写入 stream 事件。"""
        stream_id = run_stream_id(run_id)
        known_fields = {"timestamp", "display_time", "level", "message", "raw", "source", "stream", "seq"}
        message = str(log_entry.get("message", ""))
        extra = {k: v for k, v in log_entry.items() if k not in known_fields}

        with _get_run_lock(run_id):
            entry = build_log_entry(
                stream=stream_id,
                message=message,
                timestamp=log_entry.get("timestamp"),
                display_time=log_entry.get("display_time"),
                level=log_entry.get("level", "INFO"),
                raw=log_entry.get("raw"),
                source=log_entry.get("source", "run"),
                extra=extra,
            )
            _run_logs[run_id].append(entry)
            event = self.append_stream_event(
                stream_id,
                "log_appended",
                {"entry": entry},
            )
            event_entry = event["payload"]["entry"]
            event_entry["seq"] = event["seq"]
            event_entry["stream"] = event["stream"]

    def run_stream_exists(self, run_id: int) -> bool:
        stream_id = run_stream_id(run_id)
        return (
            run_id in _run_status
            or run_id in _run_progress
            or run_id in _run_logs
            or stream_id in _stream_events
        )

    def close_run_stream(self, run_id: int, *, final_status: str):
        snapshot = _run_status.setdefault(run_id, {})
        if snapshot.get("stream_closed"):
            return
        snapshot["stream_closed"] = True
        snapshot["stream_final_status"] = final_status
        self.append_stream_event(
            run_stream_id(run_id),
            "stream_closed",
            {"run_id": run_id, "final_status": final_status},
        )

    def init_experiment(
        self,
        experiment_id: int,
        *,
        status: str,
        total_pairs: int,
        total_tasks: int,
        pipelines: List[str],
    ):
        """初始化实验批次轻量状态。"""
        _experiment_status[experiment_id] = {
            "status": status,
            "total_pairs": total_pairs,
            "total_tasks": total_tasks,
            "pipelines": list(pipelines),
        }

    def update_experiment_status(self, experiment_id: int, **kwargs):
        """更新实验批次轻量状态。"""
        if experiment_id not in _experiment_status:
            _experiment_status[experiment_id] = {}
        _experiment_status[experiment_id].update(kwargs)

    def get_experiment_status(self, experiment_id: int) -> Optional[dict]:
        """获取实验批次轻量状态。"""
        snapshot = _experiment_status.get(experiment_id)
        return dict(snapshot) if snapshot is not None else None

    def clear_experiment_status(self, experiment_id: int):
        """清理实验批次轻量状态。"""
        _experiment_status.pop(experiment_id, None)

    def cleanup_task(self, task_uuid: str):
        """清理任务数据"""
        # 保留日志队列一段时间，以便后续查询
        # 只清理取消标志
        if task_uuid in _task_cancelled:
            del _task_cancelled[task_uuid]
        self.clear_task_steps(task_uuid)

    # ============== 批量任务管理 ==============

    def init_batch(
        self,
        batch_id: str,
        total: int,
        *,
        is_unlimited: bool = False,
        consecutive_failures: int = 0,
        max_consecutive_failures: int = 10,
        stop_reason: Optional[str] = None,
        domain_stats: Optional[List[dict]] = None,
    ):
        """初始化批量任务"""
        _batch_status[batch_id] = {
            "status": "running",
            "total": total,
            "completed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "current_index": 0,
            "finished": False,
            "is_unlimited": is_unlimited,
            "consecutive_failures": consecutive_failures,
            "max_consecutive_failures": max_consecutive_failures,
            "stop_reason": stop_reason,
            "domain_stats": [] if domain_stats is None else list(domain_stats),
        }
        logger.info(f"批量任务 {batch_id} 已初始化，总数: {total}")

    def add_batch_log(self, batch_id: str, log_message: str):
        """添加批量任务日志并推送"""
        with _get_batch_lock(batch_id):
            stream_id = batch_stream_id(batch_id)
            entry = build_log_entry(
                stream=stream_id,
                message=log_message,
                source="batch",
            )
            _batch_logs[batch_id].append(entry)
            event = self.append_stream_event(
                stream_id,
                "log_appended",
                {"entry": entry},
            )
            event_entry = event["payload"]["entry"]
            event_entry["seq"] = event["seq"]
            event_entry["stream"] = event["stream"]
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_batch_stream_event(batch_id, event),
                    self._loop,
                )
            except Exception as e:
                logger.warning(f"推送 batch stream 事件到 WebSocket 失败: {e}")

    def update_batch_status(self, batch_id: str, **kwargs):
        """更新批量任务状态"""
        if batch_id not in _batch_status:
            logger.warning(f"批量任务 {batch_id} 不存在")
            return

        if "domain_stats" in kwargs and kwargs["domain_stats"] is not None:
            kwargs["domain_stats"] = list(kwargs["domain_stats"])

        _batch_status[batch_id].update(kwargs)

        event = self.append_stream_event(
            batch_stream_id(batch_id),
            "batch_progress_updated",
            {"batch_id": batch_id, **_batch_status[batch_id]},
        )
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_batch_stream_event(batch_id, event),
                    self._loop,
                )
            except Exception as e:
                logger.warning(f"广播 batch stream 状态事件失败: {e}")

    def close_batch_stream(self, batch_id: str, *, final_status: str):
        """显式关闭 batch stream（用于前端 reducer 停止等待）。"""
        snapshot = _batch_status.setdefault(batch_id, {})
        if snapshot.get("stream_closed"):
            return
        snapshot["stream_closed"] = True
        snapshot["stream_final_status"] = final_status

        event = self.append_stream_event(
            batch_stream_id(batch_id),
            "stream_closed",
            {"batch_id": batch_id, "final_status": final_status},
        )
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(
                    self.broadcast_batch_stream_event(batch_id, event),
                    self._loop,
                )
            except Exception as e:
                logger.warning(f"广播 batch stream 关闭事件失败: {e}")

    def get_batch_status(self, batch_id: str) -> Optional[dict]:
        """获取批量任务状态"""
        return _batch_status.get(batch_id)

    def batch_stream_exists(self, batch_id: str) -> bool:
        """判断批量 stream 是否存在（状态 / 日志 / 事件任一存在）"""
        stream_id = batch_stream_id(batch_id)
        return (
            batch_id in _batch_status
            or batch_id in _batch_logs
            or stream_id in _stream_events
        )

    def get_batch_logs(self, batch_id: str) -> List[str]:
        """获取批量任务日志"""
        with _get_batch_lock(batch_id):
            return [str(item.get("message", "")) for item in _batch_logs.get(batch_id, [])]

    def is_batch_cancelled(self, batch_id: str) -> bool:
        """检查批量任务是否已取消"""
        status = _batch_status.get(batch_id, {})
        return status.get("cancelled", False)

    def cancel_batch(self, batch_id: str):
        """取消批量任务"""
        if batch_id in _batch_status:
            _batch_status[batch_id]["cancelled"] = True
            _batch_status[batch_id]["status"] = "cancelling"
            logger.info(f"批量任务 {batch_id} 已标记为取消")

    def register_batch_websocket(
        self,
        batch_id: str,
        websocket: Any,
        *,
        mode: Literal["replaying", "active"] = "active",
        after_seq: int = 0,
    ):
        """注册 batch WebSocket 连接（支持 replaying/active）。"""
        self._ensure_ws_state(
            self._stream_ws_key_for_batch(batch_id),
            websocket,
            mode=mode,
            after_seq=after_seq,
        )
        logger.info(f"批量任务 WebSocket 连接已注册(batch): {batch_id} mode={mode}")

    def unregister_batch_websocket(self, batch_id: str, websocket):
        """注销批量任务 WebSocket 连接"""
        key = self._stream_ws_key_for_batch(batch_id)
        ws_id = id(websocket)
        with _ws_lock:
            if key in _ws_connections:
                _ws_connections[key].pop(ws_id, None)
            if key in _ws_sent_index:
                _ws_sent_index[key].pop(ws_id, None)
        logger.info(f"批量任务 WebSocket 连接已注销: {batch_id}")

    def create_log_callback(self, task_uuid: str, prefix: str = "", batch_id: str = "") -> Callable[[str], None]:
        """创建日志回调函数，可附加任务编号前缀，并同时推送到批量任务频道"""
        def callback(msg: str):
            full_msg = f"{prefix} {msg}" if prefix else msg
            self.add_log(task_uuid, full_msg)
            # 如果属于批量任务，同步推送到 batch 频道，前端可在混合日志中看到详细步骤
            if batch_id:
                self.add_batch_log(batch_id, full_msg)
        return callback

    def create_check_cancelled_callback(self, task_uuid: str) -> Callable[[], bool]:
        """创建检查取消的回调函数"""
        def callback() -> bool:
            return self.is_cancelled(task_uuid)
        return callback


# 全局实例
task_manager = TaskManager()
