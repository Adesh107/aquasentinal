from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.routes.water_bodies import router as water_bodies_router
from app.database import engine
from app.routes.alerts import router as alerts_router
from app.routes.satellite_observations import (
    router as satellite_observations_router,
)
from app.routes.analysis_results import (
    router as analysis_results_router,
)
from app.routes.history import router as history_router


app = FastAPI(
    title="AquaSentinel API",
    description="Backend API for satellite-based water quality intelligence",
    version="0.2.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(water_bodies_router)
app.include_router(alerts_router)
app.include_router(satellite_observations_router)
app.include_router(analysis_results_router)
app.include_router(history_router)


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
