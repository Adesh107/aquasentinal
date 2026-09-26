from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalysisResult, SatelliteObservation, WaterBody


router = APIRouter(
    prefix="/water-bodies",
    tags=["Historical Analysis"],
)


@router.get("/{water_body_id}/timeline")
def get_water_body_timeline(
    water_body_id: int,
    db: Session = Depends(get_db),
):
    water_body = (
        db.query(WaterBody)
        .filter(WaterBody.id == water_body_id)
        .first()
    )

    if water_body is None:
        raise HTTPException(
            status_code=404,
            detail="Water body not found",
        )

    observations = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.water_body_id == water_body_id
        )
        .order_by(
            SatelliteObservation.observation_date.asc()
        )
        .all()
    )

    timeline = []

    for observation in observations:
        latest_analysis = (
            db.query(AnalysisResult)
            .filter(
                AnalysisResult.observation_id == observation.id
            )
            .order_by(
                AnalysisResult.created_at.desc()
            )
            .first()
        )

        entry = {
            "observation_id": observation.id,
            "observation_date": observation.observation_date,
            "satellite": observation.satellite,
            "scene_id": observation.scene_id,
            "cloud_percentage": observation.cloud_percentage,
            "quality_score": observation.quality_score,
            "analysis_id": None,
            "model_name": None,
            "model_version": None,
            "turbidity": None,
            "chlorophyll": None,
            "anomaly_score": None,
            "anomaly_detected": False,
            "confidence": None,
            "evidence": [],
        }

        if latest_analysis is not None:
            data = latest_analysis.analysis_data

            entry.update({
                "analysis_id": latest_analysis.id,
                "model_name": latest_analysis.model_name,
                "model_version": latest_analysis.model_version,
                "turbidity": data.get("turbidity"),
                "chlorophyll": data.get("chlorophyll"),
                "anomaly_score": data.get("anomaly_score"),
                "anomaly_detected": data.get(
                    "anomaly_detected",
                    False,
                ),
                "confidence": data.get("confidence"),
                "evidence": data.get(
                    "evidence",
                    [],
                ),
            })

        timeline.append(entry)

    return timeline
