from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalysisResult, SatelliteObservation
from app.schemas.analysis_result import (
    AnalysisResultCreate,
    AnalysisResultResponse,
)


router = APIRouter(
    prefix="/analysis-results",
    tags=["Analysis Results"],
)


# ---------------------------------------------------------
# CREATE ANALYSIS RESULT
# ---------------------------------------------------------

@router.post(
    "",
    response_model=AnalysisResultResponse,
    status_code=201,
)
def create_analysis_result(
    data: AnalysisResultCreate,
    db: Session = Depends(get_db),
):
    # Confirm that the referenced satellite observation exists.
    observation = (
        db.query(SatelliteObservation)
        .filter(SatelliteObservation.id == data.observation_id)
        .first()
    )

    if observation is None:
        raise HTTPException(
            status_code=404,
            detail="Satellite observation not found",
        )

    analysis_result = AnalysisResult(
        observation_id=data.observation_id,
        model_name=data.model_name,
        model_version=data.model_version,
        analysis_data=data.analysis_data,
    )

    db.add(analysis_result)
    db.commit()
    db.refresh(analysis_result)

    return analysis_result


# ---------------------------------------------------------
# GET ALL / FILTERED ANALYSIS RESULTS
# ---------------------------------------------------------

@router.get(
    "",
    response_model=list[AnalysisResultResponse],
)
def get_analysis_results(
    observation_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(AnalysisResult)

    if observation_id is not None:
        query = query.filter(
            AnalysisResult.observation_id == observation_id
        )

    return (
        query
        .order_by(AnalysisResult.created_at.desc())
        .all()
    )


# ---------------------------------------------------------
# GET SINGLE ANALYSIS RESULT
# ---------------------------------------------------------

@router.get(
    "/{analysis_id}",
    response_model=AnalysisResultResponse,
)
def get_analysis_result(
    analysis_id: int,
    db: Session = Depends(get_db),
):
    analysis_result = (
        db.query(AnalysisResult)
        .filter(AnalysisResult.id == analysis_id)
        .first()
    )

    if analysis_result is None:
        raise HTTPException(
            status_code=404,
            detail="Analysis result not found",
        )

    return analysis_result