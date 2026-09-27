from datetime import datetime

from pydantic import BaseModel, Field


class AIAnalyzeRequest(BaseModel):
    water_body_id: int
    observation_date: datetime
    image_reference: str | None = Field(
        default=None,
        description="Optional Sentinel-2 L2A STAC item ID.",
    )


class AIObservationQuality(BaseModel):
    cloud_percentage: float
    mask_quality_status: str
    water_pixel_pct: float
    fragmentation_index: float
    cloud_overlap_pct: float
    window_widened: bool
    scl_available: bool

    quality_guard_failures: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)
    expected_water_pixels: int = Field(default=0, ge=0)
    overlap_water_pixels: int = Field(default=0, ge=0)
    detected_inside_expected_pct: float = Field(default=0.0, ge=0.0)
    expected_coverage_pct: float = Field(default=0.0, ge=0.0)
    out_of_footprint_pct: float = Field(default=0.0, ge=0.0)
    spatial_prior_warning: str | None = None


class AIAnalyzeResponse(BaseModel):
    schema_version: str
    status: str
    water_body_id: int
    water_body_name: str
    ai_water_body_id: str

    observation_id: int
    analysis_id: int | None = None
    alert_id: int | None = None

    observation_date: datetime
    satellite: str
    scene_id: str
    cloud_percentage: float
    water_area_km2: float

    turbidity_indicator: float
    chlorophyll_indicator: float
    algal_indicator: float

    anomaly_score: float
    anomaly_level: str
    affected_area_km2: float | None = None

    baseline_status: str
    baseline_observation_count: int

    observation_quality: AIObservationQuality
    mode: str
    model_version: str | None = None
    processing_version: str
    calibration_status: dict[str, str]
    anomaly_explanation: list[str]
    anomaly_individual_scores: dict[str, float]

    spatial_anomaly: dict = Field(default_factory=dict)

    # No synthetic anomaly polygon is returned. Spatial anomaly geometry
    # requires pixel-level anomaly masks, not a scaled copy of the water boundary.
    water_boundary: dict
    anomaly_regions: dict | None = None



class AIBaselineResponse(BaseModel):
    water_body_id: int
    ai_water_body_id: str
    status: str
    minimum_required: int
    eligible_observation_count: int
    total_history_count: int
    excluded_observation_count: int
    remaining_observations: int
    date_range: dict[str, str]
    water_area_stats: dict[str, float] = Field(default_factory=dict)
    turbidity_stats: dict[str, float] = Field(default_factory=dict)
    chlorophyll_stats: dict[str, float] = Field(default_factory=dict)
    algal_stats: dict[str, float] = Field(default_factory=dict)

class AIHealthResponse(BaseModel):
    status: str
    schema_version: str
    processing_version: str
    components: dict[str, str]
