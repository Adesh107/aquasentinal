from pydantic import BaseModel, Field
from typing import Literal


class PolygonGeometry(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[list[float]]]


class WaterBodyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    state: str = Field(default="Maharashtra", max_length=100)
    geometry: PolygonGeometry


class WaterBodyResponse(BaseModel):
    id: int
    name: str
    type: str | None
    district: str | None
    state: str
    geometry: PolygonGeometry
    area_sq_km: float | None
    source: str
    active: bool