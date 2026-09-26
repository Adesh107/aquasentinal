from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, AnalysisResult, SatelliteObservation, WaterBody
from app.schemas.ai_analysis import (
    AIAnalyzeRequest,
    AIAnalyzeResponse,
    AIBaselineResponse,
    AIHealthResponse,
)
from app.services.ai_pipeline import run_satellite_analysis, _backend_water_body_to_ai_id
from ai.features.baseline import HistoricalBaseline, MIN_OBSERVATIONS


router = APIRouter(prefix="/ai", tags=["Satellite AI"])


@router.post("/analyze", response_model=AIAnalyzeResponse, status_code=201)
def analyze_water_body(
    data: AIAnalyzeRequest,
    db: Session = Depends(get_db),
):
    water_body = (
        db.query(WaterBody)
        .filter(
            WaterBody.id == data.water_body_id,
            WaterBody.active == True,
        )
        .first()
    )
    if water_body is None:
        raise HTTPException(status_code=404, detail="Active water body not found")

    try:
        result = run_satellite_analysis(
            water_body=water_body,
            observation_date=data.observation_date,
            image_reference=data.image_reference,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Persist one observation record using stable STAC metadata only.
    existing_observation = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.water_body_id == water_body.id,
            SatelliteObservation.scene_id == result["scene_id"],
        )
        .first()
    )

    observation_metadata = {
        "pipeline": "sentinel-2-l2a",
        "ai_water_body_id": result["ai_water_body_id"],
        "schema_version": result["schema_version"],
        "status": result["status"],
        "mode": result["mode"],
        "processing_version": result["processing_version"],
        "observation_quality": result["observation_quality"],
        "satellite_metadata": result["satellite_metadata"],
        "note": "Signed asset URLs are intentionally not persisted because they expire.",
    }

    quality_score = max(
        0.0,
        min(1.0, 1.0 - (result["cloud_percentage"] / 100.0)),
    )

    if existing_observation is None:
        observation = SatelliteObservation(
            water_body_id=water_body.id,
            satellite=result["satellite"],
            observation_date=result["observation_date"],
            scene_id=result["scene_id"],
            cloud_percentage=result["cloud_percentage"],
            quality_score=quality_score,
            source_url=result["satellite_metadata"]["source_url"],
            observation_metadata=observation_metadata,
        )
        db.add(observation)
    else:
        observation = existing_observation
        observation.satellite = result["satellite"]
        observation.observation_date = result["observation_date"]
        observation.cloud_percentage = result["cloud_percentage"]
        observation.quality_score = quality_score
        observation.source_url = result["satellite_metadata"]["source_url"]
        observation.observation_metadata = observation_metadata

    db.flush()

    analysis_data = {
        "turbidity": result["turbidity_indicator"],
        "chlorophyll": result["chlorophyll_indicator"],
        "algal": result["algal_indicator"],
        "water_area_km2": result["water_area_km2"],
        "anomaly_score": result["anomaly_score"],
        "anomaly_detected": result["anomaly_level"] != "NONE",
        "anomaly_level": result["anomaly_level"],
        "confidence": None,
        "affected_area_km2": result["affected_area_km2"],
        "baseline_status": result["baseline_status"],
        "baseline_observation_count": result["baseline_observation_count"],
        "mode": result["mode"],
        "processing_version": result["processing_version"],
        "calibration_status": result["calibration_status"],
        "observation_quality": result["observation_quality"],
        "individual_scores": result["anomaly_individual_scores"],
        "evidence": result["anomaly_explanation"],
        "geojson": {
            "water_boundary": result["water_boundary"],
            "anomaly_regions": None,
        },
    }

    analysis = AnalysisResult(
        observation_id=observation.id,
        model_name="sentinel-2-spectral-monitoring",
        model_version=result["model_version"] or "prototype-indicator-only",
        analysis_data=analysis_data,
    )
    db.add(analysis)
    db.flush()

    alert = None
    if (
        result["anomaly_level"] != "NONE"
        and result["anomaly_score"] >= 0.25
    ):
        scores = result["anomaly_individual_scores"]
        ranked = sorted(
            (
                (name, score)
                for name, score in scores.items()
                if name != "area"
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        indicator = ranked[0][0] if ranked else "multiple"

        alert = Alert(
            water_body_id=water_body.id,
            analysis_id=analysis.id,
            date=datetime.fromisoformat(
                result["observation_date"].replace("Z", "+00:00")
            ),
            indicator=indicator,
            severity=result["anomaly_level"],
            confidence=None,
            affected_area_km2=None,
            explanation={
                "messages": result["anomaly_explanation"],
                "indicator_scores": result["anomaly_individual_scores"],
                "spatial_note": "Affected-area geometry is not spatially resolved yet.",
            },
            geometry=None,
            status="active",
        )
        db.add(alert)

    db.commit()
    db.refresh(observation)
    db.refresh(analysis)
    if alert is not None:
        db.refresh(alert)

    result["observation_id"] = observation.id
    result["analysis_id"] = analysis.id
    result["alert_id"] = alert.id if alert is not None else None
    return result



@router.get(
    "/baseline/{water_body_id}",
    response_model=AIBaselineResponse,
)
def get_baseline_status(
    water_body_id: int,
    db: Session = Depends(get_db),
):
    water_body = (
        db.query(WaterBody)
        .filter(
            WaterBody.id == water_body_id,
            WaterBody.active == True,
        )
        .first()
    )
    if water_body is None:
        raise HTTPException(status_code=404, detail="Active water body not found")

    manager = HistoricalBaseline()
    ai_water_body_id = _backend_water_body_to_ai_id(water_body_id)
    history = manager.load_history(ai_water_body_id)
    baseline = manager.compute_baseline(ai_water_body_id)

    eligible_count = baseline.num_observations
    total_count = len(history)

    return {
        "water_body_id": water_body_id,
        "ai_water_body_id": ai_water_body_id,
        "status": baseline.status,
        "minimum_required": MIN_OBSERVATIONS,
        "eligible_observation_count": eligible_count,
        "total_history_count": total_count,
        "excluded_observation_count": max(0, total_count - eligible_count),
        "remaining_observations": max(0, MIN_OBSERVATIONS - eligible_count),
        "date_range": baseline.date_range,
        "water_area_stats": baseline.water_area_stats,
        "turbidity_stats": baseline.turbidity_stats,
        "chlorophyll_stats": baseline.chlorophyll_stats,
        "algal_stats": baseline.algal_stats,
    }


@router.get("/health", response_model=AIHealthResponse)
def ai_health():
    components: dict[str, str] = {}

    checks = {
        "satellite_client": "ai.satellite.client",
        "preprocessor": "ai.preprocessing.preprocessor",
        "water_segmentation": "ai.segmentation.waternet",
        "spectral_features": "ai.features.spectral",
        "indicator_engine": "ai.inference.indicators",
        "baseline": "ai.features.baseline",
        "anomaly_detector": "ai.anomaly.detector",
    }

    import importlib

    for name, module_name in checks.items():
        try:
            importlib.import_module(module_name)
            components[name] = "available"
        except Exception as exc:
            components[name] = f"error: {exc}"

    import ai

    status = (
        "ok"
        if all(value == "available" for value in components.values())
        else "degraded"
    )

    return {
        "status": status,
        "schema_version": "1.0.0",
        "processing_version": "0.1.0",
        "components": components,
    }
