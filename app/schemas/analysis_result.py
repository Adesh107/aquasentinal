from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnalysisData(BaseModel):
    turbidity: float | None = None
    chlorophyll: float | None = None
    anomaly_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    anomaly_detected: bool = False
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    evidence: list[str] = []


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