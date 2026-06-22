from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class CompareTarget(BaseModel):
    snapshot_id: int | None = None
    appid: int | None = None
    label: str | None = None

    @model_validator(mode="after")
    def has_selector(self) -> "CompareTarget":
        if not any((self.snapshot_id, self.appid, self.label)):
            raise ValueError("snapshot_id, appid, or label is required")
        return self


class CompareRequest(BaseModel):
    left: CompareTarget
    right: CompareTarget


class ComparisonMetric(BaseModel):
    field: str
    left: int | str | bool | None
    right: int | str | bool | None
    delta: int | None = None
    comparable: bool = True
    note: str | None = None


class ComparisonResult(BaseModel):
    left_snapshot_id: int
    right_snapshot_id: int
    left_appid: int
    right_appid: int
    left_collected_at: datetime
    right_collected_at: datetime
    comparable_region: bool
    comparable_currency: bool
    summary: str
    metrics: list[ComparisonMetric] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
