from fastapi import APIRouter, Query

from . import realtime_streams as realtime_stream_routes

router = APIRouter()


@router.get('/task/{task_uuid}/snapshot')
async def get_task_stream_snapshot(task_uuid: str):
    return await realtime_stream_routes.get_task_stream_snapshot(task_uuid)


@router.get('/task/{task_uuid}/events')
async def get_task_stream_events(task_uuid: str, after_seq: int = Query(0, ge=0)):
    return await realtime_stream_routes.get_task_stream_events(task_uuid, after_seq=after_seq)


@router.get('/batch/{batch_id}/snapshot')
async def get_batch_stream_snapshot(batch_id: str):
    return await realtime_stream_routes.get_batch_stream_snapshot(batch_id)


@router.get('/batch/{batch_id}/events')
async def get_batch_stream_events(batch_id: str, after_seq: int = Query(0, ge=0)):
    return await realtime_stream_routes.get_batch_stream_events(batch_id, after_seq=after_seq)
