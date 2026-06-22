from sqlmodel import Session, select

from app.db.models import MonitorAlert, MonitorTask
from app.schemas.monitor import MonitorTaskCreate


def list_monitor_tasks(session: Session) -> list[MonitorTask]:
    return list(session.exec(select(MonitorTask).order_by(MonitorTask.created_at.desc())).all())  # type: ignore[attr-defined]


def create_monitor_task(session: Session, payload: MonitorTaskCreate) -> MonitorTask:
    task = MonitorTask(
        appid=payload.appid,
        interval_minutes=payload.interval_minutes,
        enabled=payload.enabled,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def delete_monitor_task(session: Session, monitor_id: int) -> None:
    task = session.get(MonitorTask, monitor_id)
    if task is None:
        raise LookupError(f"monitor task {monitor_id} was not found")
    session.delete(task)
    session.commit()


def list_monitor_alerts(session: Session, limit: int = 20) -> list[MonitorAlert]:
    return list(
        session.exec(select(MonitorAlert).order_by(MonitorAlert.created_at.desc()).limit(limit)).all()  # type: ignore[attr-defined]
    )
