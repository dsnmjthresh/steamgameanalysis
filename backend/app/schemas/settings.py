from pydantic import BaseModel, Field


class AppSettingsRead(BaseModel):
    default_cc: str
    default_language: str
    default_currency: str
    deepseek_model: str
    allow_model_fallback: bool
    collection_interval_minutes: int
    deepseek_api_key: bool
    steam_api_key: bool
    firecrawl_api_key: bool


class AppSettingsUpdate(BaseModel):
    default_cc: str | None = Field(default=None, min_length=2, max_length=2)
    default_language: str | None = None
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    deepseek_model: str | None = None
    allow_model_fallback: bool | None = None
    collection_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
