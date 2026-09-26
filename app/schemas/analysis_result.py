from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AnalysisResultCreate(BaseModel):
    observation_id: int
    model_name: str
    model_version: str | None = None
    analysis_data: dict


class AnalysisResultResponse(BaseModel):
    id: int
    observation_id: int
    model_name: str
    model_version: str | None = None
    analysis_data: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)