from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.monitor import MonitorAlertRead, MonitorTaskCreate, MonitorTaskRead
from app.services.monitor_service import (
    create_monitor_task,
    delete_monitor_task,
    list_monitor_alerts,
    list_monitor_tasks,
)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.get("", response_model=list[MonitorTaskRead])
def read_monitors(session: Session = Depends(get_session)) -> list[MonitorTaskRead]:
    return [MonitorTaskRead.model_validate(item) for item in list_monitor_tasks(session)]


@router.post("", response_model=MonitorTaskRead)
def create_monitor(
    payload: MonitorTaskCreate,
    session: Session = Depends(get_session),
) -> MonitorTaskRead:
    task = create_monitor_task(session, payload)
    result = MonitorTaskRead.model_validate(task)

    # Register with the running scheduler
    try:
        from app.services.scheduler_service import add_monitor_job

        add_monitor_job(task.appid, task.id or 0, task.interval_minutes)
    except Exception:
        pass  # scheduler may not be running — task is still persisted

    return result


@router.get("/alerts", response_model=list[MonitorAlertRead])
def read_monitor_alerts(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[MonitorAlertRead]:
    return [MonitorAlertRead.model_validate(item) for item in list_monitor_alerts(session, limit)]


@router.delete("/{monitor_id}", status_code=204)
def delete_monitor(monitor_id: int, session: Session = Depends(get_session)) -> None:
    task = None
    try:
        from app.db.models import MonitorTask
        task = session.get(MonitorTask, monitor_id)
    except Exception:
        pass

    try:
        delete_monitor_task(session, monitor_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Unregister from the running scheduler
    if task is not None:
        try:
            from app.services.scheduler_service import remove_monitor_job

            remove_monitor_job(task.appid, monitor_id)
        except Exception:
            pass
