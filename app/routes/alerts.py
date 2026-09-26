from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from datetime import datetime

from app.database import get_db
from app.models import Alert
from app.schemas.alert import AlertCreate, AlertResponse


router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
)


@router.post("", response_model=AlertResponse)
def create_alert(
    data: AlertCreate,
    db: Session = Depends(get_db),
):
    geometry_wkt = None

    if data.geometry is not None:
        coordinates = data.geometry.coordinates

        if len(coordinates) != 1:
            raise HTTPException(
                status_code=400,
                detail="Alert polygon must contain exactly one outer ring",
            )

        ring = coordinates[0]

        if len(ring) < 4:
            raise HTTPException(
                status_code=400,
                detail="Alert polygon must contain at least 4 coordinate points",
            )

        if ring[0] != ring[-1]:
            raise HTTPException(
                status_code=400,
                detail="Alert polygon must be closed: first and last coordinates must match",
            )

        coordinate_text = ", ".join(
            f"{longitude} {latitude}"
            for longitude, latitude in ring
        )

        geometry_wkt = f"POLYGON(({coordinate_text}))"

    alert = Alert(
        water_body_id=data.water_body_id,
        analysis_id=data.analysis_id,
        date=data.date,
        indicator=data.indicator,
        severity=data.severity,
        confidence=data.confidence,
        affected_area_km2=data.affected_area_km2,
        explanation=data.explanation,
        geometry=geometry_wkt,
        status=data.status,
    )

    db.add(alert)
    db.commit()
    db.refresh(alert)

    return alert


# ---------------------------------------------------------
# GET ALL ALERTS
# ---------------------------------------------------------



@router.get("", response_model=list[AlertResponse])
def get_alerts(
    water_body_id: int | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Alert)

    if water_body_id is not None:
        query = query.filter(Alert.water_body_id == water_body_id)

    if from_date is not None:
        query = query.filter(Alert.date >= from_date)

    if to_date is not None:
        query = query.filter(Alert.date <= to_date)

    return query.order_by(Alert.date.desc()).all()


# ---------------------------------------------------------
# ALERT GEOMETRY
# IMPORTANT: keep this BEFORE /{alert_id}
# ---------------------------------------------------------

@router.get("/{alert_id}/geometry")
def get_alert_geometry(
    alert_id: int,
    db: Session = Depends(get_db),
):
    alert = (
        db.query(Alert)
        .filter(Alert.id == alert_id)
        .first()
    )

    if alert is None:
        raise HTTPException(
            status_code=404,
            detail="Alert not found",
        )

    if alert.geometry is None:
        raise HTTPException(
            status_code=404,
            detail="No geometry is associated with this alert",
        )

    geometry = mapping(
        to_shape(alert.geometry)
    )

    return {
        "type": "Feature",
        "id": alert.id,
        "properties": {
            "water_body_id": alert.water_body_id,
            "analysis_id": alert.analysis_id,
            "date": alert.date,
            "indicator": alert.indicator,
            "severity": alert.severity,
            "confidence": alert.confidence,
            "affected_area_km2": alert.affected_area_km2,
            "status": alert.status,
        },
        "geometry": {
            "type": geometry["type"],
            "coordinates": geometry["coordinates"],
        },
    }


# ---------------------------------------------------------
# GET SINGLE ALERT
# ---------------------------------------------------------

@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: int,
    db: Session = Depends(get_db),
):
    alert = (
        db.query(Alert)
        .filter(Alert.id == alert_id)
        .first()
    )

    if alert is None:
        raise HTTPException(
            status_code=404,
            detail="Alert not found",
        )

    return alert