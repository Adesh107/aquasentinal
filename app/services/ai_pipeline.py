"""
AquaSentinel satellite-analysis integration.

This service adapts the member 3/4 remote-sensing pipeline to the backend's
integer water-body IDs and PostgreSQL/PostGIS records.

Important scientific boundary:
- turbidity/chlorophyll/algal values are normalized indicators unless a promoted
  ground-truth-calibrated model exists;
- anomaly geometry is not fabricated here. Affected-area geometry is left
  unresolved until a pixel-level anomaly mask is available.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shapely.geometry import mapping
from geoalchemy2.shape import to_shape

from ai.anomaly.detector import AnomalyDetector
from ai.features.baseline import HistoricalBaseline, ObservationRecord
from ai.features.spectral import SpectralFeatureExtractor
from ai.inference.indicators import IndicatorEngine
from ai.preprocessing.preprocessor import SentinelPreprocessor
from ai.satellite.client import PlanetaryComputerSentinelClient
from ai.segmentation.waternet import WaterNetSegmenter


SCHEMA_VERSION = "1.0.0"


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _backend_water_body_to_ai_id(water_body_id: int) -> str:
    return f"WB_DB_{water_body_id}"


def _water_body_bbox(water_body) -> list[float]:
    geometry = to_shape(water_body.geometry)
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    return [float(min_lon), float(min_lat), float(max_lon), float(max_lat)]


def _prior_baseline(
    manager: HistoricalBaseline,
    water_body_id: str,
    observation_date: str,
):
    history = list(manager.load_history(water_body_id))
    # Exclude an existing record for the exact same observation date so a
    # re-run cannot score an observation against its own previous run.
    manager._histories[water_body_id] = [
        record for record in history
        if record.observation_date != observation_date
    ]
    baseline = manager.compute_baseline(water_body_id)
    manager._histories[water_body_id] = history
    return baseline


def run_satellite_analysis(
    water_body,
    observation_date: datetime,
    image_reference: str | None = None,
) -> dict[str, Any]:
    ai_water_body_id = _backend_water_body_to_ai_id(water_body.id)
    target_date = _iso(observation_date)
    bbox = _water_body_bbox(water_body)

    client = PlanetaryComputerSentinelClient()

    if image_reference:
        satellite_observation = client.get_observation_by_id(
            image_reference,
            ai_water_body_id,
        )
    else:
        satellite_observation = client.search_observation(
            water_body_id=ai_water_body_id,
            bbox=bbox,
            target_date=target_date,
            initial_window_days=15,
            initial_cloud_threshold=20.0,
        )

    preprocessor = SentinelPreprocessor(buffer_meters=500.0)
    ard = preprocessor.process(
        observation=satellite_observation,
        wgs84_bbox=bbox,
    )

    segmenter = WaterNetSegmenter()
    # Validate segmentation against the stored water-body footprint. The
    # footprint is used as a spatial prior, not as a pixel-level ground truth.
    stored_geometry = mapping(to_shape(water_body.geometry))
    segmentation = segmenter.segment(
        ard,
        expected_water_geometry={
            "type": "Feature",
            "geometry": stored_geometry,
        },
    )

    spectral = SpectralFeatureExtractor().extract(ard, segmentation)
    indicators = IndicatorEngine().compute(spectral.to_dict())

    baseline_manager = HistoricalBaseline()
    observation_key = satellite_observation.observation_date
    baseline = _prior_baseline(
        baseline_manager,
        ai_water_body_id,
        observation_key,
    )

    anomaly = AnomalyDetector().detect(
        water_body_id=ai_water_body_id,
        observation_date=observation_key,
        current_turbidity=indicators.turbidity_indicator,
        current_chlorophyll=indicators.chlorophyll_indicator,
        current_algal=indicators.algal_indicator,
        current_water_area_km2=segmentation.water_area_km2,
        baseline=baseline,
    )

    record = ObservationRecord(
        water_body_id=ai_water_body_id,
        observation_date=observation_key,
        source_reference=satellite_observation.source_reference,
        water_area_km2=segmentation.water_area_km2,
        turbidity_indicator=indicators.turbidity_indicator,
        chlorophyll_indicator=indicators.chlorophyll_indicator,
        algal_indicator=indicators.algal_indicator,
        cloud_percentage=satellite_observation.cloud_percentage,
        mask_quality_status=segmentation.quality_report.status,
        mode=indicators.mode,
        anomaly_score=anomaly.anomaly_score,
        anomaly_level=anomaly.anomaly_level,
    )
    baseline_manager.add_observation(record)

    # Quality problems and review warnings take precedence over baseline
    # availability. A warned mask must not silently enter the baseline.
    if not segmentation.quality_report.is_valid:
        pipeline_status = "degraded"
    elif segmentation.quality_report.status != "ok":
        pipeline_status = "quality_warning"
    elif baseline.status != "valid":
        pipeline_status = "insufficient_baseline"
    else:
        pipeline_status = "ok"

    boundary = segmentation.boundary_geojson
    if not boundary.get("geometry"):
        raise ValueError("Satellite pipeline returned no water-boundary geometry.")

    boundary_feature = {
        "type": "Feature",
        "geometry": boundary["geometry"],
        "properties": {
            "crs": "EPSG:4326",
            "feature_type": "water_boundary",
            "water_body_id": water_body.id,
        },
    }

    # Do not reuse the AI project's synthetic scaled-boundary anomaly polygon.
    # The backend will highlight the water body itself when an alert exists,
    # while a true affected-area geometry waits for a pixel anomaly mask.
    return {
        "schema_version": SCHEMA_VERSION,
        "status": pipeline_status,
        "water_body_id": water_body.id,
        "water_body_name": water_body.name,
        "ai_water_body_id": ai_water_body_id,
        "observation_date": satellite_observation.observation_date,
        "satellite": satellite_observation.satellite_name,
        "scene_id": satellite_observation.source_reference,
        "cloud_percentage": float(satellite_observation.cloud_percentage),
        "water_area_km2": float(round(segmentation.water_area_km2, 4)),
        "turbidity_indicator": float(indicators.turbidity_indicator),
        "chlorophyll_indicator": float(indicators.chlorophyll_indicator),
        "algal_indicator": float(indicators.algal_indicator),
        "anomaly_score": float(anomaly.anomaly_score),
        "anomaly_level": anomaly.anomaly_level,
        "affected_area_km2": None,
        "baseline_status": anomaly.baseline_status,
        "baseline_observation_count": int(baseline.num_observations),
        "observation_quality": {
            "cloud_percentage": float(satellite_observation.cloud_percentage),
            "mask_quality_status": segmentation.quality_report.status,
            "water_pixel_pct": float(segmentation.quality_report.water_pixel_pct),
            "fragmentation_index": float(segmentation.quality_report.fragmentation_index),
            "cloud_overlap_pct": float(segmentation.quality_report.cloud_overlap_pct),
            "window_widened": bool(satellite_observation.window_widened),
            "scl_available": bool(satellite_observation.quality_info.scl_available),
            "quality_guard_failures": list(segmentation.quality_report.failure_reasons),
            "quality_warnings": list(segmentation.quality_report.quality_warnings),
            "expected_water_pixels": int(segmentation.quality_report.expected_water_pixels),
            "overlap_water_pixels": int(segmentation.quality_report.overlap_water_pixels),
            "detected_inside_expected_pct": float(
                segmentation.quality_report.detected_inside_expected_pct
            ),
            "expected_coverage_pct": float(
                segmentation.quality_report.expected_coverage_pct
            ),
            "out_of_footprint_pct": float(
                segmentation.quality_report.out_of_footprint_pct
            ),
            "spatial_prior_warning": segmentation.quality_report.spatial_prior_warning,
        },
        "mode": indicators.mode,
        "model_version": indicators.model_version,
        "processing_version": indicators.processing_version,
        "calibration_status": dict(indicators.calibration_status),
        "anomaly_explanation": list(anomaly.explanation),
        "anomaly_individual_scores": dict(anomaly.individual_scores),
        "water_boundary": boundary_feature,
        "anomaly_regions": None,
        "satellite_metadata": {
            "stac_collection": "sentinel-2-l2a",
            "source_reference": satellite_observation.source_reference,
            "window_widened": satellite_observation.window_widened,
            "widening_attempts": list(satellite_observation.widening_attempts),
            "quality_info": satellite_observation.quality_info.raw_properties,
            "source_url": (
                "https://planetarycomputer.microsoft.com/api/stac/v1/"
                f"collections/sentinel-2-l2a/items/{satellite_observation.source_reference}"
            ),
        },
    }
