"""
WebSocket 路由
提供任务/批量/run stream 事件回放与实时推送
"""

import asyncio
import logging
from typing import Awaitable, Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..realtime_streams import batch_stream_id, run_stream_id, task_stream_id
from ..task_manager import task_manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_after_seq(websocket: WebSocket) -> int:
    raw_value = websocket.query_params.get("after_seq", "0")
    try:
        parsed = int(raw_value) if raw_value is not None else 0
    except ValueError:
        logger.warning("WebSocket after_seq 非法，使用默认值 0: value=%s", raw_value)
        return 0
    if parsed < 0:
        logger.warning("WebSocket after_seq 小于 0，已自动钳制到 0: value=%s", raw_value)
        return 0
    return parsed


async def _serve_stream_websocket(
    websocket: WebSocket,
    *,
    stream_id: str,
    register: Callable[[int], None],
    send_control: Callable[[WebSocket, dict], Awaitable[None]],
    send_event: Callable[[WebSocket, dict], Awaitable[None]],
    finish_replay: Callable[[WebSocket], Awaitable[None]],
    unregister: Callable[[WebSocket], None],
    connected_log_label: str,
    disconnect_log_label: str,
    error_log_label: str,
    heartbeat_failed_log_label: str,
    on_cancel: Callable[[], None] | None = None,
) -> None:
    await websocket.accept()
    after_seq = _parse_after_seq(websocket)

    register(after_seq)

    if task_manager.is_stream_after_seq_expired(stream_id, after_seq=after_seq):
        await send_control(
            websocket,
            {
                "stream": stream_id,
                "kind": "snapshot_required",
                "payload": {"reason": "after_seq_expired"},
            },
        )
    else:
        replay = task_manager.get_stream_events_after(stream_id, after_seq=after_seq)
        for event in replay:
            await send_event(websocket, event)

    await finish_replay(websocket)
    logger.info("%s", connected_log_label)

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)

                if data.get("type") == "ping":
                    await send_control(websocket, {"type": "pong"})
                elif data.get("type") == "cancel" and on_cancel is not None:
                    on_cancel()

            except asyncio.TimeoutError:
                try:
                    await send_control(websocket, {"type": "ping"})
                except Exception:
                    logger.info("%s", heartbeat_failed_log_label)
                    break

    except WebSocketDisconnect:
        logger.info("%s", disconnect_log_label)

    except Exception:
        logger.exception("%s", error_log_label)

    finally:
        unregister(websocket)


@router.websocket("/ws/task/{task_uuid}")
async def task_websocket(websocket: WebSocket, task_uuid: str):
    stream_id = task_stream_id(task_uuid)

    def _on_task_cancel() -> None:
        task_manager.cancel_task(task_uuid)
        task_manager.update_status(
            task_uuid,
            "cancelling",
            message="取消请求已提交，正在踩刹车，别慌",
        )

    await _serve_stream_websocket(
        websocket,
        stream_id=stream_id,
        register=lambda after_seq: task_manager.register_websocket(
            task_uuid,
            websocket,
            mode="replaying",
            after_seq=after_seq,
        ),
        send_control=lambda ws, payload: task_manager.send_task_control_message(task_uuid, ws, payload),
        send_event=lambda ws, event: task_manager.send_task_stream_event(task_uuid, ws, event),
        finish_replay=lambda ws: task_manager.finish_task_websocket_replay(task_uuid, ws),
        unregister=lambda ws: task_manager.unregister_websocket(task_uuid, ws),
        connected_log_label=f"WebSocket 连接已建立(task): {task_uuid}",
        disconnect_log_label=f"WebSocket 断开: {task_uuid}",
        error_log_label="WebSocket 错误",
        heartbeat_failed_log_label=f"WebSocket 心跳检测失败: {task_uuid}",
        on_cancel=_on_task_cancel,
    )


@router.websocket("/ws/batch/{batch_id}")
async def batch_websocket(websocket: WebSocket, batch_id: str):
    stream_id = batch_stream_id(batch_id)

    def _on_batch_cancel() -> None:
        task_manager.cancel_batch(batch_id)
        task_manager.update_batch_status(
            batch_id,
            cancelled=True,
            status="cancelling",
            message="取消请求已提交，正在让整队缓缓靠边停车",
        )

    await _serve_stream_websocket(
        websocket,
        stream_id=stream_id,
        register=lambda after_seq: task_manager.register_batch_websocket(
            batch_id,
            websocket,
            mode="replaying",
            after_seq=after_seq,
        ),
        send_control=lambda ws, payload: task_manager.send_batch_control_message(batch_id, ws, payload),
        send_event=lambda ws, event: task_manager.send_batch_stream_event(batch_id, ws, event),
        finish_replay=lambda ws: task_manager.finish_batch_websocket_replay(batch_id, ws),
        unregister=lambda ws: task_manager.unregister_batch_websocket(batch_id, ws),
        connected_log_label=f"批量任务 WebSocket 连接已建立(batch): {batch_id}",
        disconnect_log_label=f"批量任务 WebSocket 断开: {batch_id}",
        error_log_label="批量任务 WebSocket 错误",
        heartbeat_failed_log_label=f"批量任务 WebSocket 心跳检测失败: {batch_id}",
        on_cancel=_on_batch_cancel,
    )


@router.websocket("/ws/run/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: int):
    stream_id = run_stream_id(run_id)

    await _serve_stream_websocket(
        websocket,
        stream_id=stream_id,
        register=lambda after_seq: task_manager.register_run_websocket(
            run_id,
            websocket,
            mode="replaying",
            after_seq=after_seq,
        ),
        send_control=lambda ws, payload: task_manager.send_run_control_message(run_id, ws, payload),
        send_event=lambda ws, event: task_manager.send_run_stream_event(run_id, ws, event),
        finish_replay=lambda ws: task_manager.finish_run_websocket_replay(run_id, ws),
        unregister=lambda ws: task_manager.unregister_run_websocket(run_id, ws),
        connected_log_label=f"WebSocket 连接已建立(run): {run_id}",
        disconnect_log_label=f"Run WebSocket 断开: {run_id}",
        error_log_label="Run WebSocket 错误",
        heartbeat_failed_log_label=f"Run WebSocket 心跳检测失败: {run_id}",
    )
