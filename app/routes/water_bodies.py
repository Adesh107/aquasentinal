from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape
from geoalchemy2.elements import WKBElement
from shapely.geometry import mapping

from app.database import get_db
from app.models import WaterBody
from app.schemas.water_body import WaterBodyCreate, WaterBodyUpdate


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


def validate_and_convert_polygon(coordinates: list[list[list[float]]]) -> str:
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

    for longitude, latitude in ring:
        if not -180 <= longitude <= 180:
            raise HTTPException(
                status_code=400,
                detail="Polygon longitude must be between -180 and 180",
            )
        if not -90 <= latitude <= 90:
            raise HTTPException(
                status_code=400,
                detail="Polygon latitude must be between -90 and 90",
            )

    coordinate_text = ", ".join(
        f"{longitude} {latitude}"
        for longitude, latitude in ring
    )

    return f"POLYGON(({coordinate_text}))"


def calculate_area_sq_km(db: Session, water_body_id: int) -> float | None:
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
        {"id": water_body_id},
    )
    return area_result.scalar()


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
# GEOJSON GEOMETRY
# ---------------------------------------------------------

@router.get("/{water_body_id}/geometry")
def get_water_body_geometry(
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

    geometry = mapping(
        to_shape(water_body.geometry)
    )

    return {
        "type": "Feature",
        "id": water_body.id,
        "properties": {
            "name": water_body.name,
            "type": water_body.type,
            "district": water_body.district,
            "state": water_body.state,
            "area_sq_km": water_body.area_sq_km,
            "source": water_body.source,
            "active": water_body.active,
        },
        "geometry": {
            "type": geometry["type"],
            "coordinates": geometry["coordinates"],
        },
    }


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

@router.post("", status_code=201)
def create_water_body(
    data: WaterBodyCreate,
    db: Session = Depends(get_db),
):
    wkt = validate_and_convert_polygon(
        data.geometry.coordinates
    )

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

    water_body.area_sq_km = calculate_area_sq_km(
        db,
        water_body.id,
    )

    db.commit()
    db.refresh(water_body)

    return water_body_to_response(water_body)


# ---------------------------------------------------------
# UPDATE WATER BODY
# ---------------------------------------------------------

@router.patch("/{water_body_id}")
def update_water_body(
    water_body_id: int,
    data: WaterBodyUpdate,
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

    update_data = data.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(
            status_code=400,
            detail="At least one field must be provided for update",
        )

    if "geometry" in update_data:
        geometry_data = update_data.pop("geometry")
        wkt = validate_and_convert_polygon(
            geometry_data["coordinates"]
        )
        water_body.geometry = wkt

    for field in (
        "name",
        "type",
        "district",
        "state",
        "active",
    ):
        if field in update_data:
            setattr(
                water_body,
                field,
                update_data[field],
            )

    if "geometry" in data.model_fields_set:
        water_body.area_sq_km = calculate_area_sq_km(
            db,
            water_body.id,
        )

    db.commit()
    db.refresh(water_body)

    if not water_body.active:
        return water_body_to_response(water_body)

    return water_body_to_response(water_body)


# ---------------------------------------------------------
# DELETE WATER BODY
# ---------------------------------------------------------

@router.delete("/{water_body_id}")
def delete_water_body(
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

    if not water_body.active:
        raise HTTPException(
            status_code=404,
            detail="Water body not found",
        )

    water_body.active = False

    db.commit()

    return {
        "message": "Water body deleted",
        "id": water_body.id,
    }
