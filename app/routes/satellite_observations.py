from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SatelliteObservation, WaterBody
from app.schemas.satellite_observation import (
    SatelliteObservationCreate,
    SatelliteObservationResponse,
)

router = APIRouter(
    prefix="/satellite-observations",
    tags=["Satellite Observations"],
)


@router.post(
    "",
    response_model=SatelliteObservationResponse,
    status_code=201,
)
def create_satellite_observation(
    observation: SatelliteObservationCreate,
    db: Session = Depends(get_db),
):
    # Confirm that the referenced water body exists.
    water_body = (
        db.query(WaterBody)
        .filter(WaterBody.id == observation.water_body_id)
        .first()
    )

    if water_body is None:
        raise HTTPException(
            status_code=404,
            detail="Water body not found",
        )

    db_observation = SatelliteObservation(
        water_body_id=observation.water_body_id,
        satellite=observation.satellite,
        observation_date=observation.observation_date,
        scene_id=observation.scene_id,
        cloud_percentage=observation.cloud_percentage,
        quality_score=observation.quality_score,
        source_url=observation.source_url,
        observation_metadata=observation.observation_metadata,
    )

    db.add(db_observation)
    db.commit()
    db.refresh(db_observation)

    return db_observation


@router.get(
    "",
    response_model=list[SatelliteObservationResponse],
)
def get_satellite_observations(
    water_body_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(SatelliteObservation)

    if water_body_id is not None:
        query = query.filter(
            SatelliteObservation.water_body_id == water_body_id
        )

    return query.order_by(
        SatelliteObservation.observation_date.desc()
    ).all()


@router.get(
    "/{observation_id}",
    response_model=SatelliteObservationResponse,
)
def get_satellite_observation(
    observation_id: int,
    db: Session = Depends(get_db),
):
    observation = (
        db.query(SatelliteObservation)
        .filter(SatelliteObservation.id == observation_id)
        .first()
    )

    if observation is None:
        raise HTTPException(
            status_code=404,
            detail="Satellite observation not found",
        )

    return observation