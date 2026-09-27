"""
OpenStreetMap water-body discovery for AquaSentinel.

The discovery step provides real named water-body footprints for the application.
It uses the read-only Overpass API and stores only validated Polygon geometries
in the existing PostGIS water_bodies table. Satellite analysis remains a separate
step: discovered water bodies are then used as the spatial target for Sentinel-2.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polygonize, unary_union
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import WaterBody

logger = logging.getLogger("AquaSentinel.WaterBodyDiscovery")

DEFAULT_OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

MAHARASHTRA_BBOX = (15.50, 72.50, 22.20, 81.00)
OVERPASS_QUERY_TIMEOUT_SECONDS = 25
OVERPASS_HTTP_TIMEOUT_SECONDS = 35


def _overpass_query() -> str:
    """Keep the discovery query bounded: ways only, named inland water, Maharashtra bbox."""
    south, west, north, east = MAHARASHTRA_BBOX
    return f"""
    [out:json][timeout:{OVERPASS_QUERY_TIMEOUT_SECONDS}];
    (
      way["natural"="water"]["name"]({south},{west},{north},{east});
      way["water"~"^(lake|reservoir)$"]["name"]({south},{west},{north},{east});
      way["landuse"="reservoir"]["name"]({south},{west},{north},{east});
    );
    out tags geom qt;
    """


def _polygon_from_element(element: dict[str, Any]) -> Polygon | None:
    """Convert an OSM way or water multipolygon relation to a usable Polygon."""
    if element.get("type") == "relation":
        lines = []
        for member in element.get("members") or []:
            if member.get("type") != "way" or member.get("role") not in {"outer", ""}:
                continue
            points = member.get("geometry") or []
            if len(points) < 2:
                continue
            coordinates = [(float(point["lon"]), float(point["lat"])) for point in points]
            try:
                lines.append(LineString(coordinates))
            except ValueError:
                continue
        if not lines:
            return None
        try:
            merged = unary_union(lines)
            polygons = list(polygonize(merged))
        except Exception:
            return None
        if not polygons:
            return None
        polygonal = unary_union(polygons)
        if isinstance(polygonal, MultiPolygon):
            polygon = max(polygonal.geoms, key=lambda item: item.area)
        elif isinstance(polygonal, Polygon):
            polygon = polygonal
        else:
            return None
    else:
        geometry = element.get("geometry") or []
        if len(geometry) < 4:
            return None
        coordinates = [(float(point["lon"]), float(point["lat"])) for point in geometry]
        if coordinates[0] != coordinates[-1]:
            return None
        polygon = Polygon(coordinates)

    if polygon.is_empty or polygon.area <= 0:
        return None

    if not polygon.is_valid:
        repaired = polygon.buffer(0)
        if isinstance(repaired, Polygon):
            polygon = repaired
        elif isinstance(repaired, MultiPolygon):
            polygon = max(repaired.geoms, key=lambda item: item.area)
        else:
            return None

    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        return None

    return polygon


def _classify_type(tags: dict[str, Any]) -> str:
    water = str(tags.get("water", "")).lower()
    natural = str(tags.get("natural", "")).lower()
    landuse = str(tags.get("landuse", "")).lower()

    if water == "reservoir" or landuse == "reservoir":
        return "Reservoir"
    if water == "pond":
        return "Pond"
    if water == "lake" or natural == "water":
        return "Lake"
    return "Water body"


def _district_from_tags(tags: dict[str, Any]) -> str | None:
    value = (
        tags.get("addr:district")
        or tags.get("district")
        or tags.get("is_in:district")
    )
    if value:
        return str(value)[:100]
    return None


def _fetch_elements() -> tuple[list[dict[str, Any]], str]:
    configured = os.getenv("OVERPASS_API_URL")
    endpoints = (configured,) if configured else DEFAULT_OVERPASS_URLS
    query = _overpass_query()
    last_error: Exception | None = None

    for endpoint in endpoints:
        try:
            response = requests.post(
                endpoint,
                data=query,
                headers={"User-Agent": "AquaSentinel/1.0 water-body-discovery"},
                timeout=OVERPASS_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            elements = payload.get("elements", [])
            logger.info(
                "Water-body discovery returned %s elements from %s.",
                len(elements),
                endpoint,
            )
            if elements:
                return elements, endpoint
            last_error = RuntimeError(
                "Overpass returned no named Maharashtra water-body ways."
            )
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning("Overpass request failed at %s: %s", endpoint, exc)

    raise RuntimeError(
        "Unable to fetch Maharashtra water bodies from Overpass within the timeout."
    ) from last_error


def _area_sq_km(db: Session, water_body_id: int) -> float | None:
    result = db.execute(
        text(
            """
            SELECT ST_Area(
                ST_Transform(geometry, 6933)
            ) / 1000000.0
            FROM water_bodies
            WHERE id = :id
            """
        ),
        {"id": water_body_id},
    )
    value = result.scalar()
    return float(value) if value is not None else None


def discover_and_import_water_bodies(
    db: Session,
    limit: int = 60,
    min_area_sq_km: float = 0.02,
) -> dict[str, Any]:
    """
    Discover named lakes/reservoirs in Maharashtra and upsert them by
    (name, district, source). Returns imported/updated counts and records.

    This is intentionally idempotent so the frontend can call it when the
    database is empty without creating duplicate rows.
    """
    limit = max(1, min(int(limit), 200))
    elements, endpoint = _fetch_elements()

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str]] = set()

    for element in elements:
        if element.get("type") not in {"way", "relation"}:
            continue

        tags = element.get("tags") or {}
        name = str(tags.get("name", "")).strip()
        if not name:
            continue

        polygon = _polygon_from_element(element)
        if polygon is None:
            continue

        # Geographic area in degrees is only used as a first-pass filter.
        # Final area is computed by PostGIS in a metre-based CRS below.
        if polygon.area <= 1e-7:
            continue

        water_type = _classify_type(tags)
        district = _district_from_tags(tags)
        key = (name.casefold(), district.casefold() if district else None, water_type)
        if key in seen:
            continue
        seen.add(key)

        candidates.append(
            {
                "name": name[:200],
                "type": water_type,
                "district": district,
                "polygon": polygon,
                "osm_id": element.get("id"),
            }
        )

    # Prefer larger named water bodies for a compact, useful demo inventory.
    # The final exact area is still calculated by PostGIS after insertion.
    candidates.sort(key=lambda item: item["polygon"].area, reverse=True)
    candidates = candidates[:limit]

    imported = 0
    updated = 0
    results: list[dict[str, Any]] = []

    for candidate in candidates:
        polygon = candidate["polygon"]
        coords = ", ".join(f"{lon} {lat}" for lon, lat in polygon.exterior.coords)
        wkt = f"POLYGON(({coords}))"

        existing = (
            db.query(WaterBody)
            .filter(
                WaterBody.name == candidate["name"],
                WaterBody.type == candidate["type"],
                WaterBody.source == "OpenStreetMap",
            )
            .first()
        )

        if existing is None:
            water_body = WaterBody(
                name=candidate["name"],
                type=candidate["type"],
                district=candidate["district"],
                state="Maharashtra",
                geometry=wkt,
                source="OpenStreetMap",
                active=True,
            )
            db.add(water_body)
            db.flush()
            water_body.area_sq_km = _area_sq_km(db, water_body.id)
            imported += 1
        else:
            water_body = existing
            water_body.district = candidate["district"] or water_body.district
            water_body.state = "Maharashtra"
            water_body.geometry = wkt
            water_body.active = True
            water_body.area_sq_km = _area_sq_km(db, water_body.id)
            updated += 1

        results.append(
            {
                "id": water_body.id,
                "name": water_body.name,
                "type": water_body.type,
                "district": water_body.district,
                "area_sq_km": water_body.area_sq_km,
                "source": water_body.source,
                "osm_id": candidate["osm_id"],
            }
        )

    db.commit()

    return {
        "source": "OpenStreetMap Overpass",
        "endpoint": endpoint,
        "requested_limit": limit,
        "discovered": len(results),
        "imported": imported,
        "updated": updated,
        "water_bodies": results,
    }
