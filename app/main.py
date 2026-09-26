from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine


app = FastAPI(
    title="AquaSentinel API",
    description="Backend API for satellite-based water quality intelligence",
    version="0.2.0",
)


@app.get("/")
def root():
    return {
        "message": "AquaSentinel backend is running",
        "status": "ok",
    }


@app.get("/database-health")
def database_health():
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))
        value = result.scalar()

    return {
        "database": "connected",
        "test": value,
    }


@app.get("/postgis-health")
def postgis_health():
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT PostGIS_Version()")
        )
        version = result.scalar()

    return {
        "postgis": "connected",
        "version": version,
    }