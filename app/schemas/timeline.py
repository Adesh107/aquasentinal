from datetime import datetime

from pydantic import BaseModel


class TimelineEntry(BaseModel):
    observation_id: int
    observation_date: datetime
    satellite: str
    scene_id: str
    cloud_percentage: float | None = None
    quality_score: float | None = None
    analysis_id: int | None = None
    model_name: str | None = None
    model_version: str | None = None
    turbidity: float | None = None
    chlorophyll: float | None = None
    anomaly_score: float | None = None
    anomaly_detected: bool = False
    confidence: float | None = None
    evidence: list[str] = []


class TimelineResponse(BaseModel):
    water_body_id: int
    entries: list[TimelineEntry]
