from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.settings import AppSettingsRead, AppSettingsUpdate
from app.services.settings_service import read_app_settings, update_app_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettingsRead)
def get_settings(session: Session = Depends(get_session)) -> AppSettingsRead:
    return read_app_settings(session)


@router.put("", response_model=AppSettingsRead)
def put_settings(
    payload: AppSettingsUpdate,
    session: Session = Depends(get_session),
) -> AppSettingsRead:
    return update_app_settings(session, payload)
