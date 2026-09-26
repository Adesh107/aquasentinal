from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SatelliteObservationCreate(BaseModel):
    water_body_id: int
    satellite: str
    observation_date: datetime
    scene_id: str
    cloud_percentage: float | None = None
    quality_score: float | None = None
    source_url: str | None = None
    observation_metadata: dict | None = None


class SatelliteObservationResponse(BaseModel):
    id: int
    water_body_id: int
    satellite: str
    observation_date: datetime
    scene_id: str
    cloud_percentage: float | None = None
    quality_score: float | None = None
    source_url: str | None = None
    observation_metadata: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)