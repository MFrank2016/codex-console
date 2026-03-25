"""
WebSocket 路由
提供任务/批量 stream 事件回放与实时推送
"""

import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..task_manager import task_manager
from ..realtime_streams import task_stream_id, batch_stream_id

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/task/{task_uuid}")
async def task_websocket(websocket: WebSocket, task_uuid: str):
    """
    任务 stream WebSocket

    消息格式：
    - 服务端发送: {"seq": 1, "stream": "task:xxx", "kind": "...", "timestamp": "...", "payload": {...}}
    - 服务端发送: {"stream": "task:xxx", "kind": "snapshot_required", "payload": {"reason": "after_seq_expired"}}
    - 客户端发送: {"type": "ping"} - 心跳
    - 客户端发送: {"type": "cancel"} - 取消任务
    """
    await websocket.accept()

    stream_id = task_stream_id(task_uuid)
    try:
        after_seq_raw = websocket.query_params.get("after_seq", "0")
        after_seq = int(after_seq_raw) if after_seq_raw is not None else 0
    except ValueError:
        after_seq = 0

    # 业务事件：走 stream envelope；控制消息：走 {"type": "..."}（ping/pong/cancel）
    # 关键点：先注册为 replaying，replay 期间产生的新事件会进入 pending，避免回放/实时切换丢事件竞态。
    task_manager.register_websocket(task_uuid, websocket, mode="replaying", after_seq=after_seq)

    if task_manager.is_stream_after_seq_expired(stream_id, after_seq=after_seq):
        await websocket.send_json({
            "stream": stream_id,
            "kind": "snapshot_required",
            "payload": {"reason": "after_seq_expired"},
        })
    else:
        replay = task_manager.get_stream_events_after(stream_id, after_seq=after_seq)
        for event in replay:
            await task_manager.send_task_stream_event(task_uuid, websocket, event)

    await task_manager.finish_task_websocket_replay(task_uuid, websocket)
    logger.info(f"WebSocket 连接已建立(task): {task_uuid}")

    try:
        # 保持连接，等待客户端消息
        while True:
            try:
                # 使用 wait_for 实现超时，但不是断开连接
                # 而是发送心跳检测
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=30.0  # 30秒超时
                )

                # 处理心跳
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

                # 处理取消请求
                elif data.get("type") == "cancel":
                    task_manager.cancel_task(task_uuid)
                    task_manager.update_status(
                        task_uuid,
                        "cancelling",
                        message="取消请求已提交，正在踩刹车，别慌",
                    )

            except asyncio.TimeoutError:
                # 超时，发送心跳检测
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    # 发送失败，可能是连接断开
                    logger.info(f"WebSocket 心跳检测失败: {task_uuid}")
                    break

    except WebSocketDisconnect:
        logger.info(f"WebSocket 断开: {task_uuid}")

    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")

    finally:
        task_manager.unregister_websocket(task_uuid, websocket)


@router.websocket("/ws/batch/{batch_id}")
async def batch_websocket(websocket: WebSocket, batch_id: str):
    """
    批量 stream WebSocket

    用于批量注册任务的实时状态更新

    消息格式：
    - 服务端发送: {"seq": 1, "stream": "batch:xxx", "kind": "...", "timestamp": "...", "payload": {...}}
    - 服务端发送: {"stream": "batch:xxx", "kind": "snapshot_required", "payload": {"reason": "after_seq_expired"}}
    - 客户端发送: {"type": "ping"} - 心跳
    - 客户端发送: {"type": "cancel"} - 取消批量任务
    """
    await websocket.accept()

    stream_id = batch_stream_id(batch_id)
    try:
        after_seq_raw = websocket.query_params.get("after_seq", "0")
        after_seq = int(after_seq_raw) if after_seq_raw is not None else 0
    except ValueError:
        after_seq = 0

    task_manager.register_batch_websocket(batch_id, websocket, mode="replaying", after_seq=after_seq)

    if task_manager.is_stream_after_seq_expired(stream_id, after_seq=after_seq):
        await websocket.send_json({
            "stream": stream_id,
            "kind": "snapshot_required",
            "payload": {"reason": "after_seq_expired"},
        })
    else:
        replay = task_manager.get_stream_events_after(stream_id, after_seq=after_seq)
        for event in replay:
            await task_manager.send_batch_stream_event(batch_id, websocket, event)

    await task_manager.finish_batch_websocket_replay(batch_id, websocket)
    logger.info(f"批量任务 WebSocket 连接已建立(batch): {batch_id}")

    try:
        # 保持连接，等待客户端消息
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=30.0
                )

                # 处理心跳
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

                # 处理取消请求
                elif data.get("type") == "cancel":
                    task_manager.cancel_batch(batch_id)
                    task_manager.update_batch_status(
                        batch_id,
                        cancelled=True,
                        status="cancelling",
                        message="取消请求已提交，正在让整队缓缓靠边停车",
                    )

            except asyncio.TimeoutError:
                # 超时，发送心跳检测
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    logger.info(f"批量任务 WebSocket 心跳检测失败: {batch_id}")
                    break

    except WebSocketDisconnect:
        logger.info(f"批量任务 WebSocket 断开: {batch_id}")

    except Exception as e:
        logger.error(f"批量任务 WebSocket 错误: {e}")

    finally:
        task_manager.unregister_batch_websocket(batch_id, websocket)
