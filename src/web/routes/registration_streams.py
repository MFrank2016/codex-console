from fastapi import APIRouter, Query

from ..task_manager import task_manager
from ..realtime_streams import task_stream_id, batch_stream_id

router = APIRouter()


@router.get("/task/{task_uuid}/snapshot")
async def get_task_stream_snapshot(task_uuid: str):
    return task_manager.build_task_stream_snapshot(task_uuid)


@router.get("/task/{task_uuid}/events")
async def get_task_stream_events(task_uuid: str, after_seq: int = Query(0, ge=0)):
    stream = task_stream_id(task_uuid)
    return {
        "stream": stream,
        "events": task_manager.get_stream_events_after(stream, after_seq=after_seq),
    }


@router.get("/batch/{batch_id}/snapshot")
async def get_batch_stream_snapshot(batch_id: str):
    return task_manager.build_batch_stream_snapshot(batch_id)


@router.get("/batch/{batch_id}/events")
async def get_batch_stream_events(batch_id: str, after_seq: int = Query(0, ge=0)):
    stream = batch_stream_id(batch_id)
    return {
        "stream": stream,
        "events": task_manager.get_stream_events_after(stream, after_seq=after_seq),
    }
