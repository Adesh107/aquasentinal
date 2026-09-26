from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape
from geoalchemy2.elements import WKBElement
from shapely.geometry import mapping

from app.database import get_db
from app.models import WaterBody
from app.schemas.water_body import WaterBodyCreate

router = APIRouter(
    prefix="/water-bodies",
    tags=["Water Bodies"],
)


def water_body_to_response(water_body: WaterBody):
    geometry = mapping(to_shape(water_body.geometry))

    return {
        "id": water_body.id,
        "name": water_body.name,
        "type": water_body.type,
        "district": water_body.district,
        "state": water_body.state,
        "geometry": {
            "type": "Polygon",
            "coordinates": geometry["coordinates"],
        },
        "area_sq_km": water_body.area_sq_km,
        "source": water_body.source,
        "active": water_body.active,
    }


# ---------------------------------------------------------
# GET ALL / FILTER
# ---------------------------------------------------------

@router.get("")
def get_water_bodies(
    district: str | None = Query(default=None),
    type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(WaterBody)
        .filter(WaterBody.active == True)
    )

    if district:
        query = query.filter(WaterBody.district == district)

    if type:
        query = query.filter(WaterBody.type == type)

    water_bodies = query.all()

    return [
        water_body_to_response(water_body)
        for water_body in water_bodies
    ]


# ---------------------------------------------------------
# NEARBY WATER BODIES
# ---------------------------------------------------------

@router.get("/nearby")
def get_nearby_water_bodies(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=5.0, gt=0),
    db: Session = Depends(get_db),
):
    radius_meters = radius_km * 1000

    query = text("""
        SELECT
            id,
            name,
            type,
            district,
            state,
            ST_AsEWKB(geometry) AS geometry,
            area_sq_km,
            source,
            active,
            ST_Distance(
                geometry::geography,
                ST_SetSRID(
                    ST_MakePoint(:longitude, :latitude),
                    4326
                )::geography
            ) AS distance_meters
        FROM water_bodies
        WHERE active = TRUE
          AND ST_DWithin(
              geometry::geography,
              ST_SetSRID(
                  ST_MakePoint(:longitude, :latitude),
                  4326
              )::geography,
              :radius_meters
          )
        ORDER BY distance_meters ASC
    """)

    result = db.execute(
        query,
        {
            "latitude": latitude,
            "longitude": longitude,
            "radius_meters": radius_meters,
        },
    )

    rows = result.mappings().all()

    response = []

    for row in rows:
        geometry_element = WKBElement(
            row["geometry"],
            srid=4326,
        )

        geometry = mapping(
            to_shape(geometry_element)
        )

        response.append({
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "district": row["district"],
            "state": row["state"],
            "geometry": {
                "type": "Polygon",
                "coordinates": geometry["coordinates"],
            },
            "area_sq_km": row["area_sq_km"],
            "source": row["source"],
            "active": row["active"],
            "distance_km": round(
                row["distance_meters"] / 1000,
                3,
            ),
        })

    return response

# ---------------------------------------------------------
# GET SINGLE WATER BODY
# ---------------------------------------------------------

@router.get("/{water_body_id}")
def get_water_body(
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
        raise HTTPException(
            status_code=404,
            detail="Water body not found",
        )

    return water_body_to_response(water_body)


# ---------------------------------------------------------
# CREATE WATER BODY
# ---------------------------------------------------------

@router.post("")
def create_water_body(
    data: WaterBodyCreate,
    db: Session = Depends(get_db),
):
    coordinates = data.geometry.coordinates

    if len(coordinates) != 1:
        raise HTTPException(
            status_code=400,
            detail="Polygon must contain exactly one outer ring",
        )

    ring = coordinates[0]

    if len(ring) < 4:
        raise HTTPException(
            status_code=400,
            detail="Polygon must contain at least 4 coordinate points",
        )

    if ring[0] != ring[-1]:
        raise HTTPException(
            status_code=400,
            detail="Polygon must be closed: first and last coordinates must match",
        )

    coordinate_text = ", ".join(
        f"{longitude} {latitude}"
        for longitude, latitude in ring
    )

    wkt = f"POLYGON(({coordinate_text}))"

    water_body = WaterBody(
        name=data.name,
        type=data.type,
        district=data.district,
        state=data.state,
        geometry=wkt,
        source="manual",
        active=True,
    )

    db.add(water_body)
    db.flush()

    area_result = db.execute(
        text("""
            SELECT ST_Area(
                ST_Transform(
                    geometry,
                    6933
                )
            ) / 1000000.0
            FROM water_bodies
            WHERE id = :id
        """),
        {"id": water_body.id},
    )

    water_body.area_sq_km = area_result.scalar()

    db.commit()
    db.refresh(water_body)

    return water_body_to_response(water_body)