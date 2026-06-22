from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MonitorTaskCreate(BaseModel):
    appid: int = Field(gt=0)
    interval_minutes: int = Field(default=60, ge=1, le=1440)
    enabled: bool = True


class MonitorTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appid: int
    interval_minutes: int
    enabled: bool
    last_run_at: datetime | None = None
    created_at: datetime


class MonitorAlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    appid: int
    snapshot_id: int
    alert_type: str
    summary: str
    severity: str
    created_at: datetime
