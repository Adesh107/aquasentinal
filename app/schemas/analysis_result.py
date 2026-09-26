from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnalysisData(BaseModel):
    turbidity: float | None = None
    chlorophyll: float | None = None
    algal: float | None = None
    water_area_km2: float | None = None

    anomaly_score: float | None = Field(default=None, ge=0.0, le=1.0)
    anomaly_detected: bool = False
    anomaly_level: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    affected_area_km2: float | None = Field(default=None, ge=0.0)
    baseline_status: str | None = None
    baseline_observation_count: int | None = Field(default=None, ge=0)

    mode: str | None = None
    processing_version: str | None = None
    calibration_status: dict[str, str] = {}
    observation_quality: dict | None = None
    individual_scores: dict[str, float] = {}
    evidence: list[str] = []
    geojson: dict | None = None


class AnalysisResultCreate(BaseModel):
    observation_id: int
    model_name: str
    model_version: str | None = None
    analysis_data: AnalysisData


class AnalysisResultResponse(BaseModel):
    id: int
    observation_id: int
    model_name: str
    model_version: str | None = None
    analysis_data: AnalysisData
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
