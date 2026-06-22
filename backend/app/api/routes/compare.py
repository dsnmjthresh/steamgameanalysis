from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.compare import CompareRequest, ComparisonResult
from app.services.comparison_service import compare_snapshots

router = APIRouter(prefix="/compare", tags=["compare"])


@router.post("", response_model=ComparisonResult)
def compare(payload: CompareRequest, session: Session = Depends(get_session)) -> ComparisonResult:
    try:
        return compare_snapshots(session, payload.left, payload.right)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
