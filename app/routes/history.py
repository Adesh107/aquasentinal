from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalysisResult, SatelliteObservation, WaterBody


router = APIRouter(
    prefix="/water-bodies",
    tags=["Historical Analysis"],
)


def validate_date_range(
    from_date: datetime | None,
    to_date: datetime | None,
) -> None:
    if from_date is not None and to_date is not None:
        if from_date > to_date:
            raise HTTPException(
                status_code=400,
                detail="from_date must be before or equal to to_date",
            )


def get_observations_for_water_body(
    water_body_id: int,
    from_date: datetime | None,
    to_date: datetime | None,
    db: Session,
):
    validate_date_range(from_date, to_date)

    query = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.water_body_id == water_body_id
        )
    )

    if from_date is not None:
        query = query.filter(
            SatelliteObservation.observation_date >= from_date
        )

    if to_date is not None:
        query = query.filter(
            SatelliteObservation.observation_date <= to_date
        )

    return (
        query
        .order_by(
            SatelliteObservation.observation_date.asc()
        )
        .all()
    )


def get_latest_analysis(
    observation_id: int,
    db: Session,
):
    return (
        db.query(AnalysisResult)
        .filter(
            AnalysisResult.observation_id == observation_id
        )
        .order_by(
            AnalysisResult.created_at.desc()
        )
        .first()
    )


def build_analysis_snapshot(
    observation: SatelliteObservation,
    analysis: AnalysisResult,
):
    data = analysis.analysis_data

    return {
        "observation_id": observation.id,
        "observation_date": observation.observation_date,
        "analysis_id": analysis.id,
        "turbidity": data.get("turbidity"),
        "chlorophyll": data.get("chlorophyll"),
        "anomaly_score": data.get("anomaly_score"),
        "anomaly_detected": data.get(
            "anomaly_detected",
            False,
        ),
        "confidence": data.get("confidence"),
    }


@router.get("/{water_body_id}/timeline")
def get_water_body_timeline(
    water_body_id: int,
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
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

    observations = get_observations_for_water_body(
        water_body_id,
        from_date,
        to_date,
        db,
    )

    timeline = []

    for observation in observations:
        latest_analysis = get_latest_analysis(
            observation.id,
            db,
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


@router.get("/{water_body_id}/trend")
def get_water_body_trend(
    water_body_id: int,
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
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

    observations = get_observations_for_water_body(
        water_body_id,
        from_date,
        to_date,
        db,
    )

    series = []
    analyzed_observation_count = 0
    anomaly_count = 0

    turbidity_values = []
    chlorophyll_values = []
    anomaly_score_values = []

    for observation in observations:
        latest_analysis = get_latest_analysis(
            observation.id,
            db,
        )

        point = {
            "observation_id": observation.id,
            "observation_date": observation.observation_date,
            "turbidity": None,
            "chlorophyll": None,
            "anomaly_score": None,
            "anomaly_detected": False,
            "confidence": None,
        }

        if latest_analysis is not None:
            analyzed_observation_count += 1
            data = latest_analysis.analysis_data

            point.update({
                "turbidity": data.get("turbidity"),
                "chlorophyll": data.get("chlorophyll"),
                "anomaly_score": data.get("anomaly_score"),
                "anomaly_detected": data.get(
                    "anomaly_detected",
                    False,
                ),
                "confidence": data.get("confidence"),
            })

            if point["anomaly_detected"]:
                anomaly_count += 1

            if point["turbidity"] is not None:
                turbidity_values.append(point["turbidity"])

            if point["chlorophyll"] is not None:
                chlorophyll_values.append(point["chlorophyll"])

            if point["anomaly_score"] is not None:
                anomaly_score_values.append(point["anomaly_score"])

        series.append(point)

    return {
        "water_body_id": water_body_id,
        "from_date": from_date,
        "to_date": to_date,
        "observation_count": len(observations),
        "analyzed_observation_count": analyzed_observation_count,
        "anomaly_count": anomaly_count,
        "summary": {
            "turbidity_min": min(turbidity_values) if turbidity_values else None,
            "turbidity_max": max(turbidity_values) if turbidity_values else None,
            "chlorophyll_min": min(chlorophyll_values) if chlorophyll_values else None,
            "chlorophyll_max": max(chlorophyll_values) if chlorophyll_values else None,
            "anomaly_score_min": (
                min(anomaly_score_values)
                if anomaly_score_values
                else None
            ),
            "anomaly_score_max": (
                max(anomaly_score_values)
                if anomaly_score_values
                else None
            ),
        },
        "series": series,
    }


@router.get("/{water_body_id}/comparison")
def get_water_body_comparison(
    water_body_id: int,
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
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

    observations = get_observations_for_water_body(
        water_body_id,
        from_date,
        to_date,
        db,
    )

    analyzed = []

    for observation in observations:
        latest_analysis = get_latest_analysis(
            observation.id,
            db,
        )

        if latest_analysis is not None:
            analyzed.append(
                build_analysis_snapshot(
                    observation,
                    latest_analysis,
                )
            )

    if len(analyzed) < 2:
        return {
            "water_body_id": water_body_id,
            "from_date": from_date,
            "to_date": to_date,
            "comparison_available": False,
            "reason": "At least two analyzed observations are required for comparison",
            "earlier": analyzed[0] if analyzed else None,
            "latest": None,
            "change": {
                "turbidity": None,
                "chlorophyll": None,
                "anomaly_score": None,
                "confidence": None,
            },
        }

    earlier = analyzed[0]
    latest = analyzed[-1]

    def calculate_change(
        earlier_value: float | None,
        latest_value: float | None,
    ):
        if earlier_value is None or latest_value is None:
            return None
        return latest_value - earlier_value

    return {
        "water_body_id": water_body_id,
        "from_date": from_date,
        "to_date": to_date,
        "comparison_available": True,
        "earlier": earlier,
        "latest": latest,
        "change": {
            "turbidity": calculate_change(
                earlier["turbidity"],
                latest["turbidity"],
            ),
            "chlorophyll": calculate_change(
                earlier["chlorophyll"],
                latest["chlorophyll"],
            ),
            "anomaly_score": calculate_change(
                earlier["anomaly_score"],
                latest["anomaly_score"],
            ),
            "confidence": calculate_change(
                earlier["confidence"],
                latest["confidence"],
            ),
        },
    }
