from sqlmodel import Session

from app.core.config import get_settings
from app.core.security import key_status
from app.db.models import AppSetting, utc_now
from app.schemas.settings import AppSettingsRead, AppSettingsUpdate

DEFAULT_INTERVAL_MINUTES = 60


def _get_value(session: Session, key: str, fallback: str) -> str:
    setting = session.get(AppSetting, key)
    return setting.value if setting else fallback


def read_app_settings(session: Session) -> AppSettingsRead:
    settings = get_settings()
    statuses = key_status()
    return AppSettingsRead(
        default_cc=_get_value(session, "default_cc", settings.default_cc),
        default_language=_get_value(session, "default_language", settings.default_language),
        default_currency=_get_value(session, "default_currency", settings.default_currency),
        deepseek_model=_get_value(session, "deepseek_model", settings.deepseek_model),
        allow_model_fallback=_get_value(
            session,
            "allow_model_fallback",
            str(settings.allow_model_fallback).lower(),
        )
        == "true",
        collection_interval_minutes=int(
            _get_value(session, "collection_interval_minutes", str(DEFAULT_INTERVAL_MINUTES))
        ),
        deepseek_api_key=statuses["deepseek_api_key"],
        steam_api_key=statuses["steam_api_key"],
        firecrawl_api_key=statuses["firecrawl_api_key"],
    )


def update_app_settings(session: Session, update: AppSettingsUpdate) -> AppSettingsRead:
    payload = update.model_dump(exclude_none=True)
    for key, value in payload.items():
        persisted = session.get(AppSetting, key)
        if persisted is None:
            persisted = AppSetting(key=key, value=str(value).lower() if isinstance(value, bool) else str(value))
            session.add(persisted)
        else:
            persisted.value = str(value).lower() if isinstance(value, bool) else str(value)
            persisted.updated_at = utc_now()
    session.commit()
    return read_app_settings(session)
