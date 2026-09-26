from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WaterBody(Base):
    __tablename__ = "water_bodies"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    district: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    state: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Maharashtra",
    )

    geometry: Mapped[object] = mapped_column(
        Geometry(
            geometry_type="POLYGON",
            srid=4326,
        ),
        nullable=False,
    )

    area_sq_km: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="manual",
    )

    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )


class SatelliteObservation(Base):
    __tablename__ = "satellite_observations"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    water_body_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )

    satellite: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    observation_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    scene_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    cloud_percentage: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    quality_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    source_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    observation_metadata: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    observation_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )

    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    analysis_data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )   


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    water_body_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )

    analysis_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    indicator: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    affected_area_km2: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    explanation: Mapped[dict | list | None] = mapped_column(
        JSON,
        nullable=True,
    )

    # Geographic area affected by this alert.
    # Stored as a PostGIS polygon using WGS84 coordinates.
    geometry: Mapped[object | None] = mapped_column(
        Geometry(
            geometry_type="POLYGON",
            srid=4326,
        ),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )