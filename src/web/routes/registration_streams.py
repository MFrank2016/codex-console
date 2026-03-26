from fastapi import APIRouter, Query

from ..stream_queries import (
    get_batch_events_or_404,
    get_batch_snapshot_or_404,
    get_task_events_or_404,
    get_task_snapshot_or_404,
)

router = APIRouter()


@router.get("/task/{task_uuid}/snapshot")
async def get_task_stream_snapshot(task_uuid: str):
    return get_task_snapshot_or_404(task_uuid)


@router.get("/task/{task_uuid}/events")
async def get_task_stream_events(task_uuid: str, after_seq: int = Query(0, ge=0)):
    return get_task_events_or_404(task_uuid, after_seq=after_seq)


@router.get("/batch/{batch_id}/snapshot")
async def get_batch_stream_snapshot(batch_id: str):
    return get_batch_snapshot_or_404(batch_id)


@router.get("/batch/{batch_id}/events")
async def get_batch_stream_events(batch_id: str, after_seq: int = Query(0, ge=0)):
    return get_batch_events_or_404(batch_id, after_seq=after_seq)
