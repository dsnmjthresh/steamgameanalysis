"""Task queue API — enqueue, poll, cancel background tasks."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.core.logging import get_request_id
from app.db.session import get_session
from app.schemas.task import TaskCreate, TaskRead
from app.services import task_queue as tq
from app.services.memory_service import resolve_user

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _to_read(task) -> TaskRead:
    """Convert an ORM ``BackgroundTask`` into a ``TaskRead`` response.

    Parses structured error_message to extract ``error_code`` and a
    human-readable ``error_detail`` for frontend consumption.
    """
    from app.schemas.common import load_json

    error_code, error_detail = tq._parse_error_db(task.error_message)

    return TaskRead(
        id=task.id or 0,
        task_type=task.task_type,
        status=task.status,
        progress_pct=task.progress_pct,
        progress_message=task.progress_message,
        input_data=load_json(task.input_json, {}),
        result_data=load_json(task.result_json, {}),
        error_message=error_detail,  # human-readable detail
        error_code=error_code,       # machine-readable code
        trace_id=task.trace_id,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        cancelled_at=task.cancelled_at,
    )


@router.post("", response_model=TaskRead, status_code=202)
def create_task(
    payload: TaskCreate,
    session: Session = Depends(get_session),
) -> TaskRead:
    """Enqueue a background task."""
    user_id = None
    if payload.user_key:
        user = resolve_user(session, payload.user_key)
        user_id = user.id if user else None

    task = tq.enqueue_task(
        session,
        task_type=payload.task_type,
        input_data=payload.input_data,
        user_id=user_id,
        trace_id=get_request_id(),
    )
    return _to_read(task)


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, session: Session = Depends(get_session)) -> TaskRead:
    """Poll task status.

    Returns the full task record including ``error_code`` (for failed tasks),
    ``error_message`` (human-readable), ``result_data`` (for completed tasks),
    and ``trace_id`` for log correlation.
    """
    task = tq.poll_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _to_read(task)


@router.post("/{task_id}/cancel", response_model=TaskRead)
def cancel_task(task_id: int, session: Session = Depends(get_session)) -> TaskRead:
    """Cancel a pending or running task.

    - *pending* → cancelled immediately.
    - *running* → marked cancelled; the handler will abort cooperatively.
    - Terminal states (completed/failed/cancelled) → returned unchanged
      (status code 200, no state mutation).
    """
    task = tq.cancel_task(session, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return _to_read(task)


@router.get("", response_model=list[TaskRead])
def list_tasks(
    status: str | None = Query(default=None, description="Filter by status"),
    task_type: str | None = Query(default=None, description="Filter by task type"),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[TaskRead]:
    tasks = tq.list_tasks(session, status=status, task_type=task_type, limit=limit)
    return [_to_read(task) for task in tasks]
