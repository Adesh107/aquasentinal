"""
Water-body discovery/import for AquaSentinel.

Primary source:
- NWDP/ISRO Surface Waterbodies Maharashtra GeoJSON (official Indian water-data
  portal; boundaries extracted from satellite imagery).

Fallback:
- OpenStreetMap Overpass for named Maharashtra lakes/reservoirs.

Satellite analysis remains a separate step: imported water bodies are used as
the spatial targets for Sentinel-2 analysis.
"""
from __future__ import annotations

import logging
import os
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import geopandas as gpd
import requests
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polygonize, unary_union
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import WaterBody

logger = logging.getLogger("AquaSentinel.WaterBodyDiscovery")

# Official NWDP/ISRO state-wise surface-waterbody boundary resource.
DEFAULT_NWDP_MAHARASHTRA_URL = (
    "https://nwdp.nwic.gov.in/dataset/"
    "811f6a62-61c2-4d79-b90b-deeee4151f6d/resource/"
    "2fae6ca8-4513-4bbc-98ca-56486fcb83f0/download/wb_mh_geojson.zip"
)
NWDP_HTTP_TIMEOUT_SECONDS = 90

DEFAULT_OVERPASS_URLS = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

MAHARASHTRA_BBOX = (15.50, 72.50, 22.20, 81.00)
OVERPASS_QUERY_TIMEOUT_SECONDS = 25
OVERPASS_HTTP_TIMEOUT_SECONDS = 35


def _overpass_query() -> str:
    """Keep the fallback OSM query bounded: named inland water ways only."""
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
    """Convert an OSM way/relation to a usable Polygon."""
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
    return str(value)[:100] if value else None


def _normalise_field(value: Any) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _row_value(row: Any, candidates: tuple[str, ...]) -> str | None:
    wanted = {_normalise_field(value) for value in candidates}
    for column in row.index:
        if _normalise_field(column) not in wanted:
            continue
        value = row[column]
        if value is None:
            continue
        text_value = str(value).strip()
        if text_value and text_value.lower() not in {"nan", "none", "null"}:
            return text_value
    return None


def _largest_polygon(geometry: Any) -> Polygon | None:
    if isinstance(geometry, Polygon):
        polygon = geometry
    elif isinstance(geometry, MultiPolygon):
        polygon = max(geometry.geoms, key=lambda item: item.area)
    else:
        return None

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

    return polygon if polygon.is_valid and polygon.area > 0 else None


def _fetch_nwdp_candidates(limit: int) -> tuple[list[dict[str, Any]], str]:
    configured_file = os.getenv("NWDP_MAHARASHTRA_FILE")
    configured_url = os.getenv("NWDP_MAHARASHTRA_GEOJSON_URL", DEFAULT_NWDP_MAHARASHTRA_URL)

    with tempfile.TemporaryDirectory(prefix="aquasentinel-nwdp-") as temp_dir:
        if configured_file:
            archive_path = Path(configured_file).expanduser()
            if not archive_path.exists():
                raise RuntimeError(f"NWDP file not found: {archive_path}")
            archive_bytes = archive_path.read_bytes()
            source = str(archive_path)
        else:
            response = requests.get(
                configured_url,
                headers={"User-Agent": "AquaSentinel/1.0 water-body-import"},
                timeout=NWDP_HTTP_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            archive_bytes = response.content
            source = configured_url

        zip_path = Path(temp_dir) / "waterbodies.zip"
        zip_path.write_bytes(archive_bytes)

        with ZipFile(zip_path) as archive:
            geojson_names = [
                name for name in archive.namelist()
                if name.lower().endswith((".geojson", ".json"))
            ]
            if not geojson_names:
                raise RuntimeError("NWDP archive contains no GeoJSON file.")
            archive.extract(geojson_names[0], temp_dir)
            geojson_path = Path(temp_dir) / geojson_names[0]

        gdf = gpd.read_file(geojson_path)
        if gdf.empty:
            raise RuntimeError("NWDP Maharashtra GeoJSON contains no features.")

        if gdf.crs is None:
            gdf = gdf.set_crs(4326)
        else:
            gdf = gdf.to_crs(4326)

        named: list[dict[str, Any]] = []
        unnamed: list[dict[str, Any]] = []

        for index, row in gdf.iterrows():
            polygon = _largest_polygon(row.geometry)
            if polygon is None:
                continue

            area_sq_km = (
                gpd.GeoSeries([polygon], crs=4326)
                .to_crs(6933)
                .area
                .iloc[0]
                / 1_000_000.0
            )
            if area_sq_km < 0.001:
                continue

            name = _row_value(
                row,
                (
                    "name",
                    "waterbody_name",
                    "waterbodyname",
                    "wb_name",
                    "wbname",
                    "lake_name",
                    "reservoir_name",
                    "local_name",
                ),
            )
            district = _row_value(
                row,
                ("district", "district_name", "districtname", "dist_name", "distname"),
            )
            type_value = _row_value(
                row,
                ("type", "waterbody_type", "waterbodytype", "category", "class"),
            )
            water_type = type_value[:100] if type_value else "Water body"

            candidate = {
                "name": name[:200] if name else f"Maharashtra Waterbody {index + 1}",
                "type": water_type,
                "district": district[:100] if district else None,
                "polygon": polygon,
                "osm_id": None,
                "area_sq_km_hint": float(area_sq_km),
            }
            (named if name else unnamed).append(candidate)

        candidates = sorted(named, key=lambda item: item["area_sq_km_hint"], reverse=True)
        candidates.extend(
            sorted(unnamed, key=lambda item: item["area_sq_km_hint"], reverse=True)
        )
        if not candidates:
            raise RuntimeError("NWDP Maharashtra GeoJSON had no usable polygon water bodies.")

        return candidates[:limit], source


def _fetch_overpass_elements() -> tuple[list[dict[str, Any]], str]:
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
            if elements:
                logger.info("Overpass returned %s elements from %s.", len(elements), endpoint)
                return elements, endpoint
            last_error = RuntimeError("Overpass returned no named Maharashtra water-body ways.")
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning("Overpass request failed at %s: %s", endpoint, exc)

    raise RuntimeError("Unable to fetch Maharashtra water bodies from available Overpass endpoints.") from last_error


def _overpass_candidates(limit: int) -> tuple[list[dict[str, Any]], str]:
    elements, endpoint = _fetch_overpass_elements()
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
        if polygon is None or polygon.area <= 1e-7:
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

    candidates.sort(key=lambda item: item["polygon"].area, reverse=True)
    return candidates[:limit], endpoint


def _area_sq_km(db: Session, water_body_id: int) -> float | None:
    result = db.execute(
        text(
            """
            SELECT ST_Area(ST_Transform(geometry, 6933)) / 1000000.0
            FROM water_bodies
            WHERE id = :id
            """
        ),
        {"id": water_body_id},
    )
    value = result.scalar()
    return float(value) if value is not None else None


def _upsert_candidates(
    db: Session,
    candidates: list[dict[str, Any]],
    source: str,
    limit: int,
) -> dict[str, Any]:
    imported = 0
    updated = 0
    results: list[dict[str, Any]] = []

    for candidate in candidates[:limit]:
        polygon = candidate["polygon"]
        coords = ", ".join(f"{lon} {lat}" for lon, lat in polygon.exterior.coords)
        wkt = f"POLYGON(({coords}))"

        existing = (
            db.query(WaterBody)
            .filter(
                WaterBody.name == candidate["name"],
                WaterBody.type == candidate["type"],
                WaterBody.source == source,
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
                source=source,
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
                "osm_id": candidate.get("osm_id"),
            }
        )

    db.commit()

    return {
        "source": source,
        "endpoint": source,
        "requested_limit": limit,
        "discovered": len(results),
        "imported": imported,
        "updated": updated,
        "water_bodies": results,
    }


def discover_and_import_water_bodies(
    db: Session,
    limit: int = 60,
    min_area_sq_km: float = 0.02,
) -> dict[str, Any]:
    """
    Import real Maharashtra water-body boundaries.

    NWDP/ISRO is attempted first. If it cannot be downloaded/parsed, fall back
    to OSM Overpass. The import is idempotent.
    """
    del min_area_sq_km  # retained for backwards-compatible call signature
    limit = max(1, min(int(limit), 200))

    try:
        candidates, source = _fetch_nwdp_candidates(limit)
        logger.info("Using official NWDP/ISRO Maharashtra waterbody source: %s", source)
        return _upsert_candidates(db, candidates, "NWDP-SAC", limit)
    except Exception as exc:
        logger.warning("NWDP waterbody import failed; falling back to Overpass: %s", exc)

    candidates, endpoint = _overpass_candidates(limit)
    return _upsert_candidates(db, candidates, "OpenStreetMap", limit)
