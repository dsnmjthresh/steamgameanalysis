"""Memory management API routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.db.session import get_session
from app.services.memory_service import (
    confirm_memory_entry,
    delete_memory_entry,
    get_memory_stats,
    get_pending_entries,
    list_memory_entries,
    resolve_user,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("")
def list_memories(
    user_key: str = Query(..., min_length=1, max_length=128),
    memory_type: str | None = None,
    appid: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> dict:
    user = resolve_user(session, user_key)
    if user is None:
        raise HTTPException(status_code=400, detail="user_key is required")

    entries = list_memory_entries(
        session, user_id=user.id or 0,
        memory_type=memory_type, appid=appid, limit=limit,
    )
    return {
        "memories": [
            {
                "id": e.id,
                "type": e.memory_type,
                "content": e.content,
                "appid": e.appid,
                "importance": e.importance,
                "access_count": e.access_count,
                "last_accessed_at": e.last_accessed_at.isoformat() if e.last_accessed_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "count": len(entries),
    }


@router.get("/stats")
def memory_stats(
    user_key: str = Query(..., min_length=1, max_length=128),
    session: Session = Depends(get_session),
) -> dict:
    user = resolve_user(session, user_key)
    if user is None:
        raise HTTPException(status_code=400, detail="user_key is required")
    return get_memory_stats(session, user.id or 0)


@router.get("/pending")
def list_pending_memories(
    user_key: str = Query(..., min_length=1, max_length=128),
    session: Session = Depends(get_session),
) -> dict:
    """List memory entries awaiting user confirmation."""
    user = resolve_user(session, user_key)
    if user is None:
        raise HTTPException(status_code=400, detail="user_key is required")

    entries = get_pending_entries(session, user.id or 0)
    return {
        "memories": [
            {
                "id": e.id,
                "type": e.memory_type,
                "content": e.content,
                "appid": e.appid,
                "importance": e.importance,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
        "count": len(entries),
    }


@router.post("/confirm/{entry_id}")
def confirm_memory(
    entry_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """Confirm a pending memory entry, activating it for recall."""
    entry = confirm_memory_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return {
        "status": "confirmed",
        "entry_id": entry_id,
        "confirmed_at": entry.confirmed_at.isoformat() if entry.confirmed_at else None,
    }


@router.delete("/{entry_id}")
def delete_memory(
    entry_id: int,
    session: Session = Depends(get_session),
) -> dict:
    delete_memory_entry(session, entry_id)
    return {"status": "deleted", "entry_id": entry_id}
