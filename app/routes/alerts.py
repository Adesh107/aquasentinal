from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

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
    alert = Alert(
        water_body_id=data.water_body_id,
        analysis_id=data.analysis_id,
        date=data.date,
        indicator=data.indicator,
        severity=data.severity,
        confidence=data.confidence,
        affected_area_km2=data.affected_area_km2,
        explanation=data.explanation,
        status=data.status,
    )

    db.add(alert)
    db.commit()
    db.refresh(alert)

    return alert


@router.get("", response_model=list[AlertResponse])
def get_alerts(
    db: Session = Depends(get_db),
):
    return (
        db.query(Alert)
        .order_by(Alert.date.desc())
        .all()
    )


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