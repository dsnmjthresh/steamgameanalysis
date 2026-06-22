from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.snapshot import (
    SnapshotCreateRequest,
    SnapshotLabelCreate,
    SnapshotLabelRead,
    SnapshotRead,
)
from app.services.snapshot_service import (
    add_snapshot_label,
    collect_snapshot,
    get_snapshot,
    list_snapshots,
)
from app.services.steam_client import SteamClient, SteamClientError

router = APIRouter(tags=["snapshots"])


@router.post("/games/{appid}/snapshots", response_model=SnapshotRead)
async def create_snapshot(
    appid: int,
    payload: SnapshotCreateRequest | None = None,
    session: Session = Depends(get_session),
) -> SnapshotRead:
    payload = payload or SnapshotCreateRequest()
    async with SteamClient() as steam:
        try:
            return await collect_snapshot(
                session=session,
                steam=steam,
                appid=appid,
                cc=payload.cc,
                language=payload.language,
                labels=payload.labels,
            )
        except SteamClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/games/{appid}/snapshots", response_model=list[SnapshotRead])
def read_snapshots(
    appid: int,
    limit: int = Query(default=50, ge=1, le=200),
    label: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    session: Session = Depends(get_session),
) -> list[SnapshotRead]:
    return list_snapshots(session, appid=appid, limit=limit, label=label, start=start, end=end)


@router.post("/snapshots/{snapshot_id}/labels", response_model=SnapshotLabelRead)
def label_snapshot(
    snapshot_id: int,
    payload: SnapshotLabelCreate,
    session: Session = Depends(get_session),
) -> SnapshotLabelRead:
    try:
        get_snapshot(session, snapshot_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    label = add_snapshot_label(session, snapshot_id, payload.label)
    return SnapshotLabelRead.model_validate(label)
