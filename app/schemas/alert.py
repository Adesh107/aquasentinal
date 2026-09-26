from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AlertCreate(BaseModel):
    water_body_id: int
    analysis_id: int | None = None
    date: datetime
    indicator: str
    severity: str
    confidence: float | None = None
    affected_area_km2: float | None = None
    explanation: dict | list | None = None
    status: str = "active"


class AlertResponse(BaseModel):
    id: int
    water_body_id: int
    analysis_id: int | None
    date: datetime
    indicator: str
    severity: str
    confidence: float | None
    affected_area_km2: float | None
    explanation: dict | list | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)