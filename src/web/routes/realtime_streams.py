from fastapi import APIRouter, HTTPException, Query

from ..realtime_streams import batch_stream_id, run_stream_id, task_stream_id
from ..task_manager import task_manager

router = APIRouter()


def get_task_snapshot_or_404(task_uuid: str) -> dict:
    if not task_manager.task_stream_exists(task_uuid):
        raise HTTPException(status_code=404, detail=f"Task stream '{task_uuid}' not found")
    return task_manager.build_task_stream_snapshot(task_uuid)


def get_task_events_or_404(task_uuid: str, *, after_seq: int) -> dict:
    stream = task_stream_id(task_uuid)
    if not task_manager.task_stream_exists(task_uuid):
        raise HTTPException(status_code=404, detail=f"Task stream '{task_uuid}' not found")
    return {
        "stream": stream,
        "events": task_manager.get_stream_events_after(stream, after_seq=after_seq),
    }


def get_batch_snapshot_or_404(batch_id: str) -> dict:
    if not task_manager.batch_stream_exists(batch_id):
        raise HTTPException(status_code=404, detail=f"Batch stream '{batch_id}' not found")
    return task_manager.build_batch_stream_snapshot(batch_id)


def get_batch_events_or_404(batch_id: str, *, after_seq: int) -> dict:
    stream = batch_stream_id(batch_id)
    if not task_manager.batch_stream_exists(batch_id):
        raise HTTPException(status_code=404, detail=f"Batch stream '{batch_id}' not found")
    return {
        "stream": stream,
        "events": task_manager.get_stream_events_after(stream, after_seq=after_seq),
    }


def get_run_snapshot_or_404(run_id: int) -> dict:
    if not task_manager.run_stream_exists(run_id):
        raise HTTPException(status_code=404, detail=f"Run stream '{run_id}' not found")
    return task_manager.build_run_stream_snapshot(run_id)


def get_run_events_or_404(run_id: int, *, after_seq: int) -> dict:
    stream = run_stream_id(run_id)
    if not task_manager.run_stream_exists(run_id):
        raise HTTPException(status_code=404, detail=f"Run stream '{run_id}' not found")
    return {
        "stream": stream,
        "events": task_manager.get_stream_events_after(stream, after_seq=after_seq),
    }


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


@router.get("/run/{run_id}/snapshot")
async def get_run_stream_snapshot(run_id: int):
    return get_run_snapshot_or_404(run_id)


@router.get("/run/{run_id}/events")
async def get_run_stream_events(run_id: int, after_seq: int = Query(0, ge=0)):
    return get_run_events_or_404(run_id, after_seq=after_seq)
